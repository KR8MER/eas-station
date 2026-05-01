"""Fix display screen templates: variable paths, out-of-bounds elements, and button.

Corrects broken screen templates that caused variables to not display:
- LED_RECEIVER_STATUS: wrong var_name 'receivers' → 'radio'; fix template paths
- VFD_TEMP_MONITORING: uses non-existent {temp.cpu}/{temp.cpu_percent};
  replace with system_resources.cpu/memory_usage_percent and rename screen
- VFD_DUAL_VU_METER: rectangle x2 coords were template strings (never
  resolved); replace with proper progress_bar elements using buffer_utilization
- VFD_AUDIO_VU_METER: peak/rms_level_linear (0-1 scale) replaced with
  peak/rms_level_percent (0-100) so bars render correctly
- OLED oled_clock_face: IP address text at y=57 extended 4 px past display
  bottom (64 px); combined with hostname → single IP row at y=50
- OLED oled_audio_telemetry: footer at y=56 extended 3 px past display bottom;
  footer removed, source count moved to header, bars resized to fill space

Revision ID: 20260501_fix_display_screens
Revises: 20260413_add_endec_fingerprint_to_eas_settings
Create Date: 2026-05-01
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "20260501_fix_display_screens"
down_revision = "20260413_add_endec_fingerprint_to_eas_settings"
branch_labels = None
depends_on = None

display_screens = table(
    "display_screens",
    column("id", sa.Integer),
    column("name", sa.String),
    column("template_data", JSONB),
    column("data_sources", JSONB),
    column("description", sa.String),
)

# ── Fixed template data ────────────────────────────────────────────────────────

LED_RECEIVER_STATUS_TEMPLATE = {
    "lines": [
        "RECEIVER STATUS",
        "{radio.receivers[0].display_name}",
        "Signal: {radio.receivers[0].latest_status.signal_strength} dBm",
        "Lock: {radio.receivers[0].latest_status.locked}",
    ],
    "color": "CYAN",
    "mode": "HOLD",
    "speed": "SPEED_3",
    "font": "FONT_7x9",
}

LED_RECEIVER_STATUS_SOURCES = [
    {"endpoint": "/api/monitoring/radio", "var_name": "radio"}
]

VFD_TEMP_MONITORING_TEMPLATE = {
    "type": "graphics",
    "elements": [
        {"type": "text", "x": 2, "y": 1, "text": "RESOURCE MONITOR"},
        {
            "type": "progress_bar",
            "x": 10, "y": 10, "width": 120, "height": 6,
            "value": "{status.system_resources.cpu_usage_percent}",
            "label": "CPU",
        },
        {
            "type": "progress_bar",
            "x": 10, "y": 20, "width": 120, "height": 6,
            "value": "{status.system_resources.memory_usage_percent}",
            "label": "MEM",
        },
    ],
}

VFD_TEMP_MONITORING_SOURCES = [
    {"endpoint": "/api/system_status", "var_name": "status"}
]

VFD_DUAL_VU_METER_TEMPLATE = {
    "type": "graphics",
    "elements": [
        {"type": "text", "x": 30, "y": 1, "text": "AUDIO VU METERS"},
        {
            "type": "progress_bar",
            "x": 10, "y": 9, "width": 120, "height": 8,
            "value": "{audio.live_metrics[0].buffer_utilization}",
            "label": "L",
        },
        {
            "type": "progress_bar",
            "x": 10, "y": 20, "width": 120, "height": 8,
            "value": "{audio.live_metrics[1].buffer_utilization}",
            "label": "R",
        },
    ],
}

VFD_DUAL_VU_METER_SOURCES = [
    {"endpoint": "/api/audio/metrics", "var_name": "audio"}
]

VFD_AUDIO_VU_METER_TEMPLATE = {
    "type": "graphics",
    "elements": [
        {"type": "text", "x": 2, "y": 1, "text": "AUDIO LEVELS"},
        {
            "type": "progress_bar",
            "x": 10, "y": 12, "width": 120, "height": 8,
            "value": "{audio.peak_level_percent}",
            "label": "PEAK",
        },
        {
            "type": "progress_bar",
            "x": 10, "y": 23, "width": 120, "height": 8,
            "value": "{audio.rms_level_percent}",
            "label": "RMS",
        },
    ],
}

# OLED clock face — IP at y=50, ends y=61 (within 64 px)
OLED_CLOCK_FACE_TEMPLATE = {
    "clear": True,
    "elements": [
        {"type": "clock", "x": 30, "y": 32, "radius": 28, "show_seconds": True, "show_ticks": True},
        {"type": "text", "text": "{now.time_24}", "x": 90, "y": 2, "font": "xlarge", "align": "center"},
        {"type": "text", "text": "{now.date}", "x": 90, "y": 32, "font": "small", "align": "center"},
        {"type": "dotted_hline", "x": 64, "y": 44, "width": 60},
        {"type": "icon", "name": "network", "x": 65, "y": 50, "size": 9},
        {
            "type": "text", "text": "{status.ip_address}",
            "x": 76, "y": 50, "font": "small",
            "max_width": 50, "overflow": "trim",
        },
    ],
}

# OLED audio levels — no out-of-bounds footer; source count in header
OLED_AUDIO_LEVELS_TEMPLATE = {
    "clear": True,
    "elements": [
        {"type": "rectangle", "x": 0, "y": 0, "width": 128, "height": 12, "filled": True},
        {"type": "icon", "name": "wave", "x": 2, "y": 2, "size": 9},
        {"type": "text", "text": "AUDIO LEVELS", "x": 13, "y": 1, "font": "small", "invert": True},
        {
            "type": "text", "text": "{audio.total_sources}src",
            "x": 125, "y": 1, "font": "small", "invert": True,
            "align": "right", "max_width": 25, "overflow": "trim",
        },
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
}


def _update_screen(conn, meta, name, template_data=None, data_sources=None, description=None):
    """Update a single screen by name; silently skips if not found."""
    tbl = meta.tables["display_screens"]
    row = conn.execute(sa.select(tbl.c.id).where(tbl.c.name == name)).first()
    if row is None:
        return
    values = {}
    if template_data is not None:
        values["template_data"] = template_data
    if data_sources is not None:
        values["data_sources"] = data_sources
    if description is not None:
        values["description"] = description
    if values:
        conn.execute(sa.update(tbl).where(tbl.c.id == row.id).values(**values))


def upgrade() -> None:
    conn = op.get_bind()
    meta = sa.MetaData()
    meta.reflect(bind=conn, only=["display_screens"])

    _update_screen(
        conn, meta,
        "led_receiver_status",
        template_data=LED_RECEIVER_STATUS_TEMPLATE,
        data_sources=LED_RECEIVER_STATUS_SOURCES,
    )

    _update_screen(
        conn, meta,
        "vfd_temp_monitoring",
        template_data=VFD_TEMP_MONITORING_TEMPLATE,
        data_sources=VFD_TEMP_MONITORING_SOURCES,
        description="CPU and memory usage monitoring with visual gauges",
    )

    _update_screen(
        conn, meta,
        "vfd_dual_vu_meter",
        template_data=VFD_DUAL_VU_METER_TEMPLATE,
        data_sources=VFD_DUAL_VU_METER_SOURCES,
    )

    _update_screen(
        conn, meta,
        "vfd_audio_vu_meter",
        template_data=VFD_AUDIO_VU_METER_TEMPLATE,
    )

    _update_screen(
        conn, meta,
        "oled_clock_face",
        template_data=OLED_CLOCK_FACE_TEMPLATE,
    )

    _update_screen(
        conn, meta,
        "oled_audio_telemetry",
        template_data=OLED_AUDIO_LEVELS_TEMPLATE,
    )


def downgrade() -> None:
    # Screen templates are forward-only data patches; no downgrade needed.
    pass
