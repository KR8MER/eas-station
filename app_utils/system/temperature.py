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

"""Thermal sensor readings."""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import psutil

from .common import _is_valid_temperature, _safe_read_text


def _collect_temperature_readings(logger, smart_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate temperature readings from psutil, sysfs, and SMART."""

    readings: Dict[str, List[Dict[str, Any]]] = {}

    try:
        temps = psutil.sensors_temperatures()
    except Exception as exc:  # pragma: no cover - depends on psutil support
        if logger:
            logger.debug("psutil temperature query failed: %s", exc)
        temps = {}

    for name, entries in (temps or {}).items():
        if not isinstance(entries, Iterable):
            continue
        for entry in entries:
            current = getattr(entry, "current", None)
            if current is None:
                continue
            
            # Validate current temperature
            if not isinstance(current, (int, float)):
                continue
            current_float = float(current)
            if not _is_valid_temperature(current_float):
                if logger:
                    logger.debug("Skipping invalid temperature reading from psutil: %s = %s°C", name, current_float)
                continue
            
            # Validate high/critical thresholds
            high = getattr(entry, "high", None)
            critical = getattr(entry, "critical", None)
            high_float = float(high) if isinstance(high, (int, float)) and _is_valid_temperature(float(high)) else None
            critical_float = float(critical) if isinstance(critical, (int, float)) and _is_valid_temperature(float(critical)) else None
            
            _add_temperature_entry(
                readings,
                name,
                getattr(entry, "label", None) or "Sensor",
                current_float,
                high_float,
                critical_float,
            )

    thermal_root = Path("/sys/class/thermal")
    if thermal_root.exists():
        for zone in sorted(thermal_root.glob("thermal_zone*")):
            zone_type = _safe_read_text(zone / "type") or zone.name
            current_value = _parse_temperature_value(_safe_read_text(zone / "temp"))
            if current_value is None:
                continue

            trip_points: Dict[str, float] = {}
            for trip_type_path in zone.glob("trip_point_*_type"):
                trip_type = _safe_read_text(trip_type_path)
                if not trip_type:
                    continue
                temp_path = zone / trip_type_path.name.replace("_type", "_temp")
                trip_temp = _parse_temperature_value(_safe_read_text(temp_path))
                if trip_temp is not None:
                    trip_points[trip_type.strip().lower()] = trip_temp

            _add_temperature_entry(
                readings,
                zone_type,
                zone_type,
                current_value,
                trip_points.get("high") or trip_points.get("passive"),
                trip_points.get("critical"),
            )

    if isinstance(smart_info, dict):
        for device in smart_info.get("devices") or []:
            temperature = device.get("temperature_celsius")
            if temperature is None:
                continue
            if not isinstance(temperature, (int, float)):
                continue
            temp_float = float(temperature)
            # Validate temperature from SMART data
            if not _is_valid_temperature(temp_float):
                if logger:
                    logger.debug("Skipping invalid temperature from SMART: %s = %s°C", device.get("name"), temp_float)
                continue
            label = (
                device.get("product")
                or device.get("model")
                or device.get("path")
                or device.get("name")
                or "Storage device"
            )
            _add_temperature_entry(
                readings,
                "Storage",
                label,
                temp_float,
                None,
                None,
            )

    for group_entries in readings.values():
        group_entries.sort(key=lambda entry: str(entry.get("label") or ""))

    return readings


def _add_temperature_entry(
    container: Dict[str, List[Dict[str, Any]]],
    group: str,
    label: str,
    current: Optional[float],
    high: Optional[float],
    critical: Optional[float],
) -> None:
    if current is None:
        return
    
    # Validate all temperature values are reasonable
    if not _is_valid_temperature(current):
        return
    
    # Validate high/critical thresholds if present
    validated_high = high if high and _is_valid_temperature(high) else None
    validated_critical = critical if critical and _is_valid_temperature(critical) else None

    entry = {
        "label": label,
        "current": current,
        "high": validated_high,
        "critical": validated_critical,
    }

    container.setdefault(group, []).append(entry)


def _parse_temperature_value(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value > 1000:
        value = value / 1000.0
    # Validate the temperature is in a reasonable range
    if not _is_valid_temperature(value):
        return None
    return value
