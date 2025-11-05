"""Add stream support to radio receivers

Revision ID: 20251105_add_stream_support_to_receivers
Revises: 20251104_add_audio_source_configs
Create Date: 2025-11-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251105_add_stream_support_to_receivers'
down_revision = '20251104_add_audio_source_configs'
branch_labels = None
depends_on = None


def upgrade():
    """Add source_type and stream_url columns to radio_receivers table."""

    # Add source_type column (defaults to 'sdr' for existing records)
    op.add_column('radio_receivers',
        sa.Column('source_type', sa.String(16), nullable=False, server_default='sdr')
    )

    # Add stream_url column (nullable)
    op.add_column('radio_receivers',
        sa.Column('stream_url', sa.String(512), nullable=True)
    )

    # Make driver, frequency_hz, and sample_rate nullable since streams don't need them
    op.alter_column('radio_receivers', 'driver',
        existing_type=sa.String(64),
        nullable=True
    )

    op.alter_column('radio_receivers', 'frequency_hz',
        existing_type=sa.Float(),
        nullable=True
    )

    op.alter_column('radio_receivers', 'sample_rate',
        existing_type=sa.Integer(),
        nullable=True
    )


def downgrade():
    """Remove stream support from radio_receivers table."""

    # Remove the new columns
    op.drop_column('radio_receivers', 'stream_url')
    op.drop_column('radio_receivers', 'source_type')

    # Restore NOT NULL constraints (this may fail if there are null values)
    op.alter_column('radio_receivers', 'driver',
        existing_type=sa.String(64),
        nullable=False
    )

    op.alter_column('radio_receivers', 'frequency_hz',
        existing_type=sa.Float(),
        nullable=False
    )

    op.alter_column('radio_receivers', 'sample_rate',
        existing_type=sa.Integer(),
        nullable=False
    )
