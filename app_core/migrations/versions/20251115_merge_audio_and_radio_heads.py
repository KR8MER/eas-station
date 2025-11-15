"""Merge audio composite and radio squelch migration heads

Revision ID: 20251115_merge_audio_and_radio_heads
Revises: 20251113_add_composite_audio_segment, 20251114_add_radio_squelch_controls
Create Date: 2025-11-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251115_merge_audio_and_radio_heads'
down_revision = ('20251113_add_composite_audio_segment', '20251114_add_radio_squelch_controls')
branch_labels = None
depends_on = None


def upgrade():
    """Merge the two migration branches - no schema changes needed."""
    pass


def downgrade():
    """Downgrade merge - no schema changes needed."""
    pass
