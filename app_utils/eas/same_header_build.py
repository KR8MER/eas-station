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

"""Building the SAME header and end-of-message burst for an outgoing broadcast."""

import math
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from app_utils.event_codes import resolve_event_code
from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS

from .same_header_constants import ORIGINATOR_DESCRIPTIONS



def _normalise_same_codes(values: Iterable[str]) -> List[str]:
    normalised: List[str] = []
    for value in values:
        digits = ''.join(ch for ch in str(value) if ch.isdigit())
        if digits:
            normalised.append(digits.zfill(6))
    return normalised




def _julian_time(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    julian_day = dt.timetuple().tm_yday
    return f"{julian_day:03d}{dt:%H%M}"




def _duration_code(sent: datetime, expires: Optional[datetime]) -> str:
    """Return the SAME TTTT duration field as a 4-character HHMM string.

    Per ECIG §3.4.1.4 and 47 CFR §11.31(b)(4), the TTTT field is HHMM, NOT
    decimal minutes.  Valid values follow these rounding rules:
      • ≤45 min  → round up to the nearest 15-min increment (0015/0030/0045)
      • >45 min  → round up to the nearest 30-min increment, max 0600 (6 hours)
    """
    if not sent or not expires:
        return '0015'
    delta = expires - sent
    total_minutes = delta.total_seconds() / 60.0
    if total_minutes <= 0:
        return '0015'  # expired; caller should handle the rejection
    if total_minutes <= 45:
        rounded = max(int(math.ceil(total_minutes / 15.0)) * 15, 15)
        return f"{rounded:04d}"  # 0015, 0030, 0045
    else:
        rounded_minutes = int(math.ceil(total_minutes / 30.0)) * 30
        rounded_minutes = min(rounded_minutes, 360)  # cap at 6 hours (0600)
        hours = rounded_minutes // 60
        mins = rounded_minutes % 60
        return f"{hours:02d}{mins:02d}"  # 0100, 0130, 0200, …, 0600




def _collect_event_code_candidates(alert: object, payload: Dict[str, object]) -> List[str]:
    candidates: List[str] = []

    def _extend(value) -> None:
        if value is None:
            return
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict):
            # NWS/IPAWS CAP-JSON (e.g. api.weather.gov) represents eventCode
            # as a dict keyed by valueName, e.g.
            # {'SAME': ['SVR'], 'NationalWeatherService': ['SVW']} -- 'SAME'
            # is the CAP-standard valueName carrying the 3-letter SAME code.
            # This branch used to be missing entirely, so a dict here (the
            # normal shape for every NWS-sourced alert) was silently
            # dropped and resolution always fell through to matching the
            # human-readable `event` name instead of the authoritative
            # SAME code the alert actually carried.
            for key in ('SAME', 'same'):
                if key in value:
                    _extend(value[key])
                    return
            # No SAME key -- don't drop the block entirely, but don't
            # guess either; other valueNames (e.g. 'NationalWeatherService')
            # aren't SAME codes and normalise_event_code() will reject
            # anything that isn't a 3-char alnum token anyway.
            for nested in value.values():
                _extend(nested)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if item is not None:
                    candidates.append(str(item))

    for key in ('event_code', 'eventCode', 'primary_event_code'):
        if key in payload:
            _extend(payload[key])
    for key in ('event_codes', 'eventCodes'):
        if key in payload:
            _extend(payload[key])

    raw_sources = []
    for container in (payload.get('raw_json'), getattr(alert, 'raw_json', None)):
        if isinstance(container, dict):
            props = container.get('properties') or {}
            raw_sources.append(props)
        else:
            raw_sources.append(None)

    for props in raw_sources:
        if not isinstance(props, dict):
            continue
        for key in ('event_code', 'eventCode', 'primary_event_code'):
            if key in props:
                _extend(props[key])
        for key in ('event_codes', 'eventCodes'):
            if key in props:
                _extend(props[key])

    ordered: List[str] = []
    seen = set()
    for candidate in candidates:
        text = str(candidate).strip()
        if not text:
            continue
        if text not in seen:
            seen.add(text)
            ordered.append(text)

    return ordered




