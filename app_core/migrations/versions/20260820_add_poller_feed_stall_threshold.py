"""Add feed_stall_alert_minutes to poller_settings for the combined
NOAA+IPAWS feed-loss alarm.

Revision ID: 20260820_add_poller_feed_stall_threshold
Revises: 20260820_add_backup_verification_runs
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260820_add_poller_feed_stall_threshold"
down_revision = "20260820_add_backup_verification_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "poller_settings" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("poller_settings")}
        if "feed_stall_alert_minutes" not in columns:
            op.add_column(
                "poller_settings",
                sa.Column("feed_stall_alert_minutes", sa.Integer(), nullable=False, server_default="15"),
            )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "poller_settings" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("poller_settings")}
        if "feed_stall_alert_minutes" in columns:
            op.drop_column("poller_settings", "feed_stall_alert_minutes")
