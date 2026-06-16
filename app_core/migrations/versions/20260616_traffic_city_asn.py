"""Add City + ASN GeoIP support to traffic analytics.

Adds:
  * ``web_request_logs.city``    — city name (GeoLite2 City database).
  * ``web_request_logs.asn_org`` — network operator / ISP (GeoLite2 ASN database).
  * ``traffic_analytics_settings.geoip_asn_database_path`` — path to the ASN DB.

Revision ID: 20260616_traffic_city_asn
Revises: 20260616_traffic_exclusions
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260616_traffic_city_asn"
down_revision = "20260616_traffic_exclusions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    if "web_request_logs" in tables:
        cols = {c["name"] for c in inspector.get_columns("web_request_logs")}
        if "city" not in cols:
            op.add_column(
                "web_request_logs", sa.Column("city", sa.String(length=128), nullable=True)
            )
        if "asn_org" not in cols:
            op.add_column(
                "web_request_logs", sa.Column("asn_org", sa.String(length=128), nullable=True)
            )

    if "traffic_analytics_settings" in tables:
        cols = {c["name"] for c in inspector.get_columns("traffic_analytics_settings")}
        if "geoip_asn_database_path" not in cols:
            op.add_column(
                "traffic_analytics_settings",
                sa.Column("geoip_asn_database_path", sa.String(length=512), nullable=True),
            )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    if "traffic_analytics_settings" in tables:
        cols = {c["name"] for c in inspector.get_columns("traffic_analytics_settings")}
        if "geoip_asn_database_path" in cols:
            op.drop_column("traffic_analytics_settings", "geoip_asn_database_path")

    if "web_request_logs" in tables:
        cols = {c["name"] for c in inspector.get_columns("web_request_logs")}
        if "asn_org" in cols:
            op.drop_column("web_request_logs", "asn_org")
        if "city" in cols:
            op.drop_column("web_request_logs", "city")
