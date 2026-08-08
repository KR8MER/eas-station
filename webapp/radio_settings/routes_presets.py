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

"""The built-in SDR tuning presets."""

from typing import Any

from flask import Flask, jsonify

from app_core.radio import (
    SDR_PRESETS,
)


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    @app.route("/api/radio/presets", methods=["GET"])
    def api_radio_presets() -> Any:
        """Get preset configurations for common SDR use cases."""
        return jsonify({"presets": SDR_PRESETS})

    @app.route("/api/radio/presets/<preset_key>", methods=["GET"])
    def api_radio_preset(preset_key: str) -> Any:
        """Get a specific preset configuration."""
        preset = SDR_PRESETS.get(preset_key)
        if preset is None:
            return jsonify({"error": f"Preset '{preset_key}' not found"}), 404
        return jsonify({"preset": preset})


__all__ = ["register"]
