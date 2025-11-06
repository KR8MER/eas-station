"""Add component audio columns for generated EAS messages."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20241112_add_eas_message_segments"
down_revision = "20241031_convert_location_json_to_jsonb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get database connection and inspector
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if the table exists first
    if "eas_messages" not in inspector.get_table_names():
        # Table doesn't exist yet, skip this migration
        return

    # Check existing columns
    existing_columns = {col['name'] for col in inspector.get_columns('eas_messages')}

    with op.batch_alter_table("eas_messages", schema=None) as batch:
        if 'same_audio_data' not in existing_columns:
            batch.add_column(sa.Column("same_audio_data", sa.LargeBinary(), nullable=True))
        if 'attention_audio_data' not in existing_columns:
            batch.add_column(sa.Column("attention_audio_data", sa.LargeBinary(), nullable=True))
        if 'tts_audio_data' not in existing_columns:
            batch.add_column(sa.Column("tts_audio_data", sa.LargeBinary(), nullable=True))
        if 'buffer_audio_data' not in existing_columns:
            batch.add_column(sa.Column("buffer_audio_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("eas_messages", schema=None) as batch:
        batch.drop_column("buffer_audio_data")
        batch.drop_column("tts_audio_data")
        batch.drop_column("attention_audio_data")
        batch.drop_column("same_audio_data")
