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
UPDATED_SCREENS = {
    "oled_system_overview": {
        "clear": True,
        "elements": [
            # Header
            {"type": "text", "text": "◢ SYSTEM STATUS ◣", "x": 0, "y": 0, "font": "medium", "invert": True},
            # Date and time
            {"type": "text", "text": "{now.date}  {now.time_24}", "x": 0, "y": 17, "font": "small"},
            # CPU bar
            {"type": "text", "text": "CPU", "x": 0, "y": 30, "font": "small"},
            {"type": "bar", "value": "{status.system_resources.cpu_usage_percent}", "x": 28, "y": 30, "width": 70, "height": 8},
            {"type": "text", "text": "{status.system_resources.cpu_usage_percent}%", "x": 102, "y": 30, "font": "small"},
            # Memory bar
            {"type": "text", "text": "MEM", "x": 0, "y": 41, "font": "small"},
            {"type": "bar", "value": "{status.system_resources.memory_usage_percent}", "x": 28, "y": 41, "width": 70, "height": 8},
            {"type": "text", "text": "{status.system_resources.memory_usage_percent}%", "x": 102, "y": 41, "font": "small"},
            # Disk bar
            {"type": "text", "text": "DISK", "x": 0, "y": 52, "font": "small"},
            {"type": "bar", "value": "{status.system_resources.disk_usage_percent}", "x": 28, "y": 52, "width": 70, "height": 8},
            {"type": "text", "text": "{status.system_resources.disk_usage_percent}%", "x": 102, "y": 52, "font": "small"},
        ],
    },
    "oled_alert_summary": {
        "clear": True,
        "lines": [
            {
                "text": "◢ ALERT STACK ◣",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "spacing": 2,
                "y": 0,
            },
            {
                "text": "Active {alerts.metadata.total_features}",
                "font": "small",
                "wrap": False,
                "y": 17,
            },
            {
                "text": "{alerts.features[0].properties.event}",
                "font": "medium",
                "y": 29,
                "max_width": 124,
                "allow_empty": True,
            },
            {
                "text": "{alerts.features[0].properties.severity}",
                "y": 45,
                "allow_empty": True,
                "max_width": 124,
            },
            {
                "text": "{alerts.features[0].properties.area_desc}",
                "y": 56,
                "max_width": 124,
                "allow_empty": True,
            },
        ],
    },
    "oled_network_beacon": {
        "clear": True,
        "lines": [
            {
                "text": "◢ NETWORK BEACON ◣",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "spacing": 2,
                "y": 0,
            },
            {
                "text": "{health.system.hostname}",
                "font": "small",
                "wrap": False,
                "y": 17,
                "max_width": 124,
            },
            {
                "text": "Up {health.system.uptime_human}",
                "y": 29,
                "allow_empty": True,
            },
            {
                "text": "IF {health.network.primary_interface_name}",
                "y": 41,
                "allow_empty": True,
            },
            {
                "text": "{health.network.primary_ipv4}",
                "y": 52,
                "allow_empty": True,
            },
        ],
    },
    "oled_ipaws_poll_watch": {
        "clear": True,
        "lines": [
            {
                "text": "◢ IPAWS POLLER ◣",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "spacing": 2,
                "y": 0,
            },
            {
                "text": "Last {status.last_poll.local_timestamp}",
                "y": 17,
                "allow_empty": True,
                "max_width": 124,
            },
            {
                "text": "Status {status.last_poll.status}",
                "y": 29,
                "allow_empty": True,
            },
            {
                "text": "+{status.last_poll.alerts_new} new",
                "y": 41,
                "allow_empty": True,
                "max_width": 124,
            },
            {
                "text": "Source {status.last_poll.data_source}",
                "y": 52,
                "allow_empty": True,
                "max_width": 124,
            },
        ],
    },
    "oled_audio_health_matrix": {
        "clear": True,
        "lines": [
            {
                "text": "◢ AUDIO HEALTH ◣",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "spacing": 2,
                "y": 0,
            },
            {
                "text": "Score {audio_health.overall_health_score}%",
                "y": 17,
                "allow_empty": True,
                "max_width": 124,
            },
            {
                "text": "{audio_health.overall_status}",
                "y": 29,
                "allow_empty": True,
            },
            {
                "text": "Active {audio_health.active_sources}/{audio_health.total_sources}",
                "y": 41,
                "allow_empty": True,
            },
            {
                "text": "{audio_health.health_records[0].source_name}",
                "y": 52,
                "allow_empty": True,
                "max_width": 124,
            },
        ],
    },
    "oled_audio_telemetry": {
        "clear": True,
        "lines": [
            {
                "text": "◢ AUDIO TELEMETRY ◣",
                "font": "medium",
                "wrap": False,
                "invert": True,
                "spacing": 2,
                "y": 0,
            },
            {
                "text": "Sources {audio.total_sources}",
                "font": "small",
                "wrap": False,
                "y": 17,
            },
            {
                "text": "{audio.live_metrics[0].source_name}",
                "y": 29,
                "allow_empty": True,
                "max_width": 124,
            },
            {
                "text": "Peak {audio.live_metrics[0].peak_level_db} dB",
                "y": 41,
                "allow_empty": True,
                "max_width": 124,
            },
            {
                "text": "Silence {audio.live_metrics[0].silence_detected}",
                "y": 52,
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
