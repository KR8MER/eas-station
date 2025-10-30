"""Create alert delivery reports table for verification analytics."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20240315_alert_delivery_reports"
down_revision = "20240229_radio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_delivery_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("originator", sa.String(length=64), nullable=True),
        sa.Column("station", sa.String(length=128), nullable=True),
        sa.Column("total_alerts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_alerts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delayed_alerts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("average_latency_seconds", sa.Integer(), nullable=True),
    )
    op.create_index(
        "idx_alert_delivery_reports_scope_window",
        "alert_delivery_reports",
        ["scope", "window_start", "window_end"],
    )
    op.create_index(
        "idx_alert_delivery_reports_originator",
        "alert_delivery_reports",
        ["originator"],
    )
    op.create_index(
        "idx_alert_delivery_reports_station",
        "alert_delivery_reports",
        ["station"],
    )


def downgrade() -> None:
    op.drop_index("idx_alert_delivery_reports_station", table_name="alert_delivery_reports")
    op.drop_index("idx_alert_delivery_reports_originator", table_name="alert_delivery_reports")
    op.drop_index("idx_alert_delivery_reports_scope_window", table_name="alert_delivery_reports")
    op.drop_table("alert_delivery_reports")
