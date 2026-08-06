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

"""US FIPS county code reference data."""

from pathlib import Path
from types import MappingProxyType
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple


STATE_ABBR_NAMES: Dict[str, str] = {
    'AL': 'Alabama',
    'AK': 'Alaska',
    'AZ': 'Arizona',
    'AR': 'Arkansas',
    'CA': 'California',
    'CO': 'Colorado',
    'CT': 'Connecticut',
    'DE': 'Delaware',
    'DC': 'District of Columbia',
    'FL': 'Florida',
    'GA': 'Georgia',
    'HI': 'Hawaii',
    'ID': 'Idaho',
    'IL': 'Illinois',
    'IN': 'Indiana',
    'IA': 'Iowa',
    'KS': 'Kansas',
    'KY': 'Kentucky',
    'LA': 'Louisiana',
    'ME': 'Maine',
    'MD': 'Maryland',
    'MA': 'Massachusetts',
    'MI': 'Michigan',
    'MN': 'Minnesota',
    'MS': 'Mississippi',
    'MO': 'Missouri',
    'MT': 'Montana',
    'NE': 'Nebraska',
    'NV': 'Nevada',
    'NH': 'New Hampshire',
    'NJ': 'New Jersey',
    'NM': 'New Mexico',
    'NY': 'New York',
    'NC': 'North Carolina',
    'ND': 'North Dakota',
    'OH': 'Ohio',
    'OK': 'Oklahoma',
    'OR': 'Oregon',
    'PA': 'Pennsylvania',
    'RI': 'Rhode Island',
    'SC': 'South Carolina',
    'SD': 'South Dakota',
    'TN': 'Tennessee',
    'TX': 'Texas',
    'UT': 'Utah',
    'VT': 'Vermont',
    'VA': 'Virginia',
    'WA': 'Washington',
    'WV': 'West Virginia',
    'WI': 'Wisconsin',
    'WY': 'Wyoming',
    'AS': 'American Samoa',
    'GU': 'Guam',
    'MP': 'Northern Mariana Islands',
    'PR': 'Puerto Rico',
    'VI': 'U.S. Virgin Islands',
    'US': 'United States',
}

NATIONWIDE_SAME_CODE = '000000'
NATIONWIDE_LABEL = 'Entire United States'

P_DIGIT_LABELS = {
    '0': 'Entire area',
    '1': 'Northwest portion',
    '2': 'North central portion',
    '3': 'Northeast portion',
    '4': 'West central portion',
    '5': 'Central portion',
    '6': 'East central portion',
    '7': 'Southwest portion',
    '8': 'South central portion',
    '9': 'Southeast portion',
}

# Data sourced from FCC / US Census FIPS code list (national_county.txt).
# Format: STATEFP + COUNTYFP -> "County Name, ST"
COUNTY_TABLE_PATH = Path(__file__).resolve().parent / 'data' / 'us_fips_counties.txt'


def _load_county_table() -> str:
    """Read the pipe-delimited county reference table shipped alongside this module.

    The table is data, not code, so it lives in ``app_utils/data/`` rather than
    inline. Each line is ``STATEFP+COUNTYFP|ST|County Name``.
    """

    try:
        return COUNTY_TABLE_PATH.read_text(encoding='utf-8')
    except OSError as exc:
        import logging as _logging
        _logging.getLogger(__name__).error(
            "Unable to read the US FIPS county table at %s: %s. "
            "County SAME code lookups will be empty.",
            COUNTY_TABLE_PATH,
            exc,
        )
        return ''


US_FIPS_COUNTY_TABLE = _load_county_table()


def _to_same_county_code(code: str) -> str:
    """Convert a county FIPS code into a 6-digit SAME code with portion digit.

    SAME codes are formatted as PSSCCC where:
    - P = portion digit (0 = entire county, 1-9 = subdivisions)
    - SS = state FIPS code
    - CCC = county FIPS code

    For county codes from the FIPS table (5 digits), this function prepends '0'
    to indicate "entire county".
    """

    digits = ''.join(ch for ch in code if ch.isdigit())
    if not digits:
        raise ValueError(f'Invalid county code: {code!r}')
    # If 5 digits, prepend '0' for "entire county" portion digit
    if len(digits) == 5:
        return '0' + digits
    # If 6 digits, return as-is (already has portion digit)
    if len(digits) == 6:
        return digits
    # For other lengths, normalize to 5 digits then prepend '0'
    normalized = digits.zfill(5)[-5:]
    return '0' + normalized


