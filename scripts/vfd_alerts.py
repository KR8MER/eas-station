"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""
VFD Alert Display Helper
========================

This module provides functions to display EAS alerts on the Noritake VFD display.
When an alert is active, it preempts normal display content and shows alert information
with graphics.

Author: Claude (Anthropic)
Date: 2025-11-05
"""

import logging
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from app_core.vfd import vfd_controller, VFD_AVAILABLE
from app_core.models import VFDDisplay
from app_core.extensions import db
from app_utils import utc_now

logger = logging.getLogger(__name__)


def display_alert_on_vfd(alert_title: str, alert_event: str, alert_id: Optional[int] = None) -> bool:
    """
    Display an EAS alert on the VFD with graphics.

    Args:
        alert_title: Alert title/headline
        alert_event: Event type (e.g., "Tornado Warning")
        alert_id: Optional database ID of the alert

    Returns:
        True if successful, False otherwise
    """
    if not VFD_AVAILABLE or not vfd_controller:
        logger.warning("VFD not available, cannot display alert")
        return False

    try:
        # Clear the display first
        vfd_controller.clear_screen()

        # Create alert graphics
        # Display width: 140px, height: 32px

        # Draw border
        vfd_controller.draw_rectangle(0, 0, 139, 31, filled=False)
        vfd_controller.draw_rectangle(1, 1, 138, 30, filled=False)

        # Display "ALERT!" text at top
        vfd_controller.draw_text(45, 3, "ALERT!")

        # Draw separator line
        vfd_controller.draw_line(5, 12, 135, 12)

        # Display event type (truncate if needed)
        event_text = alert_event[:18] if len(alert_event) > 18 else alert_event
        vfd_controller.draw_text(5, 15, event_text)

        # Draw attention indicator (flashing could be implemented with repeated calls)
        # Draw small filled rectangles as indicators
        vfd_controller.draw_rectangle(5, 3, 10, 8, filled=True)
        vfd_controller.draw_rectangle(129, 3, 134, 8, filled=True)

        # Save display to database
        display = VFDDisplay(
            content_type="alert",
            content_data=f"{alert_event}: {alert_title}",
            priority=0,  # Emergency priority
            x_position=0,
            y_position=0,
            alert_id=alert_id,
            displayed_at=utc_now()
        )
        db.session.add(display)
        db.session.commit()

        logger.info(f"Alert displayed on VFD: {alert_event}")
        return True

    except Exception as e:
        logger.error(f"Error displaying alert on VFD: {e}")
        return False


def display_status_on_vfd(county_name: str, status: str = "NO ALERTS") -> bool:
    """
    Display normal status information on the VFD.

    Args:
        county_name: County name to display
        status: Status message (default: "NO ALERTS")

    Returns:
        True if successful, False otherwise
    """
    if not VFD_AVAILABLE or not vfd_controller:
        return False

    try:
        # Clear the display
        vfd_controller.clear_screen()

        # Draw decorative border
        vfd_controller.draw_rectangle(0, 0, 139, 31, filled=False)

        # Display county name at top (truncate if needed)
        county_text = county_name[:18] if len(county_name) > 18 else county_name
        vfd_controller.draw_text(5, 3, county_text)

        # Draw separator
        vfd_controller.draw_line(5, 12, 135, 12)

        # Display status
        status_text = status[:18] if len(status) > 18 else status
        vfd_controller.draw_text(5, 16, status_text)

        # Draw decorative corners
        vfd_controller.draw_line(3, 3, 8, 3)
        vfd_controller.draw_line(3, 3, 3, 8)
        vfd_controller.draw_line(131, 3, 136, 3)
        vfd_controller.draw_line(136, 3, 136, 8)
        vfd_controller.draw_line(3, 28, 8, 28)
        vfd_controller.draw_line(3, 23, 3, 28)
        vfd_controller.draw_line(131, 28, 136, 28)
        vfd_controller.draw_line(136, 23, 136, 28)

        # Save to database
        display = VFDDisplay(
            content_type="status",
            content_data=f"{county_name} - {status}",
            priority=2,  # Normal priority
            x_position=0,
            y_position=0,
            displayed_at=utc_now()
        )
        db.session.add(display)
        db.session.commit()

        logger.debug(f"Status displayed on VFD: {status}")
        return True

    except Exception as e:
        logger.error(f"Error displaying status on VFD: {e}")
        return False


def display_logo_on_vfd(image_path: str) -> bool:
    """
    Display a custom logo/graphic on the VFD.

    Args:
        image_path: Path to image file

    Returns:
        True if successful, False otherwise
    """
    if not VFD_AVAILABLE or not vfd_controller:
        return False

    try:
        vfd_controller.clear_screen()
        vfd_controller.display_image(image_path, x=0, y=0)

        # Save to database
        display = VFDDisplay(
            content_type="logo",
            content_data=image_path,
            priority=3,  # Low priority
            x_position=0,
            y_position=0,
            displayed_at=utc_now()
        )
        db.session.add(display)
        db.session.commit()

        logger.info(f"Logo displayed on VFD from {image_path}")
        return True

    except Exception as e:
        logger.error(f"Error displaying logo on VFD: {e}")
        return False


def clear_vfd_display() -> bool:
    """
    Clear the VFD display.

    Returns:
        True if successful, False otherwise
    """
    if not VFD_AVAILABLE or not vfd_controller:
        return False

    try:
        vfd_controller.clear_screen()
        logger.debug("VFD display cleared")
        return True

    except Exception as e:
        logger.error(f"Error clearing VFD: {e}")
        return False


def display_alert_summary_on_vfd(active_alerts: int, county_name: str) -> bool:
    """
    Display a summary of active alerts.

    Args:
        active_alerts: Number of active alerts
        county_name: County name

    Returns:
        True if successful, False otherwise
    """
    if not VFD_AVAILABLE or not vfd_controller:
        return False

    try:
        vfd_controller.clear_screen()

        # Border
        vfd_controller.draw_rectangle(0, 0, 139, 31, filled=False)

        # County name
        county_text = county_name[:18] if len(county_name) > 18 else county_name
        vfd_controller.draw_text(5, 3, county_text)

        # Line
        vfd_controller.draw_line(5, 12, 135, 12)

        # Alert count
        if active_alerts == 0:
            vfd_controller.draw_text(25, 18, "NO ALERTS")
        elif active_alerts == 1:
            vfd_controller.draw_text(25, 18, "1 ALERT")
        else:
            alert_text = f"{active_alerts} ALERTS"
            vfd_controller.draw_text(20, 18, alert_text)

        # Visual indicator if alerts present
        if active_alerts > 0:
            # Draw warning triangles
            for i in range(min(active_alerts, 3)):
                x = 10 + (i * 15)
                vfd_controller.draw_line(x, 28, x + 5, 23)  # Left side
                vfd_controller.draw_line(x + 5, 23, x + 10, 28)  # Right side
                vfd_controller.draw_line(x, 28, x + 10, 28)  # Bottom

        # Save to database
        display = VFDDisplay(
            content_type="alert_summary",
            content_data=f"{county_name} - {active_alerts} alerts",
            priority=1 if active_alerts > 0 else 2,
            x_position=0,
            y_position=0,
            displayed_at=utc_now()
        )
        db.session.add(display)
        db.session.commit()

        logger.info(f"Alert summary displayed on VFD: {active_alerts} alerts")
        return True

    except Exception as e:
        logger.error(f"Error displaying alert summary on VFD: {e}")
        return False
