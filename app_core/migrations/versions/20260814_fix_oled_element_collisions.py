"""Fix element collisions and clipping across the default OLED screens.

Rendering the current default screens at real size (128x64, 1-bit) surfaced
several layout bugs the smaller design mockups didn't catch:

* GPIO Status header: "GPIO STATUS" + "{count} active" collide at small font.
* Audio Health header: "AUDIO HEALTH" + status word collide -- and duplicate
  the Score row already shown below, so the header stat is just dropped.
* IPAWS Poller header: "IPAWS POLLER" + "{time}" nearly collide (2px margin).
* Clock Face: the IP address row was squeezed into the ~60px right column
  next to the date, truncating any real address to "192.168." or worse.
* GPS Status: the compass dial's cardinal labels/needle now render outside
  the ring instead of on top of the ticks (fixed in app_core/oled.py's
  render_frame()), which needs the screen's compass and text-column
  geometry adjusted to fit; also drops the illegible 9px 'satellite' icon
  in favor of 'gps_pin', and trims lat/lon to 3 decimals to make room.

All measured against real Pillow text metrics, not eyeballed pixel guesses
-- see the render_frame() 'compass' docstring for why the dial changed.

Revision ID: 20260814_fix_oled_collisions
Revises: 20260814_restyle_gpio_status
Create Date: 2026-08-14
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "20260814_fix_oled_collisions"
down_revision = "20260814_restyle_gpio_status"
branch_labels = None
depends_on = None


display_screens = table(
    "display_screens",
    column("id", sa.Integer),
    column("name", sa.String),
    column("display_type", sa.String),
    column("template_data", JSONB),
    column("updated_at", sa.DateTime),
)


GPS_STATUS_TEMPLATE = {
    "clear": True,
    "elements": [
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 11, "filled": True},
        {"type": "text", "text": "GPS STATUS", "x": 4, "y": 1, "font": "small", "invert": True},

        {"type": "compass", "x": 27, "y": 38, "radius": 13, "heading": "{gps.track_angle}"},

        {"type": "icon", "name": "gps_pin", "x": 54, "y": 14, "size": 6},
        {
            "type": "text", "text": "{gps.fix_summary}",
            "x": 61, "y": 14, "font": "small",
            "max_width": 67, "overflow": "trim", "allow_empty": True,
        },
        {
            "type": "text", "text": "LAT {gps.latitude:.3f}",
            "x": 55, "y": 26, "font": "small",
            "max_width": 71, "overflow": "trim", "allow_empty": True,
        },
        {
            "type": "text", "text": "LON {gps.longitude:.3f}",
            "x": 55, "y": 36, "font": "small",
            "max_width": 71, "overflow": "trim", "allow_empty": True,
        },
        {
            "type": "text", "text": "{gps.altitude_m:.0f}m  {gps.speed_knots:.0f}kt",
            "x": 55, "y": 46, "font": "small",
            "max_width": 71, "overflow": "trim", "allow_empty": True,
        },
        {
            "type": "bars", "x": 55, "y": 56, "width": 71, "height": 8,
            "values_source": "gps.satellite_snrs", "max_value": 50, "gap": 1,
        },
    ],
}


CLOCK_FACE_TEMPLATE = {
    "clear": True,
    "elements": [
        {"type": "clock", "x": 26, "y": 26, "radius": 22, "show_seconds": True, "show_ticks": True},
        {"type": "text", "text": "{now.time_24}", "x": 90, "y": 2, "font": "xlarge", "align": "center"},
        {"type": "text", "text": "{now.date}", "x": 90, "y": 32, "font": "small", "align": "center"},
        {"type": "hline", "x": 0, "y": 49, "width": 128},
        {"type": "icon", "name": "network", "x": 2, "y": 52, "size": 9},
        {
            "type": "text", "text": "{status.ip_address}",
            "x": 13, "y": 52, "font": "small",
            "max_width": 113, "overflow": "trim",
        },
    ],
}


def _fix_gpio_status(elements: list) -> bool:
    changed = False
    for element in elements:
        if element.get("text") == "{gpio.active_count} active":
            element["text"] = "{gpio.active_count}"
            changed = True
    return changed


def _fix_audio_health(elements: list) -> list:
    """Drop the header right-side status word -- it collides with the
    title and duplicates the Score row already shown in the body."""
    return [
        el for el in elements
        if el.get("text") != "{audio_health.overall_status}"
    ]


def _fix_ipaws_poll_watch(elements: list) -> bool:
    changed = False
    for element in elements:
        if element.get("text") == "IPAWS POLLER":
            element["text"] = "POLLER"
            changed = True
    return changed


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    # GPS Status + Clock Face: full template replace.
    for name, template in (
        ("oled_gps_status", GPS_STATUS_TEMPLATE),
        ("oled_clock_face", CLOCK_FACE_TEMPLATE),
    ):
        serialized = json.loads(json.dumps(template))
        conn.execute(
            display_screens.update()
            .where(display_screens.c.name == name)
            .where(display_screens.c.display_type == "oled")
            .values(template_data=serialized, updated_at=now)
        )

    # GPIO Status, Audio Health, IPAWS Poller: targeted element edits so any
    # user customisation elsewhere in the template survives.
    for name, fixer in (
        ("oled_gpio_status", _fix_gpio_status),
        ("oled_ipaws_poll_watch", _fix_ipaws_poll_watch),
    ):
        row = conn.execute(
            sa.text(
                "SELECT id, template_data FROM display_screens "
                "WHERE name = :name AND display_type = 'oled'"
            ),
            {"name": name},
        ).fetchone()
        if not row:
            continue
        screen_id, template_data = row
        if fixer(template_data.get("elements", [])):
            conn.execute(
                display_screens.update()
                .where(display_screens.c.id == screen_id)
                .values(template_data=template_data, updated_at=now)
            )

    row = conn.execute(
        sa.text(
            "SELECT id, template_data FROM display_screens "
            "WHERE name = 'oled_audio_health_matrix' AND display_type = 'oled'"
        )
    ).fetchone()
    if row:
        screen_id, template_data = row
        template_data["elements"] = _fix_audio_health(template_data.get("elements", []))
        conn.execute(
            display_screens.update()
            .where(display_screens.c.id == screen_id)
            .values(template_data=template_data, updated_at=now)
        )


def downgrade() -> None:
    """No-op: previous layouts can be restored via the screen editor."""
    pass
