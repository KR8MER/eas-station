"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

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
            "Up: {network.uptime_human}",
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
            "{radio.receivers[0].display_name}",
            "Signal: {radio.receivers[0].latest_status.signal_strength} dBm",
            "Lock: {radio.receivers[0].latest_status.locked}"
        ],
        "color": "CYAN",
        "mode": "HOLD",
        "speed": "SPEED_3",
        "font": "FONT_7x9"
    },
    "data_sources": [
        {
            "endpoint": "/api/monitoring/radio",
            "var_name": "radio"
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
            # Title row with decorative rule filling the remaining width
            {"type": "text", "x": 0, "y": 0, "text": "SYSTEM"},
            {"type": "line", "x1": 44, "y1": 3, "x2": 139, "y2": 3},
            # Three aligned meter rows: label, bordered bar, value column
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
            # Title row with decorative rule
            {"type": "text", "x": 0, "y": 0, "text": "AUDIO"},
            {"type": "line", "x1": 38, "y1": 3, "x2": 139, "y2": 3},
            # PEAK meter row
            {"type": "text", "x": 0, "y": 9, "text": "PK"},
            {
                "type": "bar", "x": 16, "y": 9, "width": 100, "height": 8,
                "value": "{audio.peak_level_percent}", "border": True,
            },
            {"type": "text", "x": 120, "y": 9, "text": "{audio.peak_level_percent}"},
            # Scale ticks at 25/50/75% shared between the meters
            {"type": "vline", "x": 41, "y": 18, "height": 2},
            {"type": "vline", "x": 66, "y": 18, "height": 2},
            {"type": "vline", "x": 91, "y": 18, "height": 2},
            # RMS meter row
            {"type": "text", "x": 0, "y": 22, "text": "RMS"},
            {
                "type": "bar", "x": 16, "y": 22, "width": 100, "height": 8,
                "value": "{audio.rms_level_percent}", "border": True,
            },
            {"type": "text", "x": 120, "y": 22, "text": "{audio.rms_level_percent}"},
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
            # Corner brackets instead of a full frame for a cleaner look
            {"type": "line", "x1": 0, "y1": 0, "x2": 12, "y2": 0},
            {"type": "line", "x1": 0, "y1": 0, "x2": 0, "y2": 8},
            {"type": "line", "x1": 127, "y1": 0, "x2": 139, "y2": 0},
            {"type": "line", "x1": 139, "y1": 0, "x2": 139, "y2": 8},
            {"type": "line", "x1": 0, "y1": 31, "x2": 12, "y2": 31},
            {"type": "line", "x1": 0, "y1": 23, "x2": 0, "y2": 31},
            {"type": "line", "x1": 127, "y1": 31, "x2": 139, "y2": 31},
            {"type": "line", "x1": 139, "y1": 23, "x2": 139, "y2": 31},
            # Centered title ("NETWORK" = 7 chars x 6px = 42px wide)
            {"type": "text", "x": 49, "y": 2, "text": "NETWORK"},
            {"type": "line", "x1": 20, "y1": 11, "x2": 119, "y2": 11},
            # IP and uptime rows
            {"type": "text", "x": 8, "y": 14, "text": "IP {network.ip_address}"},
            {"type": "text", "x": 8, "y": 23, "text": "Up {network.uptime_human}"}
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
    "description": "CPU and memory usage monitoring with visual gauges",
    "display_type": "vfd",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 15,
    "duration": 10,
    "template_data": {
        "type": "graphics",
        "elements": [
            {
                "type": "text",
                "x": 2,
                "y": 1,
                "text": "RESOURCE MONITOR"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 10,
                "width": 120,
                "height": 6,
                "value": "{status.system_resources.cpu_usage_percent}",
                "label": "CPU"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 20,
                "width": 120,
                "height": 6,
                "value": "{status.system_resources.memory_usage_percent}",
                "label": "MEM"
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

VFD_DUAL_VU_METER = {
    "name": "vfd_dual_vu_meter",
    "description": "Dual audio source VU meters showing buffer utilization",
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
                "x": 30,
                "y": 1,
                "text": "AUDIO VU METERS"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 9,
                "width": 120,
                "height": 8,
                "value": "{audio.live_metrics[0].buffer_utilization}",
                "label": "L"
            },
            {
                "type": "progress_bar",
                "x": 10,
                "y": 20,
                "width": 120,
                "height": 8,
                "value": "{audio.live_metrics[1].buffer_utilization}",
                "label": "R"
            }
        ]
    },
    "data_sources": [
        {
            "endpoint": "/api/audio/metrics",
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
    "description": "Active alert spotlight with warning banner, event, severity, and area.",
    "display_type": "oled",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 15,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            # Inverted header banner with warning icon and active count
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "warning", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "ALERTS", "x": 14, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{alerts.metadata.total_features} active",
                "x": 125, "y": 1, "font": "small", "invert": True,
                "align": "right", "max_width": 60, "overflow": "trim",
            },
            # Event name, prominent
            {
                "type": "text", "text": "{alerts.features[0].properties.event}",
                "x": 2, "y": 15, "font": "medium",
                "max_width": 124, "overflow": "ellipsis", "allow_empty": True,
            },
            # Severity / expiry row
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
            # Affected area footer with shield icon
            {"type": "icon", "name": "shield", "x": 2, "y": 49, "size": 11},
            {
                "type": "text", "text": "{alerts.features[0].properties.area_desc}",
                "x": 17, "y": 50, "font": "small",
                "max_width": 109, "overflow": "ellipsis", "allow_empty": True,
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
        "elements": [
            # Inverted header banner with network icon and interface name
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "network", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "NETWORK", "x": 14, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{health.network.primary_interface_name}",
                "x": 125, "y": 1, "font": "small", "invert": True,
                "align": "right", "max_width": 50, "overflow": "trim",
            },
            # Hostname, prominent
            {
                "type": "text", "text": "{health.system.hostname}",
                "x": 2, "y": 15, "font": "medium",
                "max_width": 124, "overflow": "ellipsis",
            },
            # IPv4 address, prominent
            {
                "type": "text", "text": "{health.network.primary_ipv4}",
                "x": 2, "y": 31, "font": "medium",
                "max_width": 124, "overflow": "trim", "allow_empty": True,
            },
            {"type": "hline", "x": 0, "y": 47, "width": 128},
            # Footer: uptime left, link speed right
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
        "elements": [
            # Inverted header banner with shield icon and current time
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "shield", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "IPAWS POLLER", "x": 14, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{now.time_24}",
                "x": 125, "y": 1, "font": "small", "invert": True, "align": "right",
            },
            # Poll status, prominent, with check icon
            {"type": "icon", "name": "check", "x": 2, "y": 16, "size": 10},
            {
                "type": "text", "text": "{status.last_poll.status}",
                "x": 16, "y": 15, "font": "medium",
                "max_width": 108, "overflow": "trim", "allow_empty": True,
            },
            {"type": "dotted_hline", "x": 0, "y": 31, "width": 128},
            # New vs fetched alert counts
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
            # Last poll timestamp footer
            {"type": "icon", "name": "clock", "x": 2, "y": 51, "size": 8},
            {
                "type": "text", "text": "Last {status.last_poll.local_timestamp}",
                "x": 13, "y": 52, "font": "small",
                "max_width": 113, "overflow": "trim", "allow_empty": True,
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
        "elements": [
            # Inverted header banner with heartbeat icon and overall status
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "heartbeat", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "AUDIO HEALTH", "x": 14, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{audio_health.overall_status}",
                "x": 125, "y": 1, "font": "small", "invert": True,
                "align": "right", "max_width": 48, "overflow": "trim",
            },
            # Health score bar row
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
            # Active source count
            {
                "type": "text", "text": "Sources {audio_health.active_sources}/{audio_health.total_sources} active",
                "x": 2, "y": 34, "font": "small",
                "max_width": 124, "overflow": "trim", "allow_empty": True,
            },
            {"type": "hline", "x": 0, "y": 46, "width": 128},
            # First-source diagnosis footer
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
    "data_sources": [
        {"endpoint": "/api/audio/health", "var_name": "audio_health"},
    ],
}

OLED_AUDIO_TELEMETRY = {
    "name": "oled_audio_telemetry",
    "description": "Live audio levels with dual-source VU bars.",
    "display_type": "oled",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 5,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            # Header banner: wave icon + title + source count on right
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "wave", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "AUDIO LEVELS", "x": 13, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{audio.total_sources}src",
                "x": 125, "y": 1, "font": "small", "invert": True,
                "align": "right", "max_width": 25, "overflow": "trim",
            },
            # Source 1 row
            {
                "type": "text", "text": "{audio.live_metrics[0].source_name}",
                "x": 2, "y": 14, "font": "small", "max_width": 66, "overflow": "trim",
            },
            {
                "type": "text", "text": "{audio.live_metrics[0].peak_level_db}dB",
                "x": 125, "y": 14, "font": "small", "align": "right",
                "max_width": 50, "overflow": "trim",
            },
            {
                "type": "bar", "value": "{audio.live_metrics[0].buffer_utilization}",
                "x": 2, "y": 26, "width": 124, "height": 9, "border": True,
            },
            # Source 2 row
            {
                "type": "text", "text": "{audio.live_metrics[1].source_name}",
                "x": 2, "y": 37, "font": "small", "max_width": 66, "overflow": "trim",
            },
            {
                "type": "text", "text": "{audio.live_metrics[1].peak_level_db}dB",
                "x": 125, "y": 37, "font": "small", "align": "right",
                "max_width": 50, "overflow": "trim",
            },
            {
                "type": "bar", "value": "{audio.live_metrics[1].buffer_utilization}",
                "x": 2, "y": 49, "width": 124, "height": 14, "border": True,
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/audio/metrics", "var_name": "audio"},
    ],
}

# Analog + digital clock with network footer.
# Fixed: right-side footer fits within 64 px (IP at y=50, ends y=61).
OLED_CLOCK_FACE = {
    "name": "oled_clock_face",
    "description": "Analog clock face with digital time, date, and IP address.",
    "display_type": "oled",
    "enabled": True,
    "priority": 1,
    "refresh_interval": 10,
    "duration": 15,
    "template_data": {
        "clear": True,
        "elements": [
            # Analog clock — left half, centered at (30, 32), radius 28
            {
                "type": "clock", "x": 30, "y": 32, "radius": 28,
                "show_seconds": True, "show_ticks": True,
            },
            # Digital time — right side
            {"type": "text", "text": "{now.time_24}", "x": 90, "y": 2, "font": "xlarge", "align": "center"},
            # Date below the time
            {"type": "text", "text": "{now.date}", "x": 90, "y": 32, "font": "small", "align": "center"},
            # Footer divider (right half only)
            {"type": "dotted_hline", "x": 64, "y": 44, "width": 60},
            # Network icon + IP address — y=50 ends at y=61, within 64 px
            {"type": "icon", "name": "network", "x": 65, "y": 50, "size": 9},
            {
                "type": "text", "text": "{status.ip_address}",
                "x": 76, "y": 50, "font": "small",
                "max_width": 50, "overflow": "trim",
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/system_status", "var_name": "status"},
    ],
}

# EAS decoder health and detection statistics.
OLED_EAS_DECODER = {
    "name": "oled_eas_decoder",
    "description": "EAS decoder health gauge, sync status, and detection count.",
    "display_type": "oled",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 15,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "antenna", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "EAS DECODER", "x": 13, "y": 1, "font": "small", "invert": True},
            # Health bar row
            {"type": "text", "text": "Health", "x": 2, "y": 15, "font": "small"},
            {
                "type": "bar", "value": "{eas_monitor.health_percentage}",
                "x": 40, "y": 15, "width": 58, "height": 10,
            },
            {
                "type": "text", "text": "{eas_monitor.health_percentage}%",
                "x": 125, "y": 15, "font": "small", "align": "right",
                "max_width": 24, "overflow": "trim",
            },
            # Sync + audio status
            {"type": "icon", "name": "check", "x": 2, "y": 28, "size": 8},
            {"type": "text", "text": "Synced", "x": 12, "y": 28, "font": "small"},
            {
                "type": "text", "text": "Audio: {eas_monitor.audio_flowing}",
                "x": 125, "y": 28, "font": "small", "align": "right",
                "max_width": 70, "overflow": "trim",
            },
            # Alerts detected
            {"type": "icon", "name": "warning", "x": 2, "y": 39, "size": 8},
            {
                "type": "text", "text": "Detected: {eas_monitor.alerts_detected} alerts",
                "x": 12, "y": 39, "font": "small", "max_width": 112, "overflow": "trim",
            },
            {"type": "hline", "x": 0, "y": 50, "width": 128},
            {"type": "icon", "name": "antenna", "x": 2, "y": 53, "size": 8},
            {"type": "text", "text": "{eas_monitor.active_sources} src", "x": 12, "y": 53, "font": "small"},
            {
                "type": "text", "text": "{eas_monitor.scans_performed} scans",
                "x": 125, "y": 53, "font": "small", "align": "right",
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/eas-monitor/status", "var_name": "eas_monitor"},
    ],
}

# Radio receiver status — two receivers with lock indicator and signal strength.
OLED_RECEIVERS = {
    "name": "oled_receivers",
    "description": "Radio receiver lock status and signal strength for two receivers.",
    "display_type": "oled",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 20,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "antenna", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "RECEIVERS", "x": 13, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{radio.count}",
                "x": 125, "y": 1, "font": "small", "invert": True, "align": "right",
            },
            # Receiver 1 name
            {
                "type": "text", "text": "{radio.receivers[0].display_name}",
                "x": 2, "y": 14, "font": "small", "max_width": 124, "overflow": "ellipsis",
            },
            # Receiver 1 status
            {"type": "icon", "name": "check", "x": 2, "y": 25, "size": 8},
            {"type": "text", "text": "Locked", "x": 12, "y": 25, "font": "small"},
            {
                "type": "text", "text": "{radio.receivers[0].latest_status.signal_strength} dBm",
                "x": 125, "y": 25, "font": "small", "align": "right",
                "max_width": 60, "overflow": "trim",
            },
            {"type": "dotted_hline", "x": 0, "y": 36, "width": 128},
            # Receiver 2 name
            {
                "type": "text", "text": "{radio.receivers[1].display_name}",
                "x": 2, "y": 39, "font": "small", "max_width": 124, "overflow": "ellipsis",
            },
            # Receiver 2 status
            {"type": "icon", "name": "check", "x": 2, "y": 50, "size": 8},
            {"type": "text", "text": "Locked", "x": 12, "y": 50, "font": "small"},
            {
                "type": "text", "text": "{radio.receivers[1].latest_status.signal_strength} dBm",
                "x": 125, "y": 50, "font": "small", "align": "right",
                "max_width": 60, "overflow": "trim",
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/monitoring/radio", "var_name": "radio"},
    ],
}


# GPS / timing receiver status — fix quality, position, satellites, accuracy.
OLED_GPS_STATUS = {
    "name": "oled_gps_status",
    "description": "GPS fix quality, latitude/longitude, satellites in use, and HDOP.",
    "display_type": "oled",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 5,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "network", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "GPS", "x": 13, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{gps.fix_quality}",
                "x": 125, "y": 1, "font": "small", "invert": True,
                "align": "right", "max_width": 80, "overflow": "trim",
            },
            # Position block
            {"type": "text", "text": "Lat", "x": 2, "y": 15, "font": "small"},
            {
                "type": "text", "text": "{gps.latitude:.5f}",
                "x": 125, "y": 15, "font": "small", "align": "right",
                "max_width": 100, "overflow": "trim",
            },
            {"type": "text", "text": "Lon", "x": 2, "y": 26, "font": "small"},
            {
                "type": "text", "text": "{gps.longitude:.5f}",
                "x": 125, "y": 26, "font": "small", "align": "right",
                "max_width": 100, "overflow": "trim",
            },
            {"type": "text", "text": "Alt", "x": 2, "y": 37, "font": "small"},
            {
                "type": "text", "text": "{gps.altitude_m:.0f} m",
                "x": 125, "y": 37, "font": "small", "align": "right",
                "max_width": 100, "overflow": "trim",
            },
            {"type": "hline", "x": 0, "y": 49, "width": 128},
            {"type": "icon", "name": "antenna", "x": 2, "y": 52, "size": 9},
            {"type": "text", "text": "{gps.satellites} sats", "x": 13, "y": 53, "font": "small"},
            {
                "type": "text", "text": "HDOP {gps.hdop}",
                "x": 125, "y": 53, "font": "small", "align": "right",
                "max_width": 70, "overflow": "trim",
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/hardware/gps/status", "var_name": "gps"},
    ],
}

# SAME/AFSK decoder pipeline — sync state, message-in-progress, throughput.
OLED_DECODER = {
    "name": "oled_decoder",
    "description": "EAS SAME/AFSK decoder sync state, bytes decoded, alerts, and scans.",
    "display_type": "oled",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 3,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "antenna", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "DECODER", "x": 13, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{eas.mode}",
                "x": 125, "y": 1, "font": "small", "invert": True,
                "align": "right", "max_width": 70, "overflow": "trim",
            },
            # Health bar
            {"type": "text", "text": "Health", "x": 2, "y": 15, "font": "small"},
            {"type": "bar", "value": "{eas.health_percentage}", "x": 44, "y": 15, "width": 54, "height": 10},
            {
                "type": "text", "text": "{eas.health_percentage}%",
                "x": 125, "y": 15, "font": "small", "align": "right",
                "max_width": 26, "overflow": "trim",
            },
            # Sync + message state
            {"type": "icon", "name": "check", "x": 2, "y": 28, "size": 8},
            {"type": "text", "text": "Sync {eas.decoder_synced}", "x": 12, "y": 28, "font": "small"},
            {
                "type": "text", "text": "Msg {eas.decoder_in_message}",
                "x": 125, "y": 28, "font": "small", "align": "right",
                "max_width": 70, "overflow": "trim",
            },
            {"type": "dotted_hline", "x": 0, "y": 39, "width": 128},
            {"type": "icon", "name": "warning", "x": 2, "y": 41, "size": 8},
            {"type": "text", "text": "{eas.alerts_detected} alerts", "x": 12, "y": 41, "font": "small"},
            {
                "type": "text", "text": "{eas.scans_performed} scans",
                "x": 125, "y": 41, "font": "small", "align": "right",
                "max_width": 80, "overflow": "trim",
            },
            {
                "type": "text", "text": "Bytes {eas.decoder_bytes_decoded}",
                "x": 2, "y": 53, "font": "small", "max_width": 124, "overflow": "trim",
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/eas-monitor/status", "var_name": "eas"},
    ],
}

# Airchain capture — is broadcast audio being captured, and for how long.
OLED_AIRCHAIN_CAPTURE = {
    "name": "oled_airchain_capture",
    "description": "Airchain capture state, capture uptime, buffer fill, and throughput.",
    "display_type": "oled",
    "enabled": True,
    "priority": 1,
    "refresh_interval": 2,
    "duration": 12,
    "template_data": {
        "clear": True,
        "elements": [
            {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
            {"type": "icon", "name": "wave", "x": 2, "y": 2, "size": 9},
            {"type": "text", "text": "AIRCHAIN", "x": 13, "y": 1, "font": "small", "invert": True},
            {
                "type": "text", "text": "{eas.active_sources} src",
                "x": 125, "y": 1, "font": "small", "invert": True,
                "align": "right", "max_width": 50, "overflow": "trim",
            },
            # Capture state, large
            {"type": "text", "text": "Capturing", "x": 2, "y": 16, "font": "small"},
            {
                "type": "text", "text": "{eas.audio_flowing}",
                "x": 125, "y": 15, "font": "medium", "align": "right",
                "max_width": 60, "overflow": "trim",
            },
            # Capture uptime / duration
            {"type": "icon", "name": "clock", "x": 2, "y": 29, "size": 8},
            {
                "type": "text", "text": "Up {eas.wall_clock_runtime_seconds:.0f}s",
                "x": 12, "y": 29, "font": "small", "max_width": 116, "overflow": "trim",
            },
            # Buffer fill
            {"type": "text", "text": "Buf", "x": 2, "y": 41, "font": "small"},
            {"type": "bar", "value": "{eas.buffer_utilization}", "x": 28, "y": 41, "width": 70, "height": 9},
            {
                "type": "text", "text": "{eas.buffer_utilization:.0f}%",
                "x": 125, "y": 41, "font": "small", "align": "right",
                "max_width": 26, "overflow": "trim",
            },
            {"type": "hline", "x": 0, "y": 52, "width": 128},
            {
                "type": "text", "text": "{eas.samples_per_second:.0f} samples/s",
                "x": 2, "y": 54, "font": "small", "max_width": 124, "overflow": "trim",
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/eas-monitor/status", "var_name": "eas"},
    ],
}

# Compact VFD variants (140x32) for the same three subjects.
VFD_GPS_STATUS = {
    "name": "vfd_gps_status",
    "description": "GPS fix, position, satellites, and HDOP on the VFD.",
    "display_type": "vfd",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 5,
    "duration": 10,
    "template_data": {
        "type": "graphics",
        "elements": [
            {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 32, "filled": False},
            {"type": "text", "x": 4, "y": 2, "text": "GPS {gps.fix_quality}  {gps.satellites}sat"},
            {"type": "line", "x1": 4, "y1": 11, "x2": 135, "y2": 11},
            {"type": "text", "x": 4, "y": 13, "text": "Lat {gps.latitude:.5f}"},
            {"type": "text", "x": 4, "y": 22, "text": "Lon {gps.longitude:.5f} H{gps.hdop}"},
        ],
    },
    "data_sources": [
        {"endpoint": "/api/hardware/gps/status", "var_name": "gps"},
    ],
}

VFD_DECODER = {
    "name": "vfd_decoder",
    "description": "EAS decoder health bar, sync state, alerts, and scans on the VFD.",
    "display_type": "vfd",
    "enabled": True,
    "priority": 2,
    "refresh_interval": 3,
    "duration": 10,
    "template_data": {
        "type": "graphics",
        "elements": [
            {"type": "text", "x": 2, "y": 1, "text": "EAS DECODER"},
            {
                "type": "bar", "x": 80, "y": 1, "width": 58, "height": 7,
                "value": "{eas.health_percentage}", "border": True,
            },
            {"type": "text", "x": 2, "y": 12, "text": "Sync {eas.decoder_synced} Msg {eas.decoder_in_message}"},
            {"type": "line", "x1": 2, "y1": 21, "x2": 137, "y2": 21},
            {"type": "text", "x": 2, "y": 23, "text": "Alerts {eas.alerts_detected}  Scans {eas.scans_performed}"},
        ],
    },
    "data_sources": [
        {"endpoint": "/api/eas-monitor/status", "var_name": "eas"},
    ],
}

VFD_AIRCHAIN_CAPTURE = {
    "name": "vfd_airchain_capture",
    "description": "Airchain capture state, uptime, and buffer fill on the VFD.",
    "display_type": "vfd",
    "enabled": True,
    "priority": 1,
    "refresh_interval": 2,
    "duration": 10,
    "template_data": {
        "type": "graphics",
        "elements": [
            {"type": "text", "x": 2, "y": 1, "text": "AIRCHAIN  Live {eas.audio_flowing}"},
            {"type": "text", "x": 2, "y": 11, "text": "Up {eas.wall_clock_runtime_seconds:.0f}s  {eas.active_sources}src"},
            {
                "type": "bar", "x": 2, "y": 22, "width": 136, "height": 8,
                "value": "{eas.buffer_utilization}", "border": True,
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/eas-monitor/status", "var_name": "eas"},
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
                VFD_GPS_STATUS,
                VFD_DECODER,
                VFD_AIRCHAIN_CAPTURE,
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
                OLED_CLOCK_FACE,
                OLED_EAS_DECODER,
                OLED_RECEIVERS,
                OLED_GPS_STATUS,
                OLED_DECODER,
                OLED_AIRCHAIN_CAPTURE,
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