def _format_subdivision_display_name(
    county_label: str, raw_county: str, area_name: str, area_code: str
) -> str:
    portion = P_DIGIT_LABELS.get(area_code[:1], 'Partial area')
    canonical_county = (county_label or '').strip()
    raw_name = (raw_county or '').strip()
    area = (area_name or '').strip()

    if area and raw_name and area.lower() == raw_name.lower():
        if portion != 'Entire area' and canonical_county:
            return f"{portion} {canonical_county}".strip()
        return canonical_county or area

    if area:
        if raw_name and raw_name.lower() not in area.lower() and canonical_county:
            return f"{area} ({canonical_county})"
        return area

    if portion != 'Entire area' and canonical_county:
        return f"{portion} {canonical_county}".strip()

    return canonical_county or area_code


def _format_subdivision_label(
    county_label: str, raw_county: str, area_name: str, area_code: str, state_abbr: str
) -> str:
    display_name = _format_subdivision_display_name(
        county_label, raw_county, area_name, area_code
    )
    state = (state_abbr or '').strip()
    if state:
        return f"{display_name}, {state}"
    return display_name


def _resolve_partial_county_dbf() -> Optional[Path]:
    """Find the NWS partial-county DBF, or return None with a log hint."""
    import os as _os

    # 1. Explicit override via environment variable
    env_path = _os.environ.get('NWS_PARTIAL_COUNTIES_DBF')
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        # Configured but missing – warn and fall through to auto-detect
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "NWS_PARTIAL_COUNTIES_DBF is set to %s but the file does not exist; "
            "ignoring and attempting auto-detection.",
            env_path,
        )

    # 2. Auto-detect: newest cs*.dbf in the assets directory
    assets_root = Path(__file__).resolve().parents[1] / 'assets'
    if assets_root.is_dir():
        candidates = sorted(assets_root.glob('cs*.dbf'), reverse=True)
        if candidates:
            return candidates[0]

    # 3. Not found – log an actionable hint once
    import logging as _logging
    _logging.getLogger(__name__).info(
        "NWS partial-county (political subdivision) data not found in assets/. "
        "Partition-digit SAME codes (e.g. 627137) will not have named labels. "
        "Run  python tools/download_nws_gis_data.py  to fetch the data from "
        "https://www.weather.gov/gis/NWRPartialCounties"
    )
    return None


def _load_county_subdivision_index(
    base_mapping: Dict[str, str]
) -> Tuple[Dict[str, List[Dict[str, object]]], Dict[str, str]]:
    """Return subdivision metadata keyed by the parent SAME county code."""

    dbf_path = _resolve_partial_county_dbf()
    if dbf_path is None:
        return {}, {}

    try:
        from app_utils.zone_catalog import iter_county_subdivision_records
    except Exception:
        return {}, {}

    subdivisions: Dict[str, List[Dict[str, object]]] = {}
    labels: Dict[str, str] = {}

    for record in iter_county_subdivision_records(dbf_path):
        entire_code = ''.join(ch for ch in record.entire_same if ch.isdigit())
        area_code = ''.join(ch for ch in record.area_same if ch.isdigit())
        if len(entire_code) != 6 or len(area_code) != 6:
            continue
        if area_code == entire_code:
            continue

        base_label = base_mapping.get(entire_code, '')
        county_label = base_label.split(',')[0].strip() if ',' in base_label else base_label
        state_abbr = base_label.split(',')[-1].strip() if ',' in base_label else record.state_code
        entry = {
            'code': area_code,
            'name': _format_subdivision_display_name(
                county_label,
                record.county_name,
                record.area_name,
                area_code,
            ),
            'latitude': record.latitude,
            'longitude': record.longitude,
        }
        bucket = subdivisions.setdefault(entire_code, [])
        replaced = False
        for index, existing in enumerate(bucket):
            if existing['code'] == area_code:
                bucket[index] = entry
                replaced = True
                break
        if not replaced:
            bucket.append(entry)

        labels[area_code] = _format_subdivision_label(
            county_label,
            record.county_name,
            record.area_name,
            area_code,
            state_abbr or record.state_code,
        )

    for bucket in subdivisions.values():
        bucket.sort(key=lambda item: (item['code'][0], item['name']))

    return subdivisions, labels


