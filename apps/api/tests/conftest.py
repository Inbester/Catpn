"""Test fixtures: a throwaway database per run and an HTTP client."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

# Settings are read at import time, so the environment must be set first.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-anywhere-real-0123456789")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://quanta:quanta_dev_password@localhost:5432/quanta_test",
    ),
)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import quanta.models  # noqa: F401  (registers tables)
from quanta.core.config import get_settings
from quanta.db.base import Base
from quanta.db.session import get_db
from quanta.main import create_app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator:
    """One engine for the session; schema created once and dropped at the end."""
    settings = get_settings()
    eng = create_async_engine(str(settings.database_url), poolclass=NullPool)

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """A session wrapped in a transaction that is rolled back after the test."""
    connection = await engine.connect()
    transaction = await connection.begin()
    # create_savepoint makes the route handlers' own commit() release a
    # SAVEPOINT instead of ending the outer transaction, so the rollback
    # below still undoes everything the test wrote.
    factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """An HTTP client bound to the app, sharing the test's transaction."""
    app = create_app()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=True
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def api_prefix() -> str:
    return get_settings().api_prefix
