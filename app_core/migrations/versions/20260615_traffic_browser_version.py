"""Add browser_version to web-traffic analytics.

Stores the parsed browser major[.minor] version (e.g. "120") so the Traffic
Analytics dashboard can report versions awstats-style.

Revision ID: 20260615_traffic_browser_version
Revises: 20260615_traffic_hostname_country_code
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260615_traffic_browser_version"
down_revision = "20260615_traffic_hostname_country_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "web_request_logs" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("web_request_logs")}
    if "browser_version" not in cols:
        op.add_column(
            "web_request_logs",
            sa.Column("browser_version", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "web_request_logs" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("web_request_logs")}
    if "browser_version" in cols:
        op.drop_column("web_request_logs", "browser_version")
