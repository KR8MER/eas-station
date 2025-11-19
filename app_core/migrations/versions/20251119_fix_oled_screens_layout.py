"""Fix OLED screen layouts with proper spacing and bar graphs.

Revision ID: 20251119_fix_oled_screens_layout
Revises: 20251116_populate_oled_example_screens
Create Date: 2025-11-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone


revision = "20251119_fix_oled_screens_layout"
down_revision = "20251116_populate_oled_example_screens"
branch_labels = None
depends_on = None


# Define table structure
display_screens = table(
    "display_screens",
    column("id", sa.Integer),
    column("name", sa.String),
    column("template_data", JSONB),
    column("updated_at", sa.DateTime),
)


# Updated screen templates with professional bar graphs and proper spacing
# Display: 128x64 pixels
# Font heights: small=11px, medium=14px
# Max content: medium header (14px) + 3 lines (11px each) = 59px
UPDATED_SCREENS = {
    "oled_system_overview": {
        "clear": True,
        "elements": [
            # Header (y=0-13, 14px medium font inverted)
            {"type": "text", "text": "SYSTEM STATUS", "x": 0, "y": 0, "font": "medium", "invert": True},
            # CPU bar (y=17-27, bar is 8px centered in 11px line height)
            {"type": "text", "text": "CPU", "x": 0, "y": 17, "font": "small"},
            {"type": "bar", "value": "{status.system_resources.cpu_usage_percent}", "x": 26, "y": 18, "width": 76, "height": 7},
            {"type": "text", "text": "{status.system_resources.cpu_usage_percent}%", "x": 105, "y": 17, "font": "small"},
            # Memory bar (y=30-40)
            {"type": "text", "text": "MEM", "x": 0, "y": 30, "font": "small"},
            {"type": "bar", "value": "{status.system_resources.memory_usage_percent}", "x": 26, "y": 31, "width": 76, "height": 7},
            {"type": "text", "text": "{status.system_resources.memory_usage_percent}%", "x": 105, "y": 30, "font": "small"},
            # Disk bar (y=43-53)
            {"type": "text", "text": "DSK", "x": 0, "y": 43, "font": "small"},
            {"type": "bar", "value": "{status.system_resources.disk_usage_percent}", "x": 26, "y": 44, "width": 76, "height": 7},
            {"type": "text", "text": "{status.system_resources.disk_usage_percent}%", "x": 105, "y": 43, "font": "small"},
            # Date/time footer (y=56-63, only 8px showing but that's ok for small font)
            {"type": "text", "text": "{now.date} {now.time_24}", "x": 0, "y": 56, "font": "small"},
        ],
    },
    "oled_alert_summary": {
        "clear": True,
        "lines": [
            # Header (y=0-13)
            {
                "text": "ALERT STACK",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "y": 0,
            },
            # Content line 1 (y=17-27)
            {
                "text": "Active: {alerts.metadata.total_features}",
                "font": "small",
                "wrap": False,
                "y": 17,
                "max_width": 124,
            },
            # Content line 2 (y=30-40) - event name
            {
                "text": "{alerts.features[0].properties.event}",
                "font": "small",
                "y": 30,
                "max_width": 124,
                "allow_empty": True,
            },
            # Content line 3 (y=43-53) - severity and area
            {
                "text": "{alerts.features[0].properties.severity} - {alerts.features[0].properties.area_desc}",
                "font": "small",
                "y": 43,
                "max_width": 124,
                "allow_empty": True,
            },
        ],
    },
    "oled_network_beacon": {
        "clear": True,
        "lines": [
            # Header (y=0-13)
            {
                "text": "NETWORK",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "y": 0,
            },
            # Content line 1 (y=17-27)
            {
                "text": "{health.system.hostname}",
                "font": "small",
                "wrap": False,
                "y": 17,
                "max_width": 124,
            },
            # Content line 2 (y=30-40)
            {
                "text": "{health.network.primary_ipv4}",
                "font": "small",
                "y": 30,
                "allow_empty": True,
                "max_width": 124,
            },
            # Content line 3 (y=43-53)
            {
                "text": "Up {health.system.uptime_human}",
                "font": "small",
                "y": 43,
                "allow_empty": True,
                "max_width": 124,
            },
        ],
    },
    "oled_ipaws_poll_watch": {
        "clear": True,
        "lines": [
            # Header (y=0-13)
            {
                "text": "IPAWS POLLER",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "y": 0,
            },
            # Content line 1 (y=17-27)
            {
                "text": "Last: {status.last_poll.local_timestamp}",
                "font": "small",
                "y": 17,
                "allow_empty": True,
                "max_width": 124,
            },
            # Content line 2 (y=30-40)
            {
                "text": "Status: {status.last_poll.status}",
                "font": "small",
                "y": 30,
                "allow_empty": True,
                "max_width": 124,
            },
            # Content line 3 (y=43-53)
            {
                "text": "+{status.last_poll.alerts_new} new / {status.last_poll.alerts_fetched} fetched",
                "font": "small",
                "y": 43,
                "allow_empty": True,
                "max_width": 124,
            },
        ],
    },
    "oled_audio_health_matrix": {
        "clear": True,
        "lines": [
            # Header (y=0-13)
            {
                "text": "AUDIO HEALTH",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "y": 0,
            },
            # Content line 1 (y=17-27)
            {
                "text": "Score: {audio_health.overall_health_score}% ({audio_health.overall_status})",
                "font": "small",
                "y": 17,
                "allow_empty": True,
                "max_width": 124,
            },
            # Content line 2 (y=30-40)
            {
                "text": "Active: {audio_health.active_sources}/{audio_health.total_sources} sources",
                "font": "small",
                "y": 30,
                "allow_empty": True,
                "max_width": 124,
            },
            # Content line 3 (y=43-53)
            {
                "text": "{audio_health.health_records[0].source_name}",
                "font": "small",
                "y": 43,
                "allow_empty": True,
                "max_width": 124,
            },
        ],
    },
    "oled_audio_telemetry": {
        "clear": True,
        "lines": [
            # Header (y=0-13)
            {
                "text": "AUDIO METERS",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "y": 0,
            },
            # Content line 1 (y=17-27)
            {
                "text": "{audio.live_metrics[0].source_name}",
                "font": "small",
                "y": 17,
                "allow_empty": True,
                "max_width": 124,
            },
            # Content line 2 (y=30-40)
            {
                "text": "Peak: {audio.live_metrics[0].peak_level_db} dB",
                "font": "small",
                "y": 30,
                "allow_empty": True,
                "max_width": 124,
            },
            # Content line 3 (y=43-53)
            {
                "text": "RMS: {audio.live_metrics[0].rms_level_db} dB",
                "font": "small",
                "y": 43,
                "allow_empty": True,
                "max_width": 124,
            },
        ],
    },
}


def upgrade() -> None:
    """Update OLED screen templates with proper spacing and bar graphs."""
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    for screen_name, template_data in UPDATED_SCREENS.items():
        # Update the template_data for each screen
        conn.execute(
            sa.text(
                "UPDATE display_screens SET template_data = :template_data, updated_at = :updated_at "
                "WHERE name = :name AND display_type = 'oled'"
            ),
            {"template_data": template_data, "updated_at": now, "name": screen_name}
        )


def downgrade() -> None:
    """Revert to previous screen templates."""
    # We don't implement downgrade to avoid data loss
    # Users can manually edit screens via the web interface if needed
    pass
