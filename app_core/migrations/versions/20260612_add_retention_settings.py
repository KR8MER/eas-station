"""Add retention_settings table for automated data-retention policies.

Revision ID: 20260612_add_retention_settings
Revises: 20260610_refresh_default_screen_designs
Create Date: 2026-06-12

Holds the single-row (id=1) configuration consumed by
``app_core.retention.RetentionScheduler``: how long to keep raw IQ capture
files, /tmp/eas-audio debug recordings, ICY now-playing history,
audio-source alerts/metrics rows, and the ``raw_audio_data`` blobs on
``received_eas_alerts`` (blob-strip only — the alert rows themselves are
compliance history and are never deleted).

Convention: a value of ``0`` for any age field means "disabled / keep
forever".
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260612_add_retention_settings"
down_revision = "20260610_refresh_default_screen_designs"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def upgrade():
    if _table_exists("retention_settings"):
        return

    op.create_table(
        "retention_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "iq_capture_max_age_days",
            sa.Integer(),
            nullable=False,
            server_default="14",
        ),
        sa.Column(
            "temp_audio_max_age_days",
            sa.Integer(),
            nullable=False,
            server_default="7",
        ),
        sa.Column(
            "stream_metadata_max_age_days",
            sa.Integer(),
            nullable=False,
            server_default="90",
        ),
        sa.Column(
            "audio_alert_max_age_days",
            sa.Integer(),
            nullable=False,
            server_default="90",
        ),
        sa.Column(
            "audio_metrics_max_age_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "received_alert_audio_max_age_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    if not _table_exists("retention_settings"):
        return
    op.drop_table("retention_settings")