def _build_county_index() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    state_labels: Dict[str, Tuple[str, str]] = {}
    for line in US_FIPS_COUNTY_TABLE.strip().splitlines():
        code, state_abbr, county_name = line.split('|')
        same_code = _to_same_county_code(code)
        mapping[same_code] = f"{county_name}, {state_abbr}"

        state_fips = code[:2]
        state_name = STATE_ABBR_NAMES.get(state_abbr, state_abbr)
        state_labels.setdefault(state_fips, (state_abbr, state_name))

    for state_fips, (state_abbr, state_name) in state_labels.items():
        statewide_code = f"0{state_fips}000"
        mapping.setdefault(statewide_code, f"Entire {state_name}, {state_abbr}")

    mapping.setdefault(NATIONWIDE_SAME_CODE, NATIONWIDE_LABEL)
    return mapping


US_FIPS_COUNTIES: Dict[str, str] = _build_county_index()
COUNTY_SUBDIVISIONS, US_FIPS_SUBDIVISIONS = _load_county_subdivision_index(US_FIPS_COUNTIES)
US_FIPS_COUNTIES.update(US_FIPS_SUBDIVISIONS)
ALL_US_FIPS_CODES = frozenset(US_FIPS_COUNTIES.keys())


def _build_state_tree() -> List[Dict[str, object]]:
    states: Dict[str, Dict[str, object]] = {}
    for line in US_FIPS_COUNTY_TABLE.strip().splitlines():
        code, state_abbr, county_name = line.split('|')
        state_fips = code[:2]
        same_code = _to_same_county_code(code)
        state_entry = states.setdefault(
            state_abbr,
            {
                'abbr': state_abbr,
                'name': STATE_ABBR_NAMES.get(state_abbr, state_abbr),
                'state_fips': state_fips,
                'statewide_code': f"0{state_fips}000",
                'counties': [],
            },
        )
        county_entry: Dict[str, object] = {
            'code': same_code,
            'name': county_name,
        }
        subdivisions = COUNTY_SUBDIVISIONS.get(same_code)
        if subdivisions:
            county_entry['subdivisions'] = [
                {
                    'code': item['code'],
                    'name': item['name'],
                    'latitude': item.get('latitude'),
                    'longitude': item.get('longitude'),
                }
                for item in subdivisions
            ]
        state_entry['counties'].append(county_entry)

    ordered_states: List[Dict[str, object]] = []
    for state in states.values():
        state['counties'].sort(key=lambda item: item['name'])
        ordered_states.append(state)

    if 'US' not in states:
        states['US'] = {
            'abbr': 'US',
            'name': STATE_ABBR_NAMES.get('US', 'United States'),
            'state_fips': '00',
            'statewide_code': NATIONWIDE_SAME_CODE,
            'counties': [],
        }
        ordered_states.append(states['US'])
    ordered_states.sort(key=lambda item: item['name'])
    return ordered_states


def _build_same_lookup(states: List[Dict[str, object]]) -> Dict[str, str]:
    mapping = dict(US_FIPS_COUNTIES)
    for state in states:
        statewide_code = state.get('statewide_code')
        if not statewide_code:
            continue
        if statewide_code == NATIONWIDE_SAME_CODE:
            mapping[statewide_code] = NATIONWIDE_LABEL
            continue

        state_name = str(state.get('name') or state.get('abbr') or '').strip()
        state_abbr = str(state.get('abbr') or '').strip()
        if not state_name:
            state_name = state_abbr

        mapping.setdefault(
            statewide_code,
            f"Entire {state_name}, {state_abbr}" if state_abbr else f"Entire {state_name}",
        )
    mapping[NATIONWIDE_SAME_CODE] = NATIONWIDE_LABEL
    return mapping


