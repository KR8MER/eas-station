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

"""The radio settings and diagnostics surface.

``webapp/routes_settings_radio.py`` was 2,781 lines: eight module-level helpers
and a 2,114-line ``register()`` with 26 route handlers nested inside it. Every
handler closed over exactly ``app`` and ``route_logger`` (one also over a local
helper), which is what let them move here verbatim — each topic module keeps
its own small ``register(app, route_logger)`` and the handler bodies are
unchanged, not even reindented.

    deps.py           the seams a test injects fakes for
    sdr_client.py     talking to the SDR service over Redis
    serialization.py  a RadioReceiver row -> API payload
    payload.py        validating an inbound receiver payload
    sync.py           reconciling the database against the live RadioManager
    routes_*.py       the handlers, grouped by topic
"""

from flask import Flask

from . import (
    deps,
    payload,
    routes_devices,
    routes_diagnostics_analyze,
    routes_diagnostics_capture,
    routes_diagnostics_status,
    routes_diagnostics_waterfall,
    routes_monitoring,
    routes_pages,
    routes_presets,
    routes_receiver_control,
    routes_receivers,
    routes_signal,
    routes_trends,
    sdr_client,
    serialization,
    sync,
)
from .payload import _parse_receiver_payload
from .serialization import _make_offline_status, _receiver_to_dict
from .sdr_client import _send_sdr_command
from .sync import _sync_audio_monitors, _sync_radio_manager_state

# Registered in the order the original file declared them, so the URL map is
# built in exactly the same sequence.
_ROUTE_MODULES = (
    routes_pages,
    routes_receivers,
    routes_receiver_control,
    routes_devices,
    routes_presets,
    routes_signal,
    routes_monitoring,
    routes_diagnostics_status,
    routes_diagnostics_capture,
    routes_diagnostics_waterfall,
    routes_diagnostics_analyze,
    routes_trends,
)


def register(app: Flask, logger) -> None:
    """Attach every radio route to the app.

    The child logger is derived once here and handed to each topic module, so
    the logger name is identical to the pre-split one.
    """
    route_logger = logger.getChild("routes_settings_radio")
    for module in _ROUTE_MODULES:
        module.register(app, route_logger)


__all__ = [
    "_make_offline_status",
    "_parse_receiver_payload",
    "_receiver_to_dict",
    "_send_sdr_command",
    "_sync_audio_monitors",
    "_sync_radio_manager_state",
    "deps",
    "payload",
    "register",
    "routes_trends",
    "sdr_client",
    "serialization",
    "sync",
]
