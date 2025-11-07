"""Merge radio demodulation, audio segments, and TTS error tracking

Revision ID: 20251107_merge_radio_and_audio
Revises: 20251107_add_radio_demodulation_settings, 20251107_add_tone_and_narration, 20251106_add_tts_error_tracking
Create Date: 2025-11-07

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251107_merge_radio_and_audio'
down_revision = ('20251107_add_radio_demodulation_settings', '20251107_add_tone_and_narration', '20251106_add_tts_error_tracking')
branch_labels = None
depends_on = None


def upgrade():
    """Merge migration - no changes needed."""
    pass


def downgrade():
    """Merge migration - no changes needed."""
    pass
