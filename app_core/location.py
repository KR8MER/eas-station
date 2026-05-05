"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Helpers for loading and updating persisted location settings."""

import threading
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import pytz
from flask import current_app, has_app_context

from app_utils.fips_codes import (
    NATIONWIDE_SAME_CODE,
    STATE_ABBR_NAMES,
    get_same_lookup,
    get_us_state_county_tree,
)
from app_utils.location_settings import (
    DEFAULT_LOCATION_SETTINGS,
    ensure_list,
    normalise_upper,
    sanitize_fips_codes,
)
from app_utils import set_location_timezone

from .extensions import db
from .models import LocationSettings
from .zones import (
    ZoneInfo,
    forecast_zones_for_same_code,
    get_zone_lookup,
    normalise_zone_codes,
)

_location_settings_cache: Optional[Dict[str, Any]] = None
_location_settings_lock = threading.Lock()


def _default_fips_codes() -> List[str]:
    codes, _ = sanitize_fips_codes(DEFAULT_LOCATION_SETTINGS.get("fips_codes"))
    if codes:
        return codes
    fallback, _ = sanitize_fips_codes(["039137"])
    return fallback or ["039137"]


_DEFAULT_FIPS_CODES = _default_fips_codes()


_STATE_FIPS_TO_ABBR = {
    str(state.get("state_fips") or "").zfill(2): str(state.get("abbr") or "").upper()
    for state in get_us_state_county_tree()
    if state.get("state_fips")
}


def _log_warning(message: str) -> None:
    if has_app_context():
        current_app.logger.warning(message)


def _derive_county_zone_codes_from_fips(
    fips_codes: Sequence[str],
    zone_lookup: Optional[Dict[str, ZoneInfo]] = None,
) -> List[str]:
    derived: List[str] = []
    seen: Set[str] = set()
    for raw_code in fips_codes:
        digits = "".join(ch for ch in str(raw_code) if ch.isdigit())
        if len(digits) != 6 or digits.endswith("000"):
            continue

        state_fips = digits[1:3]
        county_suffix = digits[3:]
        state_abbr = _STATE_FIPS_TO_ABBR.get(state_fips)
        if not state_abbr or len(state_abbr) != 2:
            continue

        same_code = digits
        for forecast_code in forecast_zones_for_same_code(same_code, zone_lookup):
            normalized_forecast = forecast_code.upper()
            if normalized_forecast in seen:
                continue
            if zone_lookup is not None and normalized_forecast not in zone_lookup:
                continue
            seen.add(normalized_forecast)
            derived.append(normalized_forecast)

        zone_code = f"{state_abbr}C{county_suffix}"
        normalized = zone_code.upper()
        if normalized in seen:
            continue
        if zone_lookup is not None and normalized not in zone_lookup:
            continue

        seen.add(normalized)
        derived.append(normalized)

    return derived


def _resolve_fips_codes(values: Any, fallback: Any) -> Tuple[List[str], List[str]]:
    valid, invalid = sanitize_fips_codes(values)
    if valid:
        return valid, invalid

    fallback_valid, _ = sanitize_fips_codes(fallback)
    if fallback_valid:
        return fallback_valid, invalid

    return list(_DEFAULT_FIPS_CODES), invalid


def _prepare_settings_dict(settings: Dict[str, Any]) -> Dict[str, Any]:
    prepared = dict(settings)
    fips_codes, _ = sanitize_fips_codes(prepared.get("fips_codes"))
    if not fips_codes:
        fips_codes = list(_DEFAULT_FIPS_CODES)
    prepared["fips_codes"] = fips_codes
    prepared["same_codes"] = list(fips_codes)
    return prepared


def _ensure_location_settings_record() -> LocationSettings:
    settings = LocationSettings.query.first()
    if not settings:
        settings = LocationSettings()
        db.session.add(settings)
        db.session.commit()
    return settings


