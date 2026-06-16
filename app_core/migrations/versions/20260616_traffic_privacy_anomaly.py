"""Add privacy + anomaly-detection settings to traffic analytics.

Adds operator-tunable columns to ``traffic_analytics_settings``:

  * ``anonymize_ip``                     — mask visitor IPs at capture time.
  * ``anomaly_detection_enabled``        — master switch for anomaly checks.
  * ``anomaly_error_rate_pct``           — error-rate threshold (%).
  * ``anomaly_5xx_threshold``            — server-error surge threshold.
  * ``anomaly_failed_login_threshold``   — brute-force threshold per IP.
  * ``anomaly_scanner_threshold``        — scanner (4xx) threshold per IP.

Revision ID: 20260616_traffic_privacy_anomaly
Revises: 20260616_traffic_region
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260616_traffic_privacy_anomaly"
down_revision = "20260616_traffic_region"
branch_labels = None
depends_on = None


# (column name, SQLAlchemy type, server default literal)
_COLUMNS = (
    ("anonymize_ip", sa.Boolean(), sa.false()),
    ("anomaly_detection_enabled", sa.Boolean(), sa.true()),
    ("anomaly_error_rate_pct", sa.Integer(), sa.text("25")),
    ("anomaly_5xx_threshold", sa.Integer(), sa.text("25")),
    ("anomaly_failed_login_threshold", sa.Integer(), sa.text("10")),
    ("anomaly_scanner_threshold", sa.Integer(), sa.text("50")),
)


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "traffic_analytics_settings" not in tables:
        return

    cols = {c["name"] for c in inspector.get_columns("traffic_analytics_settings")}
    for name, col_type, default in _COLUMNS:
        if name not in cols:
            op.add_column(
                "traffic_analytics_settings",
                sa.Column(name, col_type, nullable=False, server_default=default),
            )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "traffic_analytics_settings" not in tables:
        return

    cols = {c["name"] for c in inspector.get_columns("traffic_analytics_settings")}
    for name, _type, _default in reversed(_COLUMNS):
        if name in cols:
            op.drop_column("traffic_analytics_settings", name)
