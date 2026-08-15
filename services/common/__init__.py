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

"""Shared bootstrap helpers for every split hardware service."""

from services.common.bootstrap import (
    configure_logging,
    init_database,
    init_runtime,
    install_service_auth,
    install_signal_handlers,
    load_environment,
    get_redis,
)
from services.common.metrics import (
    publish_displays_metrics,
    publish_gpio_metrics,
    publish_gps_metrics,
    publish_network_metrics,
    publish_zigbee_metrics,
)

__all__ = [
    "configure_logging",
    "init_database",
    "init_runtime",
    "install_service_auth",
    "install_signal_handlers",
    "load_environment",
    "get_redis",
    "publish_displays_metrics",
    "publish_gpio_metrics",
    "publish_gps_metrics",
    "publish_network_metrics",
    "publish_zigbee_metrics",
]
