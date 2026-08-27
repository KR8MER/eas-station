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

"""REST-style API routes used by the admin interface.

This package was a single 2,105-line ``webapp/admin/api.py``. It is split by
resource now, and this module keeps the old entry point: ``webapp/admin/
__init__.py`` still does ``from .api import register_api_routes``.

Layout:

    blueprint              the shared ``api_bp``
    county                 the county-wide heuristic and location terms
    hostinfo               host CPU / IP readings for the status endpoint
    motion                 the NWS storm-motion parameter parser
    display_data           one alert flattened for the detail views
    routes_*               the endpoints, grouped by resource

Dependencies run one way::

    blueprint, county, hostinfo, motion       leaves
    display_data           -> motion
    routes_geometry        -> blueprint, county
    routes_alert_detail    -> blueprint, county, display_data
    routes_alert_export    -> blueprint, display_data
    routes_alerts_list     -> blueprint, county
    routes_boundaries      -> blueprint
    routes_system          -> blueprint, hostinfo
    routes_system_history  -> blueprint
    routes_smart           -> blueprint

**A route module that stops being imported below disappears from the URL map
without raising anything.** The imports are the registration; they are not
decoration. ``tests/test_api_package.py`` asserts the full rule set so a
dropped import fails loudly instead of 404-ing in production.

**Patching module state from a test targets the submodule, not this package.**
Rebinding a name here does not change what a submodule sees in its own
globals, so ``monkeypatch.setattr(api.hostinfo, "_last_cpu_sample_value", …)``
is the form that works.

Only ``register_api_routes`` is re-exported. The private helpers are reached
through the module that owns them — ``from webapp.admin.api.county import
_detect_county_wide`` — rather than being mirrored here; nothing outside the
package imported them from the single-file module either.
"""

from . import (  # noqa: F401  - imported for their side effect of registering routes
    blueprint,
    county,
    display_data,
    hostinfo,
    motion,
    routes_alert_detail,
    routes_alert_export,
    routes_alerts_list,
    routes_boundaries,
    routes_geometry,
    routes_radar_loop,
    routes_smart,
    routes_system,
    routes_system_history,
)
from .blueprint import api_bp


def register_api_routes(app, logger):
    """Attach JSON API endpoints used by the admin UI."""

    # Store logger for use by routes
    api_bp.logger = logger

    # Register the blueprint with the app
    app.register_blueprint(api_bp)
    logger.info("API routes registered")


__all__ = ['register_api_routes']
