"""Add bias_t_enabled column to radio_receivers.

Many SDRs (RTL-SDR Blog v3/v4, Airspy Mini/R2, HackRF) can supply ~4.5 V DC
on the antenna coax to power a remote LNA, eliminating the need for a
separate USB power injector.  This setting is needed alongside
``external_lna_db`` so the driver can decide whether to enable bias-T at
device open, and so the UI can warn the operator that any short-to-ground
on the antenna feed will fault the SDR's bias-T regulator (or, on cheaper
boards, blow a series fuse / front-end transistor).

The column is nullable=False with default false because every receiver in
the table needs an explicit value, and "off" is the only safe default for
existing rows whose antenna setup we don't know.

Revision ID: 20260513_add_bias_t_enabled_to_radio_receivers
Revises: 20260512_merge_gps_and_external_lna_heads
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260513_add_bias_t_enabled_to_radio_receivers"
down_revision = "20260512_merge_gps_and_external_lna_heads"
branch_labels = None
depends_on = None


TABLE_NAME = "radio_receivers"
COLUMN_NAME = "bias_t_enabled"


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

    # server_default="false" so existing rows pick up "bias-T off" without
    # needing a backfill UPDATE.  Drop the server default afterwards so
    # the ORM-side default (False) is authoritative for new inserts.
    # Note: use the SQL literal "false" (not "0") so PostgreSQL accepts
    # it as a boolean — this matches every other Boolean migration in
    # this repo (e.g. 20260218_add_neopixel_support, 20251217_add_tts_settings).
    op.add_column(
        TABLE_NAME,
        sa.Column(COLUMN_NAME, sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column(TABLE_NAME, COLUMN_NAME, server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return

    if COLUMN_NAME not in _existing_columns(bind, TABLE_NAME):
        return

    op.drop_column(TABLE_NAME, COLUMN_NAME)
