"""Create example screen templates to showcase display capabilities.

This script creates various example screens for LED and VFD displays demonstrating:
- System status and health monitoring
- Resource usage (CPU, memory, disk)
- Network information
- Audio VU meters
- Alert summaries
- Temperature monitoring
"""

import logging
from app_core.extensions import db
from app_core.models import DisplayScreen, ScreenRotation

logger = logging.getLogger(__name__)


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


def create_example_screens(app):
    """Create example screen templates in the database.

    Args:
        app: Flask application instance
    """
    with app.app_context():
        logger.info("Creating example screen templates...")

        # LED Templates
        led_templates = [
            LED_SYSTEM_STATUS,
            LED_RESOURCES,
            LED_NETWORK_INFO,
            LED_ALERT_SUMMARY,
            LED_TIME_DATE,
            LED_RECEIVER_STATUS,
        ]

        led_screen_ids = []
        for template in led_templates:
            # Check if screen already exists
            existing = DisplayScreen.query.filter_by(name=template["name"]).first()
            if existing:
                logger.info(f"Screen '{template['name']}' already exists, skipping")
                led_screen_ids.append({"screen_id": existing.id, "duration": template["duration"]})
                continue

            screen = DisplayScreen(**template)
            db.session.add(screen)
            db.session.flush()  # Get ID
            led_screen_ids.append({"screen_id": screen.id, "duration": template["duration"]})
            logger.info(f"Created LED screen: {template['name']}")

        # VFD Templates
        vfd_templates = [
            VFD_SYSTEM_METERS,
            VFD_AUDIO_VU_METER,
            VFD_ALERT_DETAILS,
            VFD_NETWORK_STATUS,
            VFD_TEMP_MONITORING,
            VFD_DUAL_VU_METER,
        ]

        vfd_screen_ids = []
        for template in vfd_templates:
            # Check if screen already exists
            existing = DisplayScreen.query.filter_by(name=template["name"]).first()
            if existing:
                logger.info(f"Screen '{template['name']}' already exists, skipping")
                vfd_screen_ids.append({"screen_id": existing.id, "duration": template["duration"]})
                continue

            screen = DisplayScreen(**template)
            db.session.add(screen)
            db.session.flush()  # Get ID
            vfd_screen_ids.append({"screen_id": screen.id, "duration": template["duration"]})
            logger.info(f"Created VFD screen: {template['name']}")

        # Create rotations
        led_rotation_data = LED_DEFAULT_ROTATION.copy()
        led_rotation_data["screens"] = led_screen_ids

        existing_led_rotation = ScreenRotation.query.filter_by(name=led_rotation_data["name"]).first()
        if not existing_led_rotation:
            led_rotation = ScreenRotation(**led_rotation_data)
            db.session.add(led_rotation)
            logger.info(f"Created LED rotation: {led_rotation_data['name']}")
        else:
            logger.info(f"Rotation '{led_rotation_data['name']}' already exists, skipping")

        vfd_rotation_data = VFD_DEFAULT_ROTATION.copy()
        vfd_rotation_data["screens"] = vfd_screen_ids

        existing_vfd_rotation = ScreenRotation.query.filter_by(name=vfd_rotation_data["name"]).first()
        if not existing_vfd_rotation:
            vfd_rotation = ScreenRotation(**vfd_rotation_data)
            db.session.add(vfd_rotation)
            logger.info(f"Created VFD rotation: {vfd_rotation_data['name']}")
        else:
            logger.info(f"Rotation '{vfd_rotation_data['name']}' already exists, skipping")

        db.session.commit()
        logger.info("Example screen templates created successfully!")


if __name__ == "__main__":
    # Can be run standalone
    from app import create_app
    app = create_app()
    create_example_screens(app)
