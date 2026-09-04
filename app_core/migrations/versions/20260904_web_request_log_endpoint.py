"""Add endpoint column to web_request_logs for the API dashboard.

Flask's dotted view-function endpoint name (e.g.
"webapp.admin.audio_ingest.routes_alerts.api_get_source"), captured alongside
the raw path so the API dashboard can group parameterized routes
(/api/alerts/123, /api/alerts/456, ...) into one bucket instead of
fragmenting per ID. Nullable and unbackfilled -- historical rows simply have
no endpoint and are excluded from the per-route breakdown until new traffic
accumulates.

Revision ID: 20260904_web_request_log_endpoint
Revises: 20260904_map_tile_settings
Create Date: 2026-09-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260904_web_request_log_endpoint"
down_revision = "20260904_map_tile_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    existing_cols = {col["name"] for col in inspector.get_columns("web_request_logs")}
    if "endpoint" not in existing_cols:
        op.add_column(
            "web_request_logs",
            sa.Column("endpoint", sa.String(length=255), nullable=True),
        )
        op.create_index(
            "ix_web_request_logs_endpoint", "web_request_logs", ["endpoint"]
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    existing_cols = {col["name"] for col in inspector.get_columns("web_request_logs")}
    if "endpoint" in existing_cols:
        op.drop_index("ix_web_request_logs_endpoint", table_name="web_request_logs")
        op.drop_column("web_request_logs", "endpoint")
