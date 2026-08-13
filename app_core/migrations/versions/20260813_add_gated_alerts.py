"""Add gated_alerts and alert_gating_settings tables.

Backs the gated-alerts hold-off timer feature: non-Immediate/non-Extreme
alerts can be held for a configurable window before auto-forward broadcasts
them, giving an operator a chance to approve early or cancel. Immediate
urgency and Extreme severity alerts always bypass the gate.

Revision ID: 20260813_add_gated_alerts
Revises: 20260804_mfa_totp_counter
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260813_add_gated_alerts"
down_revision = "20260804_mfa_totp_counter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "gated_alerts" not in existing_tables:
        op.create_table(
            "gated_alerts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=10), nullable=False),
            sa.Column("cap_alert_id", sa.Integer(), nullable=True),
            sa.Column("identifier", sa.String(length=255), nullable=True),
            sa.Column("event_code", sa.String(length=16), nullable=True),
            sa.Column("event", sa.String(length=255), nullable=True),
            sa.Column("severity", sa.String(length=50), nullable=True),
            sa.Column("urgency", sa.String(length=50), nullable=True),
            sa.Column("headline", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("hold_until", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.String(length=100), nullable=True),
            sa.Column("resolved_by_ip", sa.String(length=45), nullable=True),
            sa.Column("resolution_reason", sa.String(length=255), nullable=True),
            sa.Column("ota_payload", sa.JSON(), nullable=True),
            sa.Column("ota_audio_wav", sa.LargeBinary(), nullable=True),
            sa.Column("broadcast_result", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["cap_alert_id"], ["cap_alerts.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("cap_alert_id", name="uq_gated_alerts_cap_alert_id"),
        )
        op.create_index("ix_gated_alerts_source", "gated_alerts", ["source"])
        op.create_index("ix_gated_alerts_identifier", "gated_alerts", ["identifier"])
        op.create_index("ix_gated_alerts_status", "gated_alerts", ["status"])

    if "alert_gating_settings" not in existing_tables:
        op.create_table(
            "alert_gating_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("hold_off_seconds", sa.Integer(), nullable=False, server_default="120"),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        """
        INSERT INTO alert_gating_settings (id, enabled, hold_off_seconds, updated_at)
        VALUES (1, false, 120, CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "alert_gating_settings" in existing_tables:
        op.drop_table("alert_gating_settings")

    if "gated_alerts" in existing_tables:
        op.drop_table("gated_alerts")
