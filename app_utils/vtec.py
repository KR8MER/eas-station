"""VTEC (Valid Time Event Code) parsing utilities.

Provides two public functions:

  extract_vtec_identity(raw_json)
      Extracts the five event-key fields and the action code from a CAP
      alert's raw_json dict.  Used at ingest time to populate indexed columns
      on CAPAlert so related updates can be found with a simple query.

  parse_vtec_display(raw_str)
      Fully decodes a single VTEC string into a display-ready dict with
      human-readable labels for every field.  Used by the alert detail view.

Both functions are safe to call on bad/missing input — they return None /
partial dicts rather than raising.

Official reference: NWS Directive 10-1703 ver 9 (March 2025)
https://www.weather.gov/media/vtec/VTEC_explanation_ver9.pdf
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Lookup tables (sourced from NWS Directive 10-1703 ver 9, March 2025)
# ---------------------------------------------------------------------------

VTEC_ACTIONS: Dict[str, str] = {
    'NEW': 'New Event',
    'CON': 'Continuing',
    'EXA': 'Extended in Area',
    'EXT': 'Extended in Time',
    'EXB': 'Extended in Area and Time',
    'CAN': 'Cancelled',
    'EXP': 'Expired',
    'UPG': 'Upgraded',
    'COR': 'Correction',
    'ROU': 'Routine',
}

# Actions that should trigger a new or updated EAS broadcast
VTEC_BROADCAST_ACTIONS = frozenset({'NEW', 'EXT', 'EXA', 'EXB', 'UPG'})

# Actions where a prior broadcast already covers this event — skip rebroadcast.
# COR per NWSI 10-1703 §2.1.2 corrects only non-VTEC/non-UGC text errors in a
# previously-issued event, so it must not re-tone an event that is already on air.
VTEC_SKIP_ACTIONS = frozenset({'CON', 'ROU', 'COR'})

# Actions that represent the event ending
VTEC_TERMINAL_ACTIONS = frozenset({'CAN', 'EXP'})

# Current phenomenon codes (NWS Directive 10-1703 ver 9)
VTEC_PHENOMENA: Dict[str, str] = {
    'AF': 'Ashfall',
    'AS': 'Air Stagnation',
    'BH': 'Beach Hazard',
    'BW': 'Brisk Wind',
    'BZ': 'Blizzard',
    'CF': 'Coastal Flood',
    'CW': 'Cold Weather',
    'DF': 'Debris Flow',
    'DS': 'Dust Storm',
    'DU': 'Blowing Dust',
    'EC': 'Extreme Cold',
    'EW': 'Extreme Wind',
    'FA': 'Flood',
    'FF': 'Flash Flood',
    'FG': 'Dense Fog',
    'FL': 'Flood',
    'FR': 'Frost',
    'FW': 'Fire Weather',
    'FZ': 'Freeze',
    'GL': 'Gale',
    'HF': 'Hurricane Force Wind',
    'HT': 'Heat',
    'HU': 'Hurricane',
    'HW': 'High Wind',
    'HY': 'Hydrologic',
    'IS': 'Ice Storm',
    'LE': 'Lake-Effect Snow',
    'LO': 'Low Water',
    'LS': 'Lakeshore Flood',
    'LW': 'Lake Wind',
    'MA': 'Marine',
    'MF': 'Marine Dense Fog',
    'MH': 'Marine Ashfall',
    'MS': 'Marine Dense Smoke',
    'RB': 'Small Craft for Rough Bar',
    'RP': 'Rip Current Risk',
    'SC': 'Small Craft',
    'SE': 'Hazardous Seas',
    'SI': 'Small Craft for Winds',
    'SM': 'Dense Smoke',
    'SQ': 'Snow Squall',
    'SR': 'Storm',
    'SS': 'Storm Surge',
    'SU': 'High Surf',
    'SV': 'Severe Thunderstorm',
    'SW': 'Small Craft for Hazardous Seas',
    'TO': 'Tornado',
    'TR': 'Tropical Storm',
    'TS': 'Tsunami',
    'TY': 'Typhoon',
    'UP': 'Freezing Spray',
    'WI': 'Wind',
    'WS': 'Winter Storm',
    'WW': 'Winter Weather',
    'XH': 'Extreme Heat',
    'ZF': 'Freezing Fog',
    'ZR': 'Freezing Rain',
    # Legacy codes retained for archived alert decoding
    'BS': 'Blowing Snow',
    'EH': 'Excessive Heat',
    'HI': 'Inland Hurricane Wind',
    'HS': 'Heavy Snow',
    'HZ': 'Hard Freeze',
    'IP': 'Sleet',
    'LB': 'Lake-Effect Snow and Blowing Snow',
    'SN': 'Snow',
    'TI': 'Inland Tropical Storm Wind',
    'WC': 'Wind Chill',
}

VTEC_SIGNIFICANCE: Dict[str, str] = {
    'W': 'Warning',
    'A': 'Watch',
    'Y': 'Advisory',
    'S': 'Statement',
    'F': 'Forecast',
    'O': 'Outlook',
    'N': 'Synopsis',
}

VTEC_PROGRAMS: Dict[str, str] = {
    'O': 'Operational',
    'T': 'Test',
    'E': 'Exercise',
    'X': 'Experimental',
}

# P-VTEC regex — format: k.aaa.cccc.pp.s.####.yymmddThhnnZ-yymmddThhnnZ
# Time group: 6-digit date (yymmdd) + T + 4-digit time (hhnn) + Z
_VTEC_RE = re.compile(
    r'([OTEX])\.'          # k   — product class
    r'([A-Z]{2,3})\.'      # aaa — action
    r'([A-Z]{4})\.'        # cccc — office ID
    r'([A-Z]{2})\.'        # pp  — phenomenon
    r'([WAYSFON])\.'       # s   — significance (Appendix A: W/A/Y/S/F/O/N)
    r'(\d{4})\.'           # #### — ETN
    r'(\d{6}T\d{4}Z)'     # begin time (yymmddThhnnZ)
    r'-'
    r'(\d{6}T\d{4}Z)',     # end time (yymmddThhnnZ)
)

# All-zeros sentinel: event was already ongoing when product was issued
_VTEC_TIME_ZERO = '000000T0000Z'


def _decode_vtec_time(s: str) -> Optional[str]:
    """Convert a VTEC yymmddThhnnZ string to a human-readable UTC string.

    Returns None for the all-zeros ongoing sentinel.
    """
    if s == _VTEC_TIME_ZERO:
        return None
    try:
        dt = datetime.strptime(s, '%y%m%dT%H%MZ').replace(tzinfo=timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M UTC')
    except ValueError:
        return s


def _vtec_year_from_time(s: str) -> Optional[int]:
    """Extract the 4-digit year from a VTEC time string, or None for zeros."""
    if s == _VTEC_TIME_ZERO:
        return None
    try:
        return datetime.strptime(s, '%y%m%dT%H%MZ').year
    except ValueError:
        return None


def _parse_raw(raw: str) -> Optional[re.Match]:
    """Strip delimiters and run the regex. Returns the match or None."""
    return _VTEC_RE.search(raw.strip().strip('/'))


# Per NWSI 10-1703 §3.1 / Table 2, an upgrade or downgrade/replacement segment
# carries two P-VTEC strings: the first ends the old event (UPG or CAN); the
# second creates/updates the new event (NEW, EXA, EXB, EXT, CON, or COR).  The
# segment's primary identity is the second string.
_PAIRED_LEAD_ACTIONS = frozenset({'UPG', 'CAN'})
_PAIRED_FOLLOW_ACTIONS = frozenset({'NEW', 'EXA', 'EXB', 'EXT', 'CON', 'COR'})


def _select_primary_vtec(vtec_list: List[str]) -> Optional[re.Match]:
    """Pick the VTEC string that represents the alert's primary event.

    For an UPG/CAN-paired segment (§3.1) the second string is the new event
    being created; treat it as primary.  Otherwise use the first string.
    """
    if not vtec_list:
        return None

    first = _parse_raw(vtec_list[0])
    if first is None:
        # First string unparseable — try the rest in order before giving up.
        for raw in vtec_list[1:]:
            m = _parse_raw(raw)
            if m is not None:
                return m
        return None

    if first.group(2) in _PAIRED_LEAD_ACTIONS and len(vtec_list) >= 2:
        second = _parse_raw(vtec_list[1])
        if second is not None and second.group(2) in _PAIRED_FOLLOW_ACTIONS:
            return second

    return first


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_vtec_identity(raw_json: Any) -> Optional[Dict[str, Any]]:
    """Extract VTEC event-key fields from a CAP alert's raw_json dict.

    Returns a dict with keys:
      vtec_office, vtec_phenomenon, vtec_significance,
      vtec_etn, vtec_year, vtec_action

    Returns None if no parseable P-VTEC string is found, or if raw_json is
    not a dict.  Only the first (primary) VTEC string is used.
    """
    if not isinstance(raw_json, dict):
        return None

    vtec_list: List[str] = (
        raw_json.get('properties', {})
        .get('parameters', {})
        .get('VTEC', [])
    )
    m = _select_primary_vtec(vtec_list)
    if not m:
        return None

    prog, action, office, phen, sig, etn_str, begin_raw, end_raw = m.groups()

    # NWSI 10-1703 §2.1.6: ETN is anchored to the year of the NEW issuance and
    # carries forward even when the event extends into the next calendar year.
    # Prefer begin time so an EXT that pushes the end time across a year
    # boundary doesn't break the (office, phen, sig, etn, year) chain key.
    # Fall back to end time only when begin is the all-zeros "ongoing" sentinel.
    year = _vtec_year_from_time(begin_raw) or _vtec_year_from_time(end_raw)

    return {
        'vtec_office':       office,
        'vtec_phenomenon':   phen,
        'vtec_significance': sig,
        'vtec_etn':          int(etn_str),
        'vtec_year':         year,
        'vtec_action':       action,
    }


def parse_vtec_display(raw: str) -> Dict[str, Any]:
    """Fully decode a single VTEC string into a display-ready dict.

    Always returns a dict.  The ``raw`` key is always present.  All other
    keys are omitted if the string cannot be parsed.
    """
    result: Dict[str, Any] = {'raw': raw}

    m = _parse_raw(raw)
    if not m:
        return result

    prog, action, office, phen, sig, etn_str, begin_raw, end_raw = m.groups()

    year = _vtec_year_from_time(begin_raw) or _vtec_year_from_time(end_raw)

    result.update({
        'program':            prog,
        'program_label':      VTEC_PROGRAMS.get(prog, prog),
        'action':             action,
        'action_label':       VTEC_ACTIONS.get(action, action),
        'office':             office,
        'phenomenon':         phen,
        'phenomenon_label':   VTEC_PHENOMENA.get(phen, phen),
        'significance':       sig,
        'significance_label': VTEC_SIGNIFICANCE.get(sig, sig),
        'event_number':       str(int(etn_str)),  # strip leading zeros
        'year':               year,
        'begin':              _decode_vtec_time(begin_raw),
        'end':                _decode_vtec_time(end_raw),
    })
    return result


def vtec_event_key(
    office: str,
    phenomenon: str,
    significance: str,
    etn: int,
    year: int,
) -> Tuple[str, str, str, int, int]:
    """Return the canonical event key tuple for use in queries and comparisons."""
    return (office, phenomenon, significance, etn, year)


__all__ = [
    'VTEC_ACTIONS',
    'VTEC_BROADCAST_ACTIONS',
    'VTEC_SKIP_ACTIONS',
    'VTEC_TERMINAL_ACTIONS',
    'VTEC_PHENOMENA',
    'VTEC_SIGNIFICANCE',
    'VTEC_PROGRAMS',
    'extract_vtec_identity',
    'parse_vtec_display',
    'vtec_event_key',
]