def _coerce_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _load_merged_settings() -> Dict[str, Any]:
    """Build the merged location settings dict from all three tables.

    Caller is responsible for any locking. This function does not touch the cache.
    """
    location_record = _ensure_location_settings_record()
    merged = location_record.to_dict()

    # Merge alert filter settings (fips_codes/zone_codes/storage_zone_codes/area_terms/same_codes)
    from .alert_filtering import get_alert_filter_settings
    filter_settings = get_alert_filter_settings()
    merged.update({
        "fips_codes": filter_settings.get("fips_codes", []),
        "zone_codes": filter_settings.get("zone_codes", []),
        "storage_zone_codes": filter_settings.get("storage_zone_codes", []),
        "area_terms": filter_settings.get("area_terms", []),
        "same_codes": filter_settings.get("same_codes", []),
    })

    # Merge led_default_lines from hardware settings (defensive — table may
    # not exist in lightweight test fixtures or before migrations have run).
    try:
        from .models import HardwareSettings
        hw_record = HardwareSettings.query.first()
        if hw_record and getattr(hw_record, "led_default_lines", None):
            merged["led_default_lines"] = list(hw_record.led_default_lines or [])
        else:
            merged["led_default_lines"] = list(DEFAULT_LOCATION_SETTINGS["led_default_lines"])
    except Exception:  # pragma: no cover - defensive
        db.session.rollback()
        merged["led_default_lines"] = list(DEFAULT_LOCATION_SETTINGS["led_default_lines"])

    return _prepare_settings_dict(merged)


def get_location_settings(force_reload: bool = False) -> Dict[str, Any]:
    """Get merged location settings from location, alert filter, and hardware tables.

    Returns a dictionary with the same shape as before the refactoring for backwards compatibility.
    """
    global _location_settings_cache

    with _location_settings_lock:
        if force_reload:
            _location_settings_cache = None

        if _location_settings_cache is None:
            _location_settings_cache = _load_merged_settings()
            set_location_timezone(_location_settings_cache["timezone"])
        return _prepare_settings_dict(_location_settings_cache)


def update_location_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    """Update location settings, dispatching to appropriate tables.
    
    For backwards compatibility, accepts a flat dict with all fields and
    dispatches them to location_settings, alert_filter_settings, and hardware_settings.
    """
    global _location_settings_cache

    with _location_settings_lock:
        record = _ensure_location_settings_record()

        # Handle location-specific fields
        county_name = str(
            data.get("county_name")
            or record.county_name
            or DEFAULT_LOCATION_SETTINGS["county_name"]
        ).strip()
        state_code = str(
            data.get("state_code")
            or record.state_code
            or DEFAULT_LOCATION_SETTINGS["state_code"]
        ).strip().upper()
        timezone_name = str(
            data.get("timezone")
            or record.timezone
            or DEFAULT_LOCATION_SETTINGS["timezone"]
        ).strip()

        map_center_lat = _coerce_float(
            data.get("map_center_lat"),
            record.map_center_lat or DEFAULT_LOCATION_SETTINGS["map_center_lat"],
        )
        map_center_lng = _coerce_float(
            data.get("map_center_lng"),
            record.map_center_lng or DEFAULT_LOCATION_SETTINGS["map_center_lng"],
        )
        map_default_zoom = _coerce_int(
            data.get("map_default_zoom"),
            record.map_default_zoom or DEFAULT_LOCATION_SETTINGS["map_default_zoom"],
        )

        try:
            pytz.timezone(timezone_name)
        except Exception as exc:  # pragma: no cover - defensive
            _log_warning(
                f"Invalid timezone provided ({timezone_name}), keeping {record.timezone}: {exc}"
            )
            timezone_name = record.timezone or DEFAULT_LOCATION_SETTINGS["timezone"]

        record.county_name = county_name
        record.state_code = state_code
        record.timezone = timezone_name
        record.map_center_lat = map_center_lat
        record.map_center_lng = map_center_lng
        record.map_default_zoom = map_default_zoom

        db.session.add(record)
        db.session.commit()

        # Handle alert filter fields if any are present
        has_filter_fields = any(
            key in data
            for key in ["fips_codes", "zone_codes", "storage_zone_codes", "area_terms"]
        )
        if has_filter_fields:
            from .alert_filtering import update_alert_filter_settings
            filter_data = {
                k: v for k, v in data.items()
                if k in ["fips_codes", "zone_codes", "storage_zone_codes", "area_terms"]
            }
            update_alert_filter_settings(filter_data)

        # Handle led_default_lines if present
        if "led_default_lines" in data:
            try:
                from app_utils.location_settings import ensure_list
                from .models import HardwareSettings

                led_lines = ensure_list(
                    data.get("led_default_lines") or DEFAULT_LOCATION_SETTINGS["led_default_lines"]
                )
                if not led_lines:
                    led_lines = list(DEFAULT_LOCATION_SETTINGS["led_default_lines"])

                hw_record = HardwareSettings.query.first()
                if not hw_record:
                    hw_record = HardwareSettings(id=1)
                hw_record.led_default_lines = led_lines
                db.session.add(hw_record)
                db.session.commit()
            except Exception as exc:  # pragma: no cover - defensive
                db.session.rollback()
                _log_warning(f"Could not persist led_default_lines to hardware_settings: {exc}")

        _location_settings_cache = None
        # Compute the fresh merged dict inline; we still hold the location lock
        # so we cannot call get_location_settings() (non-reentrant lock).
        result = _load_merged_settings()
        _location_settings_cache = result
        set_location_timezone(result["timezone"])

        return _prepare_settings_dict(result)


