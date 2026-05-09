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


revision = "20260509_add_gps_source_columns"
down_revision = "20260507_default_pps_gpio_pin_to_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hardware_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "gps_source",
                sa.String(length=16),
                nullable=False,
                server_default="auto",
            )
        )
        batch_op.add_column(
            sa.Column(
                "gps_gpsd_host",
                sa.String(length=100),
                nullable=False,
                server_default="127.0.0.1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "gps_gpsd_port",
                sa.Integer(),
                nullable=False,
                server_default="2947",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("hardware_settings") as batch_op:
        batch_op.drop_column("gps_gpsd_port")
        batch_op.drop_column("gps_gpsd_host")
        batch_op.drop_column("gps_source")
