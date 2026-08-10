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

"""``/api/smart_diag`` — SMART disk health for the diagnostics page."""

import json

from flask import jsonify

from .blueprint import api_bp


@api_bp.route('/api/smart_diag')
def api_smart_diag():
    """Diagnostic endpoint: shows raw smartctl JSON output for debugging."""
    import shutil
    import subprocess as _sp

    from app_utils.system import _nvme_controller_path

    smartctl_path = shutil.which("smartctl") or "/usr/sbin/smartctl"

    # ── Gather smartctl version ──
    smartctl_version = None
    try:
        ver = _sp.run(
            ["sudo", "-n", smartctl_path, "--version"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        first_line = (ver.stdout or "").split("\n", 1)[0].strip()
        if first_line:
            smartctl_version = first_line
    except Exception:
        pass

    # ── Discover disks via lsblk ──
    try:
        lsblk = _sp.run(
            ["lsblk", "--json", "--output", "NAME,PATH,TYPE,TRAN"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        lsblk_data = json.loads(lsblk.stdout or "{}")
    except Exception as exc:
        return jsonify({"error": f"lsblk failed: {exc}"})

    block_devs = lsblk_data.get("blockdevices") or []

    def _find_disks(entries):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if (entry.get("type") or "").lower() == "disk":
                name = entry.get("name") or ""
                if not name.startswith(("ram", "loop", "zram")):
                    yield entry
            for child in entry.get("children") or []:
                yield from _find_disks([child])

    def _run_smartctl(cmd):
        """Run a smartctl command and return a diagnostic dict."""
        attempt: dict = {"command": " ".join(cmd)}
        try:
            result = _sp.run(cmd, capture_output=True, text=True, check=False, timeout=15)
            attempt["exit_code"] = result.returncode
            attempt["stderr"] = (result.stderr or "").strip()[:500]
            raw = (result.stdout or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    attempt["json_keys"] = sorted(parsed.keys())
                    attempt["has_nvme_health_log"] = "nvme_smart_health_information_log" in parsed
                    attempt["has_temperature"] = "temperature" in parsed
                    attempt["has_smart_status"] = "smart_status" in parsed
                    # Surface smartctl messages (error/warning reasons)
                    sc = parsed.get("smartctl")
                    if isinstance(sc, dict):
                        msgs = sc.get("messages")
                        if msgs:
                            attempt["smartctl_messages"] = msgs
                    nvme_log = parsed.get("nvme_smart_health_information_log")
                    if isinstance(nvme_log, dict):
                        attempt["nvme_log_keys"] = sorted(nvme_log.keys())
                        attempt["nvme_log_sample"] = {
                            k: nvme_log.get(k)
                            for k in [
                                "temperature", "power_on_hours", "percentage_used",
                                "available_spare", "data_units_written", "power_cycles",
                            ]
                            if k in nvme_log
                        }
                except json.JSONDecodeError:
                    attempt["raw_output_start"] = raw[:500]
            else:
                attempt["raw_output_start"] = "(empty)"
        except Exception as exc:
            attempt["error"] = str(exc)
        return attempt

    devices_output: list = []

    for disk in _find_disks(block_devs):
        path = disk.get("path") or f"/dev/{disk.get('name')}"
        name = disk.get("name") or ""
        tran = (disk.get("tran") or "").lower()
        is_nvme = "nvme" in name or tran == "nvme"

        diag: dict = {
            "path": path,
            "name": name,
            "transport": tran,
            "is_nvme": is_nvme,
        }

        if is_nvme:
            # NVMe devices: try multiple strategies to find what works.
            # Different smartctl versions / kernels / platforms need
            # different path + flag combinations.
            controller_path = _nvme_controller_path(path)
            strategies = [
                (path,            "nvme"),   # namespace + -d nvme
                (controller_path, "nvme"),   # controller + -d nvme
                (path,            "auto"),   # namespace + -d auto
                (path,            None),     # namespace, no -d flag
            ]
            # Deduplicate when controller == namespace
            seen = set()
            diag["attempts"] = []
            for dev_path, d_flag in strategies:
                key = (dev_path, d_flag)
                if key in seen:
                    continue
                seen.add(key)
                cmd = ["sudo", "-n", smartctl_path]
                if d_flag:
                    cmd.extend(["-d", d_flag])
                cmd.extend(["--json", "-a", dev_path])
                diag["attempts"].append(_run_smartctl(cmd))
        else:
            cmd = ["sudo", "-n", smartctl_path, "-d", "auto", "--json", "-a", path]
            diag["attempts"] = [_run_smartctl(cmd)]

        devices_output.append(diag)

    return jsonify({
        "smartctl_version": smartctl_version,
        "devices": devices_output,
    })
