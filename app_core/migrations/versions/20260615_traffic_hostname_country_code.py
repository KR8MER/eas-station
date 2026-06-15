"""Add reverse-DNS hostname + country code to web-traffic analytics.

awstats-style enrichment of the Traffic Analytics feature:
  * ``web_request_logs.hostname`` — reverse-DNS (PTR) hostname for the visitor IP.
  * ``web_request_logs.country_code`` — ISO 3166-1 alpha-2 code for the flag.
  * ``traffic_analytics_settings.resolve_hostnames`` — toggle for reverse DNS.

Revision ID: 20260615_traffic_hostname_country_code
Revises: 20260615_web_traffic_analytics
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260615_traffic_hostname_country_code"
down_revision = "20260615_web_traffic_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "web_request_logs" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("web_request_logs")}
        if "hostname" not in cols:
            op.add_column(
                "web_request_logs",
                sa.Column("hostname", sa.String(length=255), nullable=True),
            )
            op.create_index(
                "ix_web_request_logs_hostname", "web_request_logs", ["hostname"]
            )
        if "country_code" not in cols:
            op.add_column(
                "web_request_logs",
                sa.Column("country_code", sa.String(length=2), nullable=True),
            )

    if "traffic_analytics_settings" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("traffic_analytics_settings")}
        if "resolve_hostnames" not in cols:
            op.add_column(
                "traffic_analytics_settings",
                sa.Column(
                    "resolve_hostnames",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "traffic_analytics_settings" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("traffic_analytics_settings")}
        if "resolve_hostnames" in cols:
            op.drop_column("traffic_analytics_settings", "resolve_hostnames")

    if "web_request_logs" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("web_request_logs")}
        if "country_code" in cols:
            op.drop_column("web_request_logs", "country_code")
        if "hostname" in cols:
            try:
                op.drop_index("ix_web_request_logs_hostname", table_name="web_request_logs")
            except Exception:
                pass
            op.drop_column("web_request_logs", "hostname")
