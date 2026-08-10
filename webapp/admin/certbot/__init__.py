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

"""Certbot/SSL certificate management routes.

This package was a single 1,946-line ``webapp/admin/certbot.py``. It is split
by concern now, and this module keeps the old entry point: ``webapp/admin/
__init__.py`` still does ``from .certbot import register_certbot_routes``.

Layout::

    log             the one logger, named ``webapp.admin.certbot``
    paths           the writable certbot_data tree (created on import)
    blueprint       ``certbot_bp`` plus the domain/email patterns
    failures        certbot exit -> operator-readable explanation
    nginx           is nginx up, and bring it up
    staging         detect and clear Let's Encrypt staging certificates
    install         install an obtained certificate into nginx
    routes_*        the endpoints, grouped by operation

Dependencies run one way::

    log, blueprint                 leaves
    paths                  -> log
    failures               -> paths
    nginx                  -> log
    staging                -> log, paths
    install                -> log, nginx, paths
    routes_pages           -> blueprint, log
    routes_settings        -> blueprint, log
    routes_status          -> blueprint, log, paths
    routes_obtain          -> blueprint, log, paths
    routes_obtain_execute  -> blueprint, failures, install, log, nginx,
                              paths, staging
    routes_renew           -> blueprint, failures, log, paths, staging
    routes_actions         -> blueprint, install, log, paths

**A route module that stops being imported below disappears from the URL map
without raising anything.** The imports are the registration.
``tests/test_certbot_package.py`` asserts the full rule set.

**Importing this package creates directories.** ``paths`` calls
``_ensure_certbot_directories()`` at module scope, exactly as the single-file
module did at its line 191.

``__all__`` is unchanged. The internals — ``logger``, the ``CERTBOT_*``
directories, the helpers — are reached through the module that owns them
(``from webapp.admin.certbot.paths import CERTBOT_CONFIG_DIR``) rather than
mirrored here; nothing outside the package imported them from the single-file
module either.
"""

from . import (  # noqa: F401  - imported for their side effect of registering routes
    blueprint,
    failures,
    install,
    log,
    nginx,
    paths,
    routes_actions,
    routes_obtain,
    routes_obtain_execute,
    routes_pages,
    routes_renew,
    routes_settings,
    routes_status,
    staging,
)
from .blueprint import certbot_bp


def register_certbot_routes(app, logger):
    """Register Certbot admin routes with the Flask app.

    Routes are registered with url_prefix='/admin', so Flask combines them:
    - Blueprint route '/certbot' becomes '/admin/certbot'
    - Blueprint route '/api/certbot/settings' becomes '/admin/api/certbot/settings'

    IMPORTANT: Do NOT add '/admin' prefix to route decorators above, as Flask
    will combine url_prefix with the route path, resulting in doubled paths
    like '/admin/admin/certbot' which will cause 404 errors.
    """
    app.register_blueprint(certbot_bp, url_prefix='/admin')
    logger.info("Certbot admin routes registered")


__all__ = ['certbot_bp', 'register_certbot_routes']
