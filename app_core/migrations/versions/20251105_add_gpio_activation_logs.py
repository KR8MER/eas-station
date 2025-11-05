"""Add gpio_activation_logs table for GPIO relay audit trail.

Revision ID: 20251105_add_gpio_activation_logs
Revises: 20251105_merge_heads
Create Date: 2025-11-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251105_add_gpio_activation_logs"
down_revision = "20251105_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create gpio_activation_logs table for GPIO relay audit trail."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if table already exists
    if "gpio_activation_logs" not in inspector.get_table_names():
        op.create_table(
            "gpio_activation_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pin", sa.Integer(), nullable=False),
            sa.Column("activation_type", sa.String(length=20), nullable=False),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("operator", sa.String(length=100), nullable=True),
            sa.Column("alert_id", sa.String(length=255), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes for common queries
        op.create_index(
            "ix_gpio_activation_logs_pin",
            "gpio_activation_logs",
            ["pin"],
        )
        op.create_index(
            "ix_gpio_activation_logs_activation_type",
            "gpio_activation_logs",
            ["activation_type"],
        )
        op.create_index(
            "ix_gpio_activation_logs_activated_at",
            "gpio_activation_logs",
            ["activated_at"],
        )


def downgrade() -> None:
    """Remove gpio_activation_logs table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if "gpio_activation_logs" in inspector.get_table_names():
        op.drop_index("ix_gpio_activation_logs_activated_at", table_name="gpio_activation_logs")
        op.drop_index("ix_gpio_activation_logs_activation_type", table_name="gpio_activation_logs")
        op.drop_index("ix_gpio_activation_logs_pin", table_name="gpio_activation_logs")
        op.drop_table("gpio_activation_logs")
