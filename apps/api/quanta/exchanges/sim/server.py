"""A local stand-in for the Bitunix public API.

It speaks the wire format described in SPEC §6 — the same envelope, field
names, limits and channel names — so the real :class:`BitunixAdapter` runs
against it unchanged. That makes it useful twice over: it unblocks work when
the venue is unreachable, and it gives the adapter's tests a real HTTP and
WebSocket server to talk to instead of mocks.

Run it with::

    python -m quanta.exchanges.sim
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from decimal import Decimal
from typing import Any

import structlog
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from quanta.exchanges.base import Bar, Interval
from quanta.exchanges.bitunix import FALLBACK_FEE_TIERS
from quanta.exchanges.sim.market import ANCHOR_PRICES, SIM_SYMBOLS, SyntheticMarket

logger = structlog.get_logger(__name__)

MAX_LIMIT = 200
# How often the simulated stream pushes an update for the forming bar.
STREAM_TICK_SECONDS = 1.0


def _ok(data: Any) -> JSONResponse:
    """Bitunix's success envelope."""
    return JSONResponse({"code": 0, "msg": "Success", "data": data})


def _error(code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "msg": message, "data": None})


def _bar_json(bar: Bar) -> dict[str, Any]:
    return {
        "time": bar.open_time,
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "baseVol": str(bar.volume),
        "quoteVol": str(bar.quote_volume) if bar.quote_volume is not None else None,
        "closed": bar.closed,
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def create_sim_app() -> FastAPI:
    app = FastAPI(
        title="Bitunix simulator",
        description=(
            "Development stand-in for the Bitunix public API. Serves the same "
            "envelope and field names so the real adapter runs unchanged."
        ),
        docs_url="/docs",
    )

    @app.get("/api/v1/futures/market/trading_pairs")
    async def trading_pairs() -> JSONResponse:
        return _ok(
            [
                {
                    "symbol": symbol,
                    "base": symbol.removesuffix("USDT"),
                    "quote": "USDT",
                    "minLeverage": 1,
                    # SPEC §6: BTC and ETH perpetuals go to 200x.
                    "maxLeverage": 200 if symbol in ("BTCUSDT", "ETHUSDT") else 75,
                    "defaultLeverage": 20,
                    "basePrecision": 4 if ANCHOR_PRICES[symbol] >= 1 else 0,
                    "quotePrecision": 1 if ANCHOR_PRICES[symbol] >= 1000 else 5,
                    "minTradeVolume": "0.0001",
                    "maxMarketOrderVolume": "120",
                    "symbolStatus": "OPEN",
                    "maxFundingRate": "0.00375",
                    "minFundingRate": "-0.00375",
                    "isApiSupported": True,
                }
                for symbol in SIM_SYMBOLS
            ]
        )

    @app.get("/api/v1/futures/position/get_position_tiers")
    async def position_tiers(symbol: str = Query()) -> JSONResponse:
        if symbol not in ANCHOR_PRICES:
            return _error("10001", f"unknown symbol {symbol}")

        # A plausible tier ladder: as notional grows, max leverage falls and
        # the maintenance margin rate rises (SPEC §6).
        ladder = [
            ("0", "50000", 200, "0.004"),
            ("50000", "250000", 100, "0.005"),
            ("250000", "1000000", 50, "0.01"),
            ("1000000", "5000000", 20, "0.025"),
            ("5000000", "20000000", 10, "0.05"),
            ("20000000", "50000000", 5, "0.10"),
        ]
        return _ok(
            [
                {
                    "level": index + 1,
                    "startValue": start,
                    "endValue": end,
                    "leverage": leverage,
                    "maintenanceMarginRate": mmr,
                }
                for index, (start, end, leverage, mmr) in enumerate(ladder)
            ]
        )

    @app.get("/api/v1/futures/market/fee_rate")
    async def fee_rate() -> JSONResponse:
        return _ok(
            [
                {
                    "level": tier.tier,
                    "makerFeeRate": str(tier.maker),
                    "takerFeeRate": str(tier.taker),
                    "tradeVolume": str(tier.requirement_volume_30d)
                    if tier.requirement_volume_30d is not None
                    else None,
                    "balance": str(tier.requirement_balance)
                    if tier.requirement_balance is not None
                    else None,
                }
                for tier in FALLBACK_FEE_TIERS
            ]
        )

    @app.get("/api/v1/futures/market/kline")
    async def kline(
        symbol: str = Query(),
        interval: str = Query(),
        startTime: int | None = Query(default=None),  # noqa: N803 - venue's spelling
        endTime: int | None = Query(default=None),  # noqa: N803
        limit: int = Query(default=MAX_LIMIT),
        type: str = Query(default="LAST_PRICE"),  # the venue's own parameter name
    ) -> JSONResponse:
        if symbol not in ANCHOR_PRICES:
            return _error("10001", f"unknown symbol {symbol}")
        try:
            parsed_interval = Interval(interval)
        except ValueError:
            return _error("10002", f"unsupported interval {interval}")
        if limit > MAX_LIMIT:
            return _error("10003", f"limit may not exceed {MAX_LIMIT}")

        now = _now_ms()
        step = parsed_interval.milliseconds
        # A real venue never returns a bar that has not opened. The current
        # bar is the newest one that can exist, and it is still forming.
        current_open = (now // step) * step
        end = min(endTime or now, current_open) + 1
        start = startTime if startTime is not None else end - step * limit

        market = SyntheticMarket(symbol)
        bars = market.bars(start=start, end=end, interval=parsed_interval, now_ms=now)

        # The venue returns the most recent `limit` bars of the window.
        bars = bars[-limit:]

        if type == "MARK_PRICE":
            # Mark price tracks last closely but not exactly.
            bars = [
                Bar(
                    open_time=bar.open_time,
                    open=bar.open * Decimal("1.0001"),
                    high=bar.high * Decimal("1.0001"),
                    low=bar.low * Decimal("1.0001"),
                    close=bar.close * Decimal("1.0001"),
                    volume=bar.volume,
                    quote_volume=bar.quote_volume,
                    closed=bar.closed,
                )
                for bar in bars
            ]

        return _ok([_bar_json(bar) for bar in bars])

    @app.get("/api/v1/futures/market/get_funding_rate_history")
    async def funding_history(
        symbol: str = Query(),
        startTime: int | None = Query(default=None),  # noqa: N803
        endTime: int | None = Query(default=None),  # noqa: N803
        limit: int = Query(default=MAX_LIMIT),
    ) -> JSONResponse:
        if symbol not in ANCHOR_PRICES:
            return _error("10001", f"unknown symbol {symbol}")

        # SPEC §6: funding settles every 8h at 00:00, 08:00 and 16:00 UTC.
        eight_hours = 8 * 3_600_000
        now = _now_ms()
        end = endTime or now
        start = startTime if startTime is not None else end - eight_hours * limit

        market = SyntheticMarket(symbol)
        entries: list[dict[str, Any]] = []
        settlement = (start // eight_hours) * eight_hours
        while settlement < end and len(entries) < min(limit, MAX_LIMIT):
            if settlement >= start:
                # A small rate that flips sign over time.
                factor = market.drift_at(settlement)
                entries.append(
                    {
                        "fundingTime": settlement,
                        "fundingRate": f"{factor * 0.002:.8f}",
                        "markPrice": str(market.price_now(settlement)),
                    }
                )
            settlement += eight_hours

        return _ok(entries)

    @app.get("/api/v1/futures/market/tickers")
    async def tickers() -> JSONResponse:
        now = _now_ms()
        day_ago = now - 86_400_000
        rows = []

        for symbol in SIM_SYMBOLS:
            market = SyntheticMarket(symbol)
            last = market.price_now(now)
            previous = market.price_now(day_ago)
            change = ((last - previous) / previous * 100) if previous else Decimal(0)

            daily = market.bars(start=day_ago, end=now, interval=Interval.H1, now_ms=now)
            high = max((bar.high for bar in daily), default=last)
            low = min((bar.low for bar in daily), default=last)
            volume = sum((bar.volume for bar in daily), Decimal(0))

            eight_hours = 8 * 3_600_000
            rows.append(
                {
                    "symbol": symbol,
                    "lastPrice": str(last),
                    "priceChangePercent": f"{change:.4f}",
                    "high": str(high),
                    "low": str(low),
                    "baseVol": str(volume),
                    "quoteVol": str(volume * last),
                    "markPrice": str(last * Decimal("1.0001")),
                    "indexPrice": str(last * Decimal("0.99995")),
                    "fundingRate": "0.0001",
                    "nextFundingTime": ((now // eight_hours) + 1) * eight_hours,
                    "openInterest": str(volume * Decimal("12")),
                }
            )
        return _ok(rows)

    @app.websocket("/public/")
    async def public_stream(websocket: WebSocket) -> None:
        """The public channel fan-out, mirroring the venue's protocol."""
        await websocket.accept()
        subscriptions: list[dict[str, str]] = []
        pump: asyncio.Task[None] | None = None

        async def push() -> None:
            """Emit the forming bar (and ticker) for every subscription."""
            while True:
                now = _now_ms()
                for sub in subscriptions:
                    symbol = sub.get("symbol", "")
                    channel = sub.get("ch", "")
                    if symbol not in ANCHOR_PRICES:
                        continue
                    market = SyntheticMarket(symbol)

                    if channel.startswith("market_kline_"):
                        raw_interval = channel.removeprefix("market_kline_")
                        try:
                            interval = Interval(raw_interval)
                        except ValueError:
                            continue
                        step = interval.milliseconds
                        open_time = (now // step) * step
                        bar = market.bar(open_time, interval, closed=False)
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "ch": channel,
                                    "symbol": symbol,
                                    "ts": now,
                                    "data": _bar_json(bar),
                                }
                            )
                        )
                    elif channel == "ticker":
                        last = market.price_now(now)
                        previous = market.price_now(now - 86_400_000)
                        change = ((last - previous) / previous * 100) if previous else Decimal(0)
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "ch": "ticker",
                                    "symbol": symbol,
                                    "ts": now,
                                    "data": {
                                        "symbol": symbol,
                                        "lastPrice": str(last),
                                        "priceChangePercent": f"{change:.4f}",
                                        "markPrice": str(last * Decimal("1.0001")),
                                    },
                                }
                            )
                        )
                    elif channel in ("mark_price", "markPrice"):
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "ch": "mark_price",
                                    "symbol": symbol,
                                    "ts": now,
                                    "data": {"markPrice": str(market.price_now(now))},
                                }
                            )
                        )
                await asyncio.sleep(STREAM_TICK_SECONDS)

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue

                op = message.get("op")
                if op == "subscribe":
                    args = message.get("args") or []
                    subscriptions = [a for a in args if isinstance(a, dict)]
                    await websocket.send_text(
                        json.dumps({"op": "subscribe", "success": True, "args": subscriptions})
                    )
                    if pump is None:
                        pump = asyncio.create_task(push())
                elif op == "unsubscribe":
                    subscriptions = []
                elif op == "ping":
                    await websocket.send_text(json.dumps({"op": "pong", "ts": _now_ms()}))

        except WebSocketDisconnect:
            pass
        finally:
            if pump is not None:
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump

    return app


sim_app = create_sim_app()
