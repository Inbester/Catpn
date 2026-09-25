"""Unit tests for the security primitives."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from quanta.core.security import (
    TokenError,
    create_access_token,
    create_token,
    decode_token,
    generate_recovery_codes,
    generate_totp_secret,
    hash_password,
    hash_token,
    totp_provisioning_uri,
    verify_password,
    verify_totp,
)


def test_password_round_trip() -> None:
    hashed = hash_password("Correct-Horse-Battery-9!")
    assert hashed.startswith("$argon2id$")
    assert verify_password("Correct-Horse-Battery-9!", hashed)
    assert not verify_password("wrong", hashed)


def test_password_hashes_are_salted() -> None:
    assert hash_password("same-password-1!") != hash_password("same-password-1!")


def test_verify_password_rejects_garbage_hash() -> None:
    assert not verify_password("anything", "not-a-hash")


def test_access_token_round_trip() -> None:
    token = create_access_token("8d4b1f0c-0000-4000-8000-000000000001")
    claims = decode_token(token, "access")
    assert claims["sub"] == "8d4b1f0c-0000-4000-8000-000000000001"
    assert claims["typ"] == "access"


def test_token_type_is_enforced() -> None:
    """An MFA ticket must not be usable as an access token."""
    ticket = create_token("user-1", "mfa", timedelta(minutes=5))
    with pytest.raises(TokenError):
        decode_token(ticket, "access")


def test_expired_token_is_rejected() -> None:
    token = create_token("user-1", "access", timedelta(seconds=-1))
    with pytest.raises(TokenError):
        decode_token(token, "access")


def test_tampered_token_is_rejected() -> None:
    token = create_access_token("user-1")
    head, payload, _sig = token.split(".")
    with pytest.raises(TokenError):
        decode_token(f"{head}.{payload}.AAAA", "access")


def test_totp_accepts_a_current_code() -> None:
    import pyotp

    secret = generate_totp_secret()
    assert verify_totp(secret, pyotp.TOTP(secret).now())
    assert not verify_totp(secret, "000000")
    assert not verify_totp(secret, "not-a-code")


def test_provisioning_uri_carries_issuer_and_account() -> None:
    uri = totp_provisioning_uri(generate_totp_secret(), "trader@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=Quanta" in uri


def test_recovery_codes_are_unique_and_formatted() -> None:
    codes = generate_recovery_codes(10)
    assert len(set(codes)) == 10
    assert all(len(c) == 11 and c[5] == "-" for c in codes)


def test_hash_token_is_stable_and_one_way() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")
    assert len(hash_token("abc")) == 64


def test_argon2_cost_is_not_trivial() -> None:
    """A hash that is too fast to compute is too fast to brute-force."""
    started = time.perf_counter()
    hash_password("timing-check-1!")
    assert time.perf_counter() - started > 0.005
