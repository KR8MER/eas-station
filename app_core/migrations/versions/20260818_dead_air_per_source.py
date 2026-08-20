"""Drop the station-wide dead-air detection columns.

Dead-air detection (whether a source alarms on silence, and at what
threshold) moved to a per-source policy stored in
AudioSourceConfigDB.config_params -- a station-wide flag couldn't express
"alarm on silence for this continuous broadcast monitor, but never for
that state-relay source that's supposed to be silent except when relaying
an actual alert." The output half (buzzer pin, tower-light colour) stays
on this table; only the five detection columns added by
20260818_dead_air_monitoring are dropped here.

No data-preservation step: this feature shipped hours before this
migration, in the same session, before any operator could have relied on
it, and every dropped column's own default was effectively "disabled" --
nothing meaningful to carry forward.

Revision ID: 20260818_dead_air_per_source
Revises: 20260818_retire_carrier_squelch
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_dead_air_per_source"
down_revision = "20260818_retire_carrier_squelch"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("dead_air_enabled", sa.Boolean(), False, sa.false()),
    ("dead_air_level_threshold_db", sa.Integer(), False, sa.text("-65")),
    ("dead_air_detect_open_carrier", sa.Boolean(), False, sa.true()),
    ("dead_air_flatness_threshold_pct", sa.Integer(), False, sa.text("25")),
    ("dead_air_duration_seconds", sa.Integer(), False, sa.text("20")),
)


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "hardware_settings" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("hardware_settings")}
    for name, _type, _nullable, _default in _COLUMNS:
        if name in existing:
            op.drop_column("hardware_settings", name)


def downgrade() -> None:
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
