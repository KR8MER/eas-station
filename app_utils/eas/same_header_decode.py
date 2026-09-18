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

"""Decoding and describing a received SAME header."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app_utils.event_codes import EVENT_CODE_REGISTRY

from .same_header_constants import (
    COUNTY_ABBREVIATIONS,
    NRSC4B_MAX_LOCATIONS,
    NRSC4B_STATION_ID_MAX_LEN,
    NRSC4B_VALID_ORIGINATORS,
    NRSC4B_VALID_PURGE_TIMES,
    ORIGINATOR_DESCRIPTIONS,
    P_DIGIT_MEANINGS,
    _NRSC4B_FIELD_FLAGS,
)


def decode_county_originator(originator_code: str) -> Optional[str]:
    """
    Decode county-based originator codes.

    Format: XXXXCOEM or XXXXCOSO
    Where:
    - XXXX = 4-letter county abbreviation
    - CO = County
    - EM = Emergency Management
    - SO = Sheriff's Office

    Examples:
    - PUTNCOSO = Putnam County Sheriff's Office
    - PUTNCOEM = Putnam County Emergency Management
    """
    code = originator_code.upper().strip()

    # Check if it matches the county pattern (8 characters)
    if len(code) != 8:
        return None

    # Extract components
    county_abbr = code[:4]
    middle = code[4:6]  # Should be 'CO'
    suffix = code[6:8]  # Either 'EM' or 'SO'

    # Validate the middle part
    if middle != 'CO':
        return None

    # Get county name
    county_name = COUNTY_ABBREVIATIONS.get(county_abbr)
    if not county_name:
        return None

    # Decode the suffix
    if suffix == 'EM':
        return f"{county_name} County Emergency Management"
    elif suffix == 'SO':
        return f"{county_name} County Sheriff's Office"

    return None



def describe_same_header(
    header: str,
    lookup: Optional[Dict[str, str]] = None,
    state_index: Optional[Dict[str, Dict[str, object]]] = None,
) -> Dict[str, object]:
    """Break a SAME header into its constituent fields for display."""

    if not header:
        return {}

    header = header.strip()
    if not header:
        return {}

    parts = header.split('-')
    if not parts or parts[0] != 'ZCZC':
        return {}

    originator = parts[1] if len(parts) > 1 else ''
    event_code = parts[2] if len(parts) > 2 else ''
    event_entry = EVENT_CODE_REGISTRY.get(event_code)
    event_name = event_entry.get('name') if event_entry else None

    locations: List[str] = []
    duration_fragment = ''
    index = 3

    while index < len(parts):
        fragment = parts[index]
        if '+' in fragment:
            loc_part, duration_fragment = fragment.split('+', 1)
            if loc_part:
                locations.append(loc_part)
            index += 1
            break
        if fragment:
            locations.append(fragment)
        index += 1

    julian_fragment = parts[index] if index < len(parts) else ''
    station_identifier = parts[index + 1] if index + 1 < len(parts) else ''

    duration_digits = ''.join(ch for ch in duration_fragment if ch.isdigit())[:4]
    # TTTT is HHMM, not decimal minutes (ECIG §3.4.1.4 / 47 CFR §11.31(b)(4)).
    # e.g. "0100" = 1 h 00 m = 60 min, not 100 min.
    if len(duration_digits) == 4:
        purge_minutes = int(duration_digits[:2]) * 60 + int(duration_digits[2:])
    elif duration_digits.isdigit():
        purge_minutes = int(duration_digits)
    else:
        purge_minutes = None

    def _format_duration(value: Optional[int]) -> Optional[str]:
        if value is None:
            return None
        if value == 0:
            return '0 minutes (immediate purge)'
        if value % 60 == 0:
            hours = value // 60
            return f"{hours} hour{'s' if hours != 1 else ''}"
        return f"{value} minute{'s' if value != 1 else ''}"

    julian_digits = ''.join(ch for ch in julian_fragment if ch.isdigit())[:7]
    issue_time_iso: Optional[str] = None
    issue_time_label: Optional[str] = None
    issue_components: Optional[Dict[str, int]] = None

    if len(julian_digits) == 7:
        try:
            ordinal = int(julian_digits[:3])
            hour = int(julian_digits[3:5])
            minute = int(julian_digits[5:7])
            base_year = datetime.now(timezone.utc).year
            issue_dt = datetime(base_year, 1, 1, tzinfo=timezone.utc) + timedelta(
                days=ordinal - 1,
                hours=hour,
                minutes=minute,
            )
            issue_time_iso = issue_dt.isoformat()
            issue_time_label = f"Day {ordinal:03d} at {hour:02d}:{minute:02d} UTC"
            issue_components = {'day_of_year': ordinal, 'hour': hour, 'minute': minute}
        except ValueError:
            issue_time_iso = None
            issue_time_label = None
            issue_components = None

    detailed_locations: List[Dict[str, object]] = []
    lookup = lookup or {}
    state_index = state_index or {}

    for entry in locations:
        digits = ''.join(ch for ch in entry if ch.isdigit()).zfill(6)[:6]
        if not digits:
            continue
        p_digit = digits[0]
        state_digits = digits[1:3]
        county_digits = digits[3:]
        state_info = state_index.get(state_digits) or {}
        state_name = state_info.get('name') or ''
        state_abbr = state_info.get('abbr') or state_digits
        description = lookup.get(digits)
        is_statewide = county_digits == '000'
        if is_statewide and not description:
            description = f"All Areas, {state_abbr}"

        detailed_locations.append({
            'code': digits,
            'p_digit': p_digit,
            'p_meaning': P_DIGIT_MEANINGS.get(p_digit),
            'state_fips': state_digits,
            'state_name': state_name or state_abbr,
            'state_abbr': state_abbr,
            'county_fips': county_digits,
            'is_statewide': is_statewide,
            'description': description or digits,
        })

    # ── NRSC-4-B compliance checks ────────────────────────────────────────
    # §4.3.3.2 — originator must be one of EAS, CIV, WXR, PEP.
    nrsc4b_valid_originator: bool = originator in NRSC4B_VALID_ORIGINATORS
    # §4.3.3.3 — event code must be a registered SAME code.
    nrsc4b_valid_event: bool = event_code in EVENT_CODE_REGISTRY
    # §4.3.3.4 — purge time must be one of the fourteen defined HHMM values.
    nrsc4b_valid_purge: bool = (duration_digits in NRSC4B_VALID_PURGE_TIMES)
    # §4.3.3.5 — issue time must be seven digits with valid JJJ/HH/MM ranges.
    _issue_valid = False
    if issue_components:
        try:
            _jjj = issue_components['day_of_year']
            _hh = issue_components['hour']
            _mm = issue_components['minute']
            _issue_valid = (1 <= _jjj <= 366) and (0 <= _hh <= 23) and (0 <= _mm <= 59)
        except (KeyError, TypeError, ValueError):
            pass
    nrsc4b_valid_issue_time: bool = _issue_valid
    # §4.3.3.3 — one to thirty-one location codes required.
    _loc_count = len(detailed_locations)
    nrsc4b_valid_location_count: bool = 1 <= _loc_count <= NRSC4B_MAX_LOCATIONS
    # §4.3.3.6 — station identifier must be 1–8 printable ASCII characters.
    _sid = station_identifier.strip('-')
    nrsc4b_valid_station_id: bool = bool(_sid) and len(_sid) <= NRSC4B_STATION_ID_MAX_LEN
    # Overall NRSC-4-B compliance flag.
    nrsc4b_compliant: bool = (
        nrsc4b_valid_originator
        and nrsc4b_valid_event
        and nrsc4b_valid_purge
        and nrsc4b_valid_issue_time
        and nrsc4b_valid_location_count
        and nrsc4b_valid_station_id
    )

    # ── Convenience decompositions ────────────────────────────────────────
    purge_hh: Optional[int] = int(duration_digits[:2]) if len(duration_digits) == 4 else None
    purge_mm: Optional[int] = int(duration_digits[2:]) if len(duration_digits) == 4 else None
    issue_day_of_year: Optional[int] = (
        issue_components['day_of_year'] if issue_components else None
    )
    issue_hour: Optional[int] = (
        issue_components['hour'] if issue_components else None
    )
    issue_minute: Optional[int] = (
        issue_components['minute'] if issue_components else None
    )
    # Raw station identifier as received (may include trailing dashes used as padding).
    station_identifier_raw: str = station_identifier

    return {
        # ── Structural fields ──────────────────────────────────────────────
        'preamble': parts[0] if parts else 'ZCZC',
        'preamble_description': (
            'SAME headers begin with a sixteen-byte 0xAB preamble for receiver synchronisation.'
        ),
        'start_code': parts[0] if parts else 'ZCZC',
        'header_length': len(header),
        'header_parts': parts,
        # ── Originator (NRSC-4-B §4.3.3.2) ───────────────────────────────
        'originator': originator,
        'originator_description': ORIGINATOR_DESCRIPTIONS.get(originator),
        'nrsc4b_valid_originator': nrsc4b_valid_originator,
        # ── Event code (NRSC-4-B §4.3.3.3) ───────────────────────────────
        'event_code': event_code,
        'event_name': event_name,
        'nrsc4b_valid_event': nrsc4b_valid_event,
        # ── Location codes (NRSC-4-B §4.3.3.3) ───────────────────────────
        'location_count': _loc_count,
        'location_count_valid': nrsc4b_valid_location_count,
        'locations': detailed_locations,
        'raw_locations': locations,
        # ── Purge time (NRSC-4-B §4.3.3.4) ───────────────────────────────
        'purge_code': duration_digits or None,
        'purge_hh': purge_hh,
        'purge_mm': purge_mm,
        'purge_minutes': purge_minutes,
        'purge_label': _format_duration(purge_minutes),
        'nrsc4b_valid_purge': nrsc4b_valid_purge,
        # ── Issue time (NRSC-4-B §4.3.3.5) ───────────────────────────────
        'issue_code': julian_digits or None,
        'issue_day_of_year': issue_day_of_year,
        'issue_hour': issue_hour,
        'issue_minute': issue_minute,
        'issue_time_label': issue_time_label,
        'issue_time_iso': issue_time_iso,
        'issue_components': issue_components,
        'nrsc4b_valid_issue_time': nrsc4b_valid_issue_time,
        # ── Station identifier (NRSC-4-B §4.3.3.6) ───────────────────────
        'station_identifier': station_identifier,
        'station_identifier_raw': station_identifier_raw,
        'nrsc4b_valid_station_id': nrsc4b_valid_station_id,
        # ── Overall NRSC-4-B compliance ────────────────────────────────────
        'nrsc4b_compliant': nrsc4b_compliant,
    }




def score_decode_confidence(
    fields: Optional[Dict[str, object]],
    signal_margin: float,
) -> float:
    """Score how likely a decoded SAME header is correct, in [0.0, 1.0].

    The DSP layer reports ``signal_margin`` = mean per-bit
    ``|mark_power - space_power| / (mark_power + space_power)``.  Because the
    SAME mark (2083.3 Hz) and space (1562.5 Hz) tones are separated by exactly
    one baud (520.83 Hz), a single bit period gives only ~520 Hz of frequency
    resolution, so the two Goertzel/correlator bins overlap heavily.  Each bin
    captures a large share of the other tone's energy even on a flawless
    transmission, which floors this margin near 0.5 regardless of how clean the
    decode is.  Displaying it directly makes every real alert look "low
    confidence" (~50-55%).

    This function instead derives confidence from what actually proves a good
    decode: the structural / NRSC-4-B field validity already computed by
    :func:`describe_same_header`.  SAME has no per-byte checksum — its error
    protection is the 3x burst repetition plus self-consistent framing — so a
    header whose originator, event code, purge time, issue time, location count
    and station ID all independently parse to spec-valid values is, for
    practical purposes, a verified decode.  Random bit errors are very unlikely
    to land on six simultaneously-valid fields.

    Args:
        fields: Parsed field dict from :func:`describe_same_header`.  An empty
            or ``None`` dict (e.g. an ``NNNN`` EOM or an unparseable header)
            falls back to ``signal_margin`` so the caller's forward gate still
            has a value to act on.
        signal_margin: Raw mean per-bit tone margin in [0.0, 1.0].

    Returns:
        A confidence score in [0.0, 1.0].  Fully NRSC-4-B-compliant headers
        floor high (>=0.95) so a clean alert never displays as low confidence;
        weakly-valid headers never read *higher* than their raw signal margin,
        keeping the forward gate conservative against garbled decodes.
    """
    try:
        margin = float(signal_margin)
    except (TypeError, ValueError):
        margin = 0.0
    margin = max(0.0, min(1.0, margin))

    if not fields:
        # No parseable header to corroborate the bits — the signal margin is
        # the only evidence we have.
        return margin

    passed = sum(1 for flag in _NRSC4B_FIELD_FLAGS if fields.get(flag))
    structural = passed / len(_NRSC4B_FIELD_FLAGS)

    # When fewer than half the fields validate, the structure is too weak to
    # trust; fall back to the raw signal margin so we never *inflate* a suspect
    # decode above what its FSK quality alone would justify.
    if structural < 0.5:
        return margin

    # Structural validity dominates (it is decode-correctness evidence); the
    # signal margin contributes a minority weight so that among equally-valid
    # decodes, cleaner audio still ranks slightly higher.
    confidence = 0.6 * structural + 0.4 * margin

    if fields.get('nrsc4b_compliant'):
        # Every field independently parsed to a spec-valid value — treat as a
        # verified decode and floor the score high, nudged by signal quality.
        confidence = max(confidence, 0.95 + 0.05 * margin)

    return max(0.0, min(1.0, confidence))
