"""Add VFD display tables for Noritake GU140x32F-7000B support."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251105_add_vfd_tables"
down_revision = "20251104_add_serial_to_radio_receivers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add VFD display tables for graphics display support."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Create vfd_displays table
    if "vfd_displays" not in inspector.get_table_names():
        op.create_table(
            "vfd_displays",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("content_type", sa.String(length=50), nullable=False),
            sa.Column("content_data", sa.Text(), nullable=True),
            sa.Column("binary_data", sa.LargeBinary(), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=True),
            sa.Column("x_position", sa.Integer(), nullable=True),
            sa.Column("y_position", sa.Integer(), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("scheduled_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("displayed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("alert_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["alert_id"], ["cap_alerts.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    # Create vfd_status table
    if "vfd_status" not in inspector.get_table_names():
        op.create_table(
            "vfd_status",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("port", sa.String(length=50), nullable=False),
            sa.Column("baudrate", sa.Integer(), nullable=True),
            sa.Column("brightness_level", sa.Integer(), nullable=True),
            sa.Column("is_connected", sa.Boolean(), nullable=True),
            sa.Column("error_count", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_update", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_content_type", sa.String(length=50), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    """Remove VFD display tables."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Drop tables if they exist
    if "vfd_displays" in inspector.get_table_names():
        op.drop_table("vfd_displays")

    if "vfd_status" in inspector.get_table_names():
        op.drop_table("vfd_status")
