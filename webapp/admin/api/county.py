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

"""Deciding whether an alert covers a whole county.

``_detect_county_wide`` is the heuristic behind the "county-wide" badge and the
county-fill rendering on the alert map. It compares the alert's ``area_desc``
and geometry against the configured FIPS codes, and it is deliberately
conservative: a multi-county NWS polygon must not be flagged county-wide, which
is what the ``_multi_county_list`` guard and the ``county_short`` term in the
``county_and_state`` test are for. Both are pinned by
``tests/test_detect_county_wide_false_positive.py``.

Shared by the geometry endpoint and the alert detail page, so it belongs to
neither.
"""

from typing import List


def _get_configured_fips_codes() -> List[str]:
    """Return the configured FIPS codes from LocationSettings (cached per-request)."""
    from app_core.location import get_location_settings
    settings = get_location_settings()
    return settings.get('fips_codes', []) if settings else []

def _detect_county_wide(alert) -> bool:
    """Determine whether an alert covers the configured county.

    Checks area_desc text patterns, SAME geocodes matching configured FIPS
    codes, and statewide SAME codes.  Returns True when the alert is known
    to cover the primary county.
    """
    is_county_wide = False

    # Load configured county/state so detection is not hardcoded to any
    # specific location (previously hardcoded to "Putnam County, Ohio").
    from app_core.location import get_location_settings
    settings = get_location_settings()
    configured_county_name = (settings.get('county_name', '') or '').lower().strip()
    configured_state_code = (settings.get('state_code', '') or '').lower().strip()

    # Short county name without the " county" suffix for looser matching.
    # e.g. "putnam county" → "putnam"
    county_short = configured_county_name.replace(' county', '').strip()

    # --- Text-based detection from area_desc ---
    if alert.area_desc:
        area_lower = alert.area_desc.lower().strip()

        # Exact configured county name or "entire county" phrase
        county_match = (
            (configured_county_name and configured_county_name in area_lower)
            or 'entire county' in area_lower
        )

        # Short county name appears alongside a multi-area list (e.g. "putnam; ... OH")
        # Guard: suppress this match when MULTIPLE counties from the same state are
        # listed (e.g. "Allen, OH; Putnam, OH; Van Wert, OH").  Those are multi-county
        # polygon alerts, not county-wide single-county alerts.  Detect by counting
        # how many times the pattern ", <state>" appears; more than one indicates a
        # list of counties, each with its state abbreviation.
        _multi_county_list = bool(
            configured_state_code
            and area_lower.count(f', {configured_state_code}') > 1
        )
        short_with_list = (
            county_short
            and county_short in area_lower
            and (area_lower.count(';') >= 2 or area_lower.count(',') >= 2)
            and not _multi_county_list
        )

        # Statewide text patterns (e.g. area_desc="Ohio" or "state of ohio")
        state_name_patterns = bool(
            configured_state_code
            and (
                area_lower == configured_state_code
                or f'state of {configured_state_code}' in area_lower
            )
        )

        # configured county name (short form) + state code anywhere in area_desc
        # Both must be present: checking only for "county" (as a generic word)
        # and the state code is insufficient because any alert from that state
        # containing a county name would match.  The short county name must
        # also appear in the description to avoid false positives for alerts
        # that target a *different* county in the same state.
        county_and_state = bool(
            county_short
            and configured_state_code
            and county_short in area_lower
            and 'county' in area_lower
            and configured_state_code in area_lower
        )

        is_county_wide = bool(county_match or short_with_list or state_name_patterns or county_and_state)

    # --- SAME geocode matching (statewide codes only) ---
    # Note: an exact county FIPS match (e.g. 039137) only means the alert
    # *affects* that county, not that it covers the entire county.  Only
    # statewide SAME codes (e.g. 039000) should trigger county-wide coverage.
    if not is_county_wide:
        raw_json = alert.raw_json if isinstance(alert.raw_json, dict) else {}
        same_codes = raw_json.get('properties', {}).get('geocode', {}).get('SAME', [])
        if same_codes:
            configured_fips = set(_get_configured_fips_codes())
            # Build the state-level code from each configured FIPS
            # e.g. 039137 -> 039000 (statewide Ohio)
            statewide_codes = set()
            for fips in configured_fips:
                if isinstance(fips, str) and len(fips) >= 3:
                    statewide_codes.add(fips[:3] + '000')

            for code in same_codes:
                if not isinstance(code, str):
                    continue
                # Statewide code for our state (e.g. 039000)
                if code in statewide_codes:
                    is_county_wide = True
                    break
                # Any code ending in 000 is statewide for some state;
                # check if it's our state
                if code.endswith('000') and len(code) >= 6:
                    state_prefix = code[:3]
                    if any(f.startswith(state_prefix) for f in configured_fips):
                        is_county_wide = True
                        break

    return is_county_wide

def _get_location_terms() -> tuple:
    """Return (county_short, county_name_lower, state_lower) from configured location settings.

    Used by the GeoJSON routes to determine county-wide coverage without
    hardcoding any specific location name.
    """
    from app_core.location import get_location_settings
    try:
        settings = get_location_settings() or {}
    except Exception:
        settings = {}
    county_name = (settings.get('county_name', '') or '').lower().strip()
    county_short = county_name.replace(' county', '').strip()
    state_lower = (settings.get('state_code', '') or '').lower().strip()
    return county_short, county_name, state_lower
