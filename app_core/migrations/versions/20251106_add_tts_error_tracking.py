"""Add TTS error tracking to EASMessage model

Revision ID: 20251106_add_tts_error_tracking
Revises: 20251106_remove_stream_support
Create Date: 2025-11-06

Adds tts_warning and tts_provider columns to track TTS failures in automated alerts.
This brings EASMessage in line with ManualEASActivation which already has these fields.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251106_add_tts_error_tracking'
down_revision = '20251106_remove_stream_support'
branch_labels = None
depends_on = None


def upgrade():
    """Add TTS error tracking columns to eas_messages table."""

    # Add tts_warning column (nullable to support existing records)
    op.add_column('eas_messages',
        sa.Column('tts_warning', sa.String(255), nullable=True)
    )

    # Add tts_provider column (nullable to support existing records)
    op.add_column('eas_messages',
        sa.Column('tts_provider', sa.String(32), nullable=True)
    )


def downgrade():
    """Remove TTS error tracking columns from eas_messages table."""

    op.drop_column('eas_messages', 'tts_provider')
    op.drop_column('eas_messages', 'tts_warning')
