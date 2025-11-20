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

"""Route scaffolding helpers for the NOAA alerts Flask application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from flask import Flask

from . import (
    routes_admin,
    routes_analytics,
    routes_audio_tests,
    routes_backups,
    routes_debug,
    routes_diagnostics,
    routes_eas_monitor_status,
    routes_exports,
    routes_settings_radio,
    routes_settings_audio,
    routes_led,
    routes_vfd,
    routes_screens,
    routes_monitoring,
    routes_public,
    routes_setup,
    routes_security,
    routes_stream_profiles,
    routes_rwt_schedule,
    template_helpers,
    documentation,
)
from .routes import alert_verification, eas_compliance, system_controls
from . import eas


@dataclass(frozen=True)
class RouteModule:
    """Describe a route bundle that can be attached to the Flask app."""

    name: str
    registrar: Callable[..., None]
    requires_logger: bool = True


def iter_route_modules() -> Iterable[RouteModule]:
    """Yield the registered route modules in initialization order."""

    yield RouteModule("template_helpers", template_helpers.register, requires_logger=False)
    yield RouteModule("routes_public", routes_public.register)
    yield RouteModule("routes_documentation", documentation.register_documentation_routes)
    yield RouteModule("routes_setup", routes_setup.register)
    yield RouteModule("routes_monitoring", routes_monitoring.register)
    yield RouteModule("routes_alert_verification", alert_verification.register)
    yield RouteModule("routes_eas_compliance", eas_compliance.register)
    yield RouteModule("routes_system_controls", system_controls.register)
    yield RouteModule("routes_eas_workflow", eas.register)
    yield RouteModule("routes_rwt_schedule", routes_rwt_schedule.register_routes)
    yield RouteModule("routes_settings_radio", routes_settings_radio.register)
    yield RouteModule("routes_settings_audio", routes_settings_audio.register)
    yield RouteModule("routes_eas_monitor_status", routes_eas_monitor_status.register_eas_monitor_routes)
    yield RouteModule("routes_audio_tests", routes_audio_tests.register)
    yield RouteModule("routes_exports", routes_exports.register)
    yield RouteModule("routes_led", routes_led.register)
    yield RouteModule("routes_vfd", routes_vfd.register)
    yield RouteModule("routes_screens", routes_screens.register)
    yield RouteModule("routes_analytics", routes_analytics.register)
    yield RouteModule("routes_security", routes_security.register)
    yield RouteModule("routes_backups", routes_backups.register)
    yield RouteModule("routes_debug", routes_debug.register)
    yield RouteModule("routes_diagnostics", routes_diagnostics.register)
    yield RouteModule("routes_stream_profiles", routes_stream_profiles.register)
    yield RouteModule("routes_admin", routes_admin.register)


def register_routes(app: Flask, logger) -> None:
    """Register all route groups with the provided Flask application."""

    for module in iter_route_modules():
        module_logger = logger.getChild(module.name)
        try:
            if module.requires_logger:
                module.registrar(app, logger)
            else:
                module.registrar(app)
        except Exception as exc:  # pragma: no cover - defensive
            module_logger.error("Failed to register route module: %s", exc)
            raise
        else:
            module_logger.debug("Registered route module")


__all__ = ["RouteModule", "iter_route_modules", "register_routes"]
