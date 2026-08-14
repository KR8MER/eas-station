"""Give the 3 default VFD screens the same icon/graphics vocabulary the
OLED screens have -- and seed them if they don't exist yet.

The VFD hardware (Noritake GU140x32F-7000B) already supported full bitmap
pushes via draw_bitmap(), but the template system only ever drove it
through a handful of discrete GU-7000 draw commands (text/rectangle/line)
with no icon, gauge, compass, or multi-value bar-chart support -- and two
real bugs (see scripts/vfd_controller.py's render_frame()/render_vfd_
elements() and tests/test_vfd_display_bugs.py) meant custom VFD screens
were failing to render at all. Now that both are fixed and the VFD has the
same PIL-based whole-frame render engine as the OLED, this reflows the 3
example screens (scripts/create_example_screens.py) onto it: icon+banner
headers matching the OLED convention, and a smaller ~7px font sized for
the 32px-tall canvas (roughly the panel's native 5x7/7x10 font sizes --
the old 10px default left room for only ~2 text rows).

Unlike 20260610_refresh_default_screen_designs.py (which only UPDATEs
existing rows), this inserts the screens if missing, following
20251116_populate_oled_example_screens.py's pattern: some installs never
had these seeded (no VFD hardware attached yet at setup time), so an
UPDATE-only migration would silently do nothing there -- update.sh runs
this against every install, not just ones with a VFD already configured.

Revision ID: 20260814_upgrade_vfd_screens
Revises: 20260814_fix_oled_collisions
Create Date: 2026-08-14
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "20260814_upgrade_vfd_screens"
down_revision = "20260814_fix_oled_collisions"
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


VFD_SCREENS = {
    "vfd_system_meters": {
        "description": "CPU, Memory, Disk usage as VU meters on VFD",
        "priority": 2,
        "refresh_interval": 5,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "heartbeat", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "SYSTEM", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{now.time_24}", "x": 111, "y": 0, "invert": True},

                {"type": "text", "text": "CPU", "x": 0, "y": 9},
                {"type": "bar", "x": 24, "y": 9, "width": 88, "height": 6,
                 "value": "{status.system_resources.cpu_usage_percent}"},
                {"type": "text", "text": "{status.system_resources.cpu_usage_percent:.0f}%", "x": 115, "y": 9},

                {"type": "text", "text": "MEM", "x": 0, "y": 18},
                {"type": "bar", "x": 24, "y": 18, "width": 88, "height": 6,
                 "value": "{status.system_resources.memory_usage_percent}"},
                {"type": "text", "text": "{status.system_resources.memory_usage_percent:.0f}%", "x": 115, "y": 18},

                {"type": "text", "text": "DSK", "x": 0, "y": 26},
                {"type": "bar", "x": 24, "y": 26, "width": 88, "height": 6,
                 "value": "{status.system_resources.disk_usage_percent}"},
                {"type": "text", "text": "{status.system_resources.disk_usage_percent:.0f}%", "x": 115, "y": 26},
            ],
        },
        "data_sources": [{"endpoint": "/api/system_status", "var_name": "status"}],
    },
    "vfd_audio_vu_meter": {
        "description": "Audio source VU meter on VFD display",
        "priority": 2,
        "refresh_interval": 1,
        "duration": 15,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "wave", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "AUDIO", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{audio.total_sources}src", "x": 108, "y": 0, "invert": True},

                {"type": "text", "text": "PK", "x": 0, "y": 11},
                {"type": "segments", "x": 18, "y": 10, "width": 100, "height": 8,
                 "value": "{audio.peak_level_percent}", "count": 14, "gap": 2},
                {"type": "text", "text": "{audio.peak_level_percent:.0f}", "x": 121, "y": 11},

                {"type": "text", "text": "RMS", "x": 0, "y": 22},
                {"type": "segments", "x": 18, "y": 21, "width": 100, "height": 8,
                 "value": "{audio.rms_level_percent}", "count": 14, "gap": 2},
                {"type": "text", "text": "{audio.rms_level_percent:.0f}", "x": 121, "y": 22},
            ],
        },
        "data_sources": [{"endpoint": "/api/audio/metrics/latest", "var_name": "audio"}],
    },
    "vfd_gps_status": {
        "description": "GPS fix: heading compass and lat/lon on VFD display",
        "priority": 2,
        "refresh_interval": 5,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "gps_pin", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "GPS", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{gps.fix_summary}", "x": 68, "y": 0, "invert": True},

                {"type": "compass", "x": 16, "y": 20, "radius": 11, "heading": "{gps.track_angle}"},

                {"type": "text", "text": "LAT {gps.latitude:.3f}", "x": 32, "y": 11},
                {"type": "text", "text": "LON {gps.longitude:.3f}", "x": 32, "y": 21},
            ],
        },
        "data_sources": [{"endpoint": "/api/gps_status", "var_name": "gps"}],
    },
    "vfd_network_status": {
        "description": "Hostname, IP, interface and uptime on VFD display",
        "priority": 2,
        "refresh_interval": 15,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "network", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "NETWORK", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{health.network.primary_interface_name}", "x": 100, "y": 0, "invert": True},

                {"type": "icon", "name": "network", "x": 2, "y": 11, "size": 7},
                {"type": "text", "text": "{health.system.hostname}", "x": 12, "y": 11},

                {"type": "icon", "name": "clock", "x": 2, "y": 20, "size": 7},
                {"type": "text", "text": "{health.network.primary_ipv4}  Up {health.system.uptime_human}",
                 "x": 12, "y": 20},
            ],
        },
        "data_sources": [{"endpoint": "/api/system_health", "var_name": "health"}],
    },
}


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    screen_ids = []

    for name, spec in VFD_SCREENS.items():
        existing = conn.execute(
            sa.text("SELECT id FROM display_screens WHERE name = :name"),
            {"name": name},
        ).fetchone()

        if existing:
            screen_id = existing[0]
            conn.execute(
                display_screens.update()
                .where(display_screens.c.id == screen_id)
                .values(template_data=spec["template_data"], updated_at=now)
            )
        else:
            result = conn.execute(
                display_screens.insert().values(
                    name=name,
                    description=spec["description"],
                    display_type="vfd",
                    enabled=True,
                    priority=spec["priority"],
                    refresh_interval=spec["refresh_interval"],
                    duration=spec["duration"],
                    template_data=spec["template_data"],
                    data_sources=spec["data_sources"],
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

        if screen_id is not None:
            screen_ids.append({"screen_id": screen_id, "duration": spec["duration"]})

    if not screen_ids:
        return

    rotation_result = conn.execute(
        sa.text("SELECT id, screens FROM screen_rotations WHERE name = :name"),
        {"name": "vfd_default_rotation"},
    ).fetchone()

    if rotation_result:
        existing_id, existing_screens = rotation_result
        existing_screen_ids = {s.get("screen_id") for s in (existing_screens or [])}
        new_entries = [s for s in screen_ids if s["screen_id"] not in existing_screen_ids]
        if new_entries:
            updated_screens = list(existing_screens or []) + new_entries
            conn.execute(
                screen_rotations.update()
                .where(screen_rotations.c.id == existing_id)
                .values(screens=updated_screens, updated_at=now)
            )
    else:
        conn.execute(
            screen_rotations.insert().values(
                name="vfd_default_rotation",
                description="Default VFD screen rotation cycle",
                display_type="vfd",
                enabled=True,
                screens=screen_ids,
                randomize=False,
                skip_on_alert=True,
                created_at=now,
                updated_at=None,
                current_screen_index=0,
                last_rotation_at=None,
            )
        )


def downgrade() -> None:
    """No-op: previous layouts (or the screens themselves) can be restored
    via the screen editor -- see 20251116_populate_oled_example_screens.py's
    downgrade() for the rationale.
    """
    pass
