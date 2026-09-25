"""Alembic environment, wired to the async engine and app settings."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing the models package registers every table on Base.metadata.
import quanta.models  # noqa: F401
from alembic import context
from quanta.core.config import get_settings
from quanta.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", str(get_settings().database_url))
target_metadata = Base.metadata

# Tables converted to TimescaleDB hypertables, and the time column each one
# is partitioned on. create_hypertable() adds its own descending index on
# that column; it is not in the models, so autogenerate would otherwise try
# to drop it on every run.
HYPERTABLES = {"klines": "open_time", "funding_rates": "funding_time"}

# Schemas TimescaleDB manages internally. Nothing in them is ours to migrate.
TIMESCALE_SCHEMAS = {
    "_timescaledb_internal",
    "_timescaledb_catalog",
    "_timescaledb_config",
    "_timescaledb_cache",
    "timescaledb_information",
    "timescaledb_experimental",
}


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Keep Timescale's own objects out of autogenerate."""
    schema = getattr(obj, "schema", None)
    if schema in TIMESCALE_SCHEMAS:
        return False

    if type_ == "index" and reflected and name:
        table_name = getattr(getattr(obj, "table", None), "name", None)
        time_column = HYPERTABLES.get(str(table_name))
        if time_column and name == f"{table_name}_{time_column}_idx":
            return False

    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
