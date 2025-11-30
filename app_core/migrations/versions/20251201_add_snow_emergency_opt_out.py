"""Add opt-out flag for snow emergencies.

Create Date: 2025-12-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251201_add_snow_emergency_opt_out"
down_revision = "20251129_add_snow_emergencies_table"
branch_labels = None
depends_on = None


TABLE_NAME = "snow_emergencies"
COLUMN_NAME = "issues_emergencies"


def _table_exists() -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return TABLE_NAME in inspector.get_table_names()
    except Exception:
        return False


def _column_exists() -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        columns = [col["name"] for col in inspector.get_columns(TABLE_NAME)]
        return COLUMN_NAME in columns
    except Exception:
        return False


def upgrade() -> None:
    if not _table_exists() or _column_exists():
        return

    op.add_column(
        TABLE_NAME,
        sa.Column(COLUMN_NAME, sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # Ensure existing rows default to issuing snow emergencies
    conn = op.get_bind()
    conn.execute(
        sa.text(
            f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = TRUE WHERE {COLUMN_NAME} IS NULL"
        )
    )


def downgrade() -> None:
    if not _table_exists() or not _column_exists():
        return

    op.drop_column(TABLE_NAME, COLUMN_NAME)
