"""Widen alembic_version.version_num beyond Alembic's default 32 chars.

Several revision IDs in this chain (e.g. 20260820_add_poller_feed_stall_threshold,
41 chars) exceed Alembic's default varchar(32) column, which breaks stamping on
any freshly created database (CI, new installs, disaster-recovery restores).
Production already has this column widened from an earlier ad-hoc fix; this
migration makes that the tracked, reproducible state for every database.

Revision ID: 20260820_widen_alembic_version
Revises: 20260820_add_poller_feed_stall_threshold
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260820_widen_alembic_version"
down_revision = "20260820_add_poller_feed_stall_threshold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        type_=sa.String(255),
        existing_type=sa.String(32),
    )


def downgrade() -> None:
    # Cannot safely narrow back to varchar(32): this chain's own down_revision
    # id (41 chars) would no longer fit in the column being stamped.
    pass
