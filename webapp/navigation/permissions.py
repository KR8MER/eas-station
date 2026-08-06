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


"""Permission-name shorthands used by the navigation registry.

Every name here must be a member of
``app_core.auth.roles.PermissionDefinition`` — ``tests/test_navigation_registry.py``
enforces that, because a typo would silently hide a page from every user.

Kept in its own module so ``registry.py`` and ``registry_settings.py`` share
one definition instead of each keeping a copy.
"""


ALERTS_VIEW = "alerts.view"
ALERTS_EXPORT = "alerts.export"
EAS_VIEW = "eas.view"
LOGS_VIEW = "logs.view"
RECEIVERS_VIEW = "receivers.view"
GPIO_VIEW = "gpio.view"
SYSTEM_VIEW_CONFIG = "system.view_config"
SYSTEM_CONFIGURE = "system.configure"
SYSTEM_VIEW_USERS = "system.view_users"
SYSTEM_MANAGE_USERS = "system.manage_users"


__all__ = [
    "ALERTS_EXPORT",
    "ALERTS_VIEW",
    "EAS_VIEW",
    "GPIO_VIEW",
    "LOGS_VIEW",
    "RECEIVERS_VIEW",
    "SYSTEM_CONFIGURE",
    "SYSTEM_MANAGE_USERS",
    "SYSTEM_VIEW_CONFIG",
    "SYSTEM_VIEW_USERS",
]
