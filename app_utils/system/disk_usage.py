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

"""Per-partition disk usage snapshot.

Distinct from ``block_devices.py`` / ``disks.py``, which enumerate physical
block devices for SMART health — this module reports mounted-filesystem
capacity, the figures the dashboard's disk-usage cards show.
"""

from typing import Any, Dict, List

import psutil


def _collect_disk_info() -> List[Dict[str, Any]]:
    """Sample capacity for every mounted partition.

    Falls back to the usage of ``/`` alone if the partition table itself
    cannot be enumerated (some sandboxed/containerized environments deny
    this). A partition that denies a usage query once the table is known is
    skipped rather than aborting the whole collection.
    """

    disk_info: List[Dict[str, Any]] = []
    try:
        partitions = psutil.disk_partitions()
        for partition in partitions:
            try:
                partition_usage = psutil.disk_usage(partition.mountpoint)
                disk_info.append(
                    {
                        "device": partition.device,
                        "mountpoint": partition.mountpoint,
                        "fstype": partition.fstype,
                        "total": partition_usage.total,
                        "used": partition_usage.used,
                        "free": partition_usage.free,
                        "percentage": (partition_usage.used / partition_usage.total) * 100,
                    }
                )
            except PermissionError:
                continue
    except Exception:
        disk_usage = psutil.disk_usage("/")
        disk_info.append(
            {
                "device": "/",
                "mountpoint": "/",
                "fstype": "unknown",
                "total": disk_usage.total,
                "used": disk_usage.used,
                "free": disk_usage.free,
                "percentage": (disk_usage.used / disk_usage.total) * 100,
            }
        )

    return disk_info
