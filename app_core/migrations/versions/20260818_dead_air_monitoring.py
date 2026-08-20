"""Add dead-air (silence) monitoring settings.

Adds the thresholds for the debounced dead-air monitor, the optional rack
alarm buzzer pin, and the tower-light indication for the silence state.

Revision ID: 20260818_dead_air_monitoring
Revises: 20260817_repair_vtec_chain_gaps
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_dead_air_monitoring"
down_revision = "20260817_repair_vtec_chain_gaps"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("dead_air_enabled", sa.Boolean(), False, sa.false()),
    ("dead_air_level_threshold_db", sa.Integer(), False, sa.text("-65")),
    ("dead_air_detect_open_carrier", sa.Boolean(), False, sa.true()),
    ("dead_air_flatness_threshold_pct", sa.Integer(), False, sa.text("25")),
    ("dead_air_duration_seconds", sa.Integer(), False, sa.text("20")),
    ("dead_air_buzzer_enabled", sa.Boolean(), False, sa.false()),
    ("dead_air_buzzer_gpio_pin", sa.Integer(), True, None),
    ("tower_light_silence_enabled", sa.Boolean(), False, sa.true()),
    (
        "tower_light_silence_color",
        sa.String(20),
        False,
        sa.text("'magenta'"),
    ),
    ("tower_light_silence_buzzer", sa.Boolean(), False, sa.false()),
)


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "hardware_settings" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("hardware_settings")}
    for name, type_, nullable, server_default in _COLUMNS:
        if name in existing:
            continue
        op.add_column(
            "hardware_settings",
            sa.Column(
                name,
                type_,
                nullable=nullable,
                server_default=server_default,
            ),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "hardware_settings" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("hardware_settings")}
    for name, _type, _nullable, _default in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("hardware_settings", name)