def build_same_header(alert: object, payload: Dict[str, object], config: Dict[str, object],
                      location_settings: Optional[Dict[str, object]] = None) -> Tuple[str, List[str], str]:
    event_name = (getattr(alert, 'event', '') or '').strip()
    event_candidates = _collect_event_code_candidates(alert, payload)
    event_code = resolve_event_code(event_name, event_candidates)
    if not event_code:
        pretty_event = event_name or (payload.get('event') or '').strip() or 'unknown event'
        raise ValueError(f'No authorised SAME event code available for {pretty_event}.')
    if 'resolved_event_code' not in payload:
        payload['resolved_event_code'] = event_code

    geocode = (payload.get('raw_json', {}) or {}).get('properties', {}).get('geocode', {})
    same_codes = []

    # ECIG §3.10: FIPS6 geocodes shall be treated the same as SAME geocodes.
    for key in ('SAME', 'same', 'SAMEcodes', 'FIPS6', 'fips6'):
        values = geocode.get(key)
        if values:
            if isinstance(values, (list, tuple)):
                same_codes.extend(str(v).strip() for v in values)
            else:
                same_codes.append(str(values).strip())
            break  # stop at the first key that has data; don't accumulate across keys
    same_codes = [code for code in same_codes if code and code != 'None']

    zone_codes: List[str] = []
    if location_settings:
        zone_codes = location_settings.get('zone_codes') or []

    # Filter SAME codes to only those within the configured broadcast area.
    # Alerts may cover many counties; we only forward the codes that match our
    # area so the SAME header reflects our actual coverage, not the full alert area.
    if same_codes and location_settings:
        configured_raw = (
            location_settings.get('fips_codes')
            or location_settings.get('same_codes')
            or []
        )
        configured_normalised = set(
            _normalise_same_codes([str(c).strip() for c in configured_raw if str(c).strip()])
        )
        if configured_normalised:
            filtered: List[str] = []
            for code in same_codes:
                norm = ''.join(ch for ch in str(code) if ch.isdigit()).zfill(6)
                # Nationwide (000000) and statewide (SS000) wildcards are preserved
                # as-is — they must not be stripped by the per-county filter or the
                # fallback will replace them with all configured FIPS codes, producing
                # an incorrect broadcast header.
                if norm == '000000' or (norm.endswith('000') and norm != '000000'):
                    filtered.append(code)
                elif norm in configured_normalised:
                    filtered.append(code)
            # Use filtered list; if nothing matched fall through to fallback below.
            same_codes = filtered

    if not same_codes and location_settings:
        fallback_same_raw = (
            location_settings.get('same_codes')
            or location_settings.get('fips_codes')
            or []
        )
        fallback_same = [str(code).strip() for code in fallback_same_raw if str(code).strip()]
        default_fips = [
            str(code).strip()
            for code in DEFAULT_LOCATION_SETTINGS.get('fips_codes', [])
            if str(code).strip()
        ]
        fallback_normalised = _normalise_same_codes(fallback_same)
        default_normalised = _normalise_same_codes(default_fips)
        fallback_matches_default = (
            bool(fallback_normalised)
            and fallback_normalised == default_normalised
            and bool(zone_codes)
        )
        if fallback_same and not fallback_matches_default:
            same_codes = fallback_same

    if not same_codes and zone_codes:
        same_codes = [code.replace('O', '').upper().replace(' ', '') for code in zone_codes]

    formatted_locations = _normalise_same_codes(same_codes)
    # FCC 47 CFR §11.31 limits SAME headers to 31 location codes
    if len(formatted_locations) > 31:
        formatted_locations = formatted_locations[:31]

    if not formatted_locations:
        formatted_locations = ['000000']

    sent = getattr(alert, 'sent', None) or payload.get('sent')
    expires = getattr(alert, 'expires', None) or payload.get('expires')
    sent_dt = sent if isinstance(sent, datetime) else None
    expires_dt = expires if isinstance(expires, datetime) else None

    duration_code = _duration_code(sent_dt, expires_dt)
    julian = _julian_time(sent_dt or datetime.now(timezone.utc))

    # ECIG §3.4.1.1: originator SHALL come from the CAP alert's EAS-ORG parameter
    # when present and valid; fall back to station config only as a last resort.
    originator = None
    try:
        params = (payload.get('raw_json', {}) or {}).get('properties', {}).get('parameters', {})
        if isinstance(params, dict):
            eas_org_val = params.get('EAS-ORG')
            if isinstance(eas_org_val, list):
                eas_org_val = eas_org_val[0] if eas_org_val else None
            if eas_org_val:
                candidate = str(eas_org_val).strip().upper()
                if candidate in ORIGINATOR_DESCRIPTIONS:
                    originator = candidate
    except Exception:
        pass
    if not originator:
        originator = str(config.get('originator', 'WXR'))[:3].upper()
    station = str(config.get('station_id', 'EASNODES')).strip()[:8]

    location_field = '-'.join(formatted_locations)
    header = f"ZCZC-{originator}-{event_code}-{location_field}+{duration_code}-{julian}-{station}-"

    return header, formatted_locations, event_code




def build_eom_header(config: Dict[str, object]) -> str:
    """Return the EOM payload per 47 CFR §11.31(c).

    The End Of Message burst is simply the ASCII string ``NNNN`` framed by the
    SAME preamble. No originator, location, or timing fields are transmitted.
    """

    return "NNNN"
