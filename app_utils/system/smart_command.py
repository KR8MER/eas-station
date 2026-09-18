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

"""Locating the smartctl binary and building its command line."""

import os
import shutil
from typing import List, Optional


def _find_smartctl_path(logger=None) -> Optional[str]:
    """Locate the smartctl binary via PATH, falling back to common install
    locations that may not be on PATH for the invoking process (e.g. a web
    worker running as a non-root user)."""

    smartctl_path = shutil.which("smartctl")
    if not smartctl_path:
        for candidate in (
            "/usr/sbin/smartctl",
            "/sbin/smartctl",
            "/usr/local/sbin/smartctl",
        ):
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                smartctl_path = candidate
                break
    return smartctl_path


def _build_smartctl_command(
    smartctl_path: str, device_type_flag: Optional[str], query_path: str
) -> List[str]:
    """Build the smartctl invocation for one device.

    Check if we need sudo (smartctl requires root access to read device
    data). If ``smartctl_path`` doesn't start with /usr or /sbin, or if we're
    not root, use sudo.
    """

    use_sudo = os.geteuid() != 0 if hasattr(os, "geteuid") else True

    command = []
    if use_sudo:
        # -n means don't prompt for password
        command.extend(["sudo", "-n"])

    command.append(smartctl_path)

    # Add device type flag first (must come before other flags for some
    # smartctl versions).
    if device_type_flag:
        command.extend(["-d", device_type_flag])

    # -a (all) = -H -i -c -A -l error -l selftest: provides complete device
    # info, capabilities, attributes, and health status. Using -a instead of
    # just -H -A ensures NVMe health logs and ATA attributes are both fully
    # populated in the JSON output.
    command.extend(["--json", "-a"])

    # The -n standby flag is for ATA/SATA devices to skip devices in standby
    # mode. Only add this flag for devices explicitly detected as 'ata' or
    # 'sat' type — NVMe devices don't support standby the same way, and
    # auto-detected devices may be USB/SCSI/other types that reject it with
    # "invalid argument".
    if device_type_flag and device_type_flag in ("ata", "sat"):
        command.extend(["-n", "standby"])

    command.append(query_path)

    return command
