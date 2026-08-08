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

"""The /stats dashboard.

The route is only glue: every figure on the page is produced by a section in
``webapp/public/stats_sections/``, and each of those tolerates its own failure,
so the outer handler here catches only a failure of the assembly itself.
"""

from app_core.extensions import db
from flask import render_template

from .stats_sections import build_stats_data


def register(app, route_logger) -> None:
    """Attach the stats routes to the Flask app."""
    @app.route("/stats")
    def stats():
        try:
            return render_template("stats.html", **build_stats_data(route_logger))
        except Exception as exc:  # pragma: no cover - fallback content
            db.session.rollback()
            route_logger.error("Error loading statistics: %s", exc)
            return (
                "<h1>Error loading statistics</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )


__all__ = ["register"]
