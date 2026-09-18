"""Add healthchecks_settings and healthchecks_service_heartbeats tables.

healthchecks.io's Management API (https://healthchecks.io/docs/api/) has no
"poll an external URL" product -- every check is a dead-man's-switch this box
pings out to, the same shape as the existing per-service Tickstem heartbeats
(tickstem_service_heartbeats). healthchecks_settings holds the account API
key those checks are managed through; healthchecks_service_heartbeats holds
one row per critical EAS Station service (app_core.config.get_eas_services()),
each gated on that specific service's own health so a missed ping identifies
exactly which subsystem failed.

Revision ID: 20260918_healthchecks_settings
Revises: 20260911_add_sms_message_log
Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260918_healthchecks_settings"
down_revision = "20260911_add_sms_message_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "healthchecks_settings" not in inspector.get_table_names():
        op.create_table(
            "healthchecks_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("api_key", sa.String(500), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
        )

    if "healthchecks_service_heartbeats" not in inspector.get_table_names():
        op.create_table(
            "healthchecks_service_heartbeats",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("service_name", sa.String(200), nullable=False),
            sa.Column("check_uuid", sa.String(100), nullable=False),
            sa.Column("ping_url", sa.String(500), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("interval_secs", sa.Integer(), nullable=False, server_default="300"),
            sa.Column("status", sa.String(20), nullable=True),
            sa.Column("last_ping_at", sa.DateTime(), nullable=True),
            sa.Column("last_ping_success", sa.Boolean(), nullable=True),
            sa.Column("last_ping_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("service_name", name="uq_healthchecks_service_heartbeats_service_name"),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "healthchecks_service_heartbeats" in inspector.get_table_names():
        op.drop_table("healthchecks_service_heartbeats")
    if "healthchecks_settings" in inspector.get_table_names():
        op.drop_table("healthchecks_settings")
