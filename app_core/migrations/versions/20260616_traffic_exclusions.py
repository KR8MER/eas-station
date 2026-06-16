"""Add loopback/skip-path exclusion settings to traffic analytics.

Adds operator-configurable noise filtering (awstats-style SkipHosts/SkipFiles):
  * ``exclude_loopback`` — drop server-internal (127.0.0.1/::1) requests.
  * ``excluded_paths``   — extra path prefixes to ignore.

Revision ID: 20260616_traffic_exclusions
Revises: 20260615_traffic_browser_version
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260616_traffic_exclusions"
down_revision = "20260615_traffic_browser_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "traffic_analytics_settings" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("traffic_analytics_settings")}
    if "exclude_loopback" not in cols:
        op.add_column(
            "traffic_analytics_settings",
            sa.Column(
                "exclude_loopback",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
    if "excluded_paths" not in cols:
        op.add_column(
            "traffic_analytics_settings",
            sa.Column("excluded_paths", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "traffic_analytics_settings" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("traffic_analytics_settings")}
    if "excluded_paths" in cols:
        op.drop_column("traffic_analytics_settings", "excluded_paths")
    if "exclude_loopback" in cols:
        op.drop_column("traffic_analytics_settings", "exclude_loopback")
