"""Helpers for loading and updating persisted location settings."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

import pytz
from flask import current_app, has_app_context

from app_utils.location_settings import (
    DEFAULT_LOCATION_SETTINGS,
    ensure_list,
    normalise_upper,
    sanitize_fips_codes,
)
from app_utils import set_location_timezone

from .extensions import db
from .models import LocationSettings

_location_settings_cache: Optional[Dict[str, Any]] = None
_location_settings_lock = threading.Lock()


def _default_fips_codes() -> List[str]:
    codes, _ = sanitize_fips_codes(DEFAULT_LOCATION_SETTINGS.get("fips_codes"))
    if codes:
        return codes
    fallback, _ = sanitize_fips_codes(["039137"])
    return fallback or ["039137"]


_DEFAULT_FIPS_CODES = _default_fips_codes()


def _log_warning(message: str) -> None:
    if has_app_context():
        current_app.logger.warning(message)


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

        zone_codes = normalise_upper(
            data.get("zone_codes")
            or record.zone_codes
            or DEFAULT_LOCATION_SETTINGS["zone_codes"]
        )
        if not zone_codes:
            zone_codes = list(DEFAULT_LOCATION_SETTINGS["zone_codes"])

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


__all__ = [
    "get_location_settings",
    "update_location_settings",
]
