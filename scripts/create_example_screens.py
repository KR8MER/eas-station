"""Create example screen templates to showcase display capabilities.

This script creates various example screens for LED, VFD, and OLED displays demonstrating:
- System status and health monitoring
- Resource usage (CPU, memory, disk)
- Network information
- Audio VU meters
- Alert summaries
- Temperature monitoring
"""

import argparse
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app_core.extensions import db
from app_core.models import DisplayScreen, ScreenRotation

logger = logging.getLogger(__name__)


def _append_missing_screens(
    rotation: ScreenRotation,
    new_entries: Iterable[Dict[str, int]],
) -> bool:
    """Append screen references that are not already part of a rotation."""

    existing = rotation.screens or []
    existing_ids = {entry.get("screen_id") for entry in existing if isinstance(entry, dict)}
    appended = False

    for entry in new_entries:
        screen_id = entry.get("screen_id")
        if not screen_id or screen_id in existing_ids:
            continue
        existing.append(entry)
        existing_ids.add(screen_id)
        appended = True

    if appended:
        rotation.screens = existing
    return appended


def _ensure_rotation(rotation_defaults: Dict[str, Any], screen_entries: List[Dict[str, int]]):
    """Create a rotation or append any newly created screens."""

    if not screen_entries:
        return

    rotation = ScreenRotation.query.filter_by(name=rotation_defaults["name"]).first()
    if not rotation:
        payload = dict(rotation_defaults)
        payload["screens"] = list(screen_entries)
        rotation = ScreenRotation(**payload)
        db.session.add(rotation)
        logger.info(f"Created {rotation_defaults['display_type'].upper()} rotation: {rotation_defaults['name']}")
        return

    if _append_missing_screens(rotation, screen_entries):
        db.session.add(rotation)
        logger.info(
            "Updated %s rotation '%s' with %d screen(s)",
            rotation.display_type.upper(),
            rotation.name,
            len(screen_entries),
        )
    else:
        logger.info(
            "Rotation '%s' already includes all requested screens", rotation.name
        )


# ============================================================
# LED Screen Templates
# ============================================================

LED_SYSTEM_STATUS = {
    "name": "led_system_status",
    "description": "Overall system health status on LED display",
    "display_type": "led",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 30,
    "duration": 10,
    "template_data": {
        "lines": [
            "SYSTEM STATUS",
            "Health: {status.status}",
            "Alerts: {status.active_alerts_count}",
            "DB: {status.database_status}"
        ],
        "color": "GREEN",
        "mode": "HOLD",
        "speed": "SPEED_3",
        "font": "FONT_7x9"
    },
    "data_sources": [
        {
            "endpoint": "/api/system_status",
            "var_name": "status"
        }
    ]
}

LED_RESOURCES = {
    "name": "led_resources",
    "description": "CPU, memory, and disk usage on LED display",
    "display_type": "led",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 15,
    "duration": 10,
    "template_data": {
        "lines": [
            "SYSTEM RESOURCES",
            "CPU: {status.system_resources.cpu_usage_percent}%",
            "MEM: {status.system_resources.memory_usage_percent}%",
            "DISK: {status.system_resources.disk_usage_percent}%"
        ],
        "color": "AMBER",
        "mode": "HOLD",
        "speed": "SPEED_3",
        "font": "FONT_7x9"
    },
    "data_sources": [
        {
            "endpoint": "/api/system_status",
            "var_name": "status"
        }
    ]
}

LED_NETWORK_INFO = {
    "name": "led_network_info",
    "description": "Network information and IP address",
    "display_type": "led",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 60,
    "duration": 10,
    "template_data": {
        "lines": [
            "NETWORK INFO",
            "IP: {network.ip_address}",
            "Up: {network.uptime}",
            "{now.time}"
        ],
        "color": "BLUE",
        "mode": "HOLD",
        "speed": "SPEED_3",
        "font": "FONT_5x7"
    },
    "data_sources": [
        {
            "endpoint": "/api/system_status",
            "var_name": "network"
        }
    ]
}

LED_ALERT_SUMMARY = {
    "name": "led_alert_summary",
    "description": "Active alert count and latest alert",
    "display_type": "led",
    "enabled": True,
    "priority": 1,
    "refresh_interval": 10,
    "duration": 15,
    "template_data": {
        "lines": [
            "ACTIVE ALERTS: {alerts.features.length}",
            "{alerts.features[0].properties.event}",
            "Severity: {alerts.features[0].properties.severity}",
            "Expires: {alerts.features[0].properties.expires_iso}"
        ],
        "color": "ORANGE",
        "mode": "SCROLL",
        "speed": "SPEED_4",
        "font": "FONT_7x9"
    },
    "data_sources": [
        {
            "endpoint": "/api/alerts",
            "var_name": "alerts"
        }
    ],
    "conditions": {
        "var": "alerts.features.length",
        "op": ">",
        "value": 0
    }
}

