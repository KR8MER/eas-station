"""Remove stream support from radio receivers

Revision ID: 20251106_remove_stream_support_from_receivers
Revises: 20251106_add_display_screens
Create Date: 2025-11-06

Streams are now handled exclusively through the Audio Ingestion system.
RadioReceiver is refocused on SDR hardware configuration only.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251106_remove_stream_support_from_receivers'
down_revision = '20251106_add_display_screens'
branch_labels = None
depends_on = None


def upgrade():
    """Remove stream support from radio_receivers table."""

    # First, delete any stream-type receivers before removing the columns
    # This prevents data loss issues
    op.execute("""
        DELETE FROM radio_receivers WHERE source_type = 'stream'
    """)

    # Remove stream-related columns
    op.drop_column('radio_receivers', 'stream_url')
    op.drop_column('radio_receivers', 'source_type')

    # Restore NOT NULL constraints for SDR-required fields
    # First update any null values to defaults
    op.execute("""
        UPDATE radio_receivers
        SET driver = 'rtlsdr'
        WHERE driver IS NULL
    """)

    op.execute("""
        UPDATE radio_receivers
        SET frequency_hz = 162550000
        WHERE frequency_hz IS NULL
    """)

    op.execute("""
        UPDATE radio_receivers
        SET sample_rate = 2400000
        WHERE sample_rate IS NULL
    """)

    # Now apply NOT NULL constraints
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


def downgrade():
    """Re-add stream support to radio_receivers table."""

    # Add source_type column (defaults to 'sdr' for existing records)
    op.add_column('radio_receivers',
        sa.Column('source_type', sa.String(16), nullable=False, server_default='sdr')
    )

    # Add stream_url column (nullable)
    op.add_column('radio_receivers',
        sa.Column('stream_url', sa.String(512), nullable=True)
    )

    # Make driver, frequency_hz, and sample_rate nullable again for streams
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
