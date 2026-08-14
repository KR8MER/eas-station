"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

from __future__ import annotations

"""Unified display controls route for LED, VFD, and OLED displays."""

from flask import Flask, render_template
from sqlalchemy.exc import OperationalError

from app_core.auth.decorators import require_auth, require_role
from app_core.extensions import db
import app_core.led as led_module
from app_core.vfd import VFD_AVAILABLE, vfd_controller
from app_core.models import LEDMessage, VFDDisplay, DisplayScreen, ScreenRotation, GatedAlert


def register(app: Flask, logger) -> None:
    """Register unified displays control page."""

    route_logger = logger.getChild("routes_displays")

    @app.route("/displays")
    @require_auth
    @require_role("Admin", "Operator")
    def displays_control():
        """Unified display control dashboard showing all display types."""
        try:
            # Get LED status
            led_status = None
            try:
                led_status = led_module.led_controller.get_status() if led_module.led_controller else None
            except Exception as exc:
                route_logger.debug("Could not get LED status: %s", exc)

            # Get VFD status
            vfd_status = None
            try:
                vfd_status = vfd_controller.get_status() if vfd_controller else None
            except Exception as exc:
                route_logger.debug("Could not get VFD status: %s", exc)

            # Get recent LED messages
            recent_led_messages = []
            try:
                recent_led_messages = (
                    LEDMessage.query.order_by(LEDMessage.created_at.desc()).limit(5).all()
                )
            except OperationalError as exc:
                route_logger.debug("Could not get LED messages: %s", exc)

            # Get recent VFD displays
            recent_vfd_displays = []
            try:
                recent_vfd_displays = (
                    VFDDisplay.query.order_by(VFDDisplay.created_at.desc()).limit(5).all()
                )
            except OperationalError as exc:
                route_logger.debug("Could not get VFD displays: %s", exc)

            # Get screen counts
            screens_count = 0
            rotations_count = 0
            try:
                screens_count = DisplayScreen.query.count()
                rotations_count = ScreenRotation.query.count()
            except OperationalError as exc:
                route_logger.debug("Could not get screen counts: %s", exc)

            # Gated-alerts hold-off queue ("Pending Review" scene on the
            # physical displays -- see scripts/screen_manager_gated.py).
            pending_gate_count = 0
            try:
                pending_gate_count = GatedAlert.query.filter_by(status="pending").count()
            except OperationalError as exc:
                route_logger.debug("Could not get pending gated-alerts count: %s", exc)

            return render_template(
                "displays_control.html",
                led_status=led_status,
                vfd_status=vfd_status,
                vfd_available=VFD_AVAILABLE,
                recent_led_messages=recent_led_messages,
                recent_vfd_displays=recent_vfd_displays,
                screens_count=screens_count,
                rotations_count=rotations_count,
                pending_gate_count=pending_gate_count,
            )

        except Exception as exc:
            route_logger.error("Error loading unified displays page: %s", exc)
            return (
                "<h1>Display Control Error</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )
