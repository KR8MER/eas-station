"""Add a GPS status OLED screen to the default rotation.

Adds a new example OLED screen ("GPS Status") built from the new
'compass' and 'bars' render_frame() primitives (heading dial + a
per-satellite SNR bar chart), sourced from /api/gps_status. Follows the
exact idempotent insert-if-missing pattern established by
20251116_populate_oled_example_screens.py: skip if a screen with this
name already exists, append to the existing "oled_default_rotation" if
present, create it otherwise.

Revision ID: 20260814_add_gps_oled_screen
Revises: 20260814_gate_pending_color
Create Date: 2026-08-14
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "20260814_add_gps_oled_screen"
down_revision = "20260814_gate_pending_color"
branch_labels = None
depends_on = None


display_screens = table(
    "display_screens",
    column("id", sa.Integer),
    column("name", sa.String),
    column("description", sa.Text),
    column("display_type", sa.String),
    column("enabled", sa.Boolean),
    column("priority", sa.Integer),
    column("refresh_interval", sa.Integer),
    column("duration", sa.Integer),
    column("template_data", JSONB),
    column("data_sources", JSONB),
    column("conditions", JSONB),
    column("created_at", sa.DateTime),
    column("updated_at", sa.DateTime),
    column("last_displayed_at", sa.DateTime),
    column("display_count", sa.Integer),
    column("error_count", sa.Integer),
    column("last_error", sa.Text),
)

screen_rotations = table(
    "screen_rotations",
    column("id", sa.Integer),
    column("name", sa.String),
    column("description", sa.Text),
    column("display_type", sa.String),
    column("enabled", sa.Boolean),
    column("screens", JSONB),
    column("randomize", sa.Boolean),
    column("skip_on_alert", sa.Boolean),
    column("created_at", sa.DateTime),
    column("updated_at", sa.DateTime),
    column("current_screen_index", sa.Integer),
    column("last_rotation_at", sa.DateTime),
)


GPS_SCREEN = {
    "name": "oled_gps_status",
    "description": "GPS fix: heading compass, lat/lon/altitude/speed, and a per-satellite signal bar chart.",
    "display_type": "oled",
    "enabled": True,
    "priority": 10,
    "refresh_interval": 5,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 11, "filled": True},
            {"type": "text", "text": "GPS STATUS", "x": 4, "y": 1, "font": "small", "invert": True},

            {"type": "compass", "x": 22, "y": 40, "radius": 18, "heading": "{gps.track_angle}"},

            {"type": "icon", "name": "satellite", "x": 46, "y": 13, "size": 9},
            {"type": "text", "text": "{gps.fix_summary}", "x": 58, "y": 14, "font": "small", "max_width": 68},

            {"type": "text", "text": "LAT {gps.latitude:.4f}", "x": 46, "y": 26, "font": "small", "max_width": 80},
            {"type": "text", "text": "LON {gps.longitude:.4f}", "x": 46, "y": 36, "font": "small", "max_width": 80},
            {"type": "text", "text": "ALT {gps.altitude_m:.0f}m  {gps.speed_knots:.0f}kt", "x": 46, "y": 46, "font": "small", "max_width": 80},

            {"type": "bars", "x": 46, "y": 56, "width": 80, "height": 8,
             "values_source": "gps.satellite_snrs", "max_value": 50, "gap": 1},
        ],
    },
    "data_sources": [
        {"endpoint": "/api/gps_status", "var_name": "gps"},
    ],
}


def upgrade() -> None:
    """Add the GPS status screen and append it to the default OLED rotation."""
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    existing = conn.execute(
        sa.text("SELECT id FROM display_screens WHERE name = :name"),
        {"name": GPS_SCREEN["name"]},
    ).fetchone()

    if existing:
        screen_id = existing[0]
    else:
        result = conn.execute(
            display_screens.insert().values(
                name=GPS_SCREEN["name"],
                description=GPS_SCREEN["description"],
                display_type=GPS_SCREEN["display_type"],
                enabled=GPS_SCREEN["enabled"],
                priority=GPS_SCREEN["priority"],
                refresh_interval=GPS_SCREEN["refresh_interval"],
                duration=GPS_SCREEN["duration"],
                template_data=GPS_SCREEN["template_data"],
                data_sources=GPS_SCREEN["data_sources"],
                conditions=None,
                created_at=now,
                updated_at=None,
                last_displayed_at=None,
                display_count=0,
                error_count=0,
                last_error=None,
            ).returning(display_screens.c.id)
        )
        row = result.fetchone()
        screen_id = row[0] if row else None

    if screen_id is None:
        return

    rotation_result = conn.execute(
        sa.text("SELECT id, screens FROM screen_rotations WHERE name = :name"),
        {"name": "oled_default_rotation"},
    ).fetchone()

    screen_entry = {"screen_id": screen_id, "duration": GPS_SCREEN["duration"]}

    if rotation_result:
        existing_id, existing_screens = rotation_result
        existing_screen_ids = {s.get("screen_id") for s in (existing_screens or [])}
        if screen_id not in existing_screen_ids:
            updated_screens = list(existing_screens or []) + [screen_entry]
            # Core's typed update() construct, not a raw sa.text() UPDATE --
            # a plain text() bind parameter carries no column type, so
            # psycopg2 has nothing telling it to JSON-encode a Python list
            # of dicts for the JSONB `screens` column ("can't adapt type
            # 'dict'"). table.update() knows the column is JSONB and
            # serialises it correctly.
            conn.execute(
                screen_rotations.update()
                .where(screen_rotations.c.id == existing_id)
                .values(screens=updated_screens, updated_at=now)
            )
    else:
        conn.execute(
            screen_rotations.insert().values(
                name="oled_default_rotation",
                description="Default OLED screen rotation cycle",
                display_type="oled",
                enabled=True,
                screens=[screen_entry],
                randomize=False,
                skip_on_alert=True,
                created_at=now,
                updated_at=None,
                current_screen_index=0,
                last_rotation_at=None,
            )
        )


def downgrade() -> None:
    """Intentionally a no-op -- see 20251116_populate_oled_example_screens.py's
    downgrade() for the rationale (avoid deleting a screen a user has since
    customized). Remove manually via the Screens admin UI if truly unwanted.
    """
    pass