US_STATE_COUNTY_TREE: List[Dict[str, object]] = _build_state_tree()
STATEWIDE_SAME_CODES: FrozenSet[str] = frozenset(
    state.get('statewide_code')
    for state in US_STATE_COUNTY_TREE
    if isinstance(state.get('statewide_code'), str) and state.get('statewide_code')
)
US_FIPS_LOOKUP: Dict[str, str] = _build_same_lookup(US_STATE_COUNTY_TREE)
_US_FIPS_LOOKUP_PROXY: Mapping[str, str] = MappingProxyType(US_FIPS_LOOKUP)


def get_us_state_county_tree() -> List[Dict[str, object]]:
    """Return a copy of the state → county SAME mapping."""

    def _copy_county(county: Dict[str, object]) -> Dict[str, object]:
        entry = dict(county)
        if 'subdivisions' in entry and isinstance(entry['subdivisions'], list):
            entry['subdivisions'] = [dict(item) for item in entry['subdivisions']]
        return entry

    return [
        {
            **state,
            'counties': [
                _copy_county(county) for county in state.get('counties', [])
            ],
        }
        for state in US_STATE_COUNTY_TREE
    ]


def get_same_lookup() -> Mapping[str, str]:
    """Return an immutable mapping of SAME codes to friendly labels.

    Returns a ``MappingProxyType`` view of the module-level lookup table.
    All read operations (``get``, ``[]``, ``in``, ``keys``, iteration) work
    identically to a plain dict; mutation is prevented at the type level.
    """

    return _US_FIPS_LOOKUP_PROXY


# ---------------------------------------------------------------------------
# NWS marine SAME areas
#
# Marine, Great Lakes, and offshore alerts arrive on the SAME wire as 6-digit
# PSSCCC codes whose SS digits don't overlap the U.S. Census state FIPS grid
# (the alert in admin issue #2168 had SS=077 = American Samoa marine). The
# corresponding UGC codes that NWS publishes in the marine zone shapefile
# use 2-letter alphabetic prefixes (PSZ###, GMZ###, AMZ###, …) — those go
# into ``nws_zones`` once the operator uploads ``mz_*.dbf``.
#
# To let the admin FIPS picker surface marine areas, we need to map each
# alphabetic UGC prefix to its numeric SAME "state" digit. Only entries we
# can verify against an authoritative source live here. Adding a new prefix
# requires:
#   1. NWS confirmation of the prefix → numeric-state mapping (per-state
#      ``<XX>SAME.txt`` files at weather.gov/nwr/SAMECountyTextFiles), AND
#   2. Loading a marine zone DBF that contains entries with that prefix
#      via the admin Zones page (or tools/sync_zone_catalog.py).
# ---------------------------------------------------------------------------

# UGC prefix → numeric SAME "state" digits (the SS in PSSCCC — two digits).
#
# Source: NWS "Coastal and Offshore Marine Codes Listings for Emergency
# Alert System (EAS) and NOAA Weather Radio (NWR) Applications", §6,
# which publishes the complete Numeric ↔ Alpha ↔ Geographic-area
# correspondence. The GM=77 row was cross-verified on-station against
# an SMW with codes 077650/077633/077632/077631 whose CCC values match
# GMZ650 ("Coastal waters from Pensacola FL to Pascagoula MS"),
# GMZ633 (Perdido Bay), GMZ632 (Mississippi Sound), GMZ631 (South
# Mobile Bay) byte-for-byte in the mz16ap26 DBF.
MARINE_PREFIX_TO_SAME_STATE: Dict[str, str] = {
    # Pacific
    "PZ": "57",  # Eastern N. Pacific Ocean (US West Coast)
    "PK": "58",  # N. Pacific Ocean near Alaska
    "PH": "59",  # Central Pacific Ocean (Hawaiian Waters)
    "PS": "61",  # S. Central Pacific Ocean (American Samoa)
    "PM": "65",  # Western Pacific Ocean (Mariana Islands)
    # Atlantic / Gulf
    "AN": "73",  # Northwest N. Atlantic Ocean (US East Coast, N. of Hatteras)
    "AM": "75",  # West N. Atlantic Ocean (US East Coast S. of Hatteras + Caribbean)
    "GM": "77",  # Gulf of Mexico — verified on-air (see above)
    # Great Lakes / St. Lawrence
    "LS": "91",  # Lake Superior
    "LM": "92",  # Lake Michigan
    "LH": "93",  # Lake Huron
    "LC": "94",  # Lake St. Clair
    "LE": "96",  # Lake Erie
    "LO": "97",  # Lake Ontario
    "SL": "98",  # St. Lawrence River
}

