"""Improve OLED screens with graphical elements, icons, clocks, and gauges.

Redesigns all existing OLED screens to use the modern elements format with
graphical features: bar graphs, icons, analog clock, gauges, divider lines.
Adds two new screens: EAS Decoder status and Radio Receivers.

Revision ID: 20260216_improve_oled_screens
Revises: 20260214_add_manual_eas_triggered_at
Create Date: 2026-02-16
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table


revision = "20260216_improve_oled_screens"
down_revision = "20260214_add_manual_eas_triggered_at"
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
    column("screens", JSONB),
    column("updated_at", sa.DateTime),
)

# ═══════════════════════════════════════════════════════════════════════
# Layout constants for 128×64 monochrome OLED (SSD1306)
#
# Font heights:  small=11px  medium=14px  large=18px  xlarge=28px  huge=36px
#
# Standard layout grid:
#   y  0-11   Header banner  (12px filled rect, text y=1 in small font)
#      12     1px breathing room
#   y 13-23   Content row 1  (11px small font)
#      24     1px gap
#   y 25-35   Content row 2
#      36     1px gap
#   y 37-47   Content row 3
#      48     1px gap
#   y 49      Divider line   (1px hline)
#      50     1px gap
#   y 51-61   Footer row
# ═══════════════════════════════════════════════════════════════════════


# ── Screen 1: CLOCK FACE ───────────────────────────────────────────────
# Analog clock on the left, digital time + station info on the right.
# This is the "hero" screen — visually striking and always useful.
#
#  ┌────────────────────────────────────────┐
#  │   ╭──·──╮                              │
#  │  ╱  |   ╲     14:30                    │
#  │ ·   |    ·    Mon Feb 16               │
#  │ ·   o────·    2026                     │
#  │  ╲      ╱    ─────────                 │
#  │   ╰──·──╯    wx-station               │
#  │               192.168.10.25            │
#  └────────────────────────────────────────┘
CLOCK_FACE_TEMPLATE = {
    "clear": True,
    "elements": [
        # Analog clock face - left side
        {"type": "clock", "x": 30, "y": 32, "radius": 28, "show_seconds": True, "show_ticks": True},

        # Digital time - large, right side
        {"type": "text", "text": "{now.time_24}", "x": 90, "y": 2, "font": "xlarge", "align": "center"},

        # Date
        {"type": "text", "text": "{now.date}", "x": 90, "y": 32, "font": "small", "align": "center"},

        # Dotted divider on the right side
        {"type": "dotted_hline", "x": 64, "y": 44, "width": 60},

        # Network icon + IP address — y=50 ends at y=61, safely within 64 px
        {"type": "icon", "name": "network", "x": 65, "y": 50, "size": 9},
        {
            "type": "text", "text": "{status.ip_address}", "x": 76, "y": 50, "font": "small",
            "max_width": 50, "overflow": "trim",
        },
    ],
}


# ── Screen 2: SYSTEM OVERVIEW (refined) ────────────────────────────────
# Header banner + three bar-graph rows + divider + footer.
# Keeps the proven bar layout but adds icons and alert count.
#
#  ┌────────────────────────────────────────┐
#  │▓♥ SYSTEM STATUS▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓14:30▓│
#  │ CPU [████████░░░░░░░░░░]          43%  │
#  │ MEM [██████████████░░░░]          58%  │
#  │ DSK [████████████████░░]          71%  │
#  │─────────────────────────────────────── │
#  │ All systems OK          ⚠ 0 alerts    │
#  └────────────────────────────────────────┘
SYSTEM_OVERVIEW_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "heartbeat", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "SYSTEM", "x": 13, "y": 1, "font": "small", "invert": True},
        {"type": "text", "text": "{now.time_24}", "x": 125, "y": 1, "font": "small", "invert": True, "align": "right"},

        # CPU row
        {"type": "text", "text": "CPU", "x": 2, "y": 14, "font": "small"},
        {"type": "bar", "value": "{status.system_resources.cpu_usage_percent}", "x": 26, "y": 14, "width": 70, "height": 10},
        {
            "type": "text",
            "text": "{status.system_resources.cpu_usage_percent}%",
            "x": 125, "y": 14, "font": "small",
            "align": "right", "max_width": 28, "overflow": "trim",
        },

        # Memory row
        {"type": "text", "text": "MEM", "x": 2, "y": 26, "font": "small"},
        {"type": "bar", "value": "{status.system_resources.memory_usage_percent}", "x": 26, "y": 26, "width": 70, "height": 10},
        {
            "type": "text",
            "text": "{status.system_resources.memory_usage_percent}%",
            "x": 125, "y": 26, "font": "small",
            "align": "right", "max_width": 28, "overflow": "trim",
        },

        # Disk row
        {"type": "text", "text": "DSK", "x": 2, "y": 38, "font": "small"},
        {"type": "bar", "value": "{status.system_resources.disk_usage_percent}", "x": 26, "y": 38, "width": 70, "height": 10},
        {
            "type": "text",
            "text": "{status.system_resources.disk_usage_percent}%",
            "x": 125, "y": 38, "font": "small",
            "align": "right", "max_width": 28, "overflow": "trim",
        },

        # Divider
        {"type": "hline", "x": 0, "y": 50, "width": 128},

        # Footer: status + alert count
        {
            "type": "text", "text": "{status.status_summary}",
            "x": 2, "y": 52, "font": "small",
            "max_width": 80, "overflow": "ellipsis",
        },
        {"type": "icon", "name": "warning", "x": 100, "y": 52, "size": 9},
        {
            "type": "text", "text": "{status.active_alerts_count}",
            "x": 125, "y": 52, "font": "small", "align": "right",
        },
    ],
}


# ── Screen 3: ALERT DASHBOARD ──────────────────────────────────────────
# Alert information with warning icon and clear visual hierarchy.
#
#  ┌────────────────────────────────────────┐
#  │▓⚠ ALERTS▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓1▓│
#  │ Flood Warning                          │  <- event in medium font
#  │ Severity: Moderate                     │
#  │ Putnam County, OH                      │
#  │─────────────────────────────────────── │
#  │ Exp 2025-11-19T08:15:00Z              │
#  └────────────────────────────────────────┘
ALERT_DASHBOARD_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner with warning icon
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "warning", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "ALERTS", "x": 13, "y": 1, "font": "small", "invert": True},
        {
            "type": "text", "text": "{alerts.metadata.total_features}",
            "x": 125, "y": 1, "font": "small", "invert": True, "align": "right",
        },

        # Event name — medium font for prominence
        {
            "type": "text", "text": "{alerts.features[0].properties.event}",
            "x": 2, "y": 14, "font": "medium",
            "max_width": 124, "overflow": "ellipsis",
        },

        # Severity
        {
            "type": "text", "text": "{alerts.features[0].properties.severity}",
            "x": 2, "y": 29, "font": "small",
            "max_width": 60, "overflow": "trim",
        },
        # Urgency on the right
        {
            "type": "text", "text": "{alerts.features[0].properties.urgency}",
            "x": 125, "y": 29, "font": "small", "align": "right",
            "max_width": 60, "overflow": "trim",
        },

        # Area description
        {
            "type": "text", "text": "{alerts.features[0].properties.area_desc}",
            "x": 2, "y": 40, "font": "small",
            "max_width": 124, "overflow": "ellipsis",
        },

        # Divider
        {"type": "hline", "x": 0, "y": 50, "width": 128},

        # Expiry
        {"type": "icon", "name": "clock", "x": 2, "y": 52, "size": 9},
        {
            "type": "text", "text": "Exp {alerts.features[0].properties.expires_iso}",
            "x": 13, "y": 52, "font": "small",
            "max_width": 112, "overflow": "trim",
        },
    ],
}


# ── Screen 4: STATION IDENTITY ─────────────────────────────────────────
# Big hostname so you can read it from across the room.
# IP address and network info below.
#
#  ┌────────────────────────────────────────┐
#  │▓🌐 STATION▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓14:30▓│
#  │                                        │
#  │      wx-station                        │  <- LARGE font
#  │                                        │
#  │  192.168.10.25                         │
#  │- - - - - - - - - - - - - - - - - - - -│
#  │ 🔌 eth0   Up 12d 5h                   │
#  └────────────────────────────────────────┘
STATION_ID_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner with network icon
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "network", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "STATION", "x": 13, "y": 1, "font": "small", "invert": True},
        {"type": "text", "text": "{now.time_24}", "x": 125, "y": 1, "font": "small", "invert": True, "align": "right"},

        # Hostname — LARGE font for visibility
        {
            "type": "text", "text": "{health.system.hostname}",
            "x": 64, "y": 16, "font": "large", "align": "center",
            "max_width": 124, "overflow": "ellipsis",
        },

        # IP address
        {
            "type": "text", "text": "{health.network.primary_ipv4}",
            "x": 64, "y": 36, "font": "small", "align": "center",
        },

        # Dotted divider
        {"type": "dotted_hline", "x": 0, "y": 49, "width": 128},

        # Interface + uptime footer
        {
            "type": "text", "text": "{health.network.primary_interface_name}",
            "x": 2, "y": 52, "font": "small",
        },
        {
            "type": "text", "text": "Up {health.system.uptime_human}",
            "x": 125, "y": 52, "font": "small", "align": "right",
            "max_width": 80, "overflow": "trim",
        },
    ],
}


# ── Screen 5: IPAWS FEED STATUS ────────────────────────────────────────
# Polling status with check/cross icons for visual status.
#
#  ┌────────────────────────────────────────┐
#  │▓🛡 IPAWS FEED▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
#  │ ✓ success                              │
#  │ Last 2025-11-19T04:47:00              │
#  │ +0 new  /  6 fetched                  │
#  │─────────────────────────────────────── │
#  │ NWS-ALPHA              02/16/2026     │
#  └────────────────────────────────────────┘
IPAWS_FEED_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner with shield icon
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "shield", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "IPAWS FEED", "x": 13, "y": 1, "font": "small", "invert": True},

        # Status line with icon (check = success, cross = fail)
        {"type": "icon", "name": "check", "x": 2, "y": 14, "size": 9},
        {
            "type": "text", "text": "{status.last_poll.status}",
            "x": 14, "y": 14, "font": "small",
            "max_width": 110, "overflow": "trim",
        },

        # Last poll timestamp
        {
            "type": "text", "text": "Last {status.last_poll.local_timestamp}",
            "x": 2, "y": 26, "font": "small",
            "max_width": 124, "overflow": "trim",
        },

        # New / fetched counts
        {
            "type": "text", "text": "+{status.last_poll.alerts_new} new",
            "x": 2, "y": 38, "font": "small",
        },
        {
            "type": "text", "text": "{status.last_poll.alerts_fetched} fetched",
            "x": 125, "y": 38, "font": "small", "align": "right",
        },

        # Divider
        {"type": "hline", "x": 0, "y": 50, "width": 128},

        # Data source + date footer
        {
            "type": "text", "text": "{status.last_poll.data_source}",
            "x": 2, "y": 52, "font": "small",
            "max_width": 70, "overflow": "trim",
        },
        {
            "type": "text", "text": "{now.date}",
            "x": 125, "y": 52, "font": "small", "align": "right",
        },
    ],
}


# ── Screen 6: AUDIO HEALTH ─────────────────────────────────────────────
# Health score gauge + source status with icons.
#
#  ┌────────────────────────────────────────┐
#  │▓🔊 AUDIO▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓healthy▓│
#  │                                        │
#  │ Health [██████████████░░░░░░]     96%  │
#  │ Sources: 3/4 active                    │
#  │ WXJ-93              Score: 97.5        │
#  │- - - - - - - - - - - - - - - - - - - -│
#  │ ✓ Healthy    No silence               │
#  └────────────────────────────────────────┘
AUDIO_HEALTH_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner with speaker icon
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "speaker", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "AUDIO", "x": 13, "y": 1, "font": "small", "invert": True},
        {
            "type": "text", "text": "{audio_health.overall_status}",
            "x": 125, "y": 1, "font": "small", "invert": True, "align": "right",
            "max_width": 60, "overflow": "trim",
        },

        # Health bar
        {"type": "text", "text": "Health", "x": 2, "y": 15, "font": "small"},
        {"type": "bar", "value": "{audio_health.overall_health_score}", "x": 40, "y": 15, "width": 58, "height": 10},
        {
            "type": "text", "text": "{audio_health.overall_health_score}%",
            "x": 125, "y": 15, "font": "small", "align": "right",
            "max_width": 24, "overflow": "trim",
        },

        # Active sources
        {
            "type": "text", "text": "Sources {audio_health.active_sources}/{audio_health.total_sources}",
            "x": 2, "y": 28, "font": "small",
        },

        # Primary source name + score
        {
            "type": "text", "text": "{audio_health.health_records[0].source_name}",
            "x": 2, "y": 39, "font": "small",
            "max_width": 70, "overflow": "trim",
        },
        {
            "type": "text", "text": "{audio_health.health_records[0].health_score}%",
            "x": 125, "y": 39, "font": "small", "align": "right",
        },

        # Divider
        {"type": "dotted_hline", "x": 0, "y": 50, "width": 128},

        # Health status icons
        {"type": "icon", "name": "check", "x": 2, "y": 53, "size": 8},
        {"type": "text", "text": "Healthy", "x": 12, "y": 53, "font": "small"},
        {"type": "icon", "name": "wave", "x": 60, "y": 53, "size": 8},
        {"type": "text", "text": "No silence", "x": 70, "y": 53, "font": "small"},
    ],
}


# ── Screen 7: AUDIO LEVELS (VU Meter Style) ────────────────────────────
# Two sources with peak bars and dB readouts — like a mixing console.
#
#  ┌────────────────────────────────────────┐
#  │▓〰 AUDIO LEVELS▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
#  │ WNCI                                  │
#  │ Peak [██████████████████]    -3.5 dB   │
#  │ WXJ-93                                │
#  │ Peak [██████████]            -8.0 dB   │
#  │─────────────────────────────────────── │
#  │ 🔊 2 sources     Active: WNCI        │
#  └────────────────────────────────────────┘
AUDIO_LEVELS_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner with wave icon + source count on right
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "wave", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "AUDIO LEVELS", "x": 13, "y": 1, "font": "small", "invert": True},
        {
            "type": "text", "text": "{audio.total_sources}src",
            "x": 125, "y": 1, "font": "small", "invert": True,
            "align": "right", "max_width": 25, "overflow": "trim",
        },

        # Source 1 name + dB level (same row)
        {
            "type": "text", "text": "{audio.live_metrics[0].source_name}",
            "x": 2, "y": 14, "font": "small",
            "max_width": 66, "overflow": "trim",
        },
        {
            "type": "text", "text": "{audio.live_metrics[0].peak_level_db}dB",
            "x": 125, "y": 14, "font": "small", "align": "right",
            "max_width": 50, "overflow": "trim",
        },

        # Source 1 VU bar — y=26, height=9 → bottom at y=34
        {"type": "bar", "value": "{audio.live_metrics[0].buffer_utilization}", "x": 2, "y": 26, "width": 124, "height": 9, "border": True},

        # Source 2 name + dB level
        {
            "type": "text", "text": "{audio.live_metrics[1].source_name}",
            "x": 2, "y": 37, "font": "small",
            "max_width": 66, "overflow": "trim",
        },
        {
            "type": "text", "text": "{audio.live_metrics[1].peak_level_db}dB",
            "x": 125, "y": 37, "font": "small", "align": "right",
            "max_width": 50, "overflow": "trim",
        },

        # Source 2 VU bar — y=49, height=14 → bottom at y=62 (within 64 px)
        {"type": "bar", "value": "{audio.live_metrics[1].buffer_utilization}", "x": 2, "y": 49, "width": 124, "height": 14, "border": True},
    ],
}


# ── Screen 8: EAS DECODER (NEW) ────────────────────────────────────────
# EAS decoder status with health gauge and detection stats.
#
#  ┌────────────────────────────────────────┐
#  │▓📡 EAS DECODER▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
#  │                                        │
#  │ Health [████████████████░░░░]     85%  │
#  │ ✓ Synced        Audio: Yes            │
#  │ Detected: 3 alerts                    │
#  │─────────────────────────────────────── │
#  │ 📡 2 sources     42 scans            │
#  └────────────────────────────────────────┘
EAS_DECODER_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner with antenna icon
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "antenna", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "EAS DECODER", "x": 13, "y": 1, "font": "small", "invert": True},

        # Health bar
        {"type": "text", "text": "Health", "x": 2, "y": 15, "font": "small"},
        {"type": "bar", "value": "{eas_monitor.health_percentage}", "x": 40, "y": 15, "width": 58, "height": 10},
        {
            "type": "text", "text": "{eas_monitor.health_percentage}%",
            "x": 125, "y": 15, "font": "small", "align": "right",
            "max_width": 24, "overflow": "trim",
        },

        # Sync status + audio flowing
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
            "x": 12, "y": 39, "font": "small",
            "max_width": 112, "overflow": "trim",
        },

        # Divider
        {"type": "hline", "x": 0, "y": 50, "width": 128},

        # Footer: sources + scans
        {"type": "icon", "name": "antenna", "x": 2, "y": 53, "size": 8},
        {
            "type": "text", "text": "{eas_monitor.active_sources} src",
            "x": 12, "y": 53, "font": "small",
        },
        {
            "type": "text", "text": "{eas_monitor.scans_performed} scans",
            "x": 125, "y": 53, "font": "small", "align": "right",
        },
    ],
}


# ── Screen 9: RADIO RECEIVERS (NEW) ────────────────────────────────────
# Receiver status with antenna icons and signal info.
#
#  ┌────────────────────────────────────────┐
#  │▓📡 RECEIVERS▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓2▓│
#  │ WXJ-93 Airspy                         │
#  │ ✓ Locked         -43.0 dBm           │
#  │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │
#  │ WNCI-FM RTL-SDR                      │
#  │─────────────────────────────────────── │
#  │ ✓ Locked         -51.2 dBm           │
#  └────────────────────────────────────────┘
RECEIVERS_TEMPLATE = {
    "clear": True,
    "elements": [
        # Header banner with antenna icon
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
            "x": 2, "y": 14, "font": "small",
            "max_width": 124, "overflow": "ellipsis",
        },

        # Receiver 1 status
        {"type": "icon", "name": "check", "x": 2, "y": 25, "size": 8},
        {"type": "text", "text": "Locked", "x": 12, "y": 25, "font": "small"},
        {
            "type": "text", "text": "{radio.receivers[0].latest_status.signal_strength} dBm",
            "x": 125, "y": 25, "font": "small", "align": "right",
            "max_width": 60, "overflow": "trim",
        },

        # Dotted divider
        {"type": "dotted_hline", "x": 0, "y": 36, "width": 128},

        # Receiver 2 name
        {
            "type": "text", "text": "{radio.receivers[1].display_name}",
            "x": 2, "y": 39, "font": "small",
            "max_width": 124, "overflow": "ellipsis",
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
}


# Map of existing screen names → their new template_data
UPDATED_SCREENS = {
    "oled_system_overview": SYSTEM_OVERVIEW_TEMPLATE,
    "oled_alert_summary": ALERT_DASHBOARD_TEMPLATE,
    "oled_network_beacon": STATION_ID_TEMPLATE,
    "oled_ipaws_poll_watch": IPAWS_FEED_TEMPLATE,
    "oled_audio_health_matrix": AUDIO_HEALTH_TEMPLATE,
    "oled_audio_telemetry": AUDIO_LEVELS_TEMPLATE,
}


# New screens to insert
NEW_SCREENS = [
    {
        "name": "oled_clock_face",
        "description": "Analog clock face with digital time, date, and station info.",
        "display_type": "oled",
        "enabled": True,
        "priority": 1,
        "refresh_interval": 1,
        "duration": 15,
        "template_data": CLOCK_FACE_TEMPLATE,
        "data_sources": [
            {"endpoint": "/api/system_status", "var_name": "status"},
        ],
    },
    {
        "name": "oled_eas_decoder",
        "description": "EAS decoder health, sync status, and alert detection counts.",
        "display_type": "oled",
        "enabled": True,
        "priority": 2,
        "refresh_interval": 10,
        "duration": 12,
        "template_data": EAS_DECODER_TEMPLATE,
        "data_sources": [
            {"endpoint": "/api/eas-monitor/status", "var_name": "eas_monitor"},
        ],
    },
    {
        "name": "oled_receivers",
        "description": "Radio receiver lock status and signal strength.",
        "display_type": "oled",
        "enabled": True,
        "priority": 2,
        "refresh_interval": 15,
        "duration": 12,
        "template_data": RECEIVERS_TEMPLATE,
        "data_sources": [
            {"endpoint": "/api/monitoring/radio", "var_name": "radio"},
        ],
    },
]


def upgrade() -> None:
    """Update existing OLED screens and add new graphical screens."""
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    # ── Update existing screens ────────────────────────────────────
    update_stmt = (
        display_screens.update()
        .where(display_screens.c.name == sa.bindparam("target_screen_name"))
        .where(display_screens.c.display_type == "oled")
    )

    for screen_name, template_data in UPDATED_SCREENS.items():
        serialized = json.loads(json.dumps(template_data))
        conn.execute(
            update_stmt,
            {
                "template_data": serialized,
                "updated_at": now,
                "target_screen_name": screen_name,
            },
        )

    # ── Insert new screens ─────────────────────────────────────────
    new_screen_ids = []

    for screen_data in NEW_SCREENS:
        # Skip if screen already exists (idempotent)
        existing = conn.execute(
            sa.text("SELECT id FROM display_screens WHERE name = :name"),
            {"name": screen_data["name"]},
        ).fetchone()

        if existing:
            new_screen_ids.append({
                "screen_id": existing[0],
                "duration": screen_data["duration"],
            })
            continue

        result = conn.execute(
            display_screens.insert()
            .values(
                name=screen_data["name"],
                description=screen_data["description"],
                display_type=screen_data["display_type"],
                enabled=screen_data["enabled"],
                priority=screen_data["priority"],
                refresh_interval=screen_data["refresh_interval"],
                duration=screen_data["duration"],
                template_data=json.loads(json.dumps(screen_data["template_data"])),
                data_sources=screen_data.get("data_sources"),
                conditions=screen_data.get("conditions"),
                created_at=now,
                updated_at=None,
                last_displayed_at=None,
                display_count=0,
                error_count=0,
                last_error=None,
            )
            .returning(display_screens.c.id)
        )

        row = result.fetchone()
        if row:
            new_screen_ids.append({
                "screen_id": row[0],
                "duration": screen_data["duration"],
            })

    # ── Add new screens to the default OLED rotation ───────────────
    if new_screen_ids:
        rotation_row = conn.execute(
            sa.text(
                "SELECT id, screens FROM screen_rotations WHERE name = :name"
            ),
            {"name": "oled_default_rotation"},
        ).fetchone()

        if rotation_row:
            rotation_id, existing_screens = rotation_row
            existing_screen_id_set = {
                s.get("screen_id") for s in (existing_screens or [])
            }

            updated_screens = list(existing_screens or [])
            for entry in new_screen_ids:
                if entry["screen_id"] not in existing_screen_id_set:
                    updated_screens.append(entry)

            if len(updated_screens) > len(existing_screens or []):
                conn.execute(
                    sa.text(
                        "UPDATE screen_rotations "
                        "SET screens = :screens, updated_at = :updated_at "
                        "WHERE id = :id"
                    ),
                    {
                        "screens": json.dumps(updated_screens),
                        "updated_at": now,
                        "id": rotation_id,
                    },
                )


def downgrade() -> None:
    # No downgrade to avoid clobbering operator customizations
    pass
