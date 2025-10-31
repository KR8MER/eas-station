"""Add table for decoded SAME audio payloads."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20240510_eas_audio_decodes"
down_revision = "20240315_alert_delivery_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get database connection and inspector
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # Only create eas_decoded_audio table if it doesn't exist
    if "eas_decoded_audio" not in existing_tables:
        op.create_table(
            "eas_decoded_audio",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("original_filename", sa.String(length=255), nullable=True),
            sa.Column("content_type", sa.String(length=128), nullable=True),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("same_headers", sa.JSON(), nullable=True),
            sa.Column("quality_metrics", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("eas_decoded_audio")
