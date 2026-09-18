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

"""Populating a device result dict from a parsed smartctl report."""

from typing import Any, Dict, List

from .common import _coerce_int, _is_valid_temperature
from .smart_fields import (
    _extract_attribute_value,
    _extract_nvme_field,
    _extract_nvme_statistics,
    _extract_temperature,
    _populate_nvme_metrics,
)


def _populate_identity_fields(device_result: Dict[str, Any], report: Dict[str, Any]) -> None:
    """Model/serial/firmware/capacity/NVMe controller identity fields."""

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


def _populate_smart_attributes(device_result: Dict[str, Any], report: Dict[str, Any]) -> None:
    """Temperature, power-on/cycle counters, reallocated/pending sectors,
    and the generic NVMe metrics `smart_fields.py` already knows how to
    extract."""

    device_result["temperature_celsius"] = _extract_temperature(report)
    device_result["power_on_hours"] = _extract_attribute_value(report, "Power_On_Hours")
    device_result["power_cycle_count"] = _extract_attribute_value(report, "Power_Cycle_Count")
    device_result["reallocated_sector_count"] = _extract_attribute_value(
        report, "Reallocated_Sector_Ct"
    )

    # Fallback: also try "Reallocated_Sector_Count" (used by some drives).
    if device_result["reallocated_sector_count"] is None:
        device_result["reallocated_sector_count"] = _extract_attribute_value(
            report, "Reallocated_Sector_Count"
        )

    # ATA pending sector count (another common health indicator).
    pending = _extract_attribute_value(report, "Current_Pending_Sector")
    if pending is not None:
        device_result.setdefault("pending_sector_count", pending)

    device_result["media_errors"] = _extract_nvme_field(report, "media_errors")
    device_result["critical_warnings"] = _extract_nvme_field(report, "critical_warning")
    nvme_stats = _extract_nvme_statistics(report)
    for key, value in nvme_stats.items():
        device_result[key] = value

    _populate_nvme_metrics(device_result, report)


def _populate_nvme_extended_fields(device_result: Dict[str, Any], report: Dict[str, Any]) -> None:
    """Spare capacity, temperature-time thresholds, error log count, and
    per-sensor temperature readings from the NVMe SMART health log."""

    nvme_info = report.get("nvme_smart_health_information_log")
    if not isinstance(nvme_info, dict):
        return

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
