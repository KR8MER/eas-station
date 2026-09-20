"""Add a world-clock + EAS status LED screen to the default LED rotation.

Adds a new LED screen ("led_world_clock_status") showing Eastern/Zulu/
Central time on three HOLD lines and a rolling EAS pipeline status line
(active alert count + decoder sync) on a fourth SCROLL line, then appends
it to the existing "led_default_rotation". Follows the exact idempotent
insert-if-missing / append-if-present pattern established by
20260814_add_gps_oled_screen.py.

Time-zone values come from two new `now.time_zulu` / `now.time_central`
built-in template variables added to ScreenRenderer.substitute_variables()
in scripts/screen_renderer.py (same change set as this migration) -- see
that file for the zoneinfo-based implementation.

Note: the Alpha 9120C hard-caps every line, including SCROLL-mode lines,
at 20 characters (scripts/led_sign_controller.py's max_chars_per_line) --
this is the sign's real per-line buffer, not a display-only limit. The
status line is written to stay within that budget for its normal range of
values; if the underlying text ever runs long it degrades by truncating
at 20 characters (the same way every other screen in this rotation
already does), never by erroring.

Revision ID: 20260919_add_led_world_clock_screen
Revises: 20260918_healthchecks_settings
Create Date: 2026-09-19
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "20260919_add_led_world_clock_screen"
down_revision = "20260918_healthchecks_settings"
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


CLOCK_SCREEN = {
    "name": "led_world_clock_status",
    "description": (
        "World clock (Eastern/Zulu/Central) with a rolling EAS pipeline "
        "status line (active alert count + decoder sync)."
    ),
    "display_type": "led",
    "enabled": True,
    "priority": 4,
    "refresh_interval": 30,
    "duration": 15,
    "template_data": {
        "font": "FONT_7x9",
        "color": "GREEN",
        "mode": "HOLD",
        "speed": "SPEED_3",
        "lines": [
            "EASTERN   {now.time}",
            "ZULU      {now.time_zulu}",
            "CENTRAL   {now.time_central}",
            {
                "text": "ALERTS:{status.active_alerts_count} SYNC:{eas_monitor.decoder_synced}",
                "mode": "SCROLL",
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/system_status", "var_name": "status"},
        {"endpoint": "/api/eas-monitor/status", "var_name": "eas_monitor"},
    ],
}


def upgrade() -> None:
    """Add the LED world-clock/status screen and append it to led_default_rotation."""
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    existing = conn.execute(
        sa.text("SELECT id FROM display_screens WHERE name = :name"),
        {"name": CLOCK_SCREEN["name"]},
    ).fetchone()

    if existing:
        screen_id = existing[0]
    else:
        result = conn.execute(
            display_screens.insert().values(
                name=CLOCK_SCREEN["name"],
                description=CLOCK_SCREEN["description"],
                display_type=CLOCK_SCREEN["display_type"],
                enabled=CLOCK_SCREEN["enabled"],
                priority=CLOCK_SCREEN["priority"],
                refresh_interval=CLOCK_SCREEN["refresh_interval"],
                duration=CLOCK_SCREEN["duration"],
                template_data=CLOCK_SCREEN["template_data"],
                data_sources=CLOCK_SCREEN["data_sources"],
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
        {"name": "led_default_rotation"},
    ).fetchone()

    screen_entry = {"screen_id": screen_id, "duration": CLOCK_SCREEN["duration"]}

    if rotation_result:
        existing_id, existing_screens = rotation_result
        existing_screen_ids = {s.get("screen_id") for s in (existing_screens or [])}
        if screen_id not in existing_screen_ids:
            updated_screens = list(existing_screens or []) + [screen_entry]
            # table.update() (not a raw sa.text() UPDATE) so the JSONB
            # `screens` column is serialised correctly -- see the identical
            # comment in 20260814_add_gps_oled_screen.py for why a bare
            # text() bind parameter breaks this.
            conn.execute(
                screen_rotations.update()
                .where(screen_rotations.c.id == existing_id)
                .values(screens=updated_screens, updated_at=now)
            )
    else:
        # No existing LED rotation -- create one. Matches skip_on_alert=False,
        # the convention already used for LED/VFD (only OLED's default
        # rotation skips during alerts; LED surfaces alerts via a
        # conditional screen inside the rotation instead -- see
        # led_alert_summary).
        conn.execute(
            screen_rotations.insert().values(
                name="led_default_rotation",
                description="Default LED screen rotation cycle",
                display_type="led",
                enabled=True,
                screens=[screen_entry],
                randomize=False,
                skip_on_alert=False,
                created_at=now,
                updated_at=None,
                current_screen_index=0,
                last_rotation_at=None,
            )
        )


def downgrade() -> None:
    """Intentionally a no-op -- see 20251116_populate_oled_example_screens.py's
    downgrade() for the rationale (avoid deleting a screen a user has since
    customized). Remove manually via the Screens admin UI (/screens) if
    truly unwanted.
    """
    pass
