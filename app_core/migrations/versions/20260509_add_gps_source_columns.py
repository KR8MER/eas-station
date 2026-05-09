"""Add gps_source / gps_gpsd_host / gps_gpsd_port columns to hardware_settings.

Tier 3 of the GPS HAT setup story (PR #2056). The GPS Manager can now
read NMEA either from the configured serial port directly (legacy
behaviour) or from gpsd over its TCP JSON socket. The latter mode lets
chrony share the GPS receiver for stratum-1 PPS time without fighting
EAS Station for ``/dev/serial0``.

Adding three columns:

    gps_source     VARCHAR(16) NOT NULL DEFAULT 'auto'
                   One of {'auto', 'serial', 'gpsd'}.
                   - auto:   prefer gpsd; fall back to serial
                   - serial: open /dev/serial0 directly (legacy)
                   - gpsd:   require gpsd; refuse to start if not reachable
    gps_gpsd_host  VARCHAR(100) NOT NULL DEFAULT '127.0.0.1'
    gps_gpsd_port  INTEGER NOT NULL DEFAULT 2947

Existing rows are backfilled with the defaults. The 'auto' default is
deliberately conservative: if gpsd isn't installed (the situation on
every install before this commit), the manager silently falls back to
the legacy direct-serial path, so this migration never breaks an
existing deployment.

Revision ID: 20260509_add_gps_source_columns
Revises: 20260507_default_pps_gpio_pin_to_18
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260509_add_gps_source_columns"
down_revision = "20260507_default_pps_gpio_pin_to_18"
branch_labels = None
depends_on = None


TABLE_NAME = "hardware_settings"


def _existing_columns(table_name: str) -> set[str]:
    """Return the set of column names currently present on ``table_name``.

    Returns an empty set if the table itself does not exist or cannot be
    introspected — callers should treat that as "nothing to skip" and let
    the underlying ``ADD COLUMN`` raise the real error.
    """

    bind = op.get_bind()
    try:
        inspector = inspect(bind)
        return {col["name"] for col in inspector.get_columns(table_name)}
    except Exception:  # pragma: no cover - defensive: rely on real error
        return set()


def upgrade() -> None:
    """Add gps_source / gps_gpsd_host / gps_gpsd_port if not already present.

    This migration is idempotent against deployments where a prior run of
    ``install.sh`` fell back to ``db.create_all()`` after a failed alembic
    upgrade. ``create_all`` would have added the new columns directly from
    the ORM model definitions while leaving ``alembic_version`` pointing
    at an earlier revision. Without the existence check below, the next
    ``alembic upgrade head`` would crash with ``column "gps_source" of
    relation "hardware_settings" already exists`` and the schema would
    never advance to this revision.
    """

    existing = _existing_columns(TABLE_NAME)

    columns_to_add = []
    if "gps_source" not in existing:
        columns_to_add.append(
            sa.Column(
                "gps_source",
                sa.String(length=16),
                nullable=False,
                server_default="auto",
            )
        )
    if "gps_gpsd_host" not in existing:
        columns_to_add.append(
            sa.Column(
                "gps_gpsd_host",
                sa.String(length=100),
                nullable=False,
                server_default="127.0.0.1",
            )
        )
    if "gps_gpsd_port" not in existing:
        columns_to_add.append(
            sa.Column(
                "gps_gpsd_port",
                sa.Integer(),
                nullable=False,
                server_default="2947",
            )
        )

    if not columns_to_add:
        return

    with op.batch_alter_table(TABLE_NAME) as batch_op:
        for column in columns_to_add:
            batch_op.add_column(column)


def downgrade() -> None:
    existing = _existing_columns(TABLE_NAME)
    columns_to_drop = [
        name
        for name in ("gps_gpsd_port", "gps_gpsd_host", "gps_source")
        if name in existing
    ]
    if not columns_to_drop:
        return

    with op.batch_alter_table(TABLE_NAME) as batch_op:
        for name in columns_to_drop:
            batch_op.drop_column(name)
