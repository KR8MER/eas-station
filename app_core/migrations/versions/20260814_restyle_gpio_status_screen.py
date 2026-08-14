"""Restyle the GPIO Status OLED screen to match the icon+bar design language.

Every other default OLED screen already went through the graphical-elements
redesign (20260216_improve_oled_screens.py, 20260610_refresh_default_screen_designs.py)
except this one, which was still on the legacy plain-text 'lines' format
with no icons or dividers. Its header line also used invert=True with no
filled rectangle behind it, which renders as black-on-black -- invisible.
Follows the exact update-existing-row pattern from those two migrations.

Revision ID: 20260814_restyle_gpio_status
Revises: 20260814_add_gps_oled_screen
Create Date: 2026-08-14
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "20260814_restyle_gpio_status"
down_revision = "20260814_add_gps_oled_screen"
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


# ── GPIO STATUS (restyled) ────────────────────────────────────────────
# Same header banner + icon-led content rows + divider + footer language
# as every other default screen (see 20260216_improve_oled_screens.py's
# layout-grid comment).
#
#  ┌────────────────────────────────────────┐
#  │▓⚡GPIO STATUS▓▓▓▓▓▓▓▓▓▓▓▓▓▓2 active▓│
#  │✓ GPIO17, GPIO27                        │
#  │┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│
#  │◷ Last GPIO17 14:32                     │
#  │──────────────────────────────────────── │
#  │⚡ 4 activations today                  │
#  └────────────────────────────────────────┘
GPIO_STATUS_TEMPLATE = {
    "clear": True,
    "elements": [
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "bolt", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "GPIO STATUS", "x": 13, "y": 1, "font": "small", "invert": True},
        {
            "type": "text", "text": "{gpio.active_count} active",
            "x": 125, "y": 1, "font": "small", "invert": True,
            "align": "right", "max_width": 60, "overflow": "trim",
        },

        {"type": "icon", "name": "check", "x": 2, "y": 15, "size": 9},
        {
            "type": "text", "text": "{gpio.active_pins_summary}",
            "x": 14, "y": 15, "font": "small",
            "max_width": 112, "overflow": "ellipsis", "allow_empty": True,
        },

        {"type": "dotted_hline", "x": 0, "y": 30, "width": 128},

        {"type": "icon", "name": "clock", "x": 2, "y": 34, "size": 9},
        {
            "type": "text", "text": "Last {gpio.last_activation_summary}",
            "x": 14, "y": 34, "font": "small",
            "max_width": 112, "overflow": "ellipsis", "allow_empty": True,
        },

        {"type": "hline", "x": 0, "y": 49, "width": 128},

        {"type": "icon", "name": "bolt", "x": 2, "y": 52, "size": 9},
        {
            "type": "text", "text": "{gpio.activations_today} activations today",
            "x": 14, "y": 52, "font": "small",
            "max_width": 112, "overflow": "trim", "allow_empty": True,
        },
    ],
}


def upgrade() -> None:
    """Apply the restyled template to the existing GPIO Status screen."""
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    serialized_template = json.loads(json.dumps(GPIO_STATUS_TEMPLATE))
    conn.execute(
        display_screens.update()
        .where(display_screens.c.name == "oled_gpio_status")
        .where(display_screens.c.display_type == "oled")
        .values(template_data=serialized_template, updated_at=now)
    )


def downgrade() -> None:
    """No-op: the previous layout can be restored via the screen editor."""
    pass
