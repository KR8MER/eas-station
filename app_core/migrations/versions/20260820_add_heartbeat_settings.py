"""Add heartbeat_settings table for the outbound dead-man's-switch ping.

Revision ID: 20260820_add_heartbeat_settings
Revises: 20260818_dead_air_per_source
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260820_add_heartbeat_settings"
down_revision = "20260818_dead_air_per_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "heartbeat_settings" not in inspector.get_table_names():
        op.create_table(
            "heartbeat_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("ping_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="300"),
            sa.Column("last_ping_at", sa.DateTime(), nullable=True),
            sa.Column("last_ping_success", sa.Boolean(), nullable=True),
            sa.Column("last_ping_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.execute(
            "INSERT INTO heartbeat_settings (id, enabled, ping_url, interval_seconds) "
            "VALUES (1, false, '', 300) ON CONFLICT (id) DO NOTHING"
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "heartbeat_settings" in inspector.get_table_names():
        op.drop_table("heartbeat_settings")
