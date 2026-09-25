"""Application settings, loaded from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Usable in development so the stack runs with no configuration; refused in
# staging and production by the validator at the bottom of Settings.
DEV_SECRET_KEY = "dev-only-insecure-secret-key-change-me-in-any-real-deployment"  # noqa: S105


class Settings(BaseSettings):
    """Runtime configuration.

    Every value can be overridden with an environment variable of the same
    name (case-insensitive). See ``.env.example`` for the development defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -----------------------------------------------------------
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    app_name: str = "Quanta"
    api_prefix: str = "/api/v1"

    # --- Database ----------------------------------------------------------
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://quanta:quanta_dev_password@localhost:5432/quanta"  # type: ignore[assignment]
    )
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # --- Redis -------------------------------------------------------------
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")  # type: ignore[assignment]

    # --- Auth --------------------------------------------------------------
    # 32+ random bytes. Generate with: python -c "import secrets;print(secrets.token_urlsafe(48))"
    secret_key: str = DEV_SECRET_KEY
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    totp_issuer: str = "Quanta"
    # Pending-2FA tickets are short-lived: just long enough to type six digits.
    mfa_ticket_ttl_seconds: int = 300

    # Cookie names and flags.
    refresh_cookie_name: str = "quanta_refresh"
    csrf_cookie_name: str = "quanta_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    cookie_secure: bool = True
    cookie_domain: str | None = None

    # --- Market data -------------------------------------------------------
    # Point these at the simulator (python -m quanta.exchanges.sim) when the
    # venue is unreachable — a restricted region per SPEC §9, or a network
    # policy that blocks it.
    exchange_rest_url: str = "https://fapi.bitunix.com"
    exchange_ws_url: str = "wss://fapi.bitunix.com/public/"
    # Symbols warmed up on boot so the chart opens on stored data.
    market_warm_symbols: Annotated[list[str], NoDecode] = ["BTCUSDT", "ETHUSDT"]
    market_warm_intervals: Annotated[list[str], NoDecode] = ["1m", "15m", "1h"]
    market_warm_bars: int = 1500
    # Off in tests, where no exchange is running.
    market_data_enabled: bool = True

    # --- CORS --------------------------------------------------------------
    # NoDecode: take the env value as a plain string so the validator below
    # can accept a comma-separated list, not only JSON.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # --- Rate limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    # Per-IP budget for the whole API.
    rate_limit_global_per_minute: int = 300
    # Much tighter budget for credential endpoints (per IP).
    rate_limit_auth_per_minute: int = 10

    # --- Security headers --------------------------------------------------
    # COOP/COEP are required for SharedArrayBuffer (browser compute, phase 4).
    cross_origin_isolation: bool = True
    hsts_max_age_seconds: int = 31_536_000

    @field_validator("cors_origins", "market_warm_symbols", "market_warm_intervals", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        """Accept a comma-separated string as well as a JSON list."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                import json

                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _reject_insecure_production_config(self) -> Settings:
        """Fail fast rather than run a deployment with development defaults."""
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.secret_key == DEV_SECRET_KEY:
            problems.append("SECRET_KEY is still the development placeholder")
        if len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be at least 32 characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true")
        if self.debug:
            problems.append("DEBUG must be false")

        if problems:
            raise ValueError(
                f"Unsafe configuration for environment={self.environment}: " + "; ".join(problems)
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment in ("staging", "production")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