# Display label per UGC prefix, used as the "state" name in the picker
# whenever the prefix is also mapped in MARINE_PREFIX_TO_SAME_STATE.
# Names follow the NWS Coastal/Offshore Marine Codes Listings (the
# same document that publishes the numeric SAME mappings above).
MARINE_AREA_LABELS: Dict[str, str] = {
    "PZ": "Eastern N. Pacific Ocean",
    "PK": "N. Pacific Ocean near Alaska",
    "PH": "Central Pacific Ocean (Hawaii)",
    "PS": "S. Central Pacific Ocean (American Samoa)",
    "PM": "Western Pacific Ocean (Mariana Islands)",
    "AN": "Northwest N. Atlantic Ocean",
    "AM": "West N. Atlantic Ocean (incl. Caribbean)",
    "GM": "Gulf of Mexico",
    "LS": "Lake Superior",
    "LM": "Lake Michigan",
    "LH": "Lake Huron",
    "LC": "Lake St. Clair",
    "LE": "Lake Erie",
    "LO": "Lake Ontario",
    "SL": "St. Lawrence River",
}


def _normalise_marine_state_code(state_code: str) -> str:
    """Return the upper-case prefix portion of a ``nws_zones.state_code`` value."""

    return (state_code or "").strip().upper()


def _marine_same_code(prefix: str, zone_number: str) -> Optional[str]:
    """Build the numeric SAME code (``PSSCCC``, P=0) for a marine UGC zone.

    SAME location codes are six digits: a one-digit partition code ``P``
    (always ``0`` for an entire marine zone), two-digit "state" ``SS``,
    and three-digit area ``CCC``. Returns ``None`` if the prefix isn't
    in :data:`MARINE_PREFIX_TO_SAME_STATE` or the zone number doesn't
    normalise to three digits.
    """

    state_digits = MARINE_PREFIX_TO_SAME_STATE.get(prefix)
    if not state_digits or len(state_digits) != 2 or not state_digits.isdigit():
        return None
    digits = "".join(ch for ch in (zone_number or "") if ch.isdigit())
    if not digits:
        return None
    return f"0{state_digits}{digits.zfill(3)[-3:]}"


def get_marine_state_tree() -> List[Dict[str, object]]:
    """Return marine "state" entries derived from the ``nws_zones`` table.

    Each returned entry mirrors the shape of a state in
    :func:`get_us_state_county_tree`: ``abbr`` (the marine UGC prefix),
    ``name`` (display label), ``statewide_code`` (``0SS000``), and
    ``counties`` (the marine areas under that prefix, sorted by name with
    their 6-digit numeric SAME code).

    Returns an empty list if the database isn't reachable yet (e.g. during
    module import) or if no zones for any configured marine prefix have
    been loaded. Never raises.
    """

    if not MARINE_PREFIX_TO_SAME_STATE:
        return []

    try:
        from app_core.models import NWSZone  # Lazy import to avoid cycles
        from app_core.extensions import db
    except Exception:
        return []

    try:
        rows = (
            db.session.query(NWSZone.state_code, NWSZone.zone_number, NWSZone.name)
            .filter(NWSZone.state_code.in_(tuple(MARINE_PREFIX_TO_SAME_STATE.keys())))
            .all()
        )
    except Exception:
        # DB not ready, table missing, or query failed — silently degrade.
        return []

    grouped: Dict[str, List[Dict[str, object]]] = {}
    for state_code, zone_number, name in rows:
        prefix = _normalise_marine_state_code(state_code)
        same = _marine_same_code(prefix, zone_number or "")
        if not same:
            continue
        grouped.setdefault(prefix, []).append(
            {"code": same, "name": (name or "").strip() or f"{prefix}{zone_number}"}
        )

    tree: List[Dict[str, object]] = []
    for prefix, counties in grouped.items():
        seen: Dict[str, Dict[str, object]] = {}
        for entry in counties:
            seen.setdefault(str(entry["code"]), entry)
        ordered = sorted(seen.values(), key=lambda item: str(item["name"]).lower())

        state_digits = MARINE_PREFIX_TO_SAME_STATE[prefix]
        tree.append(
            {
                "abbr": prefix,
                "name": MARINE_AREA_LABELS.get(prefix, f"{prefix} Marine"),
                "state_fips": None,  # Intentionally omitted — not a Census state.
                "statewide_code": f"0{state_digits}000",  # PSSCCC: P=0, CCC=000
                "counties": ordered,
                "is_marine": True,
            }
        )

    tree.sort(key=lambda item: str(item["name"]).lower())
    return tree


