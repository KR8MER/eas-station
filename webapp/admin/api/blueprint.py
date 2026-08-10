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

"""The shared ``api_bp`` blueprint.

Every route module in this package decorates its handlers with the blueprint
defined here, and ``register_api_routes`` in the package ``__init__`` attaches
the logger to it before registering it on the app. It lives in its own module
so that importing the blueprint cannot pull in a route module — which would
make the side-effect import order in ``__init__`` significant.

``import_name`` stays ``webapp.admin.api``, the value the single-file module
gave it. Flask resolves a blueprint's root path from ``import_name``, so using
this module's own ``__name__`` would have quietly changed it.
"""

from flask import Blueprint


# Create Blueprint for API routes
#
# ``__package__`` is ``webapp.admin.api`` here, which is what
# ``__name__`` was in the single-file module. Passing this module's
# ``__name__`` instead would silently move the blueprint's root path
# down to ``webapp/admin/api/blueprint`` — pinned by
# tests/test_api_package.py.
api_bp = Blueprint('api', __package__)
