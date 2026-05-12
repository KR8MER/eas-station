"""Merge GPS source and external LNA migrations into a single head.

Revision ID: 20260512_merge_gps_and_external_lna_heads
Revises: 20260509_add_gps_source_columns, 20260512_add_external_lna_db_to_radio_receivers
Create Date: 2026-05-12
"""

from alembic import op


revision = "20260512_merge_gps_and_external_lna_heads"
down_revision = (
    "20260509_add_gps_source_columns",
    "20260512_add_external_lna_db_to_radio_receivers",
)
branch_labels = None
depends_on = None


def upgrade():
    """Merge migration — no schema changes needed."""
    pass


def downgrade():
    """Merge migration — no schema changes needed."""
    pass
