"""Research request and response bodies (SPEC §3.2)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator

from quanta.schemas.strategy import BacktestConfigPayload

# One backtest per cell, so the grid is bounded on the way in.
MAX_CELLS = 144
MAX_SURFACE_POINTS = 200


class LeverageRequest(BaseModel):
    symbol: str = Field(max_length=32)
    interval: str = Field(default="1h", max_length=8)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    margins: list[float] = Field(default=[5.0, 10.0, 20.0, 40.0], min_length=1, max_length=12)
    leverages: list[float] = Field(default=[1.0, 2.0, 5.0, 10.0, 25.0], min_length=1, max_length=12)
    # Negative: the deepest drawdown the user will accept.
    budget_percent: float | None = Field(default=None, lt=0, ge=-100)
    config: BacktestConfigPayload = Field(default_factory=BacktestConfigPayload)

    @model_validator(mode="after")
    def _within_limits(self) -> LeverageRequest:
        if any(m <= 0 or m > 100 for m in self.margins):
            raise ValueError("Each margin must be above 0 and at most 100 percent.")
        if any(lev < 1 or lev > 200 for lev in self.leverages):
            raise ValueError("Each leverage must be between 1 and 200.")
        cells = len(self.margins) * len(self.leverages)
        if cells > MAX_CELLS:
            raise ValueError(
                f"{cells} cells is more than the {MAX_CELLS} an interactive sweep runs."
            )
        return self


class StudyRequest(BaseModel):
    symbol: str = Field(max_length=32)
    interval: str = Field(default="1h", max_length=8)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    config: BacktestConfigPayload = Field(default_factory=BacktestConfigPayload)


class RobustnessRequest(StudyRequest):
    grid: dict[str, list[float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _surface_is_reasonable(self) -> RobustnessRequest:
        total = 1
        for values in self.grid.values():
            if not values:
                raise ValueError("A parameter in the grid has no values.")
            total *= len(values)
        if total > MAX_SURFACE_POINTS:
            raise ValueError(
                f"{total} parameter points is more than the {MAX_SURFACE_POINTS} "
                "an interactive surface runs."
            )
        return self


class DiscoverPlanRequest(BaseModel):
    symbol: str = Field(max_length=32)
    interval: str = Field(default="1h", max_length=8)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    sources: list[str] = Field(default=["price", "ema", "rsi"], max_length=8)
    mix_indicators: bool = False


class DiscoverRequest(DiscoverPlanRequest):
    # A round trip in percent. Default is Bitunix VIP0 taker both ways plus
    # slippage, because a search with costs off finds rules nobody can take.
    cost_percent: float = Field(default=0.13, ge=0, le=5)
    max_hits: int = Field(default=200, ge=1, le=2000)


class JobResponse(BaseModel):
    id: str
    kind: str
    label: str
    state: str
    done: int
    total: int
    percent: float
    created_at: str
    finished_at: str | None
    error: str | None


class JobHistoryEntry(BaseModel):
    id: str
    kind: str
    label: str
    state: str
    source: str
    done: int
    total: int
    created_at: str
    finished_at: str | None
    error: str | None
    request: dict[str, Any]


class JobResultResponse(JobResponse):
    result: dict[str, Any] | None = None


class SourceInfo(BaseModel):
    key: str
    label: str
    lines: list[str]


class StrategyRef(BaseModel):
    strategy_id: uuid.UUID


class ComputeRoutingUpdate(BaseModel):
    """Per-feature compute routing. Locked features are refused, not fixed."""

    routing: dict[str, str] = Field(default_factory=dict)
    cpu_share_percent: int | None = Field(default=None, ge=0, le=100)
    gpu_duty_percent: int | None = Field(default=None, ge=0, le=100)
    ram_budget_mb: int | None = Field(default=None, ge=128, le=131_072)
    device_label: str | None = Field(default=None, max_length=120)
    # What the browser reports about itself: cores, memory hint, WebGPU.
    local_profile: dict[str, Any] | None = None


class ComputeResponse(BaseModel):
    routing: dict[str, str]
    locked: dict[str, str]
    cpu_share_percent: int
    gpu_duty_percent: int
    ram_budget_mb: int
    local_profile: dict[str, Any]
    device_label: str
    server: dict[str, Any]
