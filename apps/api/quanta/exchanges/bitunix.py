"""Bitunix USDT-perpetual adapter (SPEC §6).

Public endpoints only. Order placement lives in the isolated execution
service (phase 6), so nothing importable from the web process can trade.

Endpoint and limit references, verified against SPEC §6:

* Base REST ``https://fapi.bitunix.com``, 10 req/s per IP on market data.
* Public WebSocket ``wss://fapi.bitunix.com/public/``, max 5 messages per
  second including ping/pong, up to 300 subscriptions per connection.
* Klines take ``type=LAST_PRICE|MARK_PRICE`` and ``limit`` up to 200.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from quanta.exchanges.base import (
    Bar,
    EventType,
    ExchangeError,
    FeeTier,
    Funding,
    Interval,
    PositionTier,
    PriceType,
    RateLimitError,
    StreamEvent,
    Subscription,
    Symbol,
    Ticker,
)
from quanta.exchanges.throttle import AsyncRateLimiter

logger = structlog.get_logger(__name__)

DEFAULT_REST_URL = "https://fapi.bitunix.com"
DEFAULT_WS_URL = "wss://fapi.bitunix.com/public/"

# SPEC §6: 10 req/s per IP. Left a little headroom so a burst of chart loads
# plus a backfill running underneath cannot trip it.
REST_RATE_PER_SECOND = 8
# SPEC §6: 5 messages/s including ping/pong; exceeding it disconnects.
WS_MESSAGES_PER_SECOND = 4
MAX_SUBSCRIPTIONS_PER_CONNECTION = 300
MAX_KLINE_LIMIT = 200

# Fallback fee table from SPEC §6, used only when the venue's own endpoint
# is unavailable. Rates are fractions: VIP0 taker 0.060% -> 0.0006.
FALLBACK_FEE_TIERS: tuple[FeeTier, ...] = (
    FeeTier("VIP0", Decimal("0.0002"), Decimal("0.0006")),
    FeeTier("VIP1", Decimal("0.0002"), Decimal("0.0005"), Decimal("1000000"), Decimal("1000")),
    FeeTier("VIP2", Decimal("0.00016"), Decimal("0.0005"), Decimal("5000000"), Decimal("10000")),
    FeeTier("VIP3", Decimal("0.00014"), Decimal("0.0004"), Decimal("8000000"), Decimal("50000")),
    FeeTier(
        "VIP4", Decimal("0.00012"), Decimal("0.000375"), Decimal("20000000"), Decimal("200000")
    ),
    FeeTier("VIP5", Decimal("0.0001"), Decimal("0.00035"), Decimal("50000000"), Decimal("1000000")),
    FeeTier(
        "VIP6", Decimal("0.00008"), Decimal("0.000315"), Decimal("100000000"), Decimal("2000000")
    ),
    FeeTier(
        "VIP7", Decimal("0.00006"), Decimal("0.0003"), Decimal("200000000"), Decimal("3000000")
    ),
    FeeTier("VIP8", Decimal("0"), Decimal("0.00026"), Decimal("500000000"), None),
)

_INTERVAL_TO_VENUE = {interval: interval.value for interval in Interval}
_PRICE_TYPE_TO_VENUE: dict[PriceType, str] = {"LAST": "LAST_PRICE", "MARK": "MARK_PRICE"}


def _decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    """Parse a venue number without letting a bad field kill the response."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _required_decimal(value: Any, field: str) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        raise ExchangeError(f"missing or unparsable numeric field {field!r}")
    return parsed


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class BitunixAdapter:
    """Public market data from Bitunix."""

    name = "bitunix"

    def __init__(
        self,
        *,
        rest_url: str = DEFAULT_REST_URL,
        ws_url: str = DEFAULT_WS_URL,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._rest_url = rest_url.rstrip("/")
        self._ws_url = ws_url
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._rest_url,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        self._throttle = AsyncRateLimiter(REST_RATE_PER_SECOND)

    # --- REST plumbing --------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """One throttled GET, returning the unwrapped ``data`` payload."""
        await self._throttle.acquire()

        clean = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            response = await self._client.get(path, params=clean)
        except httpx.TimeoutException as exc:
            raise ExchangeError(f"timed out calling {path}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ExchangeError(f"network error calling {path}: {exc}", retryable=True) from exc

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1") or 1)
            raise RateLimitError(f"rate limited on {path}", retry_after=retry_after)
        if response.status_code >= 500:
            raise ExchangeError(f"{path} returned {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ExchangeError(f"{path} returned {response.status_code}: {response.text[:200]}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ExchangeError(f"{path} returned a non-JSON body") from exc

        # Bitunix wraps everything as {code, msg/message, data}. code 0 is success.
        if isinstance(payload, dict) and "code" in payload:
            code = str(payload.get("code"))
            if code not in ("0", "00000"):
                message = payload.get("msg") or payload.get("message") or "unknown error"
                raise ExchangeError(f"{path}: {message}", code=code)
            return payload.get("data")
        return payload

    # --- Market metadata ------------------------------------------------

    async def symbols(self) -> list[Symbol]:
        data = await self._get("/api/v1/futures/market/trading_pairs")
        rows = data if isinstance(data, list) else []
        symbols: list[Symbol] = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("symbol")
            if not name:
                continue
            try:
                symbols.append(
                    Symbol(
                        symbol=str(name),
                        base=str(row.get("base") or row.get("baseCoin") or ""),
                        quote=str(row.get("quote") or row.get("quoteCoin") or "USDT"),
                        min_leverage=_int(row.get("minLeverage"), 1),
                        max_leverage=_int(row.get("maxLeverage"), 1),
                        default_leverage=_int(row.get("defaultLeverage"), 1),
                        base_precision=_int(row.get("basePrecision")),
                        quote_precision=_int(row.get("quotePrecision")),
                        min_trade_volume=_decimal(row.get("minTradeVolume"), Decimal(0))
                        or Decimal(0),
                        max_market_order_volume=_decimal(row.get("maxMarketOrderVolume")),
                        status=str(row.get("symbolStatus") or "OPEN"),
                        max_funding_rate=_decimal(row.get("maxFundingRate")),
                        min_funding_rate=_decimal(row.get("minFundingRate")),
                        api_supported=bool(row.get("isApiSupported", True)),
                    )
                )
            except ExchangeError:
                # One malformed row must not blank the whole symbol list.
                logger.warning("bitunix_symbol_skipped", symbol=name)
        return symbols

    async def position_tiers(self, symbol: str) -> list[PositionTier]:
        data = await self._get("/api/v1/futures/position/get_position_tiers", {"symbol": symbol})
        rows = data if isinstance(data, list) else []
        tiers = [
            PositionTier(
                level=_int(row.get("level")),
                start_value=_decimal(row.get("startValue"), Decimal(0)) or Decimal(0),
                end_value=_decimal(row.get("endValue"), Decimal(0)) or Decimal(0),
                leverage=_int(row.get("leverage"), 1),
                maintenance_margin_rate=_required_decimal(
                    row.get("maintenanceMarginRate"), "maintenanceMarginRate"
                ),
            )
            for row in rows
            if isinstance(row, dict)
        ]
        return sorted(tiers, key=lambda tier: tier.level)

    async def fee_tiers(self) -> list[FeeTier]:
        """Fee tiers, falling back to the SPEC §6 table when unavailable.

        Costs feed every research number, so the fallback is a published
        table rather than zeros — silently free trading would flatter every
        backtest.
        """
        try:
            data = await self._get("/api/v1/futures/market/fee_rate")
        except ExchangeError as exc:
            logger.warning("bitunix_fee_tiers_fallback", error=str(exc))
            return list(FALLBACK_FEE_TIERS)

        rows = data if isinstance(data, list) else []
        tiers: list[FeeTier] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            maker = _decimal(row.get("makerFeeRate") or row.get("maker"))
            taker = _decimal(row.get("takerFeeRate") or row.get("taker"))
            if maker is None or taker is None:
                continue
            tiers.append(
                FeeTier(
                    tier=str(row.get("level") or row.get("vipLevel") or f"VIP{len(tiers)}"),
                    maker=maker,
                    taker=taker,
                    requirement_volume_30d=_decimal(row.get("tradeVolume")),
                    requirement_balance=_decimal(row.get("balance")),
                )
            )
        return tiers or list(FALLBACK_FEE_TIERS)

    # --- Time series ----------------------------------------------------

    async def klines(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: int | None = None,
        end: int | None = None,
        limit: int = MAX_KLINE_LIMIT,
        price_type: PriceType = "LAST",
    ) -> list[Bar]:
        """One page of klines, oldest first.

        ``limit`` is capped at the venue's 200; use
        :meth:`iter_klines` to walk a longer range.
        """
        data = await self._get(
            "/api/v1/futures/market/kline",
            {
                "symbol": symbol,
                "interval": _INTERVAL_TO_VENUE[interval],
                "startTime": start,
                "endTime": end,
                "limit": min(limit, MAX_KLINE_LIMIT),
                "type": _PRICE_TYPE_TO_VENUE[price_type],
            },
        )
        rows = data if isinstance(data, list) else []
        bars = [parsed for row in rows if (parsed := _parse_bar(row)) is not None]
        bars.sort(key=lambda bar: bar.open_time)
        return bars

    async def iter_klines(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: int,
        end: int,
        price_type: PriceType = "LAST",
    ) -> AsyncIterator[list[Bar]]:
        """Walk a range in 200-bar pages, oldest first.

        SPEC §6: history is fetched once and stored, never queried live per
        user, so this is what the backfill job drives.
        """
        cursor = start
        step = interval.milliseconds * MAX_KLINE_LIMIT

        while cursor < end:
            window_end = min(cursor + step, end)
            page = await self.klines(
                symbol,
                interval,
                start=cursor,
                end=window_end,
                limit=MAX_KLINE_LIMIT,
                price_type=price_type,
            )
            if not page:
                # An empty window can mean a listing gap rather than the end,
                # so step past it instead of stopping.
                cursor = window_end
                continue

            yield page

            last_open = page[-1].open_time
            next_cursor = last_open + interval.milliseconds
            # Guard against a venue that returns the same page forever.
            cursor = max(next_cursor, cursor + interval.milliseconds)

    async def funding_history(
        self, symbol: str, *, start: int | None = None, end: int | None = None, limit: int = 200
    ) -> list[Funding]:
        data = await self._get(
            "/api/v1/futures/market/get_funding_rate_history",
            {
                "symbol": symbol,
                "startTime": start,
                "endTime": end,
                "limit": min(limit, MAX_KLINE_LIMIT),
            },
        )
        rows = data if isinstance(data, list) else []
        entries: list[Funding] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rate = _decimal(row.get("fundingRate"))
            funding_time = _int(row.get("fundingTime"))
            if rate is None or funding_time == 0:
                continue
            entries.append(
                Funding(
                    funding_time=funding_time,
                    funding_rate=rate,
                    mark_price=_decimal(row.get("markPrice")),
                )
            )
        entries.sort(key=lambda entry: entry.funding_time)
        return entries

    async def tickers(self) -> list[Ticker]:
        data = await self._get("/api/v1/futures/market/tickers")
        rows = data if isinstance(data, list) else []
        return [parsed for row in rows if (parsed := _parse_ticker(row)) is not None]

    # --- Public stream --------------------------------------------------

    async def stream(self, subscriptions: Sequence[Subscription]) -> AsyncIterator[StreamEvent]:
        """Yield normalised events from the public WebSocket.

        Reconnects with exponential backoff and jitter, resubscribing each
        time. The caller gap-fills over REST after a reconnect — this layer
        only reports what the socket delivered.
        """
        if len(subscriptions) > MAX_SUBSCRIPTIONS_PER_CONNECTION:
            raise ExchangeError(
                f"{len(subscriptions)} subscriptions exceeds the "
                f"{MAX_SUBSCRIPTIONS_PER_CONNECTION} per connection limit"
            )

        ws_throttle = AsyncRateLimiter(WS_MESSAGES_PER_SECOND)
        attempt = 0

        while True:
            try:
                async with websockets.connect(
                    self._ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_queue=1024,
                ) as socket:
                    attempt = 0
                    logger.info("bitunix_ws_connected", subscriptions=len(subscriptions))

                    await ws_throttle.acquire()
                    await socket.send(json.dumps(_subscribe_payload(subscriptions)))

                    async for raw in socket:
                        for event in _parse_stream_message(raw):
                            yield event

            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, OSError, ExchangeError) as exc:
                attempt += 1
                # Full jitter, capped at 30s, so many workers reconnecting
                # after an outage do not arrive together.
                delay = min(30.0, (2 ** min(attempt, 5)) * random.random())  # noqa: S311
                logger.warning(
                    "bitunix_ws_reconnecting",
                    error=str(exc),
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                )
                await asyncio.sleep(delay)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> BitunixAdapter:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


# --- Parsing ------------------------------------------------------------


def _parse_bar(row: Any) -> Bar | None:
    """Parse a kline from either the object or the array shape."""
    if isinstance(row, dict):
        open_time = _int(row.get("time") or row.get("ts") or row.get("openTime"))
        if open_time == 0:
            return None
        try:
            return Bar(
                open_time=open_time,
                open=_required_decimal(row.get("open") or row.get("o"), "open"),
                high=_required_decimal(row.get("high") or row.get("h"), "high"),
                low=_required_decimal(row.get("low") or row.get("l"), "low"),
                close=_required_decimal(row.get("close") or row.get("c"), "close"),
                volume=_decimal(row.get("baseVol") or row.get("volume") or row.get("v"), Decimal(0))
                or Decimal(0),
                quote_volume=_decimal(row.get("quoteVol") or row.get("q")),
                closed=bool(row.get("closed", True)),
            )
        except ExchangeError:
            return None

    if isinstance(row, list | tuple) and len(row) >= 5:
        try:
            return Bar(
                open_time=_int(row[0]),
                open=_required_decimal(row[1], "open"),
                high=_required_decimal(row[2], "high"),
                low=_required_decimal(row[3], "low"),
                close=_required_decimal(row[4], "close"),
                volume=_decimal(row[5] if len(row) > 5 else 0, Decimal(0)) or Decimal(0),
            )
        except ExchangeError:
            return None
    return None


def _parse_ticker(row: Any) -> Ticker | None:
    if not isinstance(row, dict):
        return None
    symbol = row.get("symbol")
    last = _decimal(row.get("lastPrice") or row.get("last") or row.get("close"))
    if not symbol or last is None:
        return None

    change = _decimal(row.get("priceChangePercent") or row.get("changePercent"), Decimal(0))
    if change is None:
        change = Decimal(0)
    # Some venues express the 24h change as a ratio rather than a percent.
    if abs(change) < 1 and row.get("priceChangePercent") is not None:
        change = change * 100

    return Ticker(
        symbol=str(symbol),
        last=last,
        change_percent_24h=change,
        high_24h=_decimal(row.get("high") or row.get("high24h")),
        low_24h=_decimal(row.get("low") or row.get("low24h")),
        base_volume_24h=_decimal(row.get("baseVol") or row.get("volume")),
        quote_volume_24h=_decimal(row.get("quoteVol") or row.get("quoteVolume")),
        mark_price=_decimal(row.get("markPrice")),
        index_price=_decimal(row.get("indexPrice")),
        funding_rate=_decimal(row.get("fundingRate")),
        next_funding_time=_int(row.get("nextFundingTime")) or None,
        open_interest=_decimal(row.get("openInterest")),
    )


def _subscribe_payload(subscriptions: Sequence[Subscription]) -> dict[str, Any]:
    args: list[dict[str, str]] = []
    for sub in subscriptions:
        if sub.channel is EventType.KLINE:
            if sub.interval is None:
                raise ExchangeError("a kline subscription needs an interval")
            args.append(
                {"symbol": sub.symbol, "ch": f"market_kline_{_INTERVAL_TO_VENUE[sub.interval]}"}
            )
        elif sub.channel is EventType.TICKER:
            args.append({"symbol": sub.symbol, "ch": "ticker"})
        elif sub.channel is EventType.MARK_PRICE:
            args.append({"symbol": sub.symbol, "ch": "mark_price"})
        elif sub.channel is EventType.DEPTH:
            args.append({"symbol": sub.symbol, "ch": "depth_books1"})
        elif sub.channel is EventType.TRADE:
            args.append({"symbol": sub.symbol, "ch": "trade"})
    return {"op": "subscribe", "args": args}


def _channel_to_event(channel: str) -> tuple[EventType, Interval | None]:
    if channel.startswith("market_kline_"):
        raw = channel.removeprefix("market_kline_")
        try:
            return EventType.KLINE, Interval(raw)
        except ValueError:
            return EventType.KLINE, None
    if channel == "ticker":
        return EventType.TICKER, None
    if channel in ("mark_price", "markPrice"):
        return EventType.MARK_PRICE, None
    if channel.startswith("depth"):
        return EventType.DEPTH, None
    return EventType.TRADE, None


def _parse_stream_message(raw: str | bytes) -> list[StreamEvent]:
    """Turn one socket frame into zero or more normalised events."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")

    try:
        message = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(message, dict):
        return []

    # Control frames: pong, subscribe acknowledgements, errors.
    channel = message.get("ch") or message.get("channel")
    if not channel or "data" not in message:
        return []

    symbol = str(message.get("symbol") or "")
    event_type, interval = _channel_to_event(str(channel))
    received_at = _int(message.get("ts")) or int(time.time() * 1000)
    payload = message["data"]

    if event_type is EventType.KLINE:
        rows = payload if isinstance(payload, list) else [payload]
        events = []
        for row in rows:
            bar = _parse_bar(row)
            if bar is not None:
                events.append(
                    StreamEvent(
                        type=EventType.KLINE,
                        symbol=symbol,
                        received_at=received_at,
                        interval=interval,
                        bar=bar,
                        raw=message,
                    )
                )
        return events

    if event_type is EventType.TICKER:
        ticker = _parse_ticker(payload if isinstance(payload, dict) else {})
        if ticker is None:
            return []
        return [
            StreamEvent(
                type=EventType.TICKER,
                symbol=ticker.symbol or symbol,
                received_at=received_at,
                ticker=ticker,
                raw=message,
            )
        ]

    if event_type is EventType.MARK_PRICE:
        source = payload if isinstance(payload, dict) else {}
        price = _decimal(source.get("markPrice") or source.get("mp") or source.get("price"))
        if price is None:
            return []
        return [
            StreamEvent(
                type=EventType.MARK_PRICE,
                symbol=symbol,
                received_at=received_at,
                price=price,
                raw=message,
            )
        ]

    return []


__all__ = ["FALLBACK_FEE_TIERS", "BitunixAdapter"]
