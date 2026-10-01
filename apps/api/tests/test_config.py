"""Configuration guards."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from quanta.core.config import DEV_SECRET_KEY, Settings

# conftest exports ENVIRONMENT, SECRET_KEY and friends for the HTTP tests.
# These cases are about the defaults and the guard, so the ambient values have
# to go or they would mask exactly what is under test.
_MANAGED_VARS = (
    "ENVIRONMENT",
    "DEBUG",
    "SECRET_KEY",
    "VAULT_MASTER_KEY",
    "COOKIE_SECURE",
    "CORS_ORIGINS",
    "RATE_LIMIT_ENABLED",
    "DATABASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _MANAGED_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    """Build Settings without reading the developer's local .env."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_development_defaults_are_usable() -> None:
    settings = make()
    assert settings.environment == "development"
    assert settings.is_production is False
    assert settings.access_token_ttl_minutes == 15


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_dev_secret_is_refused_in_production(environment: str) -> None:
    with pytest.raises(ValidationError, match="development placeholder"):
        make(environment=environment, cookie_secure=True)


def test_short_secret_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        make(environment="production", secret_key="too-short", cookie_secure=True)


def test_insecure_cookies_are_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        make(environment="production", secret_key="k" * 48, cookie_secure=False)


def test_debug_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="DEBUG"):
        make(environment="production", secret_key="k" * 48, cookie_secure=True, debug=True)


def test_valid_production_config_is_accepted() -> None:
    settings = make(
        environment="production",
        secret_key="k" * 48,
        # Its own secret, not the session one: see TestVaultMasterKey.
        vault_master_key="v" * 48,
        cookie_secure=True,
    )
    assert settings.is_production is True
    assert settings.secret_key != DEV_SECRET_KEY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
        ('["http://a.test"]', ["http://a.test"]),
        ("http://a.test", ["http://a.test"]),
    ],
)
def test_cors_origins_accepts_both_formats(raw: str, expected: list[str]) -> None:
    assert make(cors_origins=raw).cors_origins == expected


class TestVaultMasterKey:
    """SPEC §5: the exchange-key vault must not share the session secret.

    One leak should not cost both the sessions and the keys that can place
    orders, so production refuses a deployment where they are the same —
    or where the vault key is missing entirely.
    """

    def test_production_refuses_a_missing_vault_key(self) -> None:
        with pytest.raises(ValidationError, match="VAULT_MASTER_KEY must be set"):
            make(
                environment="production",
                secret_key="a" * 48,
                vault_master_key="",
                cookie_secure=True,
                debug=False,
            )

    def test_production_refuses_a_vault_key_equal_to_the_session_key(self) -> None:
        shared = "a" * 48
        with pytest.raises(ValidationError, match="must differ from SECRET_KEY"):
            make(
                environment="production",
                secret_key=shared,
                vault_master_key=shared,
                cookie_secure=True,
                debug=False,
            )

    def test_production_refuses_a_short_vault_key(self) -> None:
        with pytest.raises(ValidationError, match="at least 32"):
            make(
                environment="production",
                secret_key="a" * 48,
                vault_master_key="short",
                cookie_secure=True,
                debug=False,
            )

    def test_two_distinct_strong_keys_are_accepted(self) -> None:
        settings = make(
            environment="production",
            secret_key="a" * 48,
            vault_master_key="b" * 48,
            cookie_secure=True,
            debug=False,
        )
        assert settings.vault_master_key != settings.secret_key

    def test_development_may_leave_it_unset(self) -> None:
        """Falling back keeps `docker compose up` a one-liner locally."""
        settings = make(environment="development", secret_key="a" * 48)
        assert settings.vault_master_key == ""

    def test_the_vault_uses_its_own_key_when_one_is_set(self) -> None:
        """A row sealed under the vault key must not open under the
        session key, or separating them bought nothing."""
        from quanta.services.keyvault import KeyVault, LocalMasterKey, VaultError

        settings = make(secret_key="a" * 48, vault_master_key="b" * 48)
        vault = KeyVault.local(settings)
        sealed = vault.seal("exchange-secret", context="ctx")

        session_keyed = KeyVault(LocalMasterKey(settings.secret_key), settings=settings)
        with pytest.raises(VaultError):
            session_keyed.open(sealed, context="ctx")
