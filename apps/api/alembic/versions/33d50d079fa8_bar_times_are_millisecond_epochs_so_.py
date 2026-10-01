"""Bar times are millisecond epochs, so bigint.

Phase 5 declared them as 32-bit integers, which hold seconds until 2038
but not one millisecond timestamp: the first real alert firing failed to
save. Widening is lossless, and nothing could have been stored in them
that does not fit.

Revision ID: 33d50d079fa8
Revises: 381b6755b788
Create Date: 2026-10-01 04:54:33.868380
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "33d50d079fa8"
down_revision: str | None = "381b6755b788"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COLUMNS = (
    ("alerts", "last_fired_bar", True),
    ("alert_events", "bar_time", False),
    ("paper_sessions", "last_bar_time", True),
    ("paper_fills", "bar_time", False),
)


def upgrade() -> None:
    for table, column, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    for table, column, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=nullable,
        )
