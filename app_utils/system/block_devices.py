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

"""Block device inventory via lsblk."""

import json
import shutil
import subprocess
from typing import Any, Dict, List, Tuple

from .common import _safe_int, _to_bool


def _collect_block_devices(logger) -> Dict[str, Any]:
    """Use lsblk to inspect attached block devices."""

    result: Dict[str, Any] = {
        "available": False,
        "devices": [],
        "error": None,
        "summary": {"disks": 0, "partitions": 0, "virtual": 0},
    }

    lsblk_path = shutil.which("lsblk")
    if not lsblk_path:
        result["error"] = "lsblk utility not available"
        return result

    columns = [
        "NAME",
        "PATH",
        "TYPE",
        "SIZE",
        "MODEL",
        "SERIAL",
        "ROTA",
        "TRAN",
        "VENDOR",
        "RO",
        "RM",
        "MOUNTPOINT",
        "MOUNTPOINTS",
        "FSTYPE",
    ]

    try:
        completed = subprocess.run(
            [
                lsblk_path,
                "--bytes",
                "--json",
                "--output",
                ",".join(columns),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception as exc:  # pragma: no cover - depends on host configuration
        result["error"] = str(exc)
        if logger:
            logger.warning("Failed to execute lsblk: %s", exc)
        return result

    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        result["error"] = stderr or "lsblk returned a non-zero exit status"
        if logger:
            logger.warning("lsblk exited with status %s: %s", completed.returncode, result["error"])

    if not stdout:
        return result

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - host specific output
        result["error"] = f"Unable to parse lsblk output: {exc}"
        if logger:
            logger.warning("Unable to parse lsblk output: %s", exc)
        return result

    simplified_devices, summary = _simplify_block_devices(payload.get("blockdevices") or [])
    result["devices"] = simplified_devices
    result["summary"] = summary
    result["available"] = bool(simplified_devices)

    return result


def _simplify_block_devices(entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Normalize lsblk output into a compact, UI-friendly structure."""

    simplified: List[Dict[str, Any]] = []
    summary = {"disks": 0, "partitions": 0, "virtual": 0}

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        children_entries = entry.get("children") or []
        children, child_summary = _simplify_block_devices(children_entries)

        for key, value in child_summary.items():
            summary[key] = summary.get(key, 0) + value

        entry_type = (entry.get("type") or "").lower()
        if entry_type == "disk":
            summary["disks"] = summary.get("disks", 0) + 1
        elif entry_type == "part":
            summary["partitions"] = summary.get("partitions", 0) + 1
        elif entry_type in {"loop", "rom"}:
            summary["virtual"] = summary.get("virtual", 0) + 1

        mountpoints = entry.get("mountpoints")
        if mountpoints is None:
            mountpoint = entry.get("mountpoint")
            if mountpoint:
                mountpoints = [mountpoint]
            else:
                mountpoints = []

        if isinstance(mountpoints, str):
            mountpoints = [mountpoints]

        device = {
            "name": entry.get("name"),
            "path": entry.get("path"),
            "type": entry_type or None,
            "size_bytes": _safe_int(entry.get("size")),
            "model": entry.get("model"),
            "serial": entry.get("serial"),
            "vendor": entry.get("vendor"),
            "transport": entry.get("tran"),
            "is_rotational": _to_bool(entry.get("rota")),
            "is_read_only": _to_bool(entry.get("ro")),
            "is_removable": _to_bool(entry.get("rm")),
            "filesystem": entry.get("fstype"),
            "mountpoints": mountpoints if isinstance(mountpoints, list) else [],
            "children": children,
        }

        simplified.append(device)

    return simplified, summary
