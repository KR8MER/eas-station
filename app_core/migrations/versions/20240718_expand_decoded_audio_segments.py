"""Add audio segment columns to decoded SAME payloads."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20240718_expand_decoded_audio_segments"
down_revision = "20240717_expand_alembic_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get database connection and inspector
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check existing columns
    existing_columns = {col['name'] for col in inspector.get_columns('eas_decoded_audio')}

    with op.batch_alter_table("eas_decoded_audio", schema=None) as batch:
        if 'segment_metadata' not in existing_columns:
            batch.add_column(sa.Column("segment_metadata", sa.JSON(), nullable=True))
        if 'header_audio_data' not in existing_columns:
            batch.add_column(sa.Column("header_audio_data", sa.LargeBinary(), nullable=True))
        if 'message_audio_data' not in existing_columns:
            batch.add_column(sa.Column("message_audio_data", sa.LargeBinary(), nullable=True))
        if 'eom_audio_data' not in existing_columns:
            batch.add_column(sa.Column("eom_audio_data", sa.LargeBinary(), nullable=True))
        if 'buffer_audio_data' not in existing_columns:
            batch.add_column(sa.Column("buffer_audio_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("eas_decoded_audio", schema=None) as batch:
        batch.drop_column("buffer_audio_data")
        batch.drop_column("eom_audio_data")
        batch.drop_column("message_audio_data")
        batch.drop_column("header_audio_data")
        batch.drop_column("segment_metadata")
