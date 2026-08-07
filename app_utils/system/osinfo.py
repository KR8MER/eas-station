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

"""Operating system and virtualization detection."""

import contextlib
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .common import _safe_read_text


def _collect_operating_system_details() -> Dict[str, Any]:
    """Return distribution and kernel metadata for the host."""

    details: Dict[str, Any] = {
        "distribution": None,
        "distribution_version": None,
        "distribution_codename": None,
        "distribution_id": None,
        "distribution_like": None,
        "os_pretty_name": None,
        "kernel": platform.system(),
        "kernel_release": platform.release(),
        "kernel_version": platform.version(),
        "virtualization": None,
    }

    os_release_path = Path("/etc/os-release")
    release_data: Dict[str, str] = {}
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        content = os_release_path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().upper()
            if not key:
                continue
            value = value.strip().strip('"')
            release_data[key] = value

    if release_data:
        details["os_pretty_name"] = release_data.get("PRETTY_NAME") or None
        details["distribution"] = release_data.get("NAME") or None
        details["distribution_id"] = release_data.get("ID") or None
        details["distribution_version"] = (
            release_data.get("VERSION_ID") or release_data.get("VERSION") or None
        )
        details["distribution_codename"] = release_data.get("VERSION_CODENAME") or None
        details["distribution_like"] = release_data.get("ID_LIKE") or None

    virtualization = _detect_virtualization_environment()
    if virtualization:
        details["virtualization"] = virtualization

    return details


def _detect_virtualization_environment() -> Optional[str]:
    """Attempt to detect virtualization technology in use."""

    detect_path = shutil.which("systemd-detect-virt")
    if detect_path:
        try:
            completed = subprocess.run(
                [detect_path],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except Exception:  # pragma: no cover - host specific behaviour
            completed = None
        else:
            if completed:
                output = (completed.stdout or "").strip()
                if output and output.lower() != "none":
                    return output

    product_name = _safe_read_text(Path("/sys/class/dmi/id/product_name"))
    system_vendor = _safe_read_text(Path("/sys/class/dmi/id/sys_vendor"))

    virtualization_markers = (
        (product_name or "", "product"),
        (system_vendor or "", "vendor"),
    )
    known_labels = (
        ("virtualbox", "VirtualBox"),
        ("vmware", "VMware"),
        ("kvm", "KVM"),
        ("qemu", "QEMU"),
        ("hyper-v", "Hyper-V"),
        ("xen", "Xen"),
        ("parallels", "Parallels"),
        ("bhyve", "bhyve"),
    )

    for raw_value, _source in virtualization_markers:
        lowered = raw_value.lower() if raw_value else ""
        for marker, label in known_labels:
            if marker in lowered:
                return label

    cpuinfo_path = Path("/proc/cpuinfo")
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        content = cpuinfo_path.read_text(encoding="utf-8", errors="ignore")
        if "hypervisor" in content.lower():
            return "Hypervisor detected"

    return None
