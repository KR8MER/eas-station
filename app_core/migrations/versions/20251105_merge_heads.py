"""Merge migration heads from VFD and stream support branches.

Revision ID: 20251105_merge_heads
Revises: 20251105_add_stream_support_to_receivers, 20251105_add_vfd_tables
Create Date: 2025-11-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251105_merge_heads'
down_revision = ('20251105_add_stream_support_to_receivers', '20251105_add_vfd_tables')
branch_labels = None
depends_on = None


def upgrade():
    """Merge the two migration branches - no schema changes needed."""
    pass


def downgrade():
    """Downgrade merge - no schema changes needed."""
    pass
