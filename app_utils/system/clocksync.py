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

"""Clock/NTP drift collection for the system health snapshot.

SAME timing and RWT scheduling both depend on the system clock being
correct, but until now nothing surfaced drift as a monitored signal --
three separate ad-hoc ``timedatectl``/``chronyc`` callers existed
(``webapp/admin/health_endpoints.py``, ``webapp/routes_diagnostics.py``,
``webapp/admin/network.py``) but none fed the health snapshot or the alert
pipeline. This module is the one collector feeding both.
"""

import shutil
import subprocess
from typing import Any, Dict

from app_utils.chrony_parser import parse_chronyc_tracking_csv


def _collect_clock_sync(logger=None) -> Dict[str, Any]:
    """Best-effort clock synchronization status.

    Tries ``chronyc -c tracking`` first (gives a precise offset); falls
    back to ``timedatectl show -p NTPSynchronized --value`` (gives only a
    yes/no) when chrony isn't installed or isn't running. Never raises --
    mirrors the shape of ``_collect_smart_health`` in
    ``app_utils/system/smart.py``.
    """
    result: Dict[str, Any] = {
        "available": False,
        "synchronized": None,
        "offset_seconds": None,
        "source": None,
        "stratum": None,
        "method": None,
        "error": None,
    }

    chronyc_path = shutil.which("chronyc")
    if chronyc_path:
        try:
            proc = subprocess.run(
                [chronyc_path, "-c", "tracking"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                parsed = parse_chronyc_tracking_csv(proc.stdout)
                leap_status = (parsed.get("leap_status") or "").strip()
                result["available"] = True
                result["method"] = "chronyc"
                result["synchronized"] = "not synchronised" not in leap_status.lower()
                result["offset_seconds"] = parsed.get("system_time_offset_s")
                result["source"] = parsed.get("reference_id_name") or None
                result["stratum"] = parsed.get("stratum")
                return result
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["error"] = f"chronyc failed: {exc}"

    timedatectl_path = shutil.which("timedatectl")
    if timedatectl_path:
        try:
            proc = subprocess.run(
                [timedatectl_path, "show", "-p", "NTPSynchronized", "--value"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                result["available"] = True
                result["method"] = "timedatectl"
                result["synchronized"] = proc.stdout.strip().lower() == "yes"
                return result
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["error"] = f"timedatectl failed: {exc}"

    if result["error"] is None:
        result["error"] = "Neither chronyc nor timedatectl is available on this host"
    return result


__all__ = ["_collect_clock_sync"]
