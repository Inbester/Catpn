"""Alert request and response bodies (SPEC §3.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Source = Literal["strategy", "price", "indicator", "risk", "market", "system"]
Repeat = Literal["every", "once", "once_per_bar"]
Trigger = Literal["bar_close", "tick"]
DestinationKind = Literal["telegram", "web_push", "webhook", "email"]


class Destination(BaseModel):
    kind: DestinationKind
    target: str = Field(min_length=1, max_length=500)
    label: str = Field(default="", max_length=120)
    # Webhook signing secret. Accepted on write, never returned.
    secret: str = Field(default="", max_length=200)


class AlertPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source: Source
    setup_id: uuid.UUID | None = None
    symbol: str = Field(max_length=32)
    interval: str = Field(default="1h", max_length=8)
    condition: dict[str, Any] = Field(default_factory=dict)

    trigger_mode: Trigger = "bar_close"
    repeat_mode: Repeat = "once_per_bar"
    expires_at: datetime | None = None

    quiet_from_hour: int | None = Field(default=None, ge=0, le=23)
    quiet_to_hour: int | None = Field(default=None, ge=0, le=23)

    template: str = Field(default="", max_length=2000)
    locale: Literal["en", "fa"] = "en"
    destinations: list[Destination] = Field(default_factory=list, max_length=10)
    enabled: bool = True

    @model_validator(mode="after")
    def _quiet_hours_are_a_pair(self) -> AlertPayload:
        if (self.quiet_from_hour is None) != (self.quiet_to_hour is None):
            raise ValueError("Quiet hours need both a start and an end.")
        return self

    @model_validator(mode="after")
    def _strategy_alerts_need_a_setup(self) -> AlertPayload:
        # A strategy alert without a Setup would fire on whatever the
        # draft says today, which is the failure Setups exist to prevent.
        if self.source == "strategy" and self.setup_id is None:
            raise ValueError(
                "A strategy alert needs a setup, so it fires on the version that was validated."
            )
        return self


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source: str
    setup_id: uuid.UUID | None
    symbol: str
    interval: str
    condition: dict[str, Any]
    trigger_mode: str
    repeat_mode: str
    expires_at: datetime | None
    quiet_from_hour: int | None
    quiet_to_hour: int | None
    template: str
    locale: str
    destinations: list[dict[str, Any]]
    enabled: bool
    last_fired_at: datetime | None
    fire_count: int
    created_at: datetime


class AlertEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_id: uuid.UUID
    bar_time: int
    price: str
    message: str
    merged_count: int
    quiet: bool
    deliveries: list[dict[str, Any]]
    created_at: datetime


class ChannelPayload(BaseModel):
    kind: DestinationKind
    label: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=500)
    secrets: dict[str, Any] = Field(default_factory=dict)


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    label: str
    target: str
    verified: bool
    enabled: bool
    created_at: datetime


class TestSendRequest(BaseModel):
    """Send the alert's own template to its own destinations, now."""

    message: str = Field(default="", max_length=2000)


class PreviewRequest(BaseModel):
    template: str = Field(default="", max_length=2000)
    locale: Literal["en", "fa"] = "en"
    context: dict[str, Any] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    message: str
    # Variables the template names that nothing will fill in.
    unknown_variables: list[str]


class PaperStartRequest(BaseModel):
    setup_id: uuid.UUID
    initial_capital: float = Field(default=10_000.0, gt=0)
    # The band the backtest said to expect, so live has something to be
    # read against rather than nothing.
    expected_net_percent: float | None = None
    expected_low_percent: float | None = None
    expected_high_percent: float | None = None
    drawdown_limit_percent: float | None = Field(default=None, lt=0, ge=-100)


class PaperFillRequest(BaseModel):
    """A fill from the live feed, with what it actually cost."""

    side: Literal["long", "short"]
    action: Literal["entry", "exit"] = "entry"
    bar_time: int = Field(ge=0)
    signal_price: float = Field(gt=0)
    fill_price: float = Field(gt=0)
    quantity: float = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    fee: float = 0.0
    funding: float = 0.0
    net_pnl: float = 0.0


class PromoteRequest(BaseModel):
    # SPEC §3.3 allows promotion past a failing check behind 2FA. It is
    # recorded, because a bot promoted on an override is not the same
    # thing as one that passed.
    override: bool = False
    totp_code: str = Field(default="", max_length=10)
