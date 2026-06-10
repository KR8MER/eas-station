"""Refresh default OLED/VFD screen designs with graphical layouts.

Replaces the remaining text-only OLED example screens with element-based
layouts (icon header banners, bars, dividers) and restyles the plain VFD
screens (aligned meter rows, scale ticks, corner brackets). Mirrors the
templates in scripts/create_example_screens.py.

Revision ID: 20260610_refresh_default_screen_designs
Revises: 20260608_add_email_rendering_media
Create Date: 2026-06-10
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table


revision = "20260610_refresh_default_screen_designs"
down_revision = "20260608_add_email_rendering_media"
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


# Keep in sync with scripts/create_example_screens.py
UPDATED_SCREENS = {
    "oled_alert_summary": {
        "display_type": "oled",
        "template_data": {
            "clear": True,
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
                {"type": "icon", "name": "warning", "x": 2, "y": 2, "size": 9},
                {"type": "text", "text": "ALERTS", "x": 14, "y": 1, "font": "small", "invert": True},
                {
                    "type": "text", "text": "{alerts.metadata.total_features} active",
                    "x": 125, "y": 1, "font": "small", "invert": True,
                    "align": "right", "max_width": 60, "overflow": "trim",
                },
                {
                    "type": "text", "text": "{alerts.features[0].properties.event}",
                    "x": 2, "y": 15, "font": "medium",
                    "max_width": 124, "overflow": "ellipsis", "allow_empty": True,
                },
                {
                    "type": "text", "text": "Sev {alerts.features[0].properties.severity}",
                    "x": 2, "y": 31, "font": "small",
                    "max_width": 64, "overflow": "trim", "allow_empty": True,
                },
                {
                    "type": "text", "text": "Exp {alerts.features[0].properties.expires_iso}",
                    "x": 125, "y": 31, "font": "small", "align": "right",
                    "max_width": 60, "overflow": "trim", "allow_empty": True,
                },
                {"type": "dotted_hline", "x": 0, "y": 44, "width": 128},
                {"type": "icon", "name": "shield", "x": 2, "y": 49, "size": 11},
                {
                    "type": "text", "text": "{alerts.features[0].properties.area_desc}",
                    "x": 17, "y": 50, "font": "small",
                    "max_width": 109, "overflow": "ellipsis", "allow_empty": True,
                },
            ],
        },
    },
    "oled_network_beacon": {
        "display_type": "oled",
        "template_data": {
            "clear": True,
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
                {"type": "icon", "name": "network", "x": 2, "y": 2, "size": 9},
                {"type": "text", "text": "NETWORK", "x": 14, "y": 1, "font": "small", "invert": True},
                {
                    "type": "text", "text": "{health.network.primary_interface_name}",
                    "x": 125, "y": 1, "font": "small", "invert": True,
                    "align": "right", "max_width": 50, "overflow": "trim",
                },
                {
                    "type": "text", "text": "{health.system.hostname}",
                    "x": 2, "y": 15, "font": "medium",
                    "max_width": 124, "overflow": "ellipsis",
                },
                {
                    "type": "text", "text": "{health.network.primary_ipv4}",
                    "x": 2, "y": 31, "font": "medium",
                    "max_width": 124, "overflow": "trim", "allow_empty": True,
                },
                {"type": "hline", "x": 0, "y": 47, "width": 128},
                {"type": "icon", "name": "clock", "x": 2, "y": 51, "size": 8},
                {
                    "type": "text", "text": "Up {health.system.uptime_human}",
                    "x": 13, "y": 52, "font": "small",
                    "max_width": 70, "overflow": "trim", "allow_empty": True,
                },
                {
                    "type": "text", "text": "{health.network.primary_interface.speed_mbps}Mb",
                    "x": 125, "y": 52, "font": "small", "align": "right",
                    "max_width": 40, "overflow": "trim", "allow_empty": True,
                },
            ],
        },
    },
    "oled_ipaws_poll_watch": {
        "display_type": "oled",
        "template_data": {
            "clear": True,
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
                {"type": "icon", "name": "shield", "x": 2, "y": 2, "size": 9},
                {"type": "text", "text": "IPAWS POLLER", "x": 14, "y": 1, "font": "small", "invert": True},
                {
                    "type": "text", "text": "{now.time_24}",
                    "x": 125, "y": 1, "font": "small", "invert": True, "align": "right",
                },
                {"type": "icon", "name": "check", "x": 2, "y": 16, "size": 10},
                {
                    "type": "text", "text": "{status.last_poll.status}",
                    "x": 16, "y": 15, "font": "medium",
                    "max_width": 108, "overflow": "trim", "allow_empty": True,
                },
                {"type": "dotted_hline", "x": 0, "y": 31, "width": 128},
                {
                    "type": "text", "text": "+{status.last_poll.alerts_new} new",
                    "x": 2, "y": 35, "font": "small",
                    "max_width": 60, "overflow": "trim", "allow_empty": True,
                },
                {
                    "type": "text", "text": "{status.last_poll.alerts_fetched} fetched",
                    "x": 125, "y": 35, "font": "small", "align": "right",
                    "max_width": 64, "overflow": "trim", "allow_empty": True,
                },
                {"type": "hline", "x": 0, "y": 47, "width": 128},
                {"type": "icon", "name": "clock", "x": 2, "y": 51, "size": 8},
                {
                    "type": "text", "text": "Last {status.last_poll.local_timestamp}",
                    "x": 13, "y": 52, "font": "small",
                    "max_width": 113, "overflow": "trim", "allow_empty": True,
                },
            ],
        },
    },
    "oled_audio_health_matrix": {
        "display_type": "oled",
        "template_data": {
            "clear": True,
            "elements": [
                {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
                {"type": "icon", "name": "heartbeat", "x": 2, "y": 2, "size": 9},
                {"type": "text", "text": "AUDIO HEALTH", "x": 14, "y": 1, "font": "small", "invert": True},
                {
                    "type": "text", "text": "{audio_health.overall_status}",
                    "x": 125, "y": 1, "font": "small", "invert": True,
                    "align": "right", "max_width": 48, "overflow": "trim",
                },
                {"type": "text", "text": "Score", "x": 2, "y": 16, "font": "small"},
                {
                    "type": "bar", "value": "{audio_health.overall_health_score}",
                    "x": 36, "y": 15, "width": 62, "height": 10,
                },
                {
                    "type": "text", "text": "{audio_health.overall_health_score}%",
                    "x": 125, "y": 16, "font": "small", "align": "right",
                    "max_width": 26, "overflow": "trim", "allow_empty": True,
                },
                {"type": "dotted_hline", "x": 0, "y": 30, "width": 128},
                {
                    "type": "text", "text": "Sources {audio_health.active_sources}/{audio_health.total_sources} active",
                    "x": 2, "y": 34, "font": "small",
                    "max_width": 124, "overflow": "trim", "allow_empty": True,
                },
                {"type": "hline", "x": 0, "y": 46, "width": 128},
                {"type": "icon", "name": "wave", "x": 2, "y": 50, "size": 9},
                {
                    "type": "text", "text": "{audio_health.health_records[0].source_name}",
                    "x": 14, "y": 51, "font": "small",
                    "max_width": 74, "overflow": "ellipsis", "allow_empty": True,
                },
                {
                    "type": "text", "text": "OK {audio_health.health_records[0].is_healthy}",
                    "x": 125, "y": 51, "font": "small", "align": "right",
                    "max_width": 36, "overflow": "trim", "allow_empty": True,
                },
            ],
        },
    },
    "vfd_system_meters": {
        "display_type": "vfd",
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "text", "x": 0, "y": 0, "text": "SYSTEM"},
                {"type": "line", "x1": 44, "y1": 3, "x2": 139, "y2": 3},
                {"type": "text", "x": 0, "y": 8, "text": "CPU"},
                {
                    "type": "bar", "x": 22, "y": 8, "width": 88, "height": 7,
                    "value": "{status.system_resources.cpu_usage_percent}", "border": True,
                },
                {"type": "text", "x": 114, "y": 8, "text": "{status.system_resources.cpu_usage_percent}%"},
                {"type": "text", "x": 0, "y": 16, "text": "MEM"},
                {
                    "type": "bar", "x": 22, "y": 16, "width": 88, "height": 7,
                    "value": "{status.system_resources.memory_usage_percent}", "border": True,
                },
                {"type": "text", "x": 114, "y": 16, "text": "{status.system_resources.memory_usage_percent}%"},
                {"type": "text", "x": 0, "y": 24, "text": "DSK"},
                {
                    "type": "bar", "x": 22, "y": 24, "width": 88, "height": 7,
                    "value": "{status.system_resources.disk_usage_percent}", "border": True,
                },
                {"type": "text", "x": 114, "y": 24, "text": "{status.system_resources.disk_usage_percent}%"},
            ],
        },
    },
    "vfd_audio_vu_meter": {
        "display_type": "vfd",
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "text", "x": 0, "y": 0, "text": "AUDIO"},
                {"type": "line", "x1": 38, "y1": 3, "x2": 139, "y2": 3},
                {"type": "text", "x": 0, "y": 9, "text": "PK"},
                {
                    "type": "bar", "x": 16, "y": 9, "width": 100, "height": 8,
                    "value": "{audio.peak_level_percent}", "border": True,
                },
                {"type": "text", "x": 120, "y": 9, "text": "{audio.peak_level_percent}"},
                {"type": "vline", "x": 41, "y": 18, "height": 2},
                {"type": "vline", "x": 66, "y": 18, "height": 2},
                {"type": "vline", "x": 91, "y": 18, "height": 2},
                {"type": "text", "x": 0, "y": 22, "text": "RMS"},
                {
                    "type": "bar", "x": 16, "y": 22, "width": 100, "height": 8,
                    "value": "{audio.rms_level_percent}", "border": True,
                },
                {"type": "text", "x": 120, "y": 22, "text": "{audio.rms_level_percent}"},
            ],
        },
    },
    "vfd_network_status": {
        "display_type": "vfd",
        "template_data": {
            "type": "graphics",
            "elements": [
                {"type": "line", "x1": 0, "y1": 0, "x2": 12, "y2": 0},
                {"type": "line", "x1": 0, "y1": 0, "x2": 0, "y2": 8},
                {"type": "line", "x1": 127, "y1": 0, "x2": 139, "y2": 0},
                {"type": "line", "x1": 139, "y1": 0, "x2": 139, "y2": 8},
                {"type": "line", "x1": 0, "y1": 31, "x2": 12, "y2": 31},
                {"type": "line", "x1": 0, "y1": 23, "x2": 0, "y2": 31},
                {"type": "line", "x1": 127, "y1": 31, "x2": 139, "y2": 31},
                {"type": "line", "x1": 139, "y1": 23, "x2": 139, "y2": 31},
                {"type": "text", "x": 49, "y": 2, "text": "NETWORK"},
                {"type": "line", "x1": 20, "y1": 11, "x2": 119, "y2": 11},
                {"type": "text", "x": 8, "y": 14, "text": "IP {network.ip_address}"},
                {"type": "text", "x": 8, "y": 23, "text": "Up {network.uptime_human}"},
            ],
        },
    },
}


def upgrade() -> None:
    """Apply the refreshed graphical templates to existing default screens."""
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    update_stmt = (
        display_screens.update()
        .where(display_screens.c.name == sa.bindparam("target_screen_name"))
        .where(display_screens.c.display_type == sa.bindparam("target_display_type"))
    )

    for screen_name, payload in UPDATED_SCREENS.items():
        serialized_template = json.loads(json.dumps(payload["template_data"]))
        conn.execute(
            update_stmt,
            {
                "template_data": serialized_template,
                "updated_at": now,
                "target_screen_name": screen_name,
                "target_display_type": payload["display_type"],
            },
        )


def downgrade() -> None:
    """No-op: previous layouts can be restored via the screen editor."""
    pass
