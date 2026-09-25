"""Password hashing, TOTP, JWT and CSRF primitives.

The rules from SPEC §5:

* Argon2id for passwords.
* TOTP 2FA, required before any bot / API-key / kill-switch action.
* Short-lived access JWTs; refresh tokens live in HttpOnly SameSite=strict
  cookies and are stored server-side as hashes so they can be revoked.
* CSRF tokens on every cookie-authenticated route.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type

from quanta.core.config import get_settings

# OWASP-recommended Argon2id parameters (19 MiB, t=2, p=1).
_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

TokenType = Literal["access", "refresh", "mfa"]


# --- Passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against its Argon2id hash. Never raises on mismatch."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker parameters than the current policy."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


# --- Opaque tokens (refresh tokens, link codes) -----------------------------


def generate_token(nbytes: int = 48) -> str:
    """A URL-safe random token. Shown to the client exactly once."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Hash an opaque token for storage.

    SHA-256 is right here (unlike for passwords): these tokens already carry
    48 bytes of entropy, so stretching buys nothing and costs latency on
    every refresh.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# --- JWT --------------------------------------------------------------------


def create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Sign a JWT for ``subject``."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": settings.app_name,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID | str, **extra: Any) -> str:
    settings = get_settings()
    return create_token(
        str(user_id),
        "access",
        timedelta(minutes=settings.access_token_ttl_minutes),
        extra or None,
    )


def create_mfa_ticket(user_id: uuid.UUID | str) -> str:
    """A short-lived ticket proving step 1 (password) of a 2FA login."""
    settings = get_settings()
    return create_token(
        str(user_id),
        "mfa",
        timedelta(seconds=settings.mfa_ticket_ttl_seconds),
    )


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired or of the wrong type."""


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a JWT, enforcing its ``typ`` claim."""
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require": ["exp", "sub", "typ", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("typ") != expected_type:
        raise TokenError(f"expected a {expected_type} token")
    return payload


# --- TOTP -------------------------------------------------------------------


def generate_totp_secret() -> str:
    """A fresh base32 TOTP secret."""
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, account_name: str) -> str:
    """The ``otpauth://`` URI for an authenticator app QR code."""
    settings = get_settings()
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=settings.totp_issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code, tolerating one step of clock drift."""
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_recovery_codes(count: int = 10) -> list[str]:
    """Single-use recovery codes, formatted ``xxxxx-xxxxx``."""
    codes = []
    for _ in range(count):
        raw = base64.b32encode(secrets.token_bytes(7)).decode("ascii").rstrip("=").lower()
        codes.append(f"{raw[:5]}-{raw[5:10]}")
    return codes


# --- CSRF -------------------------------------------------------------------


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
