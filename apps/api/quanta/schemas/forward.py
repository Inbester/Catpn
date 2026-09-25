"""Forward test and Setup request/response bodies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quanta.schemas.strategy import BacktestConfigPayload


class PeriodPayload(BaseModel):
    """One explicit time range.

    Jalali presets are resolved in the browser, which already holds a
    tested calendar implementation. Sending epoch milliseconds keeps a
    single source of truth instead of a second converter that could drift.
    """

    label: str = Field(min_length=1, max_length=80)
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> PeriodPayload:
        if self.end <= self.start:
            raise ValueError("A period must end after it starts.")
        return self


class PeriodComparisonRequest(BaseModel):
    symbol: str = Field(max_length=32)
    interval: str = Field(default="1h", max_length=8)
    reference: PeriodPayload
    test: PeriodPayload
    config: BacktestConfigPayload = Field(default_factory=BacktestConfigPayload)
    monte_carlo_runs: int = Field(default=3000, ge=100, le=20_000)
    confidence: float = Field(default=0.90, gt=0.5, lt=1.0)


class WalkForwardRequest(BaseModel):
    symbol: str = Field(max_length=32)
    interval: str = Field(default="1h", max_length=8)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    in_sample_days: int = Field(default=90, ge=1, le=1000)
    out_of_sample_days: int = Field(default=30, ge=1, le=365)
    max_windows: int = Field(default=12, ge=1, le=60)
    # {param: [values]} searched per window.
    grid: dict[str, list[float]] = Field(default_factory=dict)
    config: BacktestConfigPayload = Field(default_factory=BacktestConfigPayload)

    @model_validator(mode="after")
    def _grid_is_reasonable(self) -> WalkForwardRequest:
        total = 1
        for values in self.grid.values():
            if not values:
                raise ValueError("A parameter in the grid has no values.")
            total *= len(values)
        if total > 400:
            raise ValueError(f"{total} parameter combinations is too many for an interactive run.")
        return self


class SetupPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="#6EA8FE", pattern=r"^#[0-9A-Fa-f]{6}$")
    strategy_id: uuid.UUID
    symbol: str = Field(max_length=32)
    interval: str = Field(default="1h", max_length=8)

    margin_percent: float = Field(gt=0, le=100)
    leverage: float = Field(ge=1, le=200)
    margin_mode: Literal["isolated", "cross"] = "isolated"

    fee_tier: str = Field(default="VIP0", max_length=16)
    maker_fee: float = Field(default=0.0002, ge=0, le=0.01)
    taker_fee: float = Field(default=0.0006, ge=0, le=0.01)
    max_drawdown_budget_percent: float | None = Field(default=None, lt=0, ge=-100)
    risk_of_ruin_limit_percent: float | None = Field(default=None, gt=0, le=100)

    source_run_id: uuid.UUID | None = None

    use_in_backtest: bool = True
    use_in_forward: bool = True
    use_in_paper: bool = False
    use_in_alerts: bool = False


class SetupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str
    strategy_id: uuid.UUID
    strategy_version: str
    strategy_snapshot: dict[str, Any]
    symbol: str
    interval: str
    margin_percent: float
    leverage: float
    margin_mode: str
    exposure: float
    fee_tier: str
    maker_fee: float
    taker_fee: float
    max_drawdown_budget_percent: float | None
    risk_of_ruin_limit_percent: float | None
    source_run_id: uuid.UUID | None
    pipeline: dict[str, Any]
    use_in_backtest: bool
    use_in_forward: bool
    use_in_paper: bool
    use_in_alerts: bool
    use_in_bot: bool
    created_at: datetime
    updated_at: datetime


class StageUpdate(BaseModel):
    stage: Literal["research", "backtest", "forward", "paper", "alerts", "bot"]
    status: Literal["not_started", "running", "passed", "failed"]
    note: str = Field(default="", max_length=500)


class ConflictWarning(BaseModel):
    """A risk that only shows up across Setups, not within one."""

    kind: str
    message: str
    setup_ids: list[uuid.UUID]


class SetupsOverview(BaseModel):
    setups: list[SetupResponse]
    total_exposure: float
    conflicts: list[ConflictWarning]
