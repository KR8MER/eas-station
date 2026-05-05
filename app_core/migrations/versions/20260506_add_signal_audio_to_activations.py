"""Add pre/post-alert signal audio columns to manual_eas_activations.

Revision ID: 20260506_add_signal_audio_to_activations
Revises: 20260506_split_location_settings
Create Date: 2026-05-06

Stores the rendered system-level pre/post-alert signal (bell, beep, QC-II,
DTMF, MDC1200, …) as binary blobs alongside the other per-component audio
so they can be streamed and played back from the Manual EAS print/detail
page Audio Components card.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260506_add_signal_audio_to_activations"
down_revision = "20260506_split_location_settings"
branch_labels = None
depends_on = None


TABLE_NAME = "manual_eas_activations"


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        return column_name in columns
    except Exception:
        return False


def upgrade() -> None:
    if not _column_exists(TABLE_NAME, "pre_chime_audio_data"):
        op.add_column(TABLE_NAME, sa.Column("pre_chime_audio_data", sa.LargeBinary(), nullable=True))

    if not _column_exists(TABLE_NAME, "post_chime_audio_data"):
        op.add_column(TABLE_NAME, sa.Column("post_chime_audio_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    if _column_exists(TABLE_NAME, "post_chime_audio_data"):
        op.drop_column(TABLE_NAME, "post_chime_audio_data")

    if _column_exists(TABLE_NAME, "pre_chime_audio_data"):
        op.drop_column(TABLE_NAME, "pre_chime_audio_data")
