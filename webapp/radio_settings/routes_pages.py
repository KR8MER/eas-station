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

"""The two rendered radio pages."""

from typing import Any

from flask import Flask, render_template

from app_core.location import get_location_settings
from app_core.models import RadioReceiver
from app_core.radio import (
    ensure_radio_tables,
)

from .serialization import _receiver_to_dict


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    @app.route("/admin/radio")
    def radio_settings() -> Any:
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("Radio table validation failed: %s", exc)

        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        location_settings = get_location_settings()

        return render_template(
            "admin/radio.html",
            receivers=[_receiver_to_dict(receiver) for receiver in receivers],
            location_settings=location_settings,
        )

    @app.route("/admin/radio/diagnostics")
    def radio_diagnostics_page() -> Any:
        """Display radio receiver diagnostics page."""
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:
            route_logger.debug("Radio table validation failed: %s", exc)

        return render_template("admin/radio_diagnostics.html")


__all__ = ["register"]
