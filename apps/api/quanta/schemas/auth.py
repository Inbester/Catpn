"""Request and response bodies for the auth routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PASSWORD_MIN_LENGTH = 12


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        """Require a mix of character classes.

        Deliberately simple and explicit rather than a score: the frontend
        shows the same four rules, so the messages line up.
        """
        checks = {
            "a lowercase letter": any(c.islower() for c in value),
            "an uppercase letter": any(c.isupper() for c in value),
            "a digit": any(c.isdigit() for c in value),
            "a symbol": any(not c.isalnum() for c in value),
        }
        missing = [name for name, ok in checks.items() if not ok]
        if missing:
            raise ValueError("Password must contain " + ", ".join(missing) + ".")
        return value

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Display name cannot be blank.")
        return cleaned


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    device_label: str | None = Field(default=None, max_length=120)


class MfaVerifyRequest(BaseModel):
    """Step 2 of a 2FA login."""

    ticket: str
    code: str = Field(min_length=6, max_length=14)
    device_label: str | None = Field(default=None, max_length=120)


class TotpEnrolStartResponse(BaseModel):
    secret: str
    provisioning_uri: str
    qr_svg: str


class TotpEnrolConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class TotpEnrolConfirmResponse(BaseModel):
    recovery_codes: list[str]


class TotpDisableRequest(BaseModel):
    password: str = Field(max_length=256)
    code: str = Field(min_length=6, max_length=14)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    is_verified: bool
    totp_enabled: bool
    theme: str
    locale: str
    timezone: str
    calendar: str
    created_at: datetime
    last_login_at: datetime | None


class TokenResponse(BaseModel):
    """A completed login. The refresh token travels in an HttpOnly cookie."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - a scheme name, not a secret
    expires_in: int
    csrf_token: str
    user: UserResponse


class MfaRequiredResponse(BaseModel):
    """Password accepted, TOTP still needed."""

    mfa_required: Literal[True] = True
    ticket: str
    expires_in: int


class PreferencesUpdate(BaseModel):
    theme: Literal["graphite", "paper"] | None = None
    locale: Literal["en", "fa"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    calendar: Literal["gregorian", "jalali"] | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_label: str | None
    user_agent: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
