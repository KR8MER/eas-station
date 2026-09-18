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

"""SMART/NVMe disk health collection."""

from typing import Any, Dict, List, Optional

from .disks import _detect_device_type, _iter_disk_devices, _nvme_controller_path
from .smart_attributes import (
    _populate_identity_fields,
    _populate_nvme_extended_fields,
    _populate_smart_attributes,
)
from .smart_command import _build_smartctl_command, _find_smartctl_path
from .smart_query import _query_smartctl, _validate_smartctl_output
from .smart_status import _derive_overall_status


def _device_result_skeleton(device: Dict[str, Any], path: str) -> Dict[str, Any]:
    """The full set of keys a device result may carry, defaulted so every
    device in the response has the same shape regardless of how far the
    query got."""

    return {
        "name": device.get("name"),
        "path": path,
        "model": device.get("model"),
        "serial": device.get("serial"),
        "transport": device.get("transport"),
        "is_rotational": device.get("is_rotational"),
        "firmware_version": None,
        "nvme_version_string": None,
        "nvme_controller_id": None,
        "nvme_number_of_namespaces": None,
        "total_capacity_bytes": None,
        "unallocated_capacity_bytes": None,
        "ieee_oui_identifier": None,
        "overall_status": "unknown",
        "temperature_celsius": None,
        "temperature_sensors_celsius": [],
        "power_on_hours": None,
        "power_cycle_count": None,
        "reallocated_sector_count": None,
        "media_errors": None,
        "critical_warnings": None,
        "data_units_written": None,
        "data_units_written_bytes": None,
        "data_units_read": None,
        "data_units_read_bytes": None,
        "host_writes_32mib": None,
        "host_writes_bytes": None,
        "host_reads_32mib": None,
        "host_reads_bytes": None,
        "host_read_commands": None,
        "host_write_commands": None,
        "controller_busy_time_minutes": None,
        "percentage_used": None,
        "unsafe_shutdowns": None,
        "available_spare": None,
        "available_spare_threshold": None,
        "warning_temp_time_minutes": None,
        "critical_temp_time_minutes": None,
        "num_error_log_entries": None,
        "exit_status": None,
        "error": None,
    }


def _collect_one_device(smartctl_path: str, device: Dict[str, Any], logger) -> Optional[Dict[str, Any]]:
    """Query and parse SMART data for one device. Returns ``None`` when the
    device has no derivable path (skipped, not reported)."""

    path = device.get("path") or (f"/dev/{device.get('name')}" if device.get("name") else None)
    if not path:
        return None

    device_result = _device_result_skeleton(device, path)

    # Detect device type and add appropriate flags for smartctl. Returns a
    # value even for devices with no plausible SMART support — every block
    # device gets a chance to report SMART data because some PCIe NVMe
    # drives on Raspberry Pi appear as `mmcblk` rather than `nvme`.
    device_type_flag = _detect_device_type(device, path, logger)

    # For NVMe devices, use the controller character device (/dev/nvme0)
    # instead of the namespace block device (/dev/nvme0n1). The namespace
    # path causes "Read Self-test Log failed" (exit code 4) on drives that
    # don't support the self-test log on the namespace, while the controller
    # path returns a clean exit code 0.
    query_path = _nvme_controller_path(path) if device_type_flag == "nvme" else path

    command = _build_smartctl_command(smartctl_path, device_type_flag, query_path)

    if logger:
        logger.debug("Querying SMART data for %s with command: %s", query_path, " ".join(command))

    completed, query_error = _query_smartctl(command, path, logger)
    if query_error:
        device_result["error"] = query_error
        return device_result

    device_result["exit_status"] = completed.returncode

    report, report_keys, output_error = _validate_smartctl_output(completed, path, logger)
    if output_error:
        device_result["error"] = output_error
        return device_result

    # Store diagnostic info so it's visible in the API response.
    device_result["_diag_report_keys"] = report_keys

    _populate_identity_fields(device_result, report)

    overall_status, status_error = _derive_overall_status(report, completed.returncode, path, logger)
    device_result["overall_status"] = overall_status
    if status_error:
        device_result["error"] = status_error

    _populate_smart_attributes(device_result, report)
    _populate_nvme_extended_fields(device_result, report)

    # Diagnostic: log extraction results for debugging.
    if logger:
        logger.debug(
            "SMART extraction for %s: temp=%s hours=%s pct_used=%s spare=%s media_err=%s",
            path,
            device_result.get("temperature_celsius"),
            device_result.get("power_on_hours"),
            device_result.get("percentage_used"),
            device_result.get("available_spare"),
            device_result.get("media_errors"),
        )

    # Only store stderr as error if it indicates a real problem, and only
    # when nothing more specific was already derived above (e.g. the
    # execution-failed branch's smartctl-JSON-messages/exit-code
    # explanation, which is usually more informative than raw stderr).
    stderr_output = (completed.stderr or "").strip()
    if stderr_output and completed.returncode != 0 and not device_result["error"]:
        device_result["error"] = stderr_output

    return device_result


def _collect_smart_health(logger, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collect S.M.A.R.T. health summaries for detected block devices."""

    result: Dict[str, Any] = {
        "available": False,
        "devices": [],
        "error": None,
        "install_guide": None,
    }

    smartctl_path = _find_smartctl_path(logger)
    if not smartctl_path:
        result["error"] = "smartctl utility not installed"
        result["install_guide"] = "Install smartmontools: apt install smartmontools (Debian/Ubuntu) or yum install smartmontools (RHEL/CentOS)"
        if logger:
            logger.info("SMART monitoring unavailable: smartctl not found. Install smartmontools package.")
        return result

    result["available"] = True

    for device in _iter_disk_devices(devices):
        device_result = _collect_one_device(smartctl_path, device, logger)
        if device_result is not None:
            result["devices"].append(device_result)

    if not result["devices"] and result["available"]:
        result["error"] = "No SMART-capable block devices found"
        if logger:
            logger.info("SMART monitoring available but no eligible devices found")

    return result
