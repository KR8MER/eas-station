"""Add radio demodulation settings

Revision ID: 20251107_add_radio_demodulation_settings
Revises: 20251106_remove_stream_support_from_receivers
Create Date: 2025-11-07

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251107_add_radio_demodulation_settings'
down_revision = '20251106_remove_stream_support_from_receivers'
branch_labels = None
depends_on = None


def upgrade():
    """Add audio demodulation and RBDS fields to radio_receivers table."""
    op.add_column('radio_receivers', sa.Column('modulation_type', sa.String(length=16), nullable=False, server_default='IQ'))
    op.add_column('radio_receivers', sa.Column('audio_output', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('radio_receivers', sa.Column('stereo_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('radio_receivers', sa.Column('deemphasis_us', sa.Float(), nullable=False, server_default='75.0'))
    op.add_column('radio_receivers', sa.Column('enable_rbds', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    """Remove audio demodulation and RBDS fields from radio_receivers table."""
    op.drop_column('radio_receivers', 'enable_rbds')
    op.drop_column('radio_receivers', 'deemphasis_us')
    op.drop_column('radio_receivers', 'stereo_enabled')
    op.drop_column('radio_receivers', 'audio_output')
    op.drop_column('radio_receivers', 'modulation_type')
