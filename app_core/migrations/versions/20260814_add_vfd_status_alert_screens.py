"""Add a Status/Alert screen pair to the VFD, and bring its screen count
up to parity with the OLED's 11 default screens.

None of the original 4 default VFD screens (system meters, audio VU, GPS,
network) showed whether a CAP alert was currently active -- the VFD only
surfaced alerts through the separate gated-pending overlay (screen_
manager_gated.py), which only fires for alerts still awaiting operator
approval, not alerts already broadcasting. And the 140x32 canvas has
enough room to show more than one thing at a time, which none of the
existing screens did with time/date.

Adds 7 screens using the same icon+banner-header vocabulary as the rest
of the VFD screens:

* vfd_status -- time, date and the current active-alert count in one
  screen; placed first in the rotation so it's the first thing shown.
* vfd_alert_status -- the active alert's event type and area, mirroring
  oled_alert_summary's fields (same 'alerts' data source / /api/alerts
  shape), for when the operator wants the detail behind the count.
* vfd_gpio_status, vfd_eas_decoder, vfd_audio_health, vfd_ipaws_poll_
  watch, vfd_receivers -- VFD counterparts of the 5 OLED screens that had
  no VFD equivalent (oled_gpio_status, oled_eas_decoder, oled_audio_
  health_matrix, oled_ipaws_poll_watch, oled_receivers), reusing their
  data sources and field paths, compressed from the OLED's 3-4 content
  rows to the VFD's 2 (140x32 has a lot less vertical room than 128x64).
  vfd_eas_decoder uses the 'gauge' primitive for its health score instead
  of a bar -- gauge is part of the shared graphics vocabulary but wasn't
  actually used on any VFD screen until now.

All new text elements use the new max_width/overflow truncation added to
render_vfd_elements() in this same change -- event names, area
descriptions and receiver names are unbounded-length strings, and the VFD
text element had no clipping at all before this (Pillow draws straight
past the 140px edge), unlike the OLED engine which already trims/
ellipsizes.

Also gives text elements a "font": "large" option (14pt bold, vs. the
flat 7px every VFD screen used until now) -- the OLED has a small/medium/
large/xlarge size hierarchy that gives its screens visual weight; the VFD
had one size for every row on every screen, which read as flat next to
the OLED even with icons and bars in play. vfd_status (the clock),
vfd_gpio_status (active relay count), vfd_eas_decoder and vfd_audio_health
(health percentages) and vfd_ipaws_poll_watch (new-alert count) each lead
with one large hero value instead of a wall of same-sized text.

Also flips vfd_default_rotation.skip_on_alert to False. That flag is why
"not one screen shows if an alert is present" was true even with these
two new screens added: scripts/screen_manager.py's _check_vfd_rotation()
calls _has_active_alerts() and just `return`s -- freezing the VFD on
whatever was last drawn -- whenever skip_on_alert is set and a CAP alert
is active, before it ever reaches the rotation-screens loop. The OLED has
its own dedicated scroll-text alert-preemption path for this
(_handle_oled_alert_preemption) instead of skip_on_alert; the VFD has no
equivalent, so skip_on_alert there just goes blank. With it off, rotation
keeps cycling during an active alert and vfd_alert_status gets its turn
like any other screen (gated *pending* alerts, a separate concept, still
preempt rotation via the existing _gated_pending_count check either way).

Also fixes a 1px clipping bug found while regenerating the VFD gallery to
show the two new screens: vfd_system_meters' DSK row sits at y=26, and a
7px-font text row drawn there has its descender bottom at y=33 -- one
pixel past the 32px canvas. Retiming the three meter rows to y=9/17/25
(8px spacing instead of 9px) keeps every row's bottom at or under y=32.

Revision ID: 20260814_add_vfd_status_screens
Revises: 20260814_upgrade_vfd_screens
Create Date: 2026-08-14
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "20260814_add_vfd_status_screens"
down_revision = "20260814_upgrade_vfd_screens"
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


ALERTS_SOURCE = [{"endpoint": "/api/alerts", "var_name": "alerts"}]

VFD_SCREENS = {
    "vfd_status": {
        "description": "Time, date and active-alert count on VFD display",
        "priority": 1,
        "refresh_interval": 5,
        "duration": 8,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "clock", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "STATUS", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{alerts.metadata.total_features} active",
                 "x": 95, "y": 0, "invert": True, "max_width": 43, "overflow": "trim"},

                {"type": "text", "text": "{now.time_24}", "x": 2, "y": 9, "font": "large"},
                {"type": "text", "text": "{now.date}", "x": 55, "y": 13,
                 "max_width": 83, "overflow": "trim"},
            ],
        },
        "data_sources": ALERTS_SOURCE,
    },
    "vfd_alert_status": {
        "description": "Active CAP alert event and area on VFD display",
        "priority": 2,
        "refresh_interval": 5,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "warning", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "ALERT", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{alerts.metadata.total_features} active",
                 "x": 88, "y": 0, "invert": True, "max_width": 50, "overflow": "trim"},

                {"type": "text", "text": "{alerts.features[0].properties.event}",
                 "x": 0, "y": 11, "max_width": 140, "overflow": "ellipsis"},

                {"type": "icon", "name": "shield", "x": 0, "y": 20, "size": 7},
                {"type": "text", "text": "{alerts.features[0].properties.area_desc}",
                 "x": 9, "y": 20, "max_width": 131, "overflow": "ellipsis"},
            ],
        },
        "data_sources": ALERTS_SOURCE,
    },
    "vfd_gpio_status": {
        "description": "Active GPIO relays and activation count on VFD display",
        "priority": 2,
        "refresh_interval": 5,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "bolt", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "GPIO", "x": 12, "y": 0, "invert": True},

                {"type": "text", "text": "{gpio.active_count}", "x": 2, "y": 9, "font": "large",
                 "max_width": 27, "overflow": "trim"},
                {"type": "text", "text": "{gpio.active_pins_summary}", "x": 30, "y": 13,
                 "max_width": 110, "overflow": "ellipsis"},

                {"type": "text", "text": "{gpio.activations_today} activations today",
                 "x": 0, "y": 24, "max_width": 140, "overflow": "ellipsis"},
            ],
        },
        "data_sources": [{"endpoint": "/api/gpio/status", "var_name": "gpio"}],
    },
    "vfd_eas_decoder": {
        "description": "EAS decoder health gauge and detected-alert count on VFD display",
        "priority": 2,
        "refresh_interval": 5,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "antenna", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "EAS", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{eas_monitor.active_sources} src",
                 "x": 100, "y": 0, "invert": True, "max_width": 38, "overflow": "trim"},

                {"type": "gauge", "x": 18, "y": 20, "radius": 11, "value": "{eas_monitor.health_percentage}"},
                {"type": "text", "text": "{eas_monitor.health_percentage:.0f}%", "x": 34, "y": 9,
                 "font": "large", "max_width": 60, "overflow": "trim"},
                {"type": "text", "text": "Alerts {eas_monitor.alerts_detected}",
                 "x": 34, "y": 24, "max_width": 104, "overflow": "ellipsis"},
            ],
        },
        "data_sources": [{"endpoint": "/api/eas-monitor/status", "var_name": "eas_monitor"}],
    },
    "vfd_audio_health": {
        "description": "Overall audio source health score and active-source count on VFD display",
        "priority": 2,
        "refresh_interval": 10,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "heartbeat", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "HEALTH", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{audio_health.overall_status}",
                 "x": 95, "y": 0, "invert": True, "max_width": 43, "overflow": "trim"},

                {"type": "text", "text": "{audio_health.overall_health_score:.0f}%", "x": 0, "y": 9,
                 "font": "large", "max_width": 48, "overflow": "trim"},
                {"type": "bar", "x": 50, "y": 13, "width": 84, "height": 6,
                 "value": "{audio_health.overall_health_score}"},

                {"type": "icon", "name": "wave", "x": 0, "y": 24, "size": 7},
                {"type": "text", "text": "{audio_health.active_sources}/{audio_health.total_sources} active",
                 "x": 9, "y": 24, "max_width": 131, "overflow": "ellipsis"},
            ],
        },
        "data_sources": [{"endpoint": "/api/audio/health", "var_name": "audio_health"}],
    },
    "vfd_ipaws_poll_watch": {
        "description": "Latest CAP/IPAWS poll status and fetch counts on VFD display",
        "priority": 2,
        "refresh_interval": 15,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "shield", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "POLLER", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{now.time_24}", "x": 111, "y": 0, "invert": True},

                {"type": "text", "text": "+{status.last_poll.alerts_new}", "x": 2, "y": 9, "font": "large",
                 "max_width": 40, "overflow": "trim"},
                {"type": "text", "text": "new", "x": 38, "y": 13,
                 "max_width": 30, "overflow": "trim"},

                {"type": "text", "text": "{status.last_poll.status}, {status.last_poll.alerts_fetched} fetched",
                 "x": 0, "y": 24, "max_width": 140, "overflow": "ellipsis"},
            ],
        },
        "data_sources": [{"endpoint": "/api/system_status", "var_name": "status"}],
    },
    "vfd_receivers": {
        "description": "Signal strength for up to two SDR receivers on VFD display",
        "priority": 2,
        "refresh_interval": 5,
        "duration": 10,
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 8, "filled": True},
                {"type": "icon", "name": "antenna", "x": 2, "y": 0, "size": 7, "invert": True},
                {"type": "text", "text": "RX", "x": 12, "y": 0, "invert": True},
                {"type": "text", "text": "{radio.count}",
                 "x": 111, "y": 0, "invert": True, "max_width": 27, "overflow": "trim"},

                {"type": "icon", "name": "check", "x": 0, "y": 11, "size": 7},
                {"type": "text",
                 "text": "{radio.receivers[0].display_name} {radio.receivers[0].latest_status.signal_strength}dBm",
                 "x": 9, "y": 11, "max_width": 131, "overflow": "ellipsis"},

                {"type": "icon", "name": "check", "x": 0, "y": 20, "size": 7},
                {"type": "text",
                 "text": "{radio.receivers[1].display_name} {radio.receivers[1].latest_status.signal_strength}dBm",
                 "x": 9, "y": 20, "max_width": 131, "overflow": "ellipsis"},
            ],
        },
        "data_sources": [{"endpoint": "/api/monitoring/radio", "var_name": "radio"}],
    },
}


_SYSTEM_METERS_ROW_FIX = {9: 9, 18: 17, 26: 25}


def _fix_system_meters_row_clipping(elements: list) -> bool:
    """Retime the CPU/MEM/DSK rows so DSK's text no longer draws 1px past
    the 32px canvas bottom (y=26 -> bottom=33). See module docstring."""
    changed = False
    for element in elements:
        if element.get("type") not in ("text", "bar"):
            continue
        y = element.get("y")
        if y in _SYSTEM_METERS_ROW_FIX and _SYSTEM_METERS_ROW_FIX[y] != y:
            element["y"] = _SYSTEM_METERS_ROW_FIX[y]
            changed = True
    return changed


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    new_entries_by_name = {}

    row = conn.execute(
        sa.text(
            "SELECT id, template_data FROM display_screens "
            "WHERE name = 'vfd_system_meters' AND display_type = 'vfd'"
        )
    ).fetchone()
    if row:
        screen_id, template_data = row
        if _fix_system_meters_row_clipping(template_data.get("elements", [])):
            conn.execute(
                display_screens.update()
                .where(display_screens.c.id == screen_id)
                .values(template_data=template_data, updated_at=now)
            )

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
            new_entries_by_name[name] = {"screen_id": screen_id, "duration": spec["duration"]}

    if not new_entries_by_name:
        return

    rotation_result = conn.execute(
        sa.text("SELECT id, screens FROM screen_rotations WHERE name = 'vfd_default_rotation'"),
    ).fetchone()

    if rotation_result:
        existing_id, existing_screens = rotation_result
        existing_screens = list(existing_screens or [])
        existing_screen_ids = {s.get("screen_id") for s in existing_screens}

        # vfd_status leads the rotation -- it's the at-a-glance home screen.
        # Every other new screen (vfd_alert_status plus this change's parity
        # screens) joins the back, in VFD_SCREENS dict order, alongside the
        # existing detail screens.
        if "vfd_status" in new_entries_by_name and new_entries_by_name["vfd_status"]["screen_id"] not in existing_screen_ids:
            existing_screens = [new_entries_by_name["vfd_status"]] + existing_screens

        for name, entry in new_entries_by_name.items():
            if name == "vfd_status":
                continue
            if entry["screen_id"] not in existing_screen_ids:
                existing_screens = existing_screens + [entry]

        conn.execute(
            screen_rotations.update()
            .where(screen_rotations.c.id == existing_id)
            .values(screens=existing_screens, skip_on_alert=False, updated_at=now)
        )
    else:
        ordered = []
        if "vfd_status" in new_entries_by_name:
            ordered.append(new_entries_by_name["vfd_status"])
        for name, entry in new_entries_by_name.items():
            if name != "vfd_status":
                ordered.append(entry)
        conn.execute(
            screen_rotations.insert().values(
                name="vfd_default_rotation",
                description="Default VFD screen rotation cycle",
                display_type="vfd",
                enabled=True,
                screens=ordered,
                randomize=False,
                skip_on_alert=False,
                created_at=now,
                updated_at=None,
                current_screen_index=0,
                last_rotation_at=None,
            )
        )


def downgrade() -> None:
    """No-op: the screens can be removed via the screen editor."""
    pass
