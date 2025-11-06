"""Add custom display screen templates and rotation management.

Revision ID: 20251106_add_display_screens
Revises: 20251105_add_analytics_tables
Create Date: 2025-11-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "20251106_add_display_screens"
down_revision = "20251105_add_analytics_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create display screen template and rotation management tables."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # ========================================================================
    # Create display_screens table
    # ========================================================================
    if "display_screens" not in inspector.get_table_names():
        op.create_table(
            "display_screens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("display_type", sa.String(length=10), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=True),
            sa.Column("refresh_interval", sa.Integer(), nullable=True),
            sa.Column("duration", sa.Integer(), nullable=True),
            sa.Column("template_data", JSONB, nullable=False),
            sa.Column("data_sources", JSONB, nullable=True),
            sa.Column("conditions", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_displayed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("display_count", sa.Integer(), nullable=True),
            sa.Column("error_count", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes
        op.create_index(
            op.f("ix_display_screens_name"),
            "display_screens",
            ["name"],
            unique=True,
        )
        op.create_index(
            op.f("ix_display_screens_display_type"),
            "display_screens",
            ["display_type"],
            unique=False,
        )

    # ========================================================================
    # Create screen_rotations table
    # ========================================================================
    if "screen_rotations" not in inspector.get_table_names():
        op.create_table(
            "screen_rotations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("display_type", sa.String(length=10), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("screens", JSONB, nullable=False),
            sa.Column("randomize", sa.Boolean(), nullable=True),
            sa.Column("skip_on_alert", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_screen_index", sa.Integer(), nullable=True),
            sa.Column("last_rotation_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes
        op.create_index(
            op.f("ix_screen_rotations_name"),
            "screen_rotations",
            ["name"],
            unique=True,
        )
        op.create_index(
            op.f("ix_screen_rotations_display_type"),
            "screen_rotations",
            ["display_type"],
            unique=False,
        )


def downgrade() -> None:
    """Remove display screen template and rotation management tables."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Drop indexes and tables in reverse order
    if "screen_rotations" in inspector.get_table_names():
        op.drop_index(op.f("ix_screen_rotations_display_type"), table_name="screen_rotations")
        op.drop_index(op.f("ix_screen_rotations_name"), table_name="screen_rotations")
        op.drop_table("screen_rotations")

    if "display_screens" in inspector.get_table_names():
        op.drop_index(op.f("ix_display_screens_display_type"), table_name="display_screens")
        op.drop_index(op.f("ix_display_screens_name"), table_name="display_screens")
        op.drop_table("display_screens")
