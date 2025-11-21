"""Remove storage_zone_codes column if exists

Revision ID: 20251121_remove_storage_zone_codes
Revises: 20251121_polish_network_screens
Create Date: 2025-11-21 12:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20251121_remove_storage_zone_codes'
down_revision = '20251121_polish_network_screens'
branch_labels = None
depends_on = None


def upgrade():
    """Remove storage_zone_codes column if it exists."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if the column exists
    columns = [col['name'] for col in inspector.get_columns('location_settings')]

    if 'storage_zone_codes' in columns:
        # Column exists, drop it
        op.drop_column('location_settings', 'storage_zone_codes')
        print("Dropped storage_zone_codes column from location_settings table")
    else:
        print("storage_zone_codes column does not exist, skipping")


def downgrade():
    """Re-add storage_zone_codes column."""
    # Only add back if it doesn't exist
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('location_settings')]

    if 'storage_zone_codes' not in columns:
        op.add_column('location_settings',
            sa.Column('storage_zone_codes', sa.dialects.postgresql.JSONB(), nullable=True)
        )
