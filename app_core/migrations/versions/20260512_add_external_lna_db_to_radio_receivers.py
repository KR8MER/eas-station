"""Add external_lna_db column to radio_receivers.

Outboard LNAs sit between the antenna and the SDR; the SDR's hardware AGC
has no idea they exist and will happily drive the front-end into clipping
when one is present. We record the LNA's gain (dB) per receiver so the
driver can disable AGC and pick a manual gain biased down to compensate.

Revision ID: 20260512_add_external_lna_db_to_radio_receivers
Revises: 20251114_add_radio_squelch_controls
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260512_add_external_lna_db_to_radio_receivers"
down_revision = "20251114_add_radio_squelch_controls"
branch_labels = None
depends_on = None


TABLE_NAME = "radio_receivers"
COLUMN_NAME = "external_lna_db"


def _table_exists(bind, table_name: str) -> bool:
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _existing_columns(bind, table_name: str) -> set[str]:
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return

    if COLUMN_NAME in _existing_columns(bind, TABLE_NAME):
        return

    op.add_column(
        TABLE_NAME,
        sa.Column(COLUMN_NAME, sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    op.alter_column(TABLE_NAME, COLUMN_NAME, server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return

    if COLUMN_NAME not in _existing_columns(bind, TABLE_NAME):
        return

    op.drop_column(TABLE_NAME, COLUMN_NAME)
