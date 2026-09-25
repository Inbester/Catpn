"""Market data response shapes.

Prices are serialised as strings, not numbers. JSON numbers are IEEE
doubles, and a price that loses its last digit in transit is a price the
chart draws wrong and the backtest costs wrong.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BarResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    open_time: int = Field(serialization_alias="t")
    open: str = Field(serialization_alias="o")
    high: str = Field(serialization_alias="h")
    low: str = Field(serialization_alias="l")
    close: str = Field(serialization_alias="c")
    volume: str = Field(serialization_alias="v")
    closed: bool = Field(default=True, serialization_alias="closed")


class KlineResponse(BaseModel):
    symbol: str
    interval: str
    price_type: str
    bars: list[BarResponse]


class InstrumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    base: str
    quote: str
    min_leverage: int
    max_leverage: int
    default_leverage: int
    base_precision: int
    quote_precision: int
    status: str


class TickerResponse(BaseModel):
    symbol: str
    last: str
    change_percent_24h: str
    high_24h: str | None = None
    low_24h: str | None = None
    quote_volume_24h: str | None = None
    mark_price: str | None = None
    index_price: str | None = None
    funding_rate: str | None = None
    next_funding_time: int | None = None
    open_interest: str | None = None


class FundingResponse(BaseModel):
    funding_time: int
    funding_rate: str
    mark_price: str | None = None


class FeeTierResponse(BaseModel):
    tier: str
    maker: str
    taker: str
    requirement_volume_30d: str | None = None
    requirement_balance: str | None = None


class PositionTierResponse(BaseModel):
    level: int
    start_value: str
    end_value: str
    leverage: int
    maintenance_margin_rate: str


class ServerTimeResponse(BaseModel):
    """Bar countdowns use exchange server time, not the browser clock."""

    server_time: int
