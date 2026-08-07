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

"""Public and operator-facing pages, split by surface.

webapp/routes_public.py was a single 2,849-line module whose entire body
was one 2,779-line register() function.  Every route handler was nested
inside it, closing over just app and route_logger, so the surfaces —
landing pages, sitemap, stats, alerts, logs — could not be read or tested
apart from one another.

Each surface now owns a module exposing its own register(app,
route_logger).  The handler bodies moved verbatim: they stay nested inside
a register, just a much smaller one, so no reindentation or rebinding was
needed.  webapp/routes_public.py remains as a shim re-exporting
register so webapp/__init__.py is unchanged.
"""

from pathlib import Path

from flask import Flask

from webapp.public import alerts, logs, logs_data, pages, sitemap, stats


def register(app: Flask, logger) -> None:
    """Attach public and operator-facing pages to the Flask app."""

    route_logger = logger.getChild("routes_public")
    policy_docs_root = Path(app.root_path) / "docs" / "policies"

    pages.register(app, route_logger, policy_docs_root)
    sitemap.register(app, route_logger)
    stats.register(app, route_logger)
    alerts.register(app, route_logger)
    logs.register(app, route_logger, logs_data.build_logs_loader(route_logger))


__all__ = ["register"]
