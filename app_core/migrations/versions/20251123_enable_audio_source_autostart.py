"""Enable auto_start for existing audio sources

Revision ID: 20251123_enable_audio_source_autostart
Revises: 20251121_polish_network_screens
Create Date: 2025-11-23 19:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251123_enable_audio_source_autostart'
down_revision = '20251121_polish_network_screens'
branch_labels = None
depends_on = None


def upgrade():
    """
    Enable auto_start for all existing enabled audio sources.

    This ensures that existing audio sources will automatically start
    when the audio service boots up, fixing the issue where streams
    weren't auto-starting after the separated architecture migration.
    """
    # Update all enabled audio sources to have auto_start=True
    op.execute("""
        UPDATE audio_source_configs
        SET auto_start = true
        WHERE enabled = true
    """)


def downgrade():
    """
    Revert auto_start changes.

    Note: This sets all sources back to auto_start=false, which may not
    reflect the original state before this migration. This is acceptable
    since auto_start was newly added and defaulted to false.
    """
    op.execute("""
        UPDATE audio_source_configs
        SET auto_start = false
    """)
