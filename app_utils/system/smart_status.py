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

"""Deriving a device's overall SMART health status from its smartctl report."""

from typing import Any, Dict, Optional, Tuple

from .common import _coerce_int


def _derive_overall_status(
    report: Dict[str, Any], exit_code: int, path: str, logger
) -> Tuple[str, Optional[str]]:
    """Return ``(overall_status, error_message)``.

    Prefers smartctl's own ``smart_status`` verdict. Falls back to inferring
    health from the exit code only when smartctl didn't report one.

    smartctl exit code bits, per its own man page: bit 0 = command line did
    not parse, bit 1 = device open failed or SMART command set unsupported,
    bit 2 = a SMART/ATA command to the disk failed, bit 3 = DISK FAILING,
    bit 4 = prefail attrs <= threshold, bit 5 = usage attrs <= threshold,
    bit 6 = error log has errors, bit 7 = self-test log has errors.

    Bits 0-2 mean smartctl never actually got real SMART data at all —
    there is nothing here to call "passed". Before this check existed, that
    case fell straight through to "bits 3-7 are clear -> passed", which is
    how a virtio-blk-backed cloud VM (no ATA/NVMe protocol between guest and
    host at all, so every device-type probe returns exit code 2 with a
    mostly empty but validly-parsing JSON report) ended up reported as a
    healthy drive despite smartctl never having successfully talked to
    anything.
    """

    smart_status = report.get("smart_status") or {}
    passed = smart_status.get("passed")
    if passed is True:
        return "passed", None
    if passed is False:
        return "failed", None

    status_text = smart_status.get("status") or smart_status.get("string")
    if status_text:
        return str(status_text), None

    overall_status = "unknown"
    error = None

    execution_failed_bits = exit_code & 0x07  # bits 0-2: no real data at all
    disk_failing_bits = exit_code & 0x18  # bits 3-4: critical failures
    disk_problem_bits = exit_code & 0xF8  # bits 3-7: any disk issues

    if execution_failed_bits:
        smartctl_messages = [
            msg["string"]
            for msg in (report.get("smartctl") or {}).get("messages") or []
            if isinstance(msg, dict) and msg.get("string")
        ]
        error = "; ".join(smartctl_messages) or (
            f"smartctl could not query this device (exit code {exit_code}) -- "
            "SMART data unavailable. Common on virtualized/cloud block storage "
            "(e.g. virtio-blk) where the guest has no ATA/NVMe protocol to the "
            "underlying disk at all."
        )
    else:
        nvme_info = report.get("nvme_smart_health_information_log")
        if isinstance(nvme_info, dict):
            # NVMe: use critical_warning field as authoritative source.
            critical_warning = _coerce_int(nvme_info.get("critical_warning"))
            if critical_warning is not None:
                overall_status = "failed" if critical_warning != 0 else "passed"
            elif disk_problem_bits == 0:
                overall_status = "passed"
        elif disk_failing_bits:
            # ATA/SATA with critical failure bits set.
            overall_status = "failed"
        elif disk_problem_bits == 0:
            # No disk problem bits set and we parsed valid data.
            overall_status = "passed"

    if logger:
        if overall_status != "unknown":
            logger.debug(
                "Inferred SMART status '%s' for %s from exit code %d",
                overall_status, path, exit_code,
            )
        elif exit_code == 0:
            logger.debug(
                "SMART status unavailable for %s despite successful smartctl execution", path,
            )

    return overall_status, error
