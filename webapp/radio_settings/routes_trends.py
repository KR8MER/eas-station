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

"""Historical SDR trend data for the Diagnostics page's charts/sparklines.

Reads the tiered Redis archive kept by ``app_core/radio/trends.py`` (sampled
by ``sdr_hardware_service.py``'s existing publisher loop on a 10 s throttle).
No permission decorator, matching the read-only sibling GET endpoints in
this package (``/api/radio/spectrum/<id>``, ``/api/radio/diagnostics/status``)
which also rely on the app-wide login gate rather than a per-route
permission check.
"""

import time
from typing import Any

from flask import Flask, jsonify, request

from app_core.models import RadioReceiver
from app_core.radio import trends as sdr_trends

from . import deps


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""

    @app.route("/api/radio/diagnostics/trends/<int:receiver_id>", methods=["GET"])
    def api_radio_diagnostics_trends(receiver_id: int) -> Any:
        """Return the historical trend archive for one receiver.

        Query param ``window`` selects the resolution/duration: ``1h``
        (raw 10 s samples), ``6h``/``24h``/``7d`` (5 min rollup buckets).
        Defaults to ``1h`` for an unrecognised value, same fallback
        behaviour as ``app_core.radio.trends.read_window``.
        """
        # Outside the try/except below on purpose (matches the sibling
        # capture/waterfall routes): get_or_404() raises a werkzeug
        # HTTPException, which is itself an Exception subclass -- catching
        # it here would turn a clean 404 into a 500.
        receiver = RadioReceiver.query.get_or_404(receiver_id)
        try:
            window = request.args.get("window", sdr_trends.SDR_TRENDS_DEFAULT_WINDOW)

            try:
                redis_client = deps.get_redis_client()
            except Exception as redis_exc:
                route_logger.debug("Trends: could not get Redis client: %s", redis_exc)
                redis_client = None

            result = sdr_trends.read_window(redis_client, receiver.identifier, window)

            return jsonify({
                "receiver_id": receiver.id,
                "identifier": receiver.identifier,
                "display_name": receiver.display_name,
                "window": result["window"],
                "tier": result["tier"],
                "available_windows": list(sdr_trends.SDR_TRENDS_WINDOW_TO_TIER.keys()),
                "samples": result["samples"],
                "sample_count": len(result["samples"]),
                "timestamp": time.time(),
            })
        except Exception as exc:
            route_logger.error(
                "Failed to read trend data for receiver %s: %s", receiver_id, exc, exc_info=True
            )
            deps._log_radio_event(
                "ERROR",
                f"Failed to read SDR trend data: {exc}",
                module_suffix="diagnostics",
                details={"receiver_id": receiver_id, "error": str(exc)},
            )
            return jsonify({"error": str(exc)}), 500


__all__ = ["register"]
