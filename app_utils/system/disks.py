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

"""Disk enumeration and device-type detection."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _iter_disk_devices(devices: List[Dict[str, Any]]):
    for device in devices:
        if not isinstance(device, dict):
            continue
        device_type = (device.get("type") or "").lower()
        name = device.get("name") or ""
        # Skip virtual/RAM devices that don't support SMART
        if device_type == "disk" and not name.startswith(("ram", "loop", "zram")):
            yield device
        for child in device.get("children") or []:
            yield from _iter_disk_devices([child])


def _detect_device_type(device: Dict[str, Any], path: str, logger) -> Optional[str]:
    """Detect the device type and return appropriate smartctl -d flag value.

    Returns the ``-d`` value for smartctl, or ``"auto"`` to let smartctl
    probe the device itself.  Never returns ``None`` — every block device
    gets a chance to report SMART data because some PCIe NVMe drives on
    Raspberry Pi appear as ``mmcblk`` rather than ``nvme``.
    """

    name = device.get("name") or ""
    transport = (device.get("transport") or "").lower()

    # ── Explicit NVMe detection ──
    if name.startswith("nvme") or transport == "nvme" or "nvme" in path.lower():
        return "nvme"

    # ── PCIe-attached storage (e.g. Raspberry Pi 5 NVMe hat) ──
    # On the Pi 5 an NVMe SSD on the PCIe bus can appear as /dev/mmcblk* with
    # transport "" or "pcie".  Also check the sysfs NVMe path as a hint.
    if transport in ("pcie", "pci"):
        # Almost certainly NVMe behind a PCIe bridge
        return "nvme"

    # Check sysfs for NVMe backing — covers mmcblk devices backed by NVMe
    try:
        sysfs_link = Path(f"/sys/block/{name}").resolve()
        sysfs_str = str(sysfs_link).lower()
        if "nvme" in sysfs_str or "pci" in sysfs_str:
            if logger:
                logger.debug(
                    "Detected PCIe/NVMe backing for %s via sysfs: %s",
                    path, sysfs_link,
                )
            return "nvme"
    except Exception:
        pass

    # ── Known transports ──
    if transport in ("usb", "usb-storage"):
        return "auto"
    if transport in ("sata", "scsi", "ata"):
        return "auto"

    # ── Fall-through: let smartctl auto-detect ──
    # This includes mmcblk devices where we couldn't confirm NVMe backing.
    # smartctl will gracefully fail for true SD cards.
    return "auto"


def _nvme_controller_path(path: str) -> str:
    """Convert an NVMe namespace path to its controller path.

    smartctl requires the controller character device (e.g. ``/dev/nvme0``)
    rather than the namespace block device (e.g. ``/dev/nvme0n1``) to
    retrieve SMART data.  If *path* doesn't match the namespace pattern it
    is returned unchanged.
    """
    m = re.match(r'^(/dev/nvme\d+)n\d+', path)
    return m.group(1) if m else path
