"""Add Pending Alerts indicator columns to tower light settings.

Adds a configurable enable flag and colour for a new tower-light state:
the gated-alerts Pending Alerts queue (alerts held for operator review
before broadcast) is now shown on the USB stack light, ranked below an
active/incoming alert but above quiet hours.

Revision ID: 20260814_tower_light_gate_pending_color
Revises: 20260813_add_gated_alerts
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260814_tower_light_gate_pending_color"
down_revision = "20260813_add_gated_alerts"
branch_labels = None
depends_on = None

_NEW_COLUMNS = (
    ("tower_light_gate_pending_enabled", sa.Boolean(), "true"),
    ("tower_light_gate_pending_color", sa.String(20), "blue"),
)


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "hardware_settings" not in inspector.get_table_names():
        return

    existing_cols = {col["name"] for col in inspector.get_columns("hardware_settings")}
    for name, col_type, default in _NEW_COLUMNS:
        if name not in existing_cols:
            op.add_column(
                "hardware_settings",
                sa.Column(name, col_type, nullable=False, server_default=default),
            )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "hardware_settings" not in inspector.get_table_names():
        return

    existing_cols = {col["name"] for col in inspector.get_columns("hardware_settings")}
    for name, _col_type, _default in _NEW_COLUMNS:
        if name in existing_cols:
            op.drop_column("hardware_settings", name)
