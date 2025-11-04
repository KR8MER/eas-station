"""Add serial column to radio_receivers for device identification."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251104_radio_serial"
down_revision = "20251103_rename_eas_messages_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add serial column to radio_receivers table for proper SDR device identification."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if table exists
    if "radio_receivers" in inspector.get_table_names():
        # Check if column already exists
        columns = [col["name"] for col in inspector.get_columns("radio_receivers")]
        if "serial" not in columns:
            op.add_column(
                "radio_receivers",
                sa.Column("serial", sa.String(length=128), nullable=True),
            )


def downgrade() -> None:
    """Remove serial column from radio_receivers table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if "radio_receivers" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("radio_receivers")]
        if "serial" in columns:
            op.drop_column("radio_receivers", "serial")