def get_extended_state_county_tree() -> List[Dict[str, object]]:
    """Return the U.S. state/county tree plus any loaded marine areas.

    This is the function admin templates should call so the FIPS picker
    surfaces marine alerts (e.g. American Samoa SMW codes ``077###``).
    Import-time callers must keep using :func:`get_us_state_county_tree`,
    which never touches the database.
    """

    return get_us_state_county_tree() + get_marine_state_tree()


def state_index_from_tree(
    state_tree: List[Dict[str, object]],
) -> Dict[str, Dict[str, object]]:
    """Map SAME-header SS digits → {abbr, name} for the given tree.

    ``describe_same_header`` uses this to label the per-location
    ``state_name`` / ``state_abbr`` fields. Census states key on their
    numeric ``state_fips`` (e.g. ``"12"`` → Florida). Marine entries
    from :func:`get_marine_state_tree` have ``state_fips=None`` (they
    are not Census states); their SS digit lives at characters 1:3 of
    ``statewide_code`` (a ``PSSCCC`` literal), so ``"077000"`` for the
    Gulf of Mexico yields ``"77" → {"abbr": "GM", "name": "Gulf of
    Mexico"}``. Pass :func:`get_extended_state_county_tree` to get
    proper labels for both kinds of code in a single index.
    """

    index: Dict[str, Dict[str, object]] = {}
    for state in state_tree:
        abbr = state.get("abbr")
        name = state.get("name")
        state_fips = state.get("state_fips")
        if state_fips:
            index[str(state_fips)] = {"abbr": abbr, "name": name}
        statewide_code = state.get("statewide_code")
        if isinstance(statewide_code, str) and len(statewide_code) == 6:
            index.setdefault(statewide_code[1:3], {"abbr": abbr, "name": name})
    return index


def get_extended_same_lookup() -> Dict[str, str]:
    """Return a SAME-code → description map covering U.S. + marine areas.

    The static :func:`get_same_lookup` only knows U.S. Census-state codes.
    Marine SAME codes (``077650`` Gulf of Mexico, ``091000`` Lake
    Superior, etc.) live in ``nws_zones`` and only become resolvable
    once an operator uploads the NWS marine zone DBF. This function
    merges the static lookup with a marine lookup derived from
    :func:`get_marine_state_tree`, so any caller decoding a SAME header
    for display gets human-readable names for both kinds of code.

    Returns a fresh dict (not a MappingProxyType) because we mutate it
    by merging in DB-derived entries. Never raises; if the DB isn't
    reachable, the returned dict is just the static U.S. lookup.
    """

    merged: Dict[str, str] = dict(_US_FIPS_LOOKUP_PROXY)

    for marine_state in get_marine_state_tree():
        statewide_code = marine_state.get("statewide_code")
        state_name = str(marine_state.get("name") or marine_state.get("abbr") or "")
        if isinstance(statewide_code, str) and statewide_code:
            merged.setdefault(statewide_code, f"All Areas, {state_name}")
        for area in marine_state.get("counties", []) or []:
            code = area.get("code")
            name = area.get("name")
            if isinstance(code, str) and code and isinstance(name, str) and name:
                # Marine catalog wins over any (defensively unlikely)
                # collision with a static U.S. code, because the
                # operator explicitly loaded it.
                merged[code] = name

    return merged
