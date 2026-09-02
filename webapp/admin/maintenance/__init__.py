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

"""Admin maintenance routes: backup, upgrade, database, alerts, EAS settings.

This package was a single 1,802-line ``webapp/admin/maintenance.py``. It is
split by concern now, and this module keeps the old entry point:
``webapp/admin/__init__.py`` still does ``from .maintenance import
register_maintenance_routes``.

Layout::

    blueprint       ``maintenance_bp``
    paths           ``repo_root`` — the tools scripts and .env live under it
    noaa            the api.weather.gov client behind the manual import
    serialization   a CAP alert row rendered for the admin views
    operations      backup/upgrade progress state and its lock
    eas_settings    ensuring the singleton EAS settings row
    routes_*        the endpoints, grouped by concern

Dependencies run one way::

    blueprint, paths, operations, eas_settings   leaves
    noaa                  -> (its own constants)
    serialization         -> (its own helper)
    routes_operations     -> blueprint, operations, paths
    routes_upgrade_progress -> blueprint
    routes_database       -> blueprint
    routes_env            -> blueprint, paths
    routes_poll           -> blueprint
    routes_location       -> blueprint
    routes_import         -> blueprint, noaa
    routes_alerts         -> blueprint, noaa, serialization
    routes_expiry         -> blueprint
    routes_eas_settings   -> blueprint, eas_settings

**A route module that stops being imported below disappears from the URL map
without raising anything.** The imports are the registration.
``tests/test_maintenance_package.py`` asserts the full rule set.

**``get_operation_status`` is re-exported even though it is a route handler
and is not in ``__all__``.** ``app_core/websocket_push.py`` imports it by name
to feed the admin operation-status push. That import is inside a function and
the caller logs and moves on, so losing it would have gone unnoticed — the
same shape as the ``AudioSourceConfigDB`` regression the audio_ingest split
caused. A test derives the required names from the tree so this cannot drift.
"""

from . import (  # noqa: F401  - imported for their side effect of registering routes
    blueprint,
    eas_settings,
    noaa,
    operations,
    paths,
    routes_alerts,
    routes_database,
    routes_eas_settings,
    routes_env,
    routes_expiry,
    routes_import,
    routes_location,
    routes_operations,
    routes_poll,
    routes_upgrade_progress,
    serialization,
)
from .blueprint import maintenance_bp
from .noaa import (
    NOAA_ALLOWED_QUERY_PARAMS,
    NOAA_API_BASE_URL,
    NOAA_USER_AGENT,
    NOAAImportError,
    build_noaa_alert_request,
    format_noaa_timestamp,
    normalize_manual_import_datetime,
    retrieve_noaa_alerts,
)
# Not in __all__, but app_core/websocket_push.py imports it by name.
from .routes_operations import get_operation_status  # noqa: F401
from .serialization import serialize_admin_alert


def register_maintenance_routes(app, logger):
    """Attach administrative maintenance endpoints to the Flask app."""

    # Register the blueprint with the app
    app.register_blueprint(maintenance_bp)
    logger.info("Maintenance routes registered")


__all__ = [
"NOAAImportError",
"NOAA_API_BASE_URL",
"NOAA_ALLOWED_QUERY_PARAMS",
"NOAA_USER_AGENT",
"build_noaa_alert_request",
"format_noaa_timestamp",
"normalize_manual_import_datetime",
"register_maintenance_routes",
"retrieve_noaa_alerts",
"serialize_admin_alert",
]
