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

"""Device-tree probing for single-board computers."""

import contextlib
from pathlib import Path
from typing import Any, Dict, List, Optional

DEVICE_TREE_CANDIDATES = [
    Path("/proc/device-tree"),
    Path("/sys/firmware/devicetree/base"),
]


def _collect_device_tree_details() -> Dict[str, Any]:
    """Gather platform metadata from device-tree files on ARM systems."""

    base: Optional[Path] = None
    for candidate in DEVICE_TREE_CANDIDATES:
        if candidate.exists():
            base = candidate
            break

    if base is None:
        return {}

    details: Dict[str, Any] = {}

    model = _safe_read_device_tree_text(base / "model")
    if model:
        details.setdefault("product_name", model)
        details.setdefault("board_name", model)
        if "raspberry" in model.lower():
            details.setdefault("sys_vendor", "Raspberry Pi Foundation")

    serial = _safe_read_device_tree_text(base / "serial-number")
    if serial:
        details.setdefault("product_serial", serial)

    revision = _safe_read_device_tree_revision(base / "system/linux,revision")
    if revision:
        details.setdefault("product_version", revision)
        details.setdefault("board_version", revision)

    compatible = _safe_read_device_tree_compatible(base / "compatible")
    if compatible:
        details.setdefault("compatible", compatible)

    return details


def _safe_read_device_tree_text(path: Path) -> Optional[str]:
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        data = path.read_bytes()
        if not data:
            return None
        text = data.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
        if text and text.lower() not in {"", "none", "unknown", "not specified"}:
            return text
    return None


def _safe_read_device_tree_revision(path: Path) -> Optional[str]:
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        data = path.read_bytes()
        if not data:
            return None
        if len(data) in {4, 8}:
            value = int.from_bytes(data[:4], byteorder="big", signed=False)
            if value:
                return f"0x{value:08x}"
        text = data.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
        if text:
            return text
    return None


def _safe_read_device_tree_compatible(path: Path) -> Optional[List[str]]:
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        data = path.read_bytes()
        if not data:
            return None
        parts = [
            part.decode("utf-8", errors="ignore").strip()
            for part in data.split(b"\x00")
            if part.strip()
        ]
        cleaned = [part for part in parts if part and part.lower() not in {"none", "unknown"}]
        if cleaned:
            return cleaned
    return None
