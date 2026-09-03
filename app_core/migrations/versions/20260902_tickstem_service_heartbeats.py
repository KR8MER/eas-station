"""Add tickstem_service_heartbeats table for per-service Tickstem alerts.

A third Tickstem signal alongside heartbeat_settings' unconditional ping and
tickstem_settings' (publicly-reachable-URL-only) Monitors integration: one
outbound heartbeat per critical EAS Station service (app_core.config.
get_eas_services()), each gated on that specific service's own health. A
missed ping then identifies exactly which subsystem failed, rather than
only "something is wrong" -- which is all a single aggregate heartbeat's
alert could ever say, since Tickstem's ping carries no payload.

Revision ID: 20260902_tickstem_service_heartbeats
Revises: 20260902_fcc_pw_length_floor
Create Date: 2026-09-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260902_tickstem_service_heartbeats"
down_revision = "20260902_fcc_pw_length_floor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "tickstem_service_heartbeats" not in inspector.get_table_names():
        op.create_table(
            "tickstem_service_heartbeats",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("service_name", sa.String(200), nullable=False),
            sa.Column("heartbeat_id", sa.String(100), nullable=False),
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
            sa.UniqueConstraint("service_name", name="uq_tickstem_service_heartbeats_service_name"),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "tickstem_service_heartbeats" in inspector.get_table_names():
        op.drop_table("tickstem_service_heartbeats")
