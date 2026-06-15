"""Add web-traffic analytics tables (webalizer/awstats-style dashboard).

Creates:
  * ``web_request_logs`` — one row per recorded HTTP request (page views, hits,
    visitor IP, browser/OS, screen resolution, country/network, language).
  * ``traffic_analytics_settings`` — single-row collection configuration managed
    from the Traffic Analytics dashboard UI.

Revision ID: 20260615_web_traffic_analytics
Revises: 20260615_merge_heads_for_traffic
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260615_web_traffic_analytics"
down_revision = "20260615_merge_heads_for_traffic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "web_request_logs" not in existing_tables:
        op.create_table(
            "web_request_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("method", sa.String(length=8), nullable=False),
            sa.Column("path", sa.String(length=512), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("response_time_ms", sa.Integer(), nullable=True),
            sa.Column("content_length", sa.Integer(), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("referer", sa.String(length=512), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("username", sa.String(length=128), nullable=True),
            sa.Column("is_authenticated", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_api", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("browser", sa.String(length=64), nullable=True),
            sa.Column("os", sa.String(length=64), nullable=True),
            sa.Column("screen_resolution", sa.String(length=20), nullable=True),
            sa.Column("country", sa.String(length=64), nullable=True),
            sa.Column("language", sa.String(length=20), nullable=True),
        )
        op.create_index("ix_web_request_logs_timestamp", "web_request_logs", ["timestamp"])
        op.create_index("ix_web_request_logs_path", "web_request_logs", ["path"])
        op.create_index("ix_web_request_logs_status_code", "web_request_logs", ["status_code"])
        op.create_index("ix_web_request_logs_ip_address", "web_request_logs", ["ip_address"])
        op.create_index("ix_web_request_logs_user_id", "web_request_logs", ["user_id"])
        op.create_index("ix_web_request_logs_is_bot", "web_request_logs", ["is_bot"])
        op.create_index("idx_web_request_logs_path_time", "web_request_logs", ["path", "timestamp"])
        op.create_index("idx_web_request_logs_ip_time", "web_request_logs", ["ip_address", "timestamp"])
        op.create_index("idx_web_request_logs_bot_time", "web_request_logs", ["is_bot", "timestamp"])

    if "traffic_analytics_settings" not in existing_tables:
        op.create_table(
            "traffic_analytics_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("retention_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("log_api_requests", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("log_authenticated_only", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("exclude_bots", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("geoip_database_path", sa.String(length=512), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "traffic_analytics_settings" in existing_tables:
        op.drop_table("traffic_analytics_settings")

    if "web_request_logs" in existing_tables:
        for idx in (
            "idx_web_request_logs_bot_time",
            "idx_web_request_logs_ip_time",
            "idx_web_request_logs_path_time",
            "ix_web_request_logs_is_bot",
            "ix_web_request_logs_user_id",
            "ix_web_request_logs_ip_address",
            "ix_web_request_logs_status_code",
            "ix_web_request_logs_path",
            "ix_web_request_logs_timestamp",
        ):
            try:
                op.drop_index(idx, table_name="web_request_logs")
            except Exception:
                pass
        op.drop_table("web_request_logs")
