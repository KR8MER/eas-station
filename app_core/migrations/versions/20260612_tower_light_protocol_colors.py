"""Add protocol and state-colour columns to tower light settings.

Adds support for the ANDONT 7-colour USB stack light (FF..AA framed
protocol, one colour at a time) alongside the original Adafruit #5125
three-segment protocol, plus a configurable state -> colour mapping
(standby / incoming / active alert).

Revision ID: 20260612_tower_light_protocol_colors
Revises: 20260612_add_retention_settings
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260612_tower_light_protocol_colors"
down_revision = "20260612_add_retention_settings"
branch_labels = None
depends_on = None

_NEW_COLUMNS = (
    ("tower_light_protocol", sa.String(20), "adafruit"),
    ("tower_light_standby_color", sa.String(20), "green"),
    ("tower_light_incoming_color", sa.String(20), "yellow"),
    ("tower_light_alert_color", sa.String(20), "red"),
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