LED_TIME_DATE = {
    "name": "led_time_date",
    "description": "Current time and date display",
    "display_type": "led",
    "enabled": True,
    "priority": 3,
    "refresh_interval": 60,
    "duration": 8,
    "template_data": {
        "lines": [
            "{location.county_name}",
            "{location.state_code}",
            "{now.date}",
            "{now.time}"
        ],
        "color": "GREEN",
        "mode": "HOLD",
        "speed": "SPEED_3",
        "font": "FONT_7x9"
    },
    "data_sources": [
        {
            "endpoint": "/api/system_status",
            "var_name": "location"
        }
    ]
}

LED_RECEIVER_STATUS = {
    "name": "led_receiver_status",
    "description": "Radio receiver signal strength",
    "display_type": "led",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 20,
    "duration": 10,
    "template_data": {
        "lines": [
            "RECEIVER STATUS",
            "{receivers[0].display_name}",
            "Signal: {receivers[0].latest_status.signal_strength} dBm",
            "Lock: {receivers[0].latest_status.locked}"
        ],
        "color": "CYAN",
        "mode": "HOLD",
        "speed": "SPEED_3",
        "font": "FONT_7x9"
    },
    "data_sources": [
        {
            "endpoint": "/api/monitoring/radio",
            "var_name": "receivers"
        }
    ]
}


# ============================================================
# VFD Screen Templates
# ============================================================

VFD_SYSTEM_METERS = {
    "name": "vfd_system_meters",
    "description": "CPU, Memory, Disk usage as VU meters on VFD",
    "display_type": "vfd",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 5,
    "duration": 10,
    "template_data": {
        "type": "graphics",
        "elements": [
            {
                "type": "text",
                "x": 2,
                "y": 1,
                "text": "SYSTEM RESOURCES"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 8,
                "width": 120,
                "height": 6,
                "value": "{status.system_resources.cpu_usage_percent}",
                "label": "CPU"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 17,
                "width": 120,
                "height": 6,
                "value": "{status.system_resources.memory_usage_percent}",
                "label": "MEM"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 26,
                "width": 120,
                "height": 6,
                "value": "{status.system_resources.disk_usage_percent}",
                "label": "DSK"
            }
        ]
    },
    "data_sources": [
        {
            "endpoint": "/api/system_status",
            "var_name": "status"
        }
    ]
}

VFD_AUDIO_VU_METER = {
    "name": "vfd_audio_vu_meter",
    "description": "Audio source VU meter on VFD display",
    "display_type": "vfd",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 1,
    "duration": 15,
    "template_data": {
        "type": "graphics",
        "elements": [
            {
                "type": "text",
                "x": 2,
                "y": 1,
                "text": "AUDIO LEVELS"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 12,
                "width": 120,
                "height": 8,
                "value": "{audio.peak_level_linear}",
                "label": "PEAK"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 23,
                "width": 120,
                "height": 8,
                "value": "{audio.rms_level_linear}",
                "label": "RMS"
            }
        ]
    },
    "data_sources": [
        {
            "endpoint": "/api/audio/metrics/latest",
            "var_name": "audio"
        }
    ]
}

VFD_ALERT_DETAILS = {
    "name": "vfd_alert_details",
    "description": "Detailed alert display with graphics on VFD",
    "display_type": "vfd",
    "enabled": True,
    "priority": 1,
    "refresh_interval": 10,
    "duration": 20,
    "template_data": {
        "type": "graphics",
        "elements": [
            {
                "type": "rectangle",
                "x1": 0,
                "y1": 0,
                "x2": 139,
                "y2": 31,
                "filled": False
            },
            {
                "type": "rectangle",
                "x1": 1,
                "y1": 1,
                "x2": 138,
                "y2": 30,
                "filled": False
            },
            {
                "type": "text",
                "x": 5,
                "y": 3,
                "text": "ALERT! {alerts.features[0].properties.event}"
            },
            {
                "type": "line",
                "x1": 5,
                "y1": 11,
                "x2": 135,
                "y2": 11
            },
            {
                "type": "text",
                "x": 5,
                "y": 14,
                "text": "Severity: {alerts.features[0].properties.severity}"
            },
            {
                "type": "text",
                "x": 5,
                "y": 23,
                "text": "{alerts.features[0].properties.area_desc}"
            }
        ]
    },
    "data_sources": [
        {
            "endpoint": "/api/alerts",
            "var_name": "alerts"
        }
    ],
    "conditions": {
        "var": "alerts.features.length",
        "op": ">",
        "value": 0
    }
}

