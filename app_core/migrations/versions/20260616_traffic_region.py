"""Add state/region columns to traffic analytics.

Adds the most-specific subdivision (state / province) captured from a GeoLite2
City database so the dashboard can disambiguate same-named cities:

  * ``web_request_logs.region``      — subdivision name (e.g. "Ohio").
  * ``web_request_logs.region_code`` — subdivision ISO code (e.g. "OH").

Revision ID: 20260616_traffic_region
Revises: 20260616_traffic_city_asn
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260616_traffic_region"
down_revision = "20260616_traffic_city_asn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    if "web_request_logs" in tables:
        cols = {c["name"] for c in inspector.get_columns("web_request_logs")}
        if "region" not in cols:
            op.add_column(
                "web_request_logs", sa.Column("region", sa.String(length=96), nullable=True)
            )
        if "region_code" not in cols:
            op.add_column(
                "web_request_logs", sa.Column("region_code", sa.String(length=8), nullable=True)
            )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    if "web_request_logs" in tables:
        cols = {c["name"] for c in inspector.get_columns("web_request_logs")}
        if "region_code" in cols:
            op.drop_column("web_request_logs", "region_code")
        if "region" in cols:
            op.drop_column("web_request_logs", "region")
