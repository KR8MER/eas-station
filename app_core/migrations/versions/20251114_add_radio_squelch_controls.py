"""Add carrier squelch controls to radio receivers.

Revision ID: 20251114_add_radio_squelch_controls
Revises: 20251113_add_serial_mode_to_led_sign_status
Create Date: 2025-11-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251114_add_radio_squelch_controls"
down_revision = "20251113_add_serial_mode_to_led_sign_status"
branch_labels = None
depends_on = None


TABLE_NAME = "radio_receivers"

SQUELCH_COLUMNS = (
    ("squelch_enabled", sa.Boolean(), sa.false()),
    ("squelch_threshold_db", sa.Float(), sa.text("-65")),
    ("squelch_open_ms", sa.Integer(), sa.text("150")),
    ("squelch_close_ms", sa.Integer(), sa.text("750")),
    ("squelch_alarm", sa.Boolean(), sa.false()),
)


def _table_exists(bind, table_name: str) -> bool:
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _existing_columns(bind, table_name: str) -> set[str]:
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Add squelch configuration columns for SDR receivers."""

    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return

    columns = _existing_columns(bind, TABLE_NAME)

    for name, column_type, default in SQUELCH_COLUMNS:
        if name in columns:
            continue

        op.add_column(
            TABLE_NAME,
            sa.Column(name, column_type, nullable=False, server_default=default),
        )
        # Remove the server default after populating existing rows
        op.alter_column(TABLE_NAME, name, server_default=None)


def downgrade() -> None:
    """Remove squelch configuration columns."""

    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return

    columns = _existing_columns(bind, TABLE_NAME)

    for name, *_ in reversed(SQUELCH_COLUMNS):
        if name not in columns:
            continue
        op.drop_column(TABLE_NAME, name)
