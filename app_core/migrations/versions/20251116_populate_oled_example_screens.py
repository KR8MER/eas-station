"""Populate OLED example screens and rotation.

Revision ID: 20251116_populate_oled_example_screens
Revises: 20251115_merge_audio_and_radio_heads
Create Date: 2025-11-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone


revision = "20251116_populate_oled_example_screens"
down_revision = "20251115_merge_audio_and_radio_heads"
branch_labels = None
depends_on = None


# Define table structures for data manipulation
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


# OLED screen template definitions
OLED_SCREENS = [
    {
        "name": "oled_system_overview",
        "description": "Command deck clock with health summary and resource meters.",
        "display_type": "oled",
        "enabled": True,
        "priority": 1,
        "refresh_interval": 20,
        "duration": 12,
        "template_data": {
            "clear": True,
            "lines": [
                {
                    "text": "◢ SYSTEM STATUS ◣",
                    "font": "medium",
                    "wrap": False,
                    "invert": True,
                    "spacing": 1,
                    "y": 0,
                },
                {
                    "text": "{now.date}  {now.time_24}",
                    "font": "small",
                    "wrap": False,
                    "y": 15,
                    "max_width": 124,
                },
                {"text": "{status.status_summary}", "y": 27, "max_width": 124},
                {
                    "text": "CPU {status.system_resources.cpu_usage_percent}%  MEM {status.system_resources.memory_usage_percent}%",
                    "y": 45,
                    "wrap": False,
                    "max_width": 124,
                },
                {
                    "text": "Disk {status.system_resources.disk_usage_percent}%  Alerts {status.active_alerts_count}",
                    "y": 56,
                    "wrap": False,
                    "max_width": 124,
                },
            ],
        },
        "data_sources": [
            {"endpoint": "/api/system_status", "var_name": "status"},
        ],
    },
    {
        "name": "oled_alert_summary",
        "description": "Active alert highlight with event, severity, and affected area.",
        "display_type": "oled",
        "enabled": True,
        "priority": 2,
        "refresh_interval": 15,
        "duration": 12,
        "template_data": {
            "clear": True,
            "lines": [
                {
                    "text": "◢ ALERT STACK ◣",
                    "font": "medium",
                    "wrap": False,
                    "invert": True,
                    "spacing": 1,
                },
                {
                    "text": "Active {alerts.metadata.total_features}",
                    "font": "small",
                    "wrap": False,
                    "y": 15,
                },
                {
                    "text": "{alerts.features[0].properties.event}",
                    "font": "medium",
                    "y": 26,
                    "max_width": 124,
                    "allow_empty": True,
                },
                {
                    "text": "Severity {alerts.features[0].properties.severity}  ·  Exp {alerts.features[0].properties.expires_iso}",
                    "y": 40,
                    "allow_empty": True,
                    "max_width": 124,
                },
                {
                    "text": "Area {alerts.features[0].properties.area_desc}",
                    "y": 52,
                    "max_width": 124,
                    "allow_empty": True,
                },
            ],
        },
        "data_sources": [
            {"endpoint": "/api/alerts", "var_name": "alerts"},
        ],
    },
    {
        "name": "oled_network_beacon",
        "description": "Network beacon showing hostname, uptime, and LAN details.",
        "display_type": "oled",
        "enabled": True,
        "priority": 1,
        "refresh_interval": 45,
        "duration": 12,
        "template_data": {
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
        },
        "data_sources": [
            {"endpoint": "/api/system_health", "var_name": "health"},
        ],
    },
    {
        "name": "oled_ipaws_poll_watch",
        "description": "IPAWS poll recency, status, and last data source.",
        "display_type": "oled",
        "enabled": True,
        "priority": 2,
        "refresh_interval": 30,
        "duration": 12,
        "template_data": {
            "clear": True,
            "lines": [
                {
                    "text": "◢ IPAWS POLLER ◣",
                    "font": "medium",
                    "wrap": False,
                    "invert": True,
                    "spacing": 1,
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
                    "text": "+{status.last_poll.alerts_new} new / {status.last_poll.alerts_fetched} fetched",
                    "y": 41,
                    "allow_empty": True,
                    "max_width": 124,
                },
                {
                    "text": "Source {status.last_poll.data_source}",
                    "y": 53,
                    "allow_empty": True,
                    "max_width": 124,
                },
            ],
        },
        "data_sources": [
            {"endpoint": "/api/system_status", "var_name": "status"},
        ],
    },
    {
        "name": "oled_audio_health_matrix",
        "description": "Audio ingest health and first-source diagnosis.",
        "display_type": "oled",
        "enabled": True,
        "priority": 2,
        "refresh_interval": 20,
        "duration": 12,
        "template_data": {
            "clear": True,
            "lines": [
                {
                    "text": "◢ AUDIO HEALTH ◣",
                    "font": "medium",
                    "wrap": False,
                    "invert": True,
                    "spacing": 1,
                },
                {
                    "text": "Score {audio_health.overall_health_score}% ({audio_health.overall_status})",
                    "y": 15,
                    "allow_empty": True,
                    "max_width": 124,
                },
                {
                    "text": "Active {audio_health.active_sources}/{audio_health.total_sources}",
                    "y": 27,
                    "allow_empty": True,
                },
                {
                    "text": "{audio_health.health_records[0].source_name}",
                    "y": 39,
                    "allow_empty": True,
                    "max_width": 124,
                },
                {
                    "text": "Healthy {audio_health.health_records[0].is_healthy}  Silence {audio_health.health_records[0].silence_detected}",
                    "y": 51,
                    "allow_empty": True,
                    "max_width": 124,
                },
            ],
        },
        "data_sources": [
            {"endpoint": "/api/audio/health", "var_name": "audio_health"},
        ],
    },
    {
        "name": "oled_audio_telemetry",
        "description": "Live audio peaks and buffer utilization for leading sources.",
        "display_type": "oled",
        "enabled": True,
        "priority": 2,
        "refresh_interval": 12,
        "duration": 12,
        "template_data": {
            "clear": True,
            "lines": [
                {
                    "text": "◢ AUDIO TELEMETRY ◣",
                    "font": "medium",
                    "wrap": False,
                    "invert": True,
                    "spacing": 1,
                },
                {"text": "Sources {audio.total_sources}", "font": "small", "wrap": False, "y": 15},
                {
                    "text": "{audio.live_metrics[0].source_name}: {audio.live_metrics[0].peak_level_db} dB",
                    "y": 27,
                    "allow_empty": True,
                    "max_width": 124,
                },
                {
                    "text": "RMS {audio.live_metrics[0].rms_level_db} dB  ·  Silence {audio.live_metrics[0].silence_detected}",
                    "y": 39,
                    "allow_empty": True,
                    "max_width": 124,
                },
                {
                    "text": "{audio.live_metrics[1].source_name}: {audio.live_metrics[1].peak_level_db} dB | Buf {audio.live_metrics[1].buffer_utilization}%",
                    "y": 51,
                    "allow_empty": True,
                    "max_width": 124,
                },
            ],
        },
        "data_sources": [
            {"endpoint": "/api/audio/metrics", "var_name": "audio"},
        ],
    },
]


def upgrade() -> None:
    """Populate example OLED screens and default rotation."""
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    # Track created screen IDs
    screen_ids = []

    # Insert OLED screens
    for screen_data in OLED_SCREENS:
        # Check if screen already exists
        result = conn.execute(
            sa.text("SELECT id FROM display_screens WHERE name = :name"),
            {"name": screen_data["name"]}
        ).fetchone()

        if result:
            # Screen already exists, use its ID
            screen_ids.append({"screen_id": result[0], "duration": screen_data["duration"]})
            continue

        # Insert new screen
        result = conn.execute(
            display_screens.insert().values(
                name=screen_data["name"],
                description=screen_data["description"],
                display_type=screen_data["display_type"],
                enabled=screen_data["enabled"],
                priority=screen_data["priority"],
                refresh_interval=screen_data["refresh_interval"],
                duration=screen_data["duration"],
                template_data=screen_data["template_data"],
                data_sources=screen_data.get("data_sources"),
                conditions=screen_data.get("conditions"),
                created_at=now,
                updated_at=None,
                last_displayed_at=None,
                display_count=0,
                error_count=0,
                last_error=None,
            ).returning(display_screens.c.id)
        )

        # Get the new screen ID
        new_id = result.fetchone()[0]
        screen_ids.append({"screen_id": new_id, "duration": screen_data["duration"]})

    # Create or update OLED default rotation
    rotation_result = conn.execute(
        sa.text("SELECT id, screens FROM screen_rotations WHERE name = :name"),
        {"name": "oled_default_rotation"}
    ).fetchone()

    if rotation_result:
        # Rotation exists, append any new screens
        existing_id, existing_screens = rotation_result
        existing_screen_ids = {s.get("screen_id") for s in (existing_screens or [])}

        # Add any new screens that aren't already in the rotation
        updated_screens = list(existing_screens or [])
        for screen_entry in screen_ids:
            if screen_entry["screen_id"] not in existing_screen_ids:
                updated_screens.append(screen_entry)

        if len(updated_screens) > len(existing_screens or []):
            conn.execute(
                sa.text("UPDATE screen_rotations SET screens = :screens, updated_at = :updated_at WHERE id = :id"),
                {"screens": updated_screens, "updated_at": now, "id": existing_id}
            )
    else:
        # Create new rotation
        conn.execute(
            screen_rotations.insert().values(
                name="oled_default_rotation",
                description="Default OLED screen rotation cycle",
                display_type="oled",
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
    """Remove example OLED screens (optional - keeps user data safe)."""
    # We intentionally don't remove the screens in downgrade
    # to avoid data loss if users have customized them.
    # If you really want to remove them, uncomment below:

    # conn = op.get_bind()
    # for screen_data in OLED_SCREENS:
    #     conn.execute(
    #         sa.text("DELETE FROM display_screens WHERE name = :name"),
    #         {"name": screen_data["name"]}
    #     )
    # conn.execute(
    #     sa.text("DELETE FROM screen_rotations WHERE name = 'oled_default_rotation'")
    # )
    pass
