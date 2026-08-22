"""Add tickstem_settings table for the Tickstem uptime-monitor integration.

Separate from heartbeat_settings: heartbeat is an outbound dead-man's-switch
ping compatible with any healthchecks.io-style receiver, while this stores
credentials/state for Tickstem's Monitors API specifically (an *inbound*
uptime check that Tickstem polls, managed here via their bearer-token API).

Revision ID: 20260822_tickstem_settings
Revises: 20260821_relay_interlocks
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260822_tickstem_settings"
down_revision = "20260821_relay_interlocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "tickstem_settings" not in inspector.get_table_names():
        op.create_table(
            "tickstem_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("api_key", sa.String(500), nullable=True),
            sa.Column("monitor_id", sa.String(100), nullable=True),
            sa.Column("monitor_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("monitor_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("interval_secs", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("timeout_secs", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("monitor_status", sa.String(20), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(), nullable=True),
            sa.Column("last_sync_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.execute(
            "INSERT INTO tickstem_settings (id, monitor_name, monitor_url, interval_secs, timeout_secs) "
            "VALUES (1, '', '', 60, 10) ON CONFLICT (id) DO NOTHING"
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "tickstem_settings" in inspector.get_table_names():
        op.drop_table("tickstem_settings")
