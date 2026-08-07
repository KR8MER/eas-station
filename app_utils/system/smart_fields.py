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

"""Field extraction from smartctl output."""

from typing import Any, Dict, Optional

from .common import _coerce_int

NVME_DATA_UNIT_BYTES = 512_000


def _extract_temperature(report: Dict[str, Any]) -> Optional[float]:
    temperature = report.get("temperature")
    if isinstance(temperature, dict):
        current = temperature.get("current")
        if isinstance(current, (int, float)):
            temp_value = float(current)
            # Validate temperature is in reasonable range for Celsius
            if -50 <= temp_value <= 150:
                return temp_value
            # If out of range, it might be in a different unit - skip it
            return None

    nvme_info = report.get("nvme_smart_health_information_log")
    if isinstance(nvme_info, dict):
        current = nvme_info.get("temperature")
        if isinstance(current, (int, float)):
            temp_value = float(current)
            # NVMe devices commonly report temperature in Kelvin; convert when it appears elevated.
            # Kelvin absolute zero is -273.15°C, so valid Kelvin values are > 273
            if temp_value > 200:
                # Likely Kelvin, convert to Celsius
                celsius = temp_value - 273.15
                # Validate the converted temperature is reasonable
                if -50 <= celsius <= 150:
                    return celsius
                # If still unreasonable, return None
                return None
            # If already in Celsius range, validate and return
            elif -50 <= temp_value <= 150:
                return temp_value
            # Otherwise, unreasonable value
            return None

    return None


def _extract_attribute_value(report: Dict[str, Any], name: str) -> Optional[int]:
    attributes = report.get("ata_smart_attributes")
    if isinstance(attributes, dict):
        table = attributes.get("table")
        if isinstance(table, list):
            for entry in table:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("name")) == name:
                    raw = entry.get("raw")
                    if isinstance(raw, dict):
                        value = raw.get("value")
                        if isinstance(value, (int, float)):
                            return int(value)
    # Fallback for NVMe data stored directly on the report
    direct_value = report.get(name)
    if isinstance(direct_value, (int, float)):
        return int(direct_value)
    return None


def _extract_nvme_statistics(report: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Normalise NVMe-specific counters from smartctl output."""

    stats: Dict[str, Optional[int]] = {
        "data_units_written_bytes": None,
        "data_units_read_bytes": None,
        "host_read_commands": None,
        "host_write_commands": None,
        "controller_busy_time_minutes": None,
        "unsafe_shutdowns": None,
        "percentage_used": None,
    }

    nvme_info = report.get("nvme_smart_health_information_log")
    if not isinstance(nvme_info, dict):
        return stats

    def pull(*keys: str) -> Optional[int]:
        for candidate in keys:
            if candidate in nvme_info:
                value = _coerce_int(nvme_info.get(candidate))
                if value is not None:
                    return value
        return None

    bytes_written = pull("data_units_written_bytes")
    if bytes_written is not None:
        stats["data_units_written_bytes"] = bytes_written
    else:
        units_written = pull("data_units_written", "data_units_written_raw")
        if units_written is not None:
            stats["data_units_written_bytes"] = units_written * NVME_DATA_UNIT_BYTES

    bytes_read = pull("data_units_read_bytes")
    if bytes_read is not None:
        stats["data_units_read_bytes"] = bytes_read
    else:
        units_read = pull("data_units_read", "data_units_read_raw")
        if units_read is not None:
            stats["data_units_read_bytes"] = units_read * NVME_DATA_UNIT_BYTES

    stats["host_read_commands"] = pull("host_read_commands", "host_reads")
    stats["host_write_commands"] = pull("host_write_commands", "host_writes")
    stats["controller_busy_time_minutes"] = pull("controller_busy_time_minutes", "controller_busy_time")
    stats["unsafe_shutdowns"] = pull("unsafe_shutdowns")
    stats["percentage_used"] = pull("percentage_used")

    return stats


def _extract_nvme_field(report: Dict[str, Any], key: str) -> Optional[int]:
    nvme_info = report.get("nvme_smart_health_information_log")
    if isinstance(nvme_info, dict):
        value = nvme_info.get(key)
        coerced = _coerce_int(value)
        if coerced is not None:
            return coerced
    return None


def _populate_nvme_metrics(device_result: Dict[str, Any], report: Dict[str, Any]) -> None:
    nvme_info = report.get("nvme_smart_health_information_log")
    if not isinstance(nvme_info, dict):
        return

    def _update_if_absent(field: str, *keys: str) -> None:
        if device_result.get(field) is not None:
            return
        for key in keys:
            value = _coerce_int(nvme_info.get(key))
            if value is not None:
                device_result[field] = value
                return

    _update_if_absent("power_on_hours", "power_on_hours", "power_on_time_hours")
    _update_if_absent("power_cycle_count", "power_cycles")
    _update_if_absent("unsafe_shutdowns", "unsafe_shutdowns")
    _update_if_absent("percentage_used", "percentage_used")

    for source_key, target_field in (
        ("data_units_written", "data_units_written"),
        ("data_units_read", "data_units_read"),
        ("host_writes_32mib", "host_writes_32mib"),
        ("host_reads_32mib", "host_reads_32mib"),
    ):
        value = _coerce_int(nvme_info.get(source_key))
        if value is not None:
            device_result[target_field] = value

    if device_result.get("data_units_written") is not None:
        device_result["data_units_written_bytes"] = _convert_nvme_data_units(
            device_result["data_units_written"]
        )
    if device_result.get("data_units_read") is not None:
        device_result["data_units_read_bytes"] = _convert_nvme_data_units(
            device_result["data_units_read"]
        )

    if device_result.get("host_writes_32mib") is not None:
        device_result["host_writes_bytes"] = _convert_nvme_host_io(
            device_result["host_writes_32mib"]
        )
    if device_result.get("host_reads_32mib") is not None:
        device_result["host_reads_bytes"] = _convert_nvme_host_io(
            device_result["host_reads_32mib"]
        )


def _convert_nvme_data_units(units: int) -> int:
    # Per the NVMe specification, each data unit represents 512,000 bytes.
    return int(units) * 512_000


def _convert_nvme_host_io(units_32mib: int) -> int:
    # smartctl reports host reads/writes in units of 32 MiB.
    return int(units_32mib) * 32 * 1024 * 1024
