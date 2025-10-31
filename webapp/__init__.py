"""Route scaffolding helpers for the NOAA alerts Flask application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from flask import Flask

from . import (
    routes_admin,
    routes_eas,
    routes_debug,
    routes_exports,
    routes_settings_radio,
    routes_led,
    routes_monitoring,
    routes_public,
    template_helpers,
)
from .routes import alert_verification, eas_compliance
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
    yield RouteModule("routes_monitoring", routes_monitoring.register)
    yield RouteModule("routes_alert_verification", alert_verification.register)
    yield RouteModule("routes_eas_compliance", eas_compliance.register)
    yield RouteModule("routes_eas_workflow", eas.register)
    yield RouteModule("routes_settings_radio", routes_settings_radio.register)
    yield RouteModule("routes_exports", routes_exports.register)
    yield RouteModule("routes_led", routes_led.register)
    yield RouteModule("routes_debug", routes_debug.register)
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
