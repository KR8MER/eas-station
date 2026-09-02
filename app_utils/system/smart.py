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

import json
import os
import shutil
import subprocess
from typing import Any, Dict, List

from .common import _coerce_int, _is_valid_temperature
from .disks import _detect_device_type, _iter_disk_devices, _nvme_controller_path
from .smart_fields import (
    _extract_attribute_value,
    _extract_nvme_field,
    _extract_nvme_statistics,
    _extract_temperature,
    _populate_nvme_metrics,
)


def _collect_smart_health(logger, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collect S.M.A.R.T. health summaries for detected block devices."""

    result: Dict[str, Any] = {
        "available": False, 
        "devices": [], 
        "error": None,
        "install_guide": None
    }

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
    if not smartctl_path:
        result["error"] = "smartctl utility not installed"
        result["install_guide"] = "Install smartmontools: apt install smartmontools (Debian/Ubuntu) or yum install smartmontools (RHEL/CentOS)"
        if logger:
            logger.info("SMART monitoring unavailable: smartctl not found. Install smartmontools package.")
        return result

    result["available"] = True

    for device in _iter_disk_devices(devices):
        path = device.get("path") or (f"/dev/{device.get('name')}" if device.get("name") else None)
        if not path:
            continue

        device_name = device.get("name") or ""

        device_result: Dict[str, Any] = {
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

        # Detect device type and add appropriate flags for smartctl.
        # Returns None only when there's no plausible SMART support (e.g. ramdisk).
        device_type_flag = _detect_device_type(device, path, logger)

        # For NVMe devices, use the controller character device (/dev/nvme0)
        # instead of the namespace block device (/dev/nvme0n1).  The namespace
        # path causes "Read Self-test Log failed" (exit code 4) on drives that
        # don't support the self-test log on the namespace, while the controller
        # path returns a clean exit code 0.
        query_path = _nvme_controller_path(path) if device_type_flag == "nvme" else path

        # Check if we need sudo (smartctl requires root access to read device data)
        # If smartctl_path doesn't start with /usr or /sbin, or if we're not root, use sudo
        use_sudo = os.geteuid() != 0 if hasattr(os, 'geteuid') else True

        command = []
        if use_sudo:
            # Use sudo for smartctl (requires sudoers configuration)
            command.extend(["sudo", "-n"])  # -n means don't prompt for password

        command.append(smartctl_path)

        # Add device type flag first (must come before other flags for some smartctl versions)
        if device_type_flag:
            command.extend(["-d", device_type_flag])

        # -a (all) = -H -i -c -A -l error -l selftest: provides complete
        # device info, capabilities, attributes, and health status.  Using -a
        # instead of just -H -A ensures NVMe health logs and ATA attributes
        # are both fully populated in the JSON output.
        command.extend(["--json", "-a"])

        # The -n standby flag is for ATA/SATA devices to skip devices in standby mode.
        # Only add this flag for:
        # - Devices explicitly detected as 'ata' or 'sat' type
        # Skip this flag for:
        # - NVMe devices: don't support standby mode in the same way as ATA/SATA
        # - Auto-detected devices: may be USB, SCSI, or other types that don't support -n standby
        # - Devices with no type flag (None)
        # Including -n standby for incompatible devices causes "invalid argument" errors
        if device_type_flag and device_type_flag in ("ata", "sat"):
            command.extend(["-n", "standby"])

        command.append(query_path)

        if logger:
            logger.debug("Querying SMART data for %s with command: %s", query_path, " ".join(command))

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
        except subprocess.TimeoutExpired:  # pragma: no cover - depends on hardware
            device_result["error"] = "smartctl query timed out (device may be sleeping or unresponsive)"
            if logger:
                logger.warning("smartctl timeout for %s", path)
            result["devices"].append(device_result)
            continue
        except PermissionError:  # pragma: no cover - depends on user permissions
            device_result["error"] = "Permission denied (may require root/sudo privileges)"
            if logger:
                logger.warning("smartctl permission denied for %s", path)
            result["devices"].append(device_result)
            continue
        except Exception as exc:  # pragma: no cover - depends on host configuration
            device_result["error"] = f"smartctl execution failed: {str(exc)}"
            if logger:
                logger.warning("smartctl failed for %s: %s", path, exc)
            result["devices"].append(device_result)
            continue

        device_result["exit_status"] = completed.returncode

        raw_output = (completed.stdout or "").strip()
        stderr_output = (completed.stderr or "").strip()
        
        # Log stderr for debugging, but don't necessarily treat it as an error
        if stderr_output and logger:
            logger.debug("smartctl stderr for %s: %s", path, stderr_output)
        
        # smartctl exit codes: bit 0 = command line error, bit 1 = device open failed, 
        # bit 2 = SMART command failed, bits 3-7 indicate disk problems
        if completed.returncode != 0 and not raw_output:
            # Provide more detailed error message based on exit code
            if completed.returncode & 1:
                error_msg = "Invalid command line arguments"
            elif completed.returncode & 2:
                error_msg = "Device open failed (device may be unavailable or requires elevated privileges)"
            elif completed.returncode & 4:
                error_msg = "SMART command failed (device may not support SMART)"
            else:
                error_msg = stderr_output if stderr_output else f"smartctl exited with code {completed.returncode}"
            device_result["error"] = error_msg
            if logger:
                logger.info("SMART not available for %s: %s", path, error_msg)
            result["devices"].append(device_result)
            continue
        
        if not raw_output:
            device_result["error"] = "No data returned from smartctl"
            if logger:
                logger.debug("No smartctl output for %s", path)
            result["devices"].append(device_result)
            continue

        try:
            report = json.loads(raw_output)
        except json.JSONDecodeError as exc:  # pragma: no cover - host specific output
            device_result["error"] = f"Unable to parse smartctl output: {exc}"
            if logger:
                logger.warning("Unable to parse smartctl output for %s: %s", path, exc)
            result["devices"].append(device_result)
            continue

        # Diagnostic: log which top-level JSON keys smartctl returned so we
        # can quickly identify missing sections when debugging attribute
        # extraction failures.
        report_keys = sorted(report.keys()) if isinstance(report, dict) else []
        has_nvme_log = "nvme_smart_health_information_log" in report_keys
        has_temperature = "temperature" in report_keys
        has_ata_attrs = "ata_smart_attributes" in report_keys
        if logger:
            logger.debug(
                "smartctl JSON for %s: keys=%s nvme_log=%s temp=%s ata_attrs=%s",
                path, report_keys, has_nvme_log, has_temperature, has_ata_attrs,
            )
        # Store diagnostic info so it's visible in the API response
        device_result["_diag_report_keys"] = report_keys

        device_result["model"] = (
            device_result.get("model")
            or report.get("model_name")
            or report.get("model_family")
            or report.get("device_model")
        )
        device_result["serial"] = device_result.get("serial") or report.get("serial_number")

        firmware_version = report.get("firmware_version") or report.get("firmware")
        if firmware_version:
            device_result["firmware_version"] = str(firmware_version)

        total_capacity = report.get("nvme_total_capacity")
        if total_capacity is None:
            user_capacity = report.get("user_capacity")
            if isinstance(user_capacity, dict):
                total_capacity = _coerce_int(user_capacity.get("bytes"))
        if total_capacity is not None:
            coerced_capacity = _coerce_int(total_capacity)
            if coerced_capacity is not None:
                device_result["total_capacity_bytes"] = coerced_capacity

        unallocated_capacity = report.get("nvme_unallocated_capacity")
        if unallocated_capacity is not None:
            coerced_unallocated = _coerce_int(unallocated_capacity)
            if coerced_unallocated is not None:
                device_result["unallocated_capacity_bytes"] = coerced_unallocated

        controller_id = _coerce_int(report.get("nvme_controller_id"))
        if controller_id is not None:
            device_result["nvme_controller_id"] = controller_id

        namespaces = _coerce_int(report.get("nvme_number_of_namespaces"))
        if namespaces is not None:
            device_result["nvme_number_of_namespaces"] = namespaces

        nvme_version = report.get("nvme_version")
        if isinstance(nvme_version, dict):
            version_string = nvme_version.get("string") or nvme_version.get("value")
            if version_string:
                device_result["nvme_version_string"] = str(version_string)

        ieee_identifier = _coerce_int(report.get("nvme_ieee_oui_identifier"))
        if ieee_identifier is not None:
            device_result["ieee_oui_identifier"] = f"{ieee_identifier:06X}"

        smart_status = report.get("smart_status") or {}
        passed = smart_status.get("passed")
        if passed is True:
            device_result["overall_status"] = "passed"
        elif passed is False:
            device_result["overall_status"] = "failed"
        else:
            status_text = smart_status.get("status") or smart_status.get("string")
            if status_text:
                device_result["overall_status"] = str(status_text)
            else:
                # Fallback: infer health status from exit code and available data
                # smartctl exit code bits, per its own man page:
                #   bit 0 = command line did not parse
                #   bit 1 = device open failed, or SMART command set unsupported
                #   bit 2 = a SMART/ATA command to the disk failed
                #   bit 3 = DISK FAILING, bit 4 = prefail attrs <= threshold,
                #   bit 5 = usage attrs <= threshold, bit 6 = error log has errors,
                #   bit 7 = self-test log has errors
                # Bits 0-2 mean smartctl never actually got real SMART data at
                # all -- there is nothing here to call "passed". Before this
                # check existed, that case fell straight through to "bits 3-7
                # are clear -> passed", which is how a virtio-blk-backed cloud
                # VM (no ATA/NVMe protocol between guest and host at all, so
                # every device-type probe returns exit code 2 with a mostly
                # empty but validly-parsing JSON report) ended up reported as
                # a healthy drive despite smartctl never having successfully
                # talked to anything.
                exit_code = completed.returncode
                execution_failed_bits = exit_code & 0x07  # bits 0-2: no real data at all
                disk_failing_bits = exit_code & 0x18  # bits 3-4: critical failures
                disk_problem_bits = exit_code & 0xF8  # bits 3-7: any disk issues

                if execution_failed_bits:
                    smartctl_messages = [
                        msg["string"]
                        for msg in (report.get("smartctl") or {}).get("messages") or []
                        if isinstance(msg, dict) and msg.get("string")
                    ]
                    device_result["error"] = "; ".join(smartctl_messages) or (
                        f"smartctl could not query this device (exit code {exit_code}) -- "
                        "SMART data unavailable. Common on virtualized/cloud block storage "
                        "(e.g. virtio-blk) where the guest has no ATA/NVMe protocol to the "
                        "underlying disk at all."
                    )
                else:
                    nvme_info = report.get("nvme_smart_health_information_log")
                    if isinstance(nvme_info, dict):
                        # NVMe: use critical_warning field as authoritative source
                        critical_warning = _coerce_int(nvme_info.get("critical_warning"))
                        if critical_warning is not None:
                            device_result["overall_status"] = "failed" if critical_warning != 0 else "passed"
                        elif disk_problem_bits == 0:
                            device_result["overall_status"] = "passed"
                    elif disk_failing_bits:
                        # ATA/SATA with critical failure bits set
                        device_result["overall_status"] = "failed"
                    elif disk_problem_bits == 0:
                        # No disk problem bits set and we parsed valid data
                        device_result["overall_status"] = "passed"

                if logger:
                    if device_result["overall_status"] != "unknown":
                        logger.debug(
                            "Inferred SMART status '%s' for %s from exit code %d",
                            device_result["overall_status"], path, exit_code,
                        )
                    elif exit_code == 0:
                        logger.debug(
                            "SMART status unavailable for %s despite successful smartctl execution", path,
                        )

        device_result["temperature_celsius"] = _extract_temperature(report)
        device_result["power_on_hours"] = _extract_attribute_value(report, "Power_On_Hours")
        device_result["power_cycle_count"] = _extract_attribute_value(report, "Power_Cycle_Count")
        device_result["reallocated_sector_count"] = _extract_attribute_value(
            report, "Reallocated_Sector_Ct"
        )

        # Fallback: also try "Reallocated_Sector_Count" (used by some drives)
        if device_result["reallocated_sector_count"] is None:
            device_result["reallocated_sector_count"] = _extract_attribute_value(
                report, "Reallocated_Sector_Count"
            )

        # ATA pending sector count (another common health indicator)
        pending = _extract_attribute_value(report, "Current_Pending_Sector")
        if pending is not None:
            device_result.setdefault("pending_sector_count", pending)

        device_result["media_errors"] = _extract_nvme_field(report, "media_errors")
        device_result["critical_warnings"] = _extract_nvme_field(report, "critical_warning")
        nvme_stats = _extract_nvme_statistics(report)
        for key, value in nvme_stats.items():
            device_result[key] = value

        _populate_nvme_metrics(device_result, report)

        nvme_info = report.get("nvme_smart_health_information_log")
        if isinstance(nvme_info, dict):
            available_spare = _coerce_int(nvme_info.get("available_spare"))
            if available_spare is not None:
                device_result["available_spare"] = available_spare

            spare_threshold = _coerce_int(nvme_info.get("available_spare_threshold"))
            if spare_threshold is not None:
                device_result["available_spare_threshold"] = spare_threshold

            warning_time = (
                _coerce_int(nvme_info.get("warning_comp_temperature_time"))
                or _coerce_int(nvme_info.get("warning_temp_time"))
            )
            if warning_time is not None:
                device_result["warning_temp_time_minutes"] = warning_time

            critical_time = (
                _coerce_int(nvme_info.get("critical_comp_temperature_time"))
                or _coerce_int(nvme_info.get("critical_comp_time"))
            )
            if critical_time is not None:
                device_result["critical_temp_time_minutes"] = critical_time

            error_logs = _coerce_int(nvme_info.get("num_err_log_entries"))
            if error_logs is not None:
                device_result["num_error_log_entries"] = error_logs

            sensors = nvme_info.get("temperature_sensors")
            if isinstance(sensors, list):
                readings: List[float] = []
                for entry in sensors:
                    if isinstance(entry, (int, float)):
                        value = float(entry)
                        if value > 200:
                            value -= 273.15
                        if _is_valid_temperature(value):
                            readings.append(round(value, 1))
                if readings:
                    device_result["temperature_sensors_celsius"] = readings

        # Diagnostic: log extraction results for debugging
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
        # execution_failed_bits branch's smartctl-JSON-messages/exit-code
        # explanation, which is usually more informative than raw stderr).
        if stderr_output and completed.returncode != 0 and not device_result["error"]:
            device_result["error"] = stderr_output

        result["devices"].append(device_result)

    if not result["devices"] and result["available"]:
        result["error"] = "No SMART-capable block devices found"
        if logger:
            logger.info("SMART monitoring available but no eligible devices found")

    return result
