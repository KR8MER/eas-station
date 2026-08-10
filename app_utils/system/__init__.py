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

"""System monitoring helpers.

This package was a single 2,580-line ``app_utils/system.py``.  The
``__init__`` is the compatibility shim: every name the module exposed to the
rest of the tree keeps resolving from ``app_utils.system``.

``DEVICE_TREE_CANDIDATES`` is deliberately *not* re-exported.  It is a mutable
list that tests replace with ``monkeypatch.setattr``; re-exporting it here
would make those patches silent no-ops, because ``device_tree`` reads the name
from its own globals.  Patch it on the module that reads it instead.
"""

from .badges import get_distro_logo_url, get_shields_io_badges
from .common import SystemHealth, _is_valid_temperature
from .device_tree import _collect_device_tree_details
from .disks import _detect_device_type, _nvme_controller_path
from .hardware import _collect_cpu_details, _collect_platform_details
from .smart import _collect_smart_health
from .smart_fields import (
    NVME_DATA_UNIT_BYTES,
    _extract_temperature,
    _populate_nvme_metrics,
)
from .snapshot import build_system_health_snapshot
from .temperature import _parse_temperature_value

__all__ = [
    "SystemHealth",
    "NVME_DATA_UNIT_BYTES",
    "build_system_health_snapshot",
    "get_distro_logo_url",
    "get_shields_io_badges",
    # Private helpers reached from outside the package:
    # `webapp/admin/api/routes_smart.py`
    # imports `_nvme_controller_path`, `scripts/diagnose_smart.sh` imports
    # `_collect_smart_health`, and the system-health tests exercise the
    # collectors directly.
    "_collect_cpu_details",
    "_collect_smart_health",
    "_collect_device_tree_details",
    "_collect_platform_details",
    "_detect_device_type",
    "_extract_temperature",
    "_is_valid_temperature",
    "_nvme_controller_path",
    "_parse_temperature_value",
    "_populate_nvme_metrics",
]
