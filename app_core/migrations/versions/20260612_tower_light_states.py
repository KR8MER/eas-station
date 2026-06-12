"""Add buzzer kill switch, extra states, severity colours, quiet hours to tower light.

New tower-light capabilities: a master buzzer-disable switch, a distinct
colour for test broadcasts (RWT/RMT/NPT/DMO), a system-fault state shown
when the alert pipeline / Redis is unreachable, optional severity-based
alert colours (warning / watch / advisory), and quiet hours that darken
the standby light on a schedule (alerts always override).

Revision ID: 20260612_tower_light_states
Revises: 20260612_tower_light_protocol_colors
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260612_tower_light_states"
down_revision = "20260612_tower_light_protocol_colors"
branch_labels = None
depends_on = None

_NEW_COLUMNS = (
    ("tower_light_buzzer_disabled", sa.Boolean(), sa.false()),
    ("tower_light_test_color", sa.String(20), "cyan"),
    ("tower_light_fault_enabled", sa.Boolean(), sa.true()),
    ("tower_light_fault_color", sa.String(20), "magenta"),
    ("tower_light_severity_colors", sa.Boolean(), sa.false()),
    ("tower_light_warning_color", sa.String(20), "red"),
    ("tower_light_watch_color", sa.String(20), "yellow"),
    ("tower_light_advisory_color", sa.String(20), "white"),
    ("tower_light_quiet_enabled", sa.Boolean(), sa.false()),
    ("tower_light_quiet_start", sa.String(5), "22:00"),
    ("tower_light_quiet_end", sa.String(5), "07:00"),
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
