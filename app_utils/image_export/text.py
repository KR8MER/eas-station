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

"""Text and datetime presentation helpers.

Local-time formatting for the share card, plus the ALL-CAPS to sentence-case
humanizer that makes teletype-era NWS copy readable.
"""

import os
import re
from typing import Any, Optional


def _resolve_local_tz():
    """Return the configured location tzinfo without forcing the full
    ``app_utils`` package init (which pulls in psutil and friends).

    Honours the same ``DEFAULT_TIMEZONE`` env var that
    ``app_utils.time.get_location_timezone`` reads, so behaviour stays
    consistent across the rest of the app.
    """
    tz_name = os.environ.get('DEFAULT_TIMEZONE', 'America/New_York')
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        try:
            import pytz
            return pytz.timezone(tz_name)
        except Exception:
            from datetime import timezone
            return timezone.utc


def _short_local_dt(dt: Any, ref: Optional[Any] = None) -> str:
    """Compact local-time label for the share-card footer.

    Returns e.g. ``"6:29 PM EDT"`` when *dt* and *ref* share a calendar
    day (or *ref* is None), or ``"May 19 · 6:29 PM EDT"`` when they
    don't, so an "Expires …" stamp can never appear earlier than
    "Issued …" on a quick read.
    """
    from datetime import datetime, timezone

    tz = _resolve_local_tz()

    def _to_local(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if getattr(value, 'tzinfo', None) is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(tz)

    local = _to_local(dt)
    if local is None:
        return ''

    show_date = False
    if ref is not None:
        ref_local = _to_local(ref)
        if ref_local is not None and local.date() != ref_local.date():
            show_date = True

    # %I gives zero-padded hour ("06"); strip the leading zero for the
    # share card without relying on platform-specific %-I.
    time_part = local.strftime('%I:%M %p %Z')
    if time_part.startswith('0'):
        time_part = time_part[1:]
    if show_date:
        date_part = local.strftime('%b %d').replace(' 0', ' ')
        return f"{date_part} · {time_part}"
    return time_part

# ─── ALL-CAPS → sentence-case humanizer ─────────────────────────────────────
# NWS CAP feeds arrive ALL-CAPS (a legacy of teletype-era systems).  Rendering
# them shouted on a share card is the single biggest legibility hit — bodies
# of text in caps are ~10–20% slower to read.  These helpers detect a shouted
# string and rebuild a readable sentence-case form while keeping known
# acronyms (NWS, EDT, MPH, …) and US state names properly capitalised.

# Tokens that should remain ALL-CAPS after humanising.
_PRESERVE_ACRONYMS = frozenset([
    # Issuing agencies / source systems
    'NWS', 'WFO', 'NOAA', 'NHC', 'SPC', 'WPC', 'CPC', 'IPAWS', 'FEMA',
    'EAS', 'EOC', 'NCEP', 'NWR',
    # Time zones (continental + AK/HI + Atlantic + Chamorro)
    'UTC', 'GMT', 'EST', 'EDT', 'CST', 'CDT', 'MST', 'MDT', 'PST', 'PDT',
    'AKST', 'AKDT', 'HST', 'HAST', 'AST', 'ADT', 'CHST', 'SST',
    # Compass points
    'N', 'NE', 'NNE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW',
    # Units
    'MPH', 'KPH', 'KMH', 'KTS', 'KT',
    'AM', 'PM',
    # Convective intensity
    'EF0', 'EF1', 'EF2', 'EF3', 'EF4', 'EF5',
    'F0', 'F1', 'F2', 'F3', 'F4', 'F5',
    # Protocols / identifiers commonly in alert text
    'CAP', 'VTEC', 'PVTEC', 'HVTEC', 'UGC', 'WMO', 'FIPS', 'SAME',
    'AMBER', 'AWIPS',  # AMBER is technically a backronym but is brand-cased
])

# US state / territory codes (kept uppercase)
_US_STATE_CODES = frozenset([
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC', 'PR', 'VI', 'GU', 'AS', 'MP',
])

# Full US state / territory names (lowercase key → display form).
_US_STATES = {
    'alabama': 'Alabama', 'alaska': 'Alaska', 'arizona': 'Arizona',
    'arkansas': 'Arkansas', 'california': 'California', 'colorado': 'Colorado',
    'connecticut': 'Connecticut', 'delaware': 'Delaware', 'florida': 'Florida',
    'georgia': 'Georgia', 'hawaii': 'Hawaii', 'idaho': 'Idaho',
    'illinois': 'Illinois', 'indiana': 'Indiana', 'iowa': 'Iowa',
    'kansas': 'Kansas', 'kentucky': 'Kentucky', 'louisiana': 'Louisiana',
    'maine': 'Maine', 'maryland': 'Maryland', 'massachusetts': 'Massachusetts',
    'michigan': 'Michigan', 'minnesota': 'Minnesota', 'mississippi': 'Mississippi',
    'missouri': 'Missouri', 'montana': 'Montana', 'nebraska': 'Nebraska',
    'nevada': 'Nevada', 'ohio': 'Ohio', 'oklahoma': 'Oklahoma',
    'oregon': 'Oregon', 'pennsylvania': 'Pennsylvania', 'tennessee': 'Tennessee',
    'texas': 'Texas', 'utah': 'Utah', 'vermont': 'Vermont', 'virginia': 'Virginia',
    'washington': 'Washington', 'wisconsin': 'Wisconsin', 'wyoming': 'Wyoming',
    'guam': 'Guam',
}

# Stopwords kept lowercase when title-casing enumeration lists (cities of X, Y…).
_LIST_STOPWORDS = frozenset([
    'of', 'and', 'or', 'the', 'a', 'an', 'in', 'on', 'at', 'to', 'by',
])

# Triggers that flag a coming proper-noun enumeration (NWS texts list
# affected cities/counties after these phrases).
_LIST_TRIGGER_RE = re.compile(
    r'\b(cities?\s+of|counties?\s+of|towns?\s+of|villages?\s+of|'
    r'townships?\s+of|parishes?\s+of|boroughs?\s+of|community\s+of|'
    r'communities\s+of)\b([^.]*)',
    flags=re.IGNORECASE,
)


def _is_shouting(text: str, threshold: float = 0.80) -> bool:
    """True when *text* is dominantly uppercase — likely an NWS feed string."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 12:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= threshold


def _humanize_caps_text(text: str) -> str:
    """Convert ALL-CAPS NWS-style text to readable sentence case.

    Only operates when *text* is dominantly uppercase.  The output:
    - lowercases the body,
    - capitalises the first letter and any letter following sentence
      punctuation,
    - restores known acronyms (NWS, EDT, MPH, …) and US state codes,
    - title-cases full US state names,
    - title-cases the proper-noun enumeration that follows triggers like
      "cities of" / "counties of".
    """
    if not text or not _is_shouting(text):
        return text

    out = text.lower()

    # Capitalise the very first alphabetic character.
    for i, ch in enumerate(out):
        if ch.isalpha():
            out = out[:i] + ch.upper() + out[i + 1:]
            break

    # Capitalise after sentence-ending punctuation.
    out = re.sub(
        r'([.!?]\s+)([a-z])',
        lambda m: m.group(1) + m.group(2).upper(),
        out,
    )

    def _restore_word(m: 're.Match[str]') -> str:
        word = m.group(0)
        upper = word.upper()
        if upper in _PRESERVE_ACRONYMS:
            return upper
        lower = word.lower()
        if lower in _US_STATES:
            return _US_STATES[lower]
        return word

    out = re.sub(r"[A-Za-z]+", _restore_word, out)

    # State codes are intentionally NOT in the global preserve set — too
    # many overlap with common English words (IN, OR, ME, HI, OK, PA, MA,
    # LA, DE, …) so a blanket uppercase would turn "in effect" into
    # "IN effect".  Only uppercase them when they appear at the END of a
    # comma-prefixed list item — i.e. the unambiguous "City, ST" pattern
    # closed by a list separator (``, ;``), sentence punctuation
    # (``. ! ?``), or end-of-string.  Crucially the lookahead does NOT
    # match a trailing space, since ``, in a vehicle`` and ``, or in a``
    # would otherwise look identical to ``, OH `` and get mis-shouted.
    def _state_code_after_comma(m: 're.Match[str]') -> str:
        prefix, code = m.group(1), m.group(2)
        return prefix + code.upper() if code.upper() in _US_STATE_CODES else m.group(0)

    out = re.sub(
        r'(,\s+)([A-Za-z]{2})(?=[.,;:!?]|$)',
        _state_code_after_comma,
        out,
    )

    # Title-case proper nouns inside enumeration phrases ("cities of A, B,
    # and C") — preserves city/county names that lowercase otherwise.
    def _title_list(m: 're.Match[str]') -> str:
        head, body = m.group(1), m.group(2)

        def _title_word(wm: 're.Match[str]') -> str:
            w = wm.group(0)
            if w.upper() in _PRESERVE_ACRONYMS:
                return w.upper()
            if w.lower() in _LIST_STOPWORDS:
                return w.lower()
            return w[:1].upper() + w[1:].lower()

        body = re.sub(r"[A-Za-z]+", _title_word, body)
        return head + body

    out = _LIST_TRIGGER_RE.sub(_title_list, out)
    return out