def describe_location_reference(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a structured summary of the stored zone and SAME/FIPS metadata."""

    snapshot = dict(settings or get_location_settings())

    zone_lookup = get_zone_lookup() or {}
    known_zones: List[Dict[str, Any]] = []
    missing_zones: List[str] = []
    for raw_code in snapshot.get("zone_codes", []) or []:
        code = (str(raw_code) or "").strip().upper()
        if not code:
            continue
        info = zone_lookup.get(code)
        if not info:
            missing_zones.append(code)
            continue
        zone_details = {
            "code": info.code,
            "state_code": info.state_code,
            "zone_number": info.zone_number,
            "zone_type": info.zone_type,
            "name": info.name,
            "short_name": info.short_name,
            "label": info.formatted_label(),
            "cwa": info.cwa,
            "time_zone": info.time_zone,
            "fe_area": info.fe_area,
            "latitude": info.latitude,
            "longitude": info.longitude,
        }

        if info.zone_type == "C":
            same_code = info.same_code or ""
            fips_code = info.fips_code or (same_code[1:] if len(same_code) == 6 else "")
            state_fips = info.state_fips or (same_code[1:3] if len(same_code) == 6 else "")
            county_fips = info.county_fips or (same_code[-3:] if len(same_code) == 6 else "")

            zone_details.update(
                {
                    "same_code": same_code,
                    "fips_code": fips_code,
                    "state_fips": state_fips,
                    "county_fips": county_fips,
                }
            )

        known_zones.append(zone_details)

    same_lookup = get_same_lookup()
    known_fips: List[Dict[str, Any]] = []
    missing_fips: List[str] = []
    for raw_code in snapshot.get("fips_codes", []) or []:
        code = (str(raw_code) or "").strip()
        if not code:
            continue
        label = same_lookup.get(code)
        if not label:
            missing_fips.append(code)
            continue

        if "," in label:
            county_name, state_abbr = [
                part.strip() for part in label.rsplit(",", maxsplit=1)
            ]
        elif code == NATIONWIDE_SAME_CODE:
            county_name = label
            state_abbr = "US"
        else:
            county_name = label
            state_abbr = ""

        state_name = STATE_ABBR_NAMES.get(state_abbr, state_abbr)
        state_fips = code[1:3] if len(code) == 6 else ""
        county_fips = code[3:6] if len(code) == 6 else ""
        known_fips.append(
            {
                "code": code,
                "label": label,
                "county": county_name,
                "state": state_abbr,
                "state_name": state_name,
                "state_fips": state_fips,
                "county_fips": county_fips,
                "same_subdivision": code[0] if code else "",
                "is_statewide": code.endswith("000") and code != NATIONWIDE_SAME_CODE,
                "is_nationwide": code == NATIONWIDE_SAME_CODE,
            }
        )

    area_terms: List[str] = []
    for term in snapshot.get("area_terms", []) or []:
        if not isinstance(term, str):
            continue
        stripped = term.strip()
        if stripped:
            area_terms.append(stripped)

    sources = [
        {
            "label": "SAME Location Codes Directory",
            "description": (
                "Authoritative FEMA/NOAA listing aligning SAME location codes with county "
                "and subdivision FIPS identifiers."
            ),
            "path": "assets/pd01005007curr.pdf",
            "source_type": "local_asset",
        },
        {
            "label": "NOAA Public Forecast Zones",
            "description": (
                "Official NOAA catalog of public forecast zone boundaries that informs the "
                "zone metadata bundled with EAS Station."
            ),
            "url": "https://www.weather.gov/gis/PublicZones",
            "source_type": "external",
        },
    ]

    return {
        "location": {
            "county_name": snapshot.get("county_name", ""),
            "state_code": snapshot.get("state_code", ""),
            "timezone": snapshot.get("timezone", ""),
        },
        "zones": {
            "known": known_zones,
            "missing": missing_zones,
            "total_catalog": len(zone_lookup),
        },
        "fips": {
            "known": known_fips,
            "missing": missing_fips,
            "total_catalog": len(same_lookup),
        },
        "area_terms": area_terms,
        "sources": sources,
    }


__all__ = [
    "get_location_settings",
    "update_location_settings",
    "describe_location_reference",
]
