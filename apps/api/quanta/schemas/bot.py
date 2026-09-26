"""Request shapes for exchange keys and bots (SPEC §3.5, §3.6)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ExchangeKeyCreate(BaseModel):
    """The one request in the API that carries a secret.

    It is never echoed back, never logged, and never stored in the clear.
    """

    label: str = Field(min_length=1, max_length=64)
    exchange: Literal["bitunix"] = "bitunix"
    api_key: str = Field(min_length=8, max_length=256)
    api_secret: str = Field(min_length=8, max_length=256)


class RiskLimitsPayload(BaseModel):
    max_position_notional: Decimal = Field(gt=0)
    max_daily_loss: Decimal = Field(gt=0)
    max_drawdown_percent: Decimal = Field(gt=0, le=100)
    max_leverage: int = Field(ge=1, le=200)
    max_orders_per_minute: int = Field(ge=1, le=120)


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    setup_id: uuid.UUID
    exchange_key_id: uuid.UUID
    symbol: str = Field(min_length=1, max_length=32)
    interval: str = Field(min_length=1, max_length=8)
    leverage: int = Field(ge=1, le=200)
    margin_mode: Literal["ISOLATED", "CROSS"] = "ISOLATED"
    position_mode: Literal["ONE_WAY", "HEDGE"] = "ONE_WAY"
    limits: RiskLimitsPayload


class BotUpdate(BaseModel):
    """Editing a stopped bot.

    Raising a risk limit needs 2FA; lowering one does not (SPEC §3.5), so
    the code is optional here and the route decides whether it was needed.
    """

    name: str | None = Field(default=None, min_length=1, max_length=80)
    leverage: int | None = Field(default=None, ge=1, le=200)
    limits: RiskLimitsPayload | None = None
    code: str | None = Field(default=None, min_length=6, max_length=10)


class SecondFactor(BaseModel):
    """A 2FA code, for the actions SPEC §3.5 requires one for."""

    code: str = Field(min_length=6, max_length=10)


class KillRequest(SecondFactor):
    """The kill switch.

    `confirm_flatten` has no default: the caller has to say, in the
    request, that it understands positions will be closed at market. A
    default would make the dangerous part invisible.
    """

    confirm_flatten: bool
