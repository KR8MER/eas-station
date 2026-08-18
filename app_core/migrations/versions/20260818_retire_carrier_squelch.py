"""Retire the carrier-squelch feature.

The feature never did what its name and help text promised. `_apply_squelch`
gated on the RMS of the *demodulated audio*, not on carrier presence, so:

  * it muted a feed that was already digitally silent -- a no-op, since
    muting silence produces silence; and
  * it passed full-scale hiss straight through, which is the one thing the
    panel promised to mute ("automatically mute white noise when the
    carrier drops"). An off-air FM receiver emits unsquelched noise tens of
    dB above any usable threshold, so the gate never closed on it.

Its "raise alarm on carrier loss" option only wrote a log line and a
metadata flag consumed by one status badge; it drove no GPIO, tower light
or notification, and is superseded by the debounced dead-air monitor
(app_core/audio/silence.py) which detects the open-carrier case properly
via spectral flatness and drives the tower light and rack buzzer.

Dropping the columns rather than leaving them orphaned: nothing reads them
any more, and leaving dead configuration in the schema invites someone to
wire it back up. The downgrade recreates them with their original defaults;
it cannot restore per-receiver values, which is the normal trade for a
feature removal.

Revision ID: 20260818_retire_carrier_squelch
Revises: 20260818_dead_air_monitoring
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_retire_carrier_squelch"
down_revision = "20260818_dead_air_monitoring"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("squelch_enabled", sa.Boolean(), False, sa.false()),
    ("squelch_threshold_db", sa.Float(), False, sa.text("-65")),
    ("squelch_open_ms", sa.Integer(), False, sa.text("150")),
    ("squelch_close_ms", sa.Integer(), False, sa.text("750")),
    ("squelch_alarm", sa.Boolean(), False, sa.false()),
)


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "radio_receivers" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("radio_receivers")}
    for name, _type, _nullable, _default in _COLUMNS:
        if name in existing:
            op.drop_column("radio_receivers", name)


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "radio_receivers" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("radio_receivers")}
    for name, type_, nullable, server_default in _COLUMNS:
        if name in existing:
            continue
        op.add_column(
            "radio_receivers",
            sa.Column(name, type_, nullable=nullable, server_default=server_default),
        )
