"""Market data routes, including the client WebSocket fan-out."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Annotated

import structlog
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from quanta.api.deps import CurrentUser, DbDep
from quanta.core.redis_client import get_redis
from quanta.core.security import TokenError, decode_token
from quanta.exchanges.base import ExchangeError, Interval, PriceType
from quanta.schemas.market import (
    BarResponse,
    FeeTierResponse,
    FundingResponse,
    InstrumentResponse,
    KlineResponse,
    PositionTierResponse,
    ServerTimeResponse,
    TickerResponse,
)
from quanta.services import market_store
from quanta.services.market_data import channel_for, subscribe_channel, ticker_channel

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

MAX_BARS_PER_REQUEST = 5000


def _parse_interval(value: str) -> Interval:
    try:
        return Interval(value)
    except ValueError as exc:
        supported = ", ".join(i.value for i in Interval)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported interval {value!r}. Supported: {supported}.",
        ) from exc


@router.get("/time", response_model=ServerTimeResponse)
async def server_time() -> ServerTimeResponse:
    """Server clock, for the candle countdown (SPEC §3.1)."""
    return ServerTimeResponse(server_time=int(time.time() * 1000))


@router.get("/instruments", response_model=list[InstrumentResponse])
async def list_instruments(_user: CurrentUser, db: DbDep) -> list[InstrumentResponse]:
    """Cached contract metadata for the watchlist and research ranges."""
    instruments = await market_store.read_instruments(db)
    return [InstrumentResponse.model_validate(row) for row in instruments]


@router.get("/klines", response_model=KlineResponse)
async def klines(
    _user: CurrentUser,
    db: DbDep,
    symbol: str = Query(max_length=32),
    interval: str = Query(default="15m", max_length=8),
    start: int | None = Query(default=None, ge=0),
    end: int | None = Query(default=None, ge=0),
    limit: int = Query(default=1000, ge=1, le=MAX_BARS_PER_REQUEST),
    price_type: PriceType = Query(default="LAST"),
) -> KlineResponse:
    """Stored bars for a series.

    Reads Timescale, never the exchange: SPEC §6 allows 10 requests a
    second per IP, which per-user live queries would exhaust immediately.
    """
    parsed = _parse_interval(interval)
    bars = await market_store.read_bars(
        db,
        symbol.upper(),
        parsed,
        start=start,
        end=end,
        limit=limit,
        price_type=price_type,
    )
    return KlineResponse(
        symbol=symbol.upper(),
        interval=parsed.value,
        price_type=price_type,
        bars=[
            BarResponse(
                open_time=bar.open_time,
                open=str(bar.open),
                high=str(bar.high),
                low=str(bar.low),
                close=str(bar.close),
                volume=str(bar.volume),
                closed=bar.closed,
            )
            for bar in bars
        ],
    )


@router.get("/funding", response_model=list[FundingResponse])
async def funding(
    _user: CurrentUser,
    db: DbDep,
    symbol: str = Query(max_length=32),
    start: int | None = Query(default=None, ge=0),
    end: int | None = Query(default=None, ge=0),
) -> list[FundingResponse]:
    entries = await market_store.read_funding(db, symbol.upper(), start=start, end=end)
    return [
        FundingResponse(
            funding_time=entry.funding_time,
            funding_rate=str(entry.funding_rate),
            mark_price=str(entry.mark_price) if entry.mark_price is not None else None,
        )
        for entry in entries
    ]


@router.get("/tickers", response_model=list[TickerResponse])
async def tickers(_user: CurrentUser) -> list[TickerResponse]:
    """Live 24h rollups for the watchlist."""
    from quanta.api.market_runtime import get_market_service

    service = get_market_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market data is not connected.",
        )

    try:
        rows = await service.adapter.tickers()
    except ExchangeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return [
        TickerResponse(
            symbol=row.symbol,
            last=str(row.last),
            change_percent_24h=str(row.change_percent_24h),
            high_24h=str(row.high_24h) if row.high_24h is not None else None,
            low_24h=str(row.low_24h) if row.low_24h is not None else None,
            quote_volume_24h=str(row.quote_volume_24h)
            if row.quote_volume_24h is not None
            else None,
            mark_price=str(row.mark_price) if row.mark_price is not None else None,
            index_price=str(row.index_price) if row.index_price is not None else None,
            funding_rate=str(row.funding_rate) if row.funding_rate is not None else None,
            next_funding_time=row.next_funding_time,
            open_interest=str(row.open_interest) if row.open_interest is not None else None,
        )
        for row in rows
    ]


@router.get("/fee-tiers", response_model=list[FeeTierResponse])
async def fee_tiers(_user: CurrentUser) -> list[FeeTierResponse]:
    from quanta.api.market_runtime import get_market_service

    service = get_market_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market data is not connected.",
        )
    tiers = await service.adapter.fee_tiers()
    return [
        FeeTierResponse(
            tier=tier.tier,
            maker=str(tier.maker),
            taker=str(tier.taker),
            requirement_volume_30d=str(tier.requirement_volume_30d)
            if tier.requirement_volume_30d is not None
            else None,
            requirement_balance=str(tier.requirement_balance)
            if tier.requirement_balance is not None
            else None,
        )
        for tier in tiers
    ]


@router.get("/position-tiers", response_model=list[PositionTierResponse])
async def position_tiers(
    _user: CurrentUser, symbol: str = Query(max_length=32)
) -> list[PositionTierResponse]:
    from quanta.api.market_runtime import get_market_service

    service = get_market_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market data is not connected.",
        )
    try:
        tiers = await service.adapter.position_tiers(symbol.upper())
    except ExchangeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return [
        PositionTierResponse(
            level=tier.level,
            start_value=str(tier.start_value),
            end_value=str(tier.end_value),
            leverage=tier.leverage,
            maintenance_margin_rate=str(tier.maintenance_margin_rate),
        )
        for tier in tiers
    ]


@router.websocket("/stream")
async def market_stream(
    websocket: WebSocket,
    token: Annotated[str, Query()],
    symbol: Annotated[str, Query(max_length=32)],
    interval: Annotated[str, Query(max_length=8)] = "15m",
) -> None:
    """Live bars and ticker for one series.

    Authenticated with the access token as a query parameter: the browser
    WebSocket API cannot set an Authorization header. The token is the same
    short-lived 15-minute JWT used everywhere else.
    """
    try:
        decode_token(token, "access")
    except TokenError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Not authenticated.")
        return

    try:
        parsed = Interval(interval)
    except ValueError:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason=f"Unsupported interval {interval}."
        )
        return

    redis = get_redis()
    if redis is None:
        await websocket.close(
            code=status.WS_1011_INTERNAL_ERROR, reason="Live data is unavailable."
        )
        return

    from quanta.api.market_runtime import get_market_service

    service = get_market_service()
    symbol = symbol.upper()

    await websocket.accept()

    # Adding the series to the shared upstream connection is what makes it
    # live; many clients watching the same series share one exchange socket.
    if service is not None:
        service.subscribe(symbol, parsed)

    channels = [channel_for(symbol, parsed), ticker_channel(symbol)]
    relay: asyncio.Task[None] | None = None

    async def pump() -> None:
        async for message in subscribe_channel(redis, channels):
            await websocket.send_text(json.dumps(message, separators=(",", ":")))

    try:
        relay = asyncio.create_task(pump())
        while True:
            # The client only sends keepalives; a disconnect raises here.
            raw = await websocket.receive_text()
            if raw == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # a relay failure must close cleanly
        logger.warning("market_stream_error", symbol=symbol, error=str(exc))
    finally:
        if relay is not None:
            relay.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await relay
