"""Add audio_source_configs table for persistent audio source configurations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "20251104_add_audio_source_configs"
down_revision = "20251104_radio_serial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create audio_source_configs table for persistent audio source configurations."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if table already exists
    if "audio_source_configs" not in inspector.get_table_names():
        op.create_table(
            "audio_source_configs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("source_type", sa.String(length=20), nullable=False),
            sa.Column("config", JSONB, nullable=False),
            sa.Column("priority", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("enabled", sa.Boolean(), nullable=True, server_default="true"),
            sa.Column("auto_start", sa.Boolean(), nullable=True, server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )

        # Create indexes
        op.create_index(
            "ix_audio_source_configs_name",
            "audio_source_configs",
            ["name"],
            unique=True
        )


def downgrade() -> None:
    """Remove audio_source_configs table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if "audio_source_configs" in inspector.get_table_names():
        op.drop_index("ix_audio_source_configs_name", table_name="audio_source_configs")
        op.drop_table("audio_source_configs")
