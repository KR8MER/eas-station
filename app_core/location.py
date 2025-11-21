"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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
    zone_lookup: Optional[Dict[str, "ZoneInfo"]] = None,
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


def get_location_settings(force_reload: bool = False) -> Dict[str, Any]:
    global _location_settings_cache

    # Move force_reload check inside lock to prevent race condition
    with _location_settings_lock:
        if force_reload:
            _location_settings_cache = None

        if _location_settings_cache is None:
            record = _ensure_location_settings_record()
            _location_settings_cache = _prepare_settings_dict(record.to_dict())
            set_location_timezone(_location_settings_cache["timezone"])
        return _prepare_settings_dict(_location_settings_cache)


def update_location_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    global _location_settings_cache

    with _location_settings_lock:
        record = _ensure_location_settings_record()

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

        existing_fips_source = record.fips_codes or DEFAULT_LOCATION_SETTINGS.get("fips_codes")
        requested_fips = data.get("fips_codes")
        if requested_fips is None:
            fips_codes, invalid_fips = _resolve_fips_codes(
                existing_fips_source or _DEFAULT_FIPS_CODES,
                _DEFAULT_FIPS_CODES,
            )
            log_invalid = False
        else:
            fips_codes, invalid_fips = _resolve_fips_codes(
                requested_fips,
                existing_fips_source or _DEFAULT_FIPS_CODES,
            )
            log_invalid = True

        if log_invalid and invalid_fips:
            ignored = sorted({str(item).strip() for item in invalid_fips if str(item).strip()})
            if ignored:
                _log_warning(
                    "Ignoring unrecognized location FIPS codes: %s" % ", ".join(ignored)
                )

        zone_input = data.get("zone_codes")
        raw_zone_codes = normalise_upper(
            zone_input
            or record.zone_codes
            or DEFAULT_LOCATION_SETTINGS["zone_codes"]
        )
        zone_lookup = get_zone_lookup()
        zone_codes, invalid_zone_codes = normalise_zone_codes(raw_zone_codes)
        if zone_input is not None and invalid_zone_codes:
            ignored = sorted(
                {code for code in invalid_zone_codes if code}
            )
            if ignored:
                _log_warning(
                    "Ignoring malformed NOAA zone identifiers: %s"
                    % ", ".join(ignored)
                )
        if not zone_codes:
            defaults = DEFAULT_LOCATION_SETTINGS["zone_codes"]
            zone_codes, _ = normalise_zone_codes(defaults)
            if not zone_codes:
                zone_codes = list(defaults)

        if zone_input is not None and zone_lookup:
            unknown_zones = sorted(
                {code for code in zone_codes if code not in zone_lookup}
            )
            if unknown_zones:
                _log_warning(
                    "Zone catalog does not include: %s; keeping provided values"
                    % ", ".join(unknown_zones)
                )

        derived_zone_codes = _derive_county_zone_codes_from_fips(
            fips_codes, zone_lookup
        )
        if derived_zone_codes:
            existing = set(zone_codes)
            appended = False
            for code in derived_zone_codes:
                if code not in existing:
                    zone_codes.append(code)
                    existing.add(code)
                    appended = True
            if appended and zone_input is None:
                zone_codes = normalise_upper(zone_codes)

        # Storage zone codes: subset of zone_codes for local county only
        storage_zone_input = data.get("storage_zone_codes")
        raw_storage_zone_codes = normalise_upper(
            storage_zone_input
            or getattr(record, 'storage_zone_codes', None)
            or DEFAULT_LOCATION_SETTINGS["storage_zone_codes"]
        )
        storage_zone_codes, invalid_storage_zone_codes = normalise_zone_codes(raw_storage_zone_codes)
        if storage_zone_input is not None and invalid_storage_zone_codes:
            ignored = sorted(
                {code for code in invalid_storage_zone_codes if code}
            )
            if ignored:
                _log_warning(
                    "Ignoring malformed storage zone identifiers: %s"
                    % ", ".join(ignored)
                )
        if not storage_zone_codes:
            defaults = DEFAULT_LOCATION_SETTINGS["storage_zone_codes"]
            storage_zone_codes, _ = normalise_zone_codes(defaults)
            if not storage_zone_codes:
                storage_zone_codes = list(defaults)

        area_terms = normalise_upper(
            data.get("area_terms")
            or record.area_terms
            or DEFAULT_LOCATION_SETTINGS["area_terms"]
        )
        if not area_terms:
            area_terms = list(DEFAULT_LOCATION_SETTINGS["area_terms"])

        led_lines = ensure_list(
            data.get("led_default_lines")
            or record.led_default_lines
            or DEFAULT_LOCATION_SETTINGS["led_default_lines"]
        )
        if not led_lines:
            led_lines = list(DEFAULT_LOCATION_SETTINGS["led_default_lines"])

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
        record.fips_codes = fips_codes
        record.zone_codes = zone_codes
        record.storage_zone_codes = storage_zone_codes
        record.area_terms = area_terms
        record.led_default_lines = led_lines
        record.map_center_lat = map_center_lat
        record.map_center_lng = map_center_lng
        record.map_default_zoom = map_default_zoom

        db.session.add(record)
        db.session.commit()

        _location_settings_cache = _prepare_settings_dict(record.to_dict())
        set_location_timezone(_location_settings_cache["timezone"])

        return _prepare_settings_dict(_location_settings_cache)


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
