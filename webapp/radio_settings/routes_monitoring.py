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

"""Radio status for the monitoring dashboard and the diagnostics summary."""

from typing import Any

from flask import Flask, jsonify

from app_core.models import RadioReceiver
from app_core.radio import (
    ensure_radio_tables,
    check_soapysdr_installation,
)

from . import deps
from .serialization import _receiver_to_dict


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    @app.route("/api/monitoring/radio", methods=["GET"])
    def api_monitoring_radio() -> Any:
        """Get monitoring status for all radio receivers (includes latest status updates)."""
        ensure_radio_tables(route_logger)
        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        return jsonify({"receivers": [_receiver_to_dict(receiver) for receiver in receivers]})

    @app.route("/api/radio/diagnostics", methods=["GET"])
    def api_radio_diagnostics() -> Any:
        """Check SoapySDR installation status and available drivers."""
        try:
            diagnostics = check_soapysdr_installation()
            return jsonify(diagnostics)
        except Exception as exc:
            route_logger.error("Diagnostics check failed: %s", exc)
            deps._log_radio_event(
                "ERROR",
                f"Diagnostics check failed: {exc}",
                module_suffix="diagnostics",
                details={"error": str(exc)},
            )
            return jsonify({"error": str(exc), "ready": False}), 500


__all__ = ["register"]
