from __future__ import annotations

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

Status page and entry point for pgweb (https://github.com/sosedoff/pgweb),
an optional third-party PostgreSQL browser an operator can install for
ad-hoc query access to the database -- see docs/guides/DATABASE_BROWSER.md.

pgweb has no authentication of its own. Its systemd unit
(systemd/eas-station-pgweb.service) binds it to 127.0.0.1 only; the *only*
supported way to reach it is the authenticated nginx proxy on port 8081
(the `listen 8081` server block in config/nginx-eas-station.conf, gated by
/api/internal/pgweb-auth-check -- app.py), which requires a logged-in
session with system.configure, the same permission this page itself
requires. This module doesn't proxy or embed pgweb -- it only reports
whether the service is installed/running and links to that authenticated
port, so the actual database traffic goes straight through nginx rather
than through this Flask process.
"""

import logging
import subprocess

from flask import Blueprint, render_template, request

from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission

logger = logging.getLogger(__name__)

database_browser_bp = Blueprint(
    "database_browser", __name__, url_prefix="/admin/database-browser"
)

# The port the authenticated nginx proxy listens on -- see the `listen 8081`
# server block config/nginx-eas-station.conf ships. Not user-configurable
# here: changing it means editing that file (and re-deploying nginx) too.
_PGWEB_PROXY_PORT = 8081


def _service_active(unit: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("systemctl is-active %s failed: %s", unit, exc)
        return False


def _database_browser_status() -> dict:
    pgweb_running = _service_active("eas-station-pgweb.service")
    # Best-effort only -- confirms the unit *exists* so "not installed" can
    # be told apart from "installed but stopped". A host without systemd
    # (never true for this project's supported deployment target, but this
    # keeps the check itself from ever raising) falls back to "unknown".
    try:
        list_result = subprocess.run(
            ["systemctl", "list-unit-files", "eas-station-pgweb.service"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pgweb_installed = "eas-station-pgweb.service" in (list_result.stdout or "")
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("systemctl list-unit-files failed: %s", exc)
        pgweb_installed = pgweb_running

    host = (request.host or "").split(":", 1)[0] or "localhost"
    return {
        "installed": pgweb_installed,
        "running": pgweb_running,
        "proxy_url": f"https://{host}:{_PGWEB_PROXY_PORT}/",
    }


@database_browser_bp.route("/", methods=["GET"])
@require_auth
@require_permission("system.configure")
def database_browser_page():
    return render_template(
        "admin/database_browser.html", status=_database_browser_status()
    )


def register_database_browser_routes(app, logger_):
    app.register_blueprint(database_browser_bp)
    logger_.info("Database browser status routes registered")
