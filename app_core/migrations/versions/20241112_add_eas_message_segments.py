"""Add component audio columns for generated EAS messages."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20241112_add_eas_message_segments"
down_revision = "20240718_expand_decoded_audio_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("eas_messages", schema=None) as batch:
        batch.add_column(sa.Column("same_audio_data", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("attention_audio_data", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("tts_audio_data", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("buffer_audio_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("eas_messages", schema=None) as batch:
        batch.drop_column("buffer_audio_data")
        batch.drop_column("tts_audio_data")
        batch.drop_column("attention_audio_data")
        batch.drop_column("same_audio_data")
