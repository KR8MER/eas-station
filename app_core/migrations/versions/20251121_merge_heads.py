"""Merge migration heads

Revision ID: 20251121_merge_heads
Revises: 20251121_remove_storage_zone_codes, 20251121_polish_network_screens
Create Date: 2025-11-21 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251121_merge_heads'
down_revision = ('20251121_remove_storage_zone_codes', '20251121_polish_network_screens')
branch_labels = None
depends_on = None


def upgrade():
    """Merge multiple migration heads - no schema changes needed."""
    pass


def downgrade():
    """No schema changes to revert."""
    pass
