"""Seed the LED sign's default screens for the first time; add graphics
mode; fix the LED's own alert-freeze bug.

scripts/create_example_screens.py defines 6 default LED screens (plain
scrolling/held text via send_message()) and a led_default_rotation, but
-- unlike every OLED/VFD screen migration -- nothing has ever inserted
them through Alembic; querying production confirms zero rows at
display_type='led' in either display_screens or screen_rotations. This
migration is what 20260814_upgrade_vfd_screens.py was for the VFD:
establishing the baseline for real, via the same insert-if-missing
pattern, not assuming a seed script ran at some point.

Also adds 3 new single-row "hero" graphics screens using render_led_
elements()/render_frame() (scripts/led_sign_controller.py) -- the sign's
Picture File (DOTS) capability exists at the protocol layer
(send_dots_graphic()) and was reachable manually from the Dots tab, but
was never wired into the rotation/template system the way OLED and VFD's
icon/gauge/bar vocabulary was earlier this session. The canvas is
160x16 -- half the VFD's 32 rows and a quarter of the OLED's 64 -- so
these are a single icon+hero-value+label row each, not an instrument
panel:

* led_status_graphic -- clock icon, large time, small active-alert count.
* led_alert_graphic -- warning icon, large active-alert count, "ACTIVE"
  label.
* led_system_graphic -- heartbeat icon, large CPU percentage, small
  MEM/DSK readout.

The 3 graphics screens will only display correctly once the sign's
Memory Configuration has a DOTS-type file allocated -- see webapp/
routes_led.py's new /api/led/configure_graphics_memory (Admin-only,
confirm-gated, **destructive**: erases every message stored on the sign)
and the "Sign Memory" panel on the Dots tab of the LED control page.
This migration does NOT call that itself -- memory allocation is a
one-time, deliberate, manual action against a specific physical sign,
never something a schema migration should trigger automatically. The 6
legacy text screens need no such setup and work immediately.

Also seeds led_default_rotation with skip_on_alert already False (rather
than the True scripts/create_example_screens.py would have used),
avoiding the same bug 20260814_add_vfd_status_screens.py fixed on the
VFD earlier today: _check_led_rotation() (scripts/screen_manager.py)
returns before ever reaching the rotation loop whenever skip_on_alert is
set and a CAP alert is active, freezing the sign on whatever was last
drawn -- the LED has no OLED-style alert-preemption path, so
led_alert_summary (scrolling text, seeded here unmodified from its
create_example_screens.py definition) needs the rotation to keep running
to ever actually be shown during a real alert.

Revision ID: 20260814_add_led_graphics
Revises: 20260814_add_vfd_status_screens
Create Date: 2026-08-14
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "20260814_add_led_graphics"
down_revision = "20260814_add_vfd_status_screens"
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

# The 6 legacy text screens, copied verbatim from scripts/create_example_
# screens.py's LED_SYSTEM_STATUS / LED_RESOURCES / LED_NETWORK_INFO /
# LED_ALERT_SUMMARY / LED_TIME_DATE / LED_RECEIVER_STATUS -- this
# migration is the first thing to actually seed them (see module
# docstring), so their content is preserved exactly as already defined
# and tested elsewhere, not redesigned here.
LED_LEGACY_SCREENS = {
    "led_system_status": {
        "description": "Overall system health status on LED display",
        "priority": 2,
        "refresh_interval": 30,
        "duration": 10,
        "template_data": {
            "lines": [
                "SYSTEM STATUS",
                "Health: {status.status}",
                "Alerts: {status.active_alerts_count}",
                "DB: {status.database_status}",
            ],
            "color": "GREEN", "mode": "HOLD", "speed": "SPEED_3", "font": "FONT_7x9",
        },
        "data_sources": [{"endpoint": "/api/system_status", "var_name": "status"}],
    },
    "led_resources": {
        "description": "CPU, memory, and disk usage on LED display",
        "priority": 2,
        "refresh_interval": 15,
        "duration": 10,
        "template_data": {
            "lines": [
                "SYSTEM RESOURCES",
                "CPU: {status.system_resources.cpu_usage_percent}%",
                "MEM: {status.system_resources.memory_usage_percent}%",
                "DISK: {status.system_resources.disk_usage_percent}%",
            ],
            "color": "AMBER", "mode": "HOLD", "speed": "SPEED_3", "font": "FONT_7x9",
        },
        "data_sources": [{"endpoint": "/api/system_status", "var_name": "status"}],
    },
    "led_network_info": {
        "description": "Network information and IP address",
        "priority": 2,
        "refresh_interval": 60,
        "duration": 10,
        "template_data": {
            "lines": ["NETWORK INFO", "IP: {network.ip_address}", "Up: {network.uptime_human}", "{now.time}"],
            "color": "BLUE", "mode": "HOLD", "speed": "SPEED_3", "font": "FONT_5x7",
        },
        "data_sources": [{"endpoint": "/api/system_status", "var_name": "network"}],
    },
    "led_alert_summary": {
        "description": "Active alert count and latest alert",
        "priority": 1,
        "refresh_interval": 10,
        "duration": 15,
        "template_data": {
            "lines": [
                "ACTIVE ALERTS: {alerts.features.length}",
                "{alerts.features[0].properties.event}",
                "Severity: {alerts.features[0].properties.severity}",
                "Expires: {alerts.features[0].properties.expires_iso}",
            ],
            "color": "ORANGE", "mode": "SCROLL", "speed": "SPEED_4", "font": "FONT_7x9",
        },
        "data_sources": [{"endpoint": "/api/alerts", "var_name": "alerts"}],
        "conditions": {"var": "alerts.features.length", "op": ">", "value": 0},
    },
    "led_time_date": {
        "description": "Current time and date display",
        "priority": 3,
        "refresh_interval": 60,
        "duration": 8,
        "template_data": {
            "lines": ["{location.county_name}", "{location.state_code}", "{now.date}", "{now.time}"],
            "color": "GREEN", "mode": "HOLD", "speed": "SPEED_3", "font": "FONT_7x9",
        },
        "data_sources": [{"endpoint": "/api/system_status", "var_name": "location"}],
    },
    "led_receiver_status": {
        "description": "Radio receiver signal strength",
        "priority": 2,
        "refresh_interval": 20,
        "duration": 10,
        "template_data": {
            "lines": [
                "RECEIVER STATUS",
                "{radio.receivers[0].display_name}",
                "Signal: {radio.receivers[0].latest_status.signal_strength} dBm",
                "Lock: {radio.receivers[0].latest_status.locked}",
            ],
            "color": "CYAN", "mode": "HOLD", "speed": "SPEED_3", "font": "FONT_7x9",
        },
        "data_sources": [{"endpoint": "/api/monitoring/radio", "var_name": "radio"}],
    },
}

LED_SCREENS = {
    **LED_LEGACY_SCREENS,
    "led_status_graphic": {
        "description": "Time and active-alert count on the LED sign (Dots/graphics mode)",
        "priority": 1,
        "refresh_interval": 5,
        "duration": 8,
        "template_data": {
            "elements": [
                {"type": "icon", "name": "clock", "x": 1, "y": 1, "size": 14},
                {"type": "text", "text": "{now.time_24}", "x": 18, "y": 1,
                 "font": "large", "max_width": 50, "overflow": "trim"},
                {"type": "icon", "name": "warning", "x": 78, "y": 3, "size": 9},
                {"type": "text", "text": "{alerts.metadata.total_features} active",
                 "x": 89, "y": 5, "max_width": 68, "overflow": "ellipsis"},
            ],
            "color": "AMBER",
        },
        "data_sources": ALERTS_SOURCE,
    },
    "led_alert_graphic": {
        "description": "Active CAP alert count, large, on the LED sign (Dots/graphics mode)",
        "priority": 2,
        "refresh_interval": 5,
        "duration": 10,
        "template_data": {
            "elements": [
                {"type": "icon", "name": "warning", "x": 1, "y": 1, "size": 14},
                {"type": "text", "text": "{alerts.metadata.total_features}", "x": 18, "y": 1,
                 "font": "large", "max_width": 40, "overflow": "trim"},
                {"type": "text", "text": "ACTIVE", "x": 48, "y": 5,
                 "max_width": 110, "overflow": "ellipsis"},
            ],
            "color": "RED",
        },
        "data_sources": ALERTS_SOURCE,
    },
    "led_system_graphic": {
        "description": "CPU usage, large, plus MEM/DSK on the LED sign (Dots/graphics mode)",
        "priority": 2,
        "refresh_interval": 15,
        "duration": 10,
        "template_data": {
            "elements": [
                {"type": "icon", "name": "heartbeat", "x": 1, "y": 1, "size": 14},
                {"type": "text", "text": "{status.system_resources.cpu_usage_percent:.0f}%",
                 "x": 18, "y": 1, "font": "large", "max_width": 48, "overflow": "trim"},
                {"type": "text", "text": "CPU", "x": 70, "y": 5, "max_width": 18, "overflow": "trim"},
                {"type": "text",
                 "text": "MEM {status.system_resources.memory_usage_percent:.0f}% "
                         "DSK {status.system_resources.disk_usage_percent:.0f}%",
                 "x": 90, "y": 5, "max_width": 69, "overflow": "ellipsis"},
            ],
            "color": "AMBER",
        },
        "data_sources": [{"endpoint": "/api/system_status", "var_name": "status"}],
    },
}


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    new_entries_by_name = {}

    for name, spec in LED_SCREENS.items():
        existing = conn.execute(
            sa.text("SELECT id FROM display_screens WHERE name = :name"),
            {"name": name},
        ).fetchone()

        if existing:
            screen_id = existing[0]
            conn.execute(
                display_screens.update()
                .where(display_screens.c.id == screen_id)
                .values(
                    template_data=spec["template_data"],
                    conditions=spec.get("conditions"),
                    updated_at=now,
                )
            )
        else:
            result = conn.execute(
                display_screens.insert().values(
                    name=name,
                    description=spec["description"],
                    display_type="led",
                    enabled=True,
                    priority=spec["priority"],
                    refresh_interval=spec["refresh_interval"],
                    duration=spec["duration"],
                    template_data=spec["template_data"],
                    data_sources=spec["data_sources"],
                    conditions=spec.get("conditions"),
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
        sa.text("SELECT id, screens FROM screen_rotations WHERE name = 'led_default_rotation'"),
    ).fetchone()

    if rotation_result:
        existing_id, existing_screens = rotation_result
        existing_screens = list(existing_screens or [])
        existing_screen_ids = {s.get("screen_id") for s in existing_screens}

        # led_status_graphic leads -- the at-a-glance home screen, same
        # convention as vfd_status.
        if "led_status_graphic" in new_entries_by_name and new_entries_by_name["led_status_graphic"]["screen_id"] not in existing_screen_ids:
            existing_screens = [new_entries_by_name["led_status_graphic"]] + existing_screens

        for name, entry in new_entries_by_name.items():
            if name == "led_status_graphic":
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
        if "led_status_graphic" in new_entries_by_name:
            ordered.append(new_entries_by_name["led_status_graphic"])
        for name, entry in new_entries_by_name.items():
            if name != "led_status_graphic":
                ordered.append(entry)
        conn.execute(
            screen_rotations.insert().values(
                name="led_default_rotation",
                description="Default LED screen rotation cycle",
                display_type="led",
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
