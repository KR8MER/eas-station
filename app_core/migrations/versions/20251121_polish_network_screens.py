"""Polish network screens and uptime binding"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table


revision = "20251121_polish_network_screens"
down_revision = "20251120_refine_oled_system_layout"
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


NETWORK_BEACON_TEMPLATE = {
    "clear": True,
    "lines": [
        {
            "text": "◢ NETWORK BEACON ◣",
            "font": "medium",
            "wrap": False,
            "invert": True,
            "spacing": 1,
        },
        {
            "text": "{health.system.hostname}",
            "font": "small",
            "wrap": False,
            "y": 15,
            "max_width": 124,
        },
        {
            "text": "Uptime {health.system.uptime_human}",
            "y": 27,
            "allow_empty": True,
        },
        {
            "text": "LAN {health.network.primary_interface_name}",
            "y": 39,
            "allow_empty": True,
        },
        {
            "text": "{health.network.primary_ipv4}",
            "y": 49,
            "allow_empty": True,
        },
        {
            "text": "Speed {health.network.primary_interface.speed_mbps} Mbps  MTU {health.network.primary_interface.mtu}",
            "y": 59,
            "allow_empty": True,
            "max_width": 124,
        },
    ],
}


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    conn.execute(
        sa.text(
            """
            UPDATE display_screens
            SET template_data = replace(template_data::text, 'network.uptime', 'network.uptime_human')::jsonb,
                updated_at = :now
            WHERE template_data::text LIKE '%network.uptime%'
            """
        ),
        {"now": now},
    )

    update_stmt = (
        display_screens.update()
        .where(display_screens.c.name == sa.bindparam("target_screen_name"))
        .where(display_screens.c.display_type == "oled")
    )

    conn.execute(
        update_stmt,
        {
            "template_data": json.loads(json.dumps(NETWORK_BEACON_TEMPLATE)),
            "updated_at": now,
            "target_screen_name": "oled_network_beacon",
        },
    )


def downgrade() -> None:  # pragma: no cover - destructive downgrade avoided
    pass
