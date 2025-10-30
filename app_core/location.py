"""Helpers for loading and updating persisted location settings."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

import pytz
from flask import current_app, has_app_context

from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS, ensure_list, normalise_upper
from app_utils import set_location_timezone

from .extensions import db
from .models import LocationSettings

_location_settings_cache: Optional[Dict[str, Any]] = None
_location_settings_lock = threading.Lock()


def _log_warning(message: str) -> None:
    if has_app_context():
        current_app.logger.warning(message)


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
            _location_settings_cache = record.to_dict()
            set_location_timezone(_location_settings_cache["timezone"])
        return dict(_location_settings_cache)


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
        record.zone_codes = zone_codes
        record.area_terms = area_terms
        record.led_default_lines = led_lines
        record.map_center_lat = map_center_lat
        record.map_center_lng = map_center_lng
        record.map_default_zoom = map_default_zoom

        db.session.add(record)
        db.session.commit()

        _location_settings_cache = record.to_dict()
        set_location_timezone(_location_settings_cache["timezone"])

        return dict(_location_settings_cache)


__all__ = [
    "get_location_settings",
    "update_location_settings",
]
