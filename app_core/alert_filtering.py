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

from __future__ import annotations

"""Helpers for loading and updating alert filter settings."""

import threading
from typing import Any, Dict, List, Optional

from flask import current_app, has_app_context

from app_utils.location_settings import (
    DEFAULT_LOCATION_SETTINGS,
    normalise_upper,
    sanitize_fips_codes,
)

from .extensions import db
from .models import AlertFilterSettings
from .zones import normalise_zone_codes, get_zone_lookup, forecast_zones_for_same_code, ZoneInfo
from app_utils.fips_codes import get_us_state_county_tree

_alert_filter_settings_cache: Optional[Dict[str, Any]] = None
_alert_filter_settings_lock = threading.Lock()


_STATE_FIPS_TO_ABBR = {
    str(state.get("state_fips") or "").zfill(2): str(state.get("abbr") or "").upper()
    for state in get_us_state_county_tree()
    if state.get("state_fips")
}


def _derive_county_zone_codes_from_fips(
    fips_codes,
    zone_lookup: Optional[Dict[str, ZoneInfo]] = None,
) -> List[str]:
    """Derive forecast + county zone codes from a sequence of SAME/FIPS codes."""
    derived: List[str] = []
    seen = set()
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
        zone_code = f"{state_abbr}C{county_suffix}".upper()
        if zone_code in seen:
            continue
        if zone_lookup is not None and zone_code not in zone_lookup:
            continue
        seen.add(zone_code)
        derived.append(zone_code)
    return derived


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


def _resolve_fips_codes(values: Any, fallback: Any) -> tuple[List[str], List[str]]:
    valid, invalid = sanitize_fips_codes(values)
    if valid:
        return valid, invalid

    fallback_valid, _ = sanitize_fips_codes(fallback)
    if fallback_valid:
        return fallback_valid, invalid

    return list(_DEFAULT_FIPS_CODES), invalid


def _prepare_filter_dict(settings: Dict[str, Any]) -> Dict[str, Any]:
    prepared = dict(settings)
    fips_codes, _ = sanitize_fips_codes(prepared.get("fips_codes"))
    if not fips_codes:
        fips_codes = list(_DEFAULT_FIPS_CODES)
    prepared["fips_codes"] = fips_codes
    prepared["same_codes"] = list(fips_codes)
    return prepared


def _ensure_alert_filter_settings_record() -> AlertFilterSettings:
    settings = AlertFilterSettings.query.first()
    if not settings:
        settings = AlertFilterSettings()
        db.session.add(settings)
        db.session.commit()
    return settings


def get_alert_filter_settings(force_reload: bool = False) -> Dict[str, Any]:
    global _alert_filter_settings_cache

    with _alert_filter_settings_lock:
        if force_reload:
            _alert_filter_settings_cache = None

        if _alert_filter_settings_cache is None:
            record = _ensure_alert_filter_settings_record()
            _alert_filter_settings_cache = _prepare_filter_dict(record.to_dict())
        return _prepare_filter_dict(_alert_filter_settings_cache)


def update_alert_filter_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    global _alert_filter_settings_cache

    with _alert_filter_settings_lock:
        record = _ensure_alert_filter_settings_record()

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
                    "Ignoring unrecognized FIPS codes: %s" % ", ".join(ignored)
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

        # Auto-append county zone codes derived from FIPS codes (preserves
        # behavior of the pre-split update_location_settings).
        derived_zone_codes = _derive_county_zone_codes_from_fips(
            fips_codes, zone_lookup
        )
        if derived_zone_codes:
            existing = set(zone_codes)
            for code in derived_zone_codes:
                if code not in existing:
                    zone_codes.append(code)
                    existing.add(code)

        storage_zone_input = data.get("storage_zone_codes")
        raw_storage_zone_codes = normalise_upper(
            storage_zone_input
            or record.storage_zone_codes
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

        record.fips_codes = fips_codes
        record.zone_codes = zone_codes
        record.storage_zone_codes = storage_zone_codes
        record.area_terms = area_terms

        db.session.add(record)
        db.session.commit()

        _alert_filter_settings_cache = _prepare_filter_dict(record.to_dict())

        # Invalidate the merged location-settings cache so subsequent
        # get_location_settings() calls re-read the new filter values. We
        # deliberately do NOT acquire the location lock here: this path may
        # be called from update_location_settings() which already holds it,
        # and a plain attribute assignment is sufficient for invalidation.
        try:
            from . import location as _location_module
            _location_module._location_settings_cache = None
        except Exception:  # pragma: no cover - defensive
            pass

        return _prepare_filter_dict(_alert_filter_settings_cache)
