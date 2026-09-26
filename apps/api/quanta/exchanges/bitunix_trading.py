"""Bitunix private trading calls (SPEC §3.5, §6).

Separate from `bitunix.py` on purpose: that one is public market data and is
imported throughout the web process, this one can move money and is imported
only by the execution service.

**Signing.** Bitunix uses a two-round SHA-256 over a concatenation, with the
key in the second round rather than an HMAC:

    digest = sha256(nonce + timestamp + api_key + query + body)
    sign   = sha256(digest + api_secret)

and sends `api-key`, `sign`, `nonce` and `timestamp` as headers, the
timestamp in UTC milliseconds. That much is from Bitunix's own signing page.
Two details of the concatenation — that `query` is the parameters sorted by
name and joined as `keyvalue` with no separators, and that `body` is the
compact JSON exactly as transmitted — follow the convention their examples
use but were not readable from here, because this environment's network
policy blocks `openapidoc.bitunix.com` and `www.bitunix.com`.

So everything below is written to make that cheap to correct if it turns out
to differ: the concatenation is built in one function, `signature_payload`,
which is unit-tested on its own, and the endpoint paths are constants at the
top. Nothing else in the codebase needs to change if either is wrong.

Until it has been exercised against a real key, treat this adapter as
unverified against the live venue. The simulator in `sim/trading.py`
implements the same protocol, and everything above this layer is tested
against that.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from decimal import Decimal
from typing import Any

import httpx

from quanta.exchanges.throttle import AsyncRateLimiter
from quanta.exchanges.trading import (
    Balance,
    Credentials,
    KeyPermissions,
    MarginMode,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionMode,
    TimeInForce,
    TradeSide,
    TradingError,
)

DEFAULT_REST_URL = "https://fapi.bitunix.com"

# Private endpoints are rate limited harder than public ones, and an order
# rejected for rate limiting during an exit is the expensive kind.
PRIVATE_RATE_PER_SECOND = 5

PLACE_ORDER = "/api/v1/futures/trade/place_order"
CANCEL_ORDERS = "/api/v1/futures/trade/cancel_orders"
PENDING_ORDERS = "/api/v1/futures/trade/get_pending_orders"
PENDING_POSITIONS = "/api/v1/futures/position/get_pending_positions"
ACCOUNT = "/api/v1/futures/account"
CHANGE_LEVERAGE = "/api/v1/futures/account/change_leverage"
CHANGE_MARGIN_MODE = "/api/v1/futures/account/change_margin_mode"
API_KEY_INFO = "/api/v1/futures/account/get_api_key_info"

_STATUS = {
    "INIT": OrderStatus.NEW,
    "NEW": OrderStatus.NEW,
    "PART_FILLED": OrderStatus.PARTIALLY_FILLED,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
}


def signature_payload(
    *,
    nonce: str,
    timestamp: str,
    api_key: str,
    query: dict[str, Any] | None,
    body: str,
) -> str:
    """The exact string Bitunix hashes in the first round.

    Split out and tested on its own because it is the one part of this file
    that cannot be checked against the venue from here. If the live API
    rejects signatures, this function is where the fix goes.

    Parameters are sorted by name and joined as `keyvalue` with no
    separators; `None` values are dropped, since they are not sent either.
    """
    clean = {k: v for k, v in (query or {}).items() if v is not None}
    joined = "".join(f"{key}{clean[key]}" for key in sorted(clean))
    return f"{nonce}{timestamp}{api_key}{joined}{body}"


def sign_request(
    credentials: Credentials,
    *,
    nonce: str,
    timestamp: str,
    query: dict[str, Any] | None = None,
    body: str = "",
) -> str:
    """Two rounds of SHA-256, the secret entering only in the second."""
    first = hashlib.sha256(
        signature_payload(
            nonce=nonce,
            timestamp=timestamp,
            api_key=credentials.api_key,
            query=query,
            body=body,
        ).encode()
    ).hexdigest()
    return hashlib.sha256(f"{first}{credentials.api_secret}".encode()).hexdigest()


def _plain(value: Decimal) -> str:
    """A decimal as digits, never in scientific notation.

    `str(Decimal("0.00000001"))` is `"1E-8"`, which is not a quantity any
    exchange will read back as one satoshi. Small sizes are normal on these
    contracts, so this is the difference between an order and a rejection.
    """
    return format(value, "f")


def _compact(payload: dict[str, Any]) -> str:
    """The body exactly as it goes on the wire.

    The signature covers the transmitted bytes, so the body must be
    serialised once and both signed and sent — never serialised twice with
    different separators.
    """
    clean = {k: v for k, v in payload.items() if v is not None}
    return json.dumps(clean, separators=(",", ":"), sort_keys=True)


def _decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return default


def _required_decimal(value: Any, field: str) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        raise TradingError(f"missing {field} in exchange response")
    return parsed


class BitunixTradingAdapter:
    """Private trading against Bitunix futures."""

    name = "bitunix"

    def __init__(
        self,
        *,
        rest_url: str = DEFAULT_REST_URL,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._rest_url = rest_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._rest_url,
            timeout=timeout,
            headers={"Content-Type": "application/json", "language": "en-US"},
        )
        self._throttle = AsyncRateLimiter(PRIVATE_RATE_PER_SECOND)

    # --- Plumbing --------------------------------------------------------

    async def _call(
        self,
        method: str,
        path: str,
        credentials: Credentials,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        await self._throttle.acquire()

        nonce = secrets.token_hex(16)
        timestamp = str(int(time.time() * 1000))
        body = _compact(payload) if payload is not None else ""
        headers = {
            "api-key": credentials.api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": sign_request(
                credentials, nonce=nonce, timestamp=timestamp, query=query, body=body
            ),
        }

        clean = {k: v for k, v in (query or {}).items() if v is not None}
        try:
            response = await self._client.request(
                method,
                path,
                params=clean or None,
                # The signed bytes, not a re-serialisation of the dict.
                content=body.encode() if body else None,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            # Retryable only for reads. A timed-out order may well have been
            # placed, so the execution service resolves it by client_id
            # rather than by sending it again.
            raise TradingError(
                f"timed out calling {path}", code="timeout", retryable=method == "GET"
            ) from exc
        except httpx.HTTPError as exc:
            raise TradingError(
                f"network error calling {path}: {exc}", code="network", retryable=method == "GET"
            ) from exc

        if response.status_code == 429:
            raise TradingError(f"rate limited on {path}", code="rate_limited", retryable=True)
        if response.status_code >= 500:
            raise TradingError(
                f"{path} returned {response.status_code}",
                code="upstream",
                retryable=method == "GET",
            )
        if response.status_code >= 400:
            raise TradingError(f"{path} returned {response.status_code}: {response.text[:200]}")

        try:
            parsed = response.json()
        except ValueError as exc:
            raise TradingError(f"{path} returned a non-JSON body") from exc

        if isinstance(parsed, dict) and "code" in parsed:
            code = str(parsed.get("code"))
            if code not in ("0", "00000"):
                message = parsed.get("msg") or parsed.get("message") or "unknown error"
                raise TradingError(f"{path}: {message}", code=code)
            return parsed.get("data")
        return parsed

    # --- Account ---------------------------------------------------------

    async def key_permissions(self, credentials: Credentials) -> KeyPermissions:
        data = await self._call("GET", API_KEY_INFO, credentials)
        row = data if isinstance(data, dict) else {}
        permissions = {str(p).lower() for p in (row.get("permissions") or [])}
        whitelist = tuple(str(ip) for ip in (row.get("ips") or row.get("ipWhitelist") or []))
        return KeyPermissions(
            can_read="read" in permissions or bool(permissions),
            can_trade="trade" in permissions or "futures_trade" in permissions,
            can_withdraw="withdraw" in permissions or "withdrawal" in permissions,
            ip_whitelist=whitelist,
        )

    async def balances(self, credentials: Credentials) -> list[Balance]:
        data = await self._call("GET", ACCOUNT, credentials, query={"marginCoin": "USDT"})
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        out: list[Balance] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                Balance(
                    currency=str(row.get("marginCoin") or "USDT"),
                    equity=_decimal(row.get("equity") or row.get("balance"), Decimal(0))
                    or Decimal(0),
                    available=_decimal(row.get("available"), Decimal(0)) or Decimal(0),
                    used_margin=_decimal(row.get("margin"), Decimal(0)) or Decimal(0),
                    unrealised_pnl=_decimal(row.get("unrealizedPNL"), Decimal(0)) or Decimal(0),
                )
            )
        return out

    async def position_mode(self, credentials: Credentials) -> PositionMode:
        data = await self._call("GET", ACCOUNT, credentials, query={"marginCoin": "USDT"})
        row = data[0] if isinstance(data, list) and data else data
        mode = str((row or {}).get("positionMode") or "").upper()
        return PositionMode.HEDGE if mode in ("HEDGE", "DOUBLE") else PositionMode.ONE_WAY

    async def positions(
        self, credentials: Credentials, *, symbol: str | None = None
    ) -> list[Position]:
        data = await self._call("GET", PENDING_POSITIONS, credentials, query={"symbol": symbol})
        rows = data if isinstance(data, list) else []
        return [p for p in (_parse_position(row) for row in rows) if p is not None]

    async def open_orders(
        self, credentials: Credentials, *, symbol: str | None = None
    ) -> list[Order]:
        data = await self._call("GET", PENDING_ORDERS, credentials, query={"symbol": symbol})
        rows = data.get("orderList") if isinstance(data, dict) else data
        rows = rows if isinstance(rows, list) else []
        return [o for o in (_parse_order(row) for row in rows) if o is not None]

    async def set_leverage(
        self,
        credentials: Credentials,
        symbol: str,
        leverage: int,
        *,
        margin_mode: MarginMode,
    ) -> None:
        await self._call(
            "POST",
            CHANGE_MARGIN_MODE,
            credentials,
            payload={
                "symbol": symbol,
                "marginCoin": "USDT",
                "marginMode": "ISOLATION" if margin_mode is MarginMode.ISOLATED else "CROSS",
            },
        )
        await self._call(
            "POST",
            CHANGE_LEVERAGE,
            credentials,
            payload={"symbol": symbol, "marginCoin": "USDT", "leverage": leverage},
        )

    # --- Orders ----------------------------------------------------------

    async def place_order(self, credentials: Credentials, request: OrderRequest) -> Order:
        data = await self._call("POST", PLACE_ORDER, credentials, payload=_order_payload(request))
        row = data if isinstance(data, dict) else {}
        # The place response is thin — an id and little else. The order is
        # returned as accepted, and its real state comes from open_orders or
        # the stream, not from optimism here.
        return Order(
            order_id=str(row.get("orderId") or ""),
            client_id=str(row.get("clientId") or request.client_id),
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            status=OrderStatus.NEW,
            qty=request.qty,
            filled_qty=Decimal(0),
            price=request.price,
            trade_side=request.trade_side,
            reduce_only=request.reduce_only,
            raw=row,
        )

    async def cancel_order(
        self,
        credentials: Credentials,
        symbol: str,
        *,
        client_id: str | None = None,
        order_id: str | None = None,
    ) -> Order:
        if client_id is None and order_id is None:
            raise TradingError("cancel needs a client_id or an order_id", code="bad_request")
        target: dict[str, Any] = {}
        if order_id is not None:
            target["orderId"] = order_id
        if client_id is not None:
            target["clientId"] = client_id

        await self._call(
            "POST",
            CANCEL_ORDERS,
            credentials,
            payload={"symbol": symbol, "orderList": [target]},
        )
        return Order(
            order_id=order_id or "",
            client_id=client_id or "",
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            status=OrderStatus.CANCELLED,
            qty=Decimal(0),
            filled_qty=Decimal(0),
        )

    async def cancel_all(self, credentials: Credentials, *, symbol: str | None = None) -> int:
        open_orders = await self.open_orders(credentials, symbol=symbol)
        cancelled = 0
        for order in open_orders:
            await self.cancel_order(credentials, order.symbol, order_id=order.order_id)
            cancelled += 1
        return cancelled

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> BitunixTradingAdapter:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


def _order_payload(request: OrderRequest) -> dict[str, Any]:
    """The SPEC §6 field list, as Bitunix names it."""
    payload: dict[str, Any] = {
        "symbol": request.symbol,
        "qty": _plain(request.qty),
        "side": request.side.value,
        "orderType": request.order_type.value,
        "clientId": request.client_id,
        "effect": request.time_in_force.value,
        "reduceOnly": request.reduce_only,
    }
    if request.price is not None:
        payload["price"] = _plain(request.price)
    if request.trade_side is not None:
        payload["tradeSide"] = request.trade_side.value
    if request.position_id is not None:
        payload["positionId"] = request.position_id
    if request.tp_price is not None:
        payload["tpPrice"] = _plain(request.tp_price)
        payload["tpStopType"] = request.tp_stop_type.value
        payload["tpOrderType"] = request.tp_order_type.value
        if request.tp_order_price is not None:
            payload["tpOrderPrice"] = _plain(request.tp_order_price)
    if request.sl_price is not None:
        payload["slPrice"] = _plain(request.sl_price)
        payload["slStopType"] = request.sl_stop_type.value
        payload["slOrderType"] = request.sl_order_type.value
        if request.sl_order_price is not None:
            payload["slOrderPrice"] = _plain(request.sl_order_price)
    return payload


def _parse_order(row: Any) -> Order | None:
    if not isinstance(row, dict):
        return None
    try:
        return Order(
            order_id=str(row.get("orderId") or ""),
            client_id=str(row.get("clientId") or ""),
            symbol=str(row["symbol"]),
            side=OrderSide(str(row.get("side") or "BUY").upper()),
            order_type=OrderType(str(row.get("orderType") or "LIMIT").upper()),
            status=_STATUS.get(str(row.get("status") or "").upper(), OrderStatus.NEW),
            qty=_required_decimal(row.get("qty"), "qty"),
            filled_qty=_decimal(row.get("tradeQty") or row.get("dealQty"), Decimal(0))
            or Decimal(0),
            price=_decimal(row.get("price")),
            average_price=_decimal(row.get("avgPrice")),
            fee=_decimal(row.get("fee")),
            trade_side=TradeSide(str(row["tradeSide"]).upper()) if row.get("tradeSide") else None,
            reduce_only=bool(row.get("reduceOnly")),
            created_at=int(row["ctime"]) if str(row.get("ctime") or "").isdigit() else None,
            updated_at=int(row["mtime"]) if str(row.get("mtime") or "").isdigit() else None,
            raw=row,
        )
    except (KeyError, ValueError, TradingError):
        # One unparseable row must not lose the rest of the list.
        return None


def _parse_position(row: Any) -> Position | None:
    if not isinstance(row, dict):
        return None
    try:
        return Position(
            symbol=str(row["symbol"]),
            side=OrderSide(str(row.get("side") or "BUY").upper()),
            qty=_required_decimal(row.get("qty"), "qty"),
            entry_price=_required_decimal(
                row.get("avgOpenPrice") or row.get("entryValue"), "entry"
            ),
            leverage=int(row.get("leverage") or 1),
            margin_mode=(
                MarginMode.CROSS
                if str(row.get("marginMode") or "").upper() == "CROSS"
                else MarginMode.ISOLATED
            ),
            position_id=str(row["positionId"]) if row.get("positionId") else None,
            mark_price=_decimal(row.get("markPrice")),
            liquidation_price=_decimal(row.get("liqPrice")),
            unrealised_pnl=_decimal(row.get("unrealizedPNL")),
            realised_pnl=_decimal(row.get("realizedPNL")),
            margin=_decimal(row.get("margin")),
            raw=row,
        )
    except (KeyError, ValueError, TradingError):
        return None


__all__ = [
    "BitunixTradingAdapter",
    "TimeInForce",
    "sign_request",
    "signature_payload",
]