VFD_NETWORK_STATUS = {
    "name": "vfd_network_status",
    "description": "Network status with graphics on VFD",
    "display_type": "vfd",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 30,
    "duration": 10,
    "template_data": {
        "type": "graphics",
        "elements": [
            {
                "type": "rectangle",
                "x1": 2,
                "y1": 2,
                "x2": 137,
                "y2": 29,
                "filled": False
            },
            {
                "type": "text",
                "x": 6,
                "y": 5,
                "text": "NETWORK STATUS"
            },
            {
                "type": "line",
                "x1": 6,
                "y1": 13,
                "x2": 133,
                "y2": 13
            },
            {
                "type": "text",
                "x": 6,
                "y": 16,
                "text": "IP: {network.ip_address}"
            },
            {
                "type": "text",
                "x": 6,
                "y": 24,
                "text": "Uptime: {network.uptime}"
            }
        ]
    },
    "data_sources": [
        {
            "endpoint": "/api/system_status",
            "var_name": "network"
        }
    ]
}

VFD_TEMP_MONITORING = {
    "name": "vfd_temp_monitoring",
    "description": "Temperature monitoring with visual gauge",
    "display_type": "vfd",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 60,
    "duration": 10,
    "template_data": {
        "type": "graphics",
        "elements": [
            {
                "type": "text",
                "x": 2,
                "y": 1,
                "text": "TEMPERATURE"
            },
            {
                "type": "rectangle",
                "x1": 10,
                "y1": 10,
                "x2": 130,
                "y2": 28,
                "filled": False
            },
            {
                "type": "text",
                "x": 15,
                "y": 14,
                "text": "CPU Temp: {temp.cpu}°C"
            },
            {
                "type": "progress_bar",
                "x": 15,
                "y": 21,
                "width": 110,
                "height": 6,
                "value": "{temp.cpu_percent}",
                "label": ""
            }
        ]
    },
    "data_sources": [
        {
            "endpoint": "/api/system_status",
            "var_name": "temp"
        }
    ]
}

VFD_DUAL_VU_METER = {
    "name": "vfd_dual_vu_meter",
    "description": "Dual audio channel VU meters",
    "display_type": "vfd",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 1,
    "duration": 15,
    "template_data": {
        "type": "graphics",
        "elements": [
            {
                "type": "text",
                "x": 40,
                "y": 1,
                "text": "AUDIO VU METERS"
            },
            {
                "type": "text",
                "x": 2,
                "y": 10,
                "text": "L"
            },
            {
                "type": "rectangle",
                "x1": 10,
                "y1": 9,
                "x2": 135,
                "y2": 15,
                "filled": False
            },
            {
                "type": "rectangle",
                "x1": 11,
                "y1": 10,
                "x2": "{audio.left_bar_width}",
                "y2": 14,
                "filled": True
            },
            {
                "type": "text",
                "x": 2,
                "y": 20,
                "text": "R"
            },
            {
                "type": "rectangle",
                "x1": 10,
                "y1": 19,
                "x2": 135,
                "y2": 25,
                "filled": False
            },
            {
                "type": "rectangle",
                "x1": 11,
                "y1": 20,
                "x2": "{audio.right_bar_width}",
                "y2": 24,
                "filled": True
            },
            {
                "type": "text",
                "x": 40,
                "y": 28,
                "text": "{audio.peak_level_db} dB"
            }
        ]
    },
    "data_sources": [
        {
            "endpoint": "/api/audio/metrics/latest",
            "var_name": "audio"
        }
    ]
}


# ============================================================
# OLED Screen Templates
# ============================================================

OLED_SYSTEM_OVERVIEW = {
    "name": "oled_system_overview",
    "description": "Command deck clock with bounded CPU/MEM/DSK bars and footer summary.",
    "display_type": "oled",
    "enabled": True,
    "priority": 1,
    "refresh_interval": 20,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 14, "filled": True},
            {"type": "text", "text": "SYSTEM STATUS", "x": 2, "y": 2, "font": "small", "invert": True},
            {"type": "text", "text": "{now.time_24}", "x": 125, "y": 2, "font": "small", "invert": True, "align": "right"},
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
    },
    "data_sources": [
        {"endpoint": "/api/system_status", "var_name": "status"},
    ],
}

OLED_ALERT_SUMMARY = {
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
}

OLED_NETWORK_BEACON = {
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
}

OLED_IPAWS_POLL_WATCH = {
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
}

OLED_AUDIO_HEALTH_MATRIX = {
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
}

OLED_AUDIO_TELEMETRY = {
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
}


# ============================================================
# Screen Rotations
# ============================================================

LED_DEFAULT_ROTATION = {
    "name": "led_default_rotation",
    "description": "Default LED screen rotation cycle",
    "display_type": "led",
    "enabled": True,
    "screens": [],  # Will be populated with screen IDs
    "randomize": False,
    "skip_on_alert": True
}

