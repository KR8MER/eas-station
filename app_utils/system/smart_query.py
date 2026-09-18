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

"""Running smartctl and validating its output."""

import json
import subprocess
from typing import Any, Dict, List, Optional, Tuple


def _query_smartctl(
    command: List[str], path: str, logger, timeout: int = 15
) -> Tuple[Optional[subprocess.CompletedProcess], Optional[str]]:
    """Run smartctl. Returns ``(completed_process, error_message)`` — exactly
    one of the two is non-``None``."""

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return completed, None
    except subprocess.TimeoutExpired:  # pragma: no cover - depends on hardware
        if logger:
            logger.warning("smartctl timeout for %s", path)
        return None, "smartctl query timed out (device may be sleeping or unresponsive)"
    except PermissionError:  # pragma: no cover - depends on user permissions
        if logger:
            logger.warning("smartctl permission denied for %s", path)
        return None, "Permission denied (may require root/sudo privileges)"
    except Exception as exc:  # pragma: no cover - depends on host configuration
        if logger:
            logger.warning("smartctl failed for %s: %s", path, exc)
        return None, f"smartctl execution failed: {str(exc)}"


def _validate_smartctl_output(
    completed: subprocess.CompletedProcess, path: str, logger
) -> Tuple[Optional[Dict[str, Any]], List[str], Optional[str]]:
    """Validate smartctl's exit code and stdout, then parse the JSON report.

    Returns ``(report, report_keys, error_message)``. ``report`` is ``None``
    exactly when ``error_message`` is set; ``report_keys`` is ``[]`` in that
    case.

    smartctl exit codes are a bitmask: bit 0 = command line error, bit 1 =
    device open failed, bit 2 = SMART command failed, bits 3-7 indicate disk
    problems (handled by ``_derive_overall_status``, not here).
    """

    raw_output = (completed.stdout or "").strip()
    stderr_output = (completed.stderr or "").strip()

    # Log stderr for debugging, but don't necessarily treat it as an error.
    if stderr_output and logger:
        logger.debug("smartctl stderr for %s: %s", path, stderr_output)

    if completed.returncode != 0 and not raw_output:
        if completed.returncode & 1:
            error_msg = "Invalid command line arguments"
        elif completed.returncode & 2:
            error_msg = "Device open failed (device may be unavailable or requires elevated privileges)"
        elif completed.returncode & 4:
            error_msg = "SMART command failed (device may not support SMART)"
        else:
            error_msg = stderr_output if stderr_output else f"smartctl exited with code {completed.returncode}"
        if logger:
            logger.info("SMART not available for %s: %s", path, error_msg)
        return None, [], error_msg

    if not raw_output:
        if logger:
            logger.debug("No smartctl output for %s", path)
        return None, [], "No data returned from smartctl"

    try:
        report = json.loads(raw_output)
    except json.JSONDecodeError as exc:  # pragma: no cover - host specific output
        if logger:
            logger.warning("Unable to parse smartctl output for %s: %s", path, exc)
        return None, [], f"Unable to parse smartctl output: {exc}"

    # Diagnostic: log which top-level JSON keys smartctl returned so we can
    # quickly identify missing sections when debugging attribute extraction
    # failures.
    report_keys = sorted(report.keys()) if isinstance(report, dict) else []
    has_nvme_log = "nvme_smart_health_information_log" in report_keys
    has_temperature = "temperature" in report_keys
    has_ata_attrs = "ata_smart_attributes" in report_keys
    if logger:
        logger.debug(
            "smartctl JSON for %s: keys=%s nvme_log=%s temp=%s ata_attrs=%s",
            path, report_keys, has_nvme_log, has_temperature, has_ata_attrs,
        )

    return report, report_keys, None
