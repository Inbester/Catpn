"""Strategy and backtest request/response bodies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_EXPRESSION_LENGTH = 4000


class ExitRulesPayload(BaseModel):
    atr_stop_multiple: float | None = Field(default=None, gt=0)
    atr_length: int = Field(default=14, ge=1, le=500)
    take_profit_r: float | None = Field(default=None, gt=0)
    break_even_at_r: float | None = Field(default=None, gt=0)
    trailing_atr_multiple: float | None = Field(default=None, gt=0)
    exit_on_opposite: bool = True
    time_exit_bars: int | None = Field(default=None, ge=1, le=100_000)


class StrategyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    long_entry: str | None = Field(default=None, max_length=MAX_EXPRESSION_LENGTH)
    short_entry: str | None = Field(default=None, max_length=MAX_EXPRESSION_LENGTH)
    exits: ExitRulesPayload = Field(default_factory=ExitRulesPayload)
    params: dict[str, float] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def _check_params(cls, value: dict[str, float]) -> dict[str, float]:
        if len(value) > 32:
            raise ValueError("A strategy may define at most 32 parameters.")
        for name in value:
            if not name.isidentifier():
                raise ValueError(f"{name!r} is not a valid parameter name.")
        return value


class StrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    long_entry: str | None
    short_entry: str | None
    exits: dict[str, Any]
    params: dict[str, float]
    version: str
    created_at: datetime
    updated_at: datetime


class ValidationResponse(BaseModel):
    """What the Formula view shows while the user types."""

    valid: bool
    version: str | None = None
    error: str | None = None
    position: int | None = None
    # The canonical rendering, which the Builder view mirrors.
    normalized_long: str | None = None
    normalized_short: str | None = None


class BacktestConfigPayload(BaseModel):
    initial_capital: float = Field(default=10_000.0, gt=0, le=1e12)
    margin_percent: float = Field(default=10.0, gt=0, le=100)
    leverage: float = Field(default=10.0, ge=1, le=200)
    margin_mode: Literal["isolated", "cross"] = "isolated"
    maker_fee: float = Field(default=0.0002, ge=0, le=0.01)
    taker_fee: float = Field(default=0.0006, ge=0, le=0.01)
    slippage_bps: float = Field(default=1.0, ge=0, le=1000)
    apply_funding: bool = True
    # Resolving intrabar TP/SL needs 1m bars; off by default because it
    # costs a second query and most runs do not have them stored.
    use_magnifier: bool = True


class BacktestRequest(BaseModel):
    symbol: str = Field(max_length=32)
    interval: str = Field(default="15m", max_length=8)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    config: BacktestConfigPayload = Field(default_factory=BacktestConfigPayload)


class TradeResponse(BaseModel):
    side: str
    entry_time: int
    entry_price: float
    exit_time: int
    exit_price: float
    quantity: float
    margin: float
    leverage: float
    liquidation_price: float
    exit_reason: str
    gross_pnl: float
    fees: float
    funding: float
    net_pnl: float
    return_on_margin: float
    run_up: float
    drawdown: float
    bars_held: int
    equity_after: float


class EquityResponse(BaseModel):
    time: list[int]
    value: list[float]
    drawdown: list[float]


class BacktestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    strategy_version: str
    symbol: str
    interval: str
    start_time: int
    end_time: int
    config: dict[str, Any]
    stats: dict[str, Any]
    trades: list[TradeResponse]
    equity: EquityResponse
    duration_ms: int
    created_at: datetime


class BacktestSummary(BaseModel):
    """A run in the history list, without the trade and equity payloads."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    strategy_version: str
    symbol: str
    interval: str
    stats: dict[str, Any]
    duration_ms: int
    created_at: datetime


class FunctionReference(BaseModel):
    name: str
    min_args: int
    max_args: int
    doc: str
