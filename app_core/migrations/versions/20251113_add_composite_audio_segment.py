"""Add composite audio segment to EASDecodedAudio

Revision ID: 20251113_add_composite_audio_segment
Revises: 20251113_add_serial_mode_to_led_sign_status
Create Date: 2025-11-13 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251113_add_composite_audio_segment'
down_revision = '20251113_add_serial_mode_to_led_sign_status'
branch_labels = None
depends_on = None


def upgrade():
    """Add composite_audio_data column to eas_decoded_audio table."""
    op.add_column('eas_decoded_audio', sa.Column('composite_audio_data', sa.LargeBinary(), nullable=True))


def downgrade():
    """Remove composite_audio_data column from eas_decoded_audio table."""
    op.drop_column('eas_decoded_audio', 'composite_audio_data')
