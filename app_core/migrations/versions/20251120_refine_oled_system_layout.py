"""Refine OLED system overview layout with bounded elements."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table


revision = "20251120_refine_oled_system_layout"
down_revision = "20251119_fix_oled_screens_layout"
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


SYSTEM_OVERVIEW_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner with inverted text
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 14, "filled": True},
        {"type": "text", "text": "SYSTEM STATUS", "x": 2, "y": 2, "font": "small", "invert": True},
        {"type": "text", "text": "{now.time_24}", "x": 125, "y": 2, "font": "small", "invert": True, "align": "right"},
        # CPU row
        {"type": "text", "text": "CPU", "x": 2, "y": 17, "font": "small"},
        {"type": "bar", "value": "{status.system_resources.cpu_usage_percent}", "x": 28, "y": 16, "width": 72, "height": 9},
        {
            "type": "text",
            "text": "{status.system_resources.cpu_usage_percent}%",
            "x": 125,
            "y": 17,
            "font": "small",
            "align": "right",
            "max_width": 28,
            "overflow": "trim",
        },
        # Memory row
        {"type": "text", "text": "MEM", "x": 2, "y": 29, "font": "small"},
        {"type": "bar", "value": "{status.system_resources.memory_usage_percent}", "x": 28, "y": 28, "width": 72, "height": 9},
        {
            "type": "text",
            "text": "{status.system_resources.memory_usage_percent}%",
            "x": 125,
            "y": 29,
            "font": "small",
            "align": "right",
            "max_width": 28,
            "overflow": "trim",
        },
        # Disk row
        {"type": "text", "text": "DSK", "x": 2, "y": 41, "font": "small"},
        {"type": "bar", "value": "{status.system_resources.disk_usage_percent}", "x": 28, "y": 40, "width": 72, "height": 9},
        {
            "type": "text",
            "text": "{status.system_resources.disk_usage_percent}%",
            "x": 125,
            "y": 41,
            "font": "small",
            "align": "right",
            "max_width": 28,
            "overflow": "trim",
        },
        # Footer divider and summary row
        {"type": "rectangle", "x": 0, "y": 50, "width": 128, "height": 1, "filled": True},
        {
            "type": "text",
            "text": "{status.status_summary}",
            "x": 2,
            "y": 52,
            "font": "small",
            "max_width": 66,
            "overflow": "ellipsis",
        },
        {
            "type": "text",
            "text": "{now.date}",
            "x": 125,
            "y": 52,
            "font": "small",
            "align": "right",
            "max_width": 48,
            "overflow": "ellipsis",
        },
    ],
}


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    update_stmt = (
        display_screens.update()
        .where(display_screens.c.name == sa.bindparam("target_screen_name"))
        .where(display_screens.c.display_type == "oled")
    )

    conn.execute(
        update_stmt,
        {
            "template_data": json.loads(json.dumps(SYSTEM_OVERVIEW_TEMPLATE)),
            "updated_at": now,
            "target_screen_name": "oled_system_overview",
        },
    )


def downgrade() -> None:
    # No downgrade to avoid clobbering operator customizations
    pass
