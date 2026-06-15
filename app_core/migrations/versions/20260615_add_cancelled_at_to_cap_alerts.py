"""Add cancelled_at column to cap_alerts.

Records the moment an alert is explicitly cancelled (CAP ``msgType=Cancel`` or
VTEC action ``CAN``) rather than simply reaching its ``expires`` time.  The
original ``expires`` is left untouched so the UI can show that an event was
lifted early instead of conflating an early cancellation with a natural expiry.

Revision ID: 20260615_cap_alert_cancelled_at
Revises: 20260614_add_auto_purge_settings
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260615_cap_alert_cancelled_at"
down_revision = "20260614_add_auto_purge_settings"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return {col["name"] for col in inspector.get_columns(table_name)}
    except Exception:
        return set()


def upgrade() -> None:
    if "cancelled_at" not in _columns("cap_alerts"):
        op.add_column(
            "cap_alerts",
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if "cancelled_at" in _columns("cap_alerts"):
        op.drop_column("cap_alerts", "cancelled_at")