VFD_DEFAULT_ROTATION = {
    "name": "vfd_default_rotation",
    "description": "Default VFD screen rotation cycle",
    "display_type": "vfd",
    "enabled": True,
    "screens": [],  # Will be populated with screen IDs
    "randomize": False,
    "skip_on_alert": True
}

OLED_DEFAULT_ROTATION = {
    "name": "oled_default_rotation",
    "description": "Default OLED screen rotation cycle",
    "display_type": "oled",
    "enabled": True,
    "screens": [],
    "randomize": False,
    "skip_on_alert": True,
}


def create_example_screens(app, display_types: Optional[Sequence[str]] = None):
    """Create example screen templates in the database.

    Args:
        app: Flask application instance
        display_types: Optional iterable of display types to limit creation to
    """

    requested = set(display_types or ("led", "vfd", "oled"))
    valid_types = {"led", "vfd", "oled"}
    requested &= valid_types

    if not requested:
        logger.warning("No valid display types requested; nothing to create")
        return

    with app.app_context():
        logger.info("Creating example screen templates for: %s", ", ".join(sorted(requested)))

        if "led" in requested:
            led_templates = [
                LED_SYSTEM_STATUS,
                LED_RESOURCES,
                LED_NETWORK_INFO,
                LED_ALERT_SUMMARY,
                LED_TIME_DATE,
                LED_RECEIVER_STATUS,
            ]

            led_screen_ids: List[Dict[str, int]] = []
            for template in led_templates:
                existing = DisplayScreen.query.filter_by(name=template["name"]).first()
                if existing:
                    logger.info(f"Screen '{template['name']}' already exists, skipping")
                    led_screen_ids.append({"screen_id": existing.id, "duration": template["duration"]})
                    continue

                screen = DisplayScreen(**template)
                db.session.add(screen)
                db.session.flush()
                led_screen_ids.append({"screen_id": screen.id, "duration": template["duration"]})
                logger.info(f"Created LED screen: {template['name']}")

            _ensure_rotation(LED_DEFAULT_ROTATION, led_screen_ids)
        else:
            logger.info("Skipping LED templates (not requested)")

        if "vfd" in requested:
            vfd_templates = [
                VFD_SYSTEM_METERS,
                VFD_AUDIO_VU_METER,
                VFD_ALERT_DETAILS,
                VFD_NETWORK_STATUS,
                VFD_TEMP_MONITORING,
                VFD_DUAL_VU_METER,
            ]

            vfd_screen_ids: List[Dict[str, int]] = []
            for template in vfd_templates:
                existing = DisplayScreen.query.filter_by(name=template["name"]).first()
                if existing:
                    logger.info(f"Screen '{template['name']}' already exists, skipping")
                    vfd_screen_ids.append({"screen_id": existing.id, "duration": template["duration"]})
                    continue

                screen = DisplayScreen(**template)
                db.session.add(screen)
                db.session.flush()
                vfd_screen_ids.append({"screen_id": screen.id, "duration": template["duration"]})
                logger.info(f"Created VFD screen: {template['name']}")

            _ensure_rotation(VFD_DEFAULT_ROTATION, vfd_screen_ids)
        else:
            logger.info("Skipping VFD templates (not requested)")

        if "oled" in requested:
            oled_templates = [
                OLED_SYSTEM_OVERVIEW,
                OLED_ALERT_SUMMARY,
                OLED_NETWORK_BEACON,
                OLED_IPAWS_POLL_WATCH,
                OLED_AUDIO_HEALTH_MATRIX,
                OLED_AUDIO_TELEMETRY,
            ]

            oled_screen_ids: List[Dict[str, int]] = []
            for template in oled_templates:
                existing = DisplayScreen.query.filter_by(name=template["name"]).first()
                if existing:
                    logger.info(f"Screen '{template['name']}' already exists, skipping")
                    oled_screen_ids.append({"screen_id": existing.id, "duration": template["duration"]})
                    continue

                screen = DisplayScreen(**template)
                db.session.add(screen)
                db.session.flush()
                oled_screen_ids.append({"screen_id": screen.id, "duration": template["duration"]})
                logger.info(f"Created OLED screen: {template['name']}")

            _ensure_rotation(OLED_DEFAULT_ROTATION, oled_screen_ids)
        else:
            logger.info("Skipping OLED templates (not requested)")

        db.session.commit()
        logger.info("Example screen templates created successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Provision example LED, VFD, and OLED screen templates"
    )
    parser.add_argument(
        "-d",
        "--display-type",
        action="append",
        choices=["led", "vfd", "oled"],
        help="Limit template creation to the specified display type (can be repeated)",
    )
    args = parser.parse_args()

    from app import create_app

    app = create_app()
    create_example_screens(app, args.display_type)
