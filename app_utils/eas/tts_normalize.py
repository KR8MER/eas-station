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

"""ALL-CAPS CAP text -> natural sentence-case text ready for TTS."""

import re
from typing import List

from flask import has_app_context



def _load_pronunciation_rules(db_session=None) -> List[tuple]:
    """Load user-defined pronunciation rules from the database.

    Returns a list of (original_text, replacement_text, match_case) tuples
    for all enabled rules, ordered so longer patterns are applied first
    (prevents shorter prefixes from masking longer tokens).

    Args:
        db_session: Optional raw SQLAlchemy session.  The CAP poller and the
            OTA monitor generate broadcast audio outside any Flask application
            context, where the Flask-SQLAlchemy ``Model.query`` proxy raises.
            Callers in those processes must pass their own session or the
            dictionary is silently skipped (same pattern as ``load_eas_config``).

    Falls back gracefully to an empty list when the database is unavailable
    or the table does not yet exist (e.g. before the first migration run).
    """
    try:
        from app_core.models import TTSPronunciationRule
        from sqlalchemy import func as _sa_func

        if db_session is not None:
            query = db_session.query(TTSPronunciationRule)
        else:
            from flask import has_app_context
            if not has_app_context():
                return []
            query = TTSPronunciationRule.query
        rules = (
            query
            .filter_by(enabled=True)
            .order_by(
                # Longer originals first so "Bellefontaine" is matched before "Bell"
                _sa_func.length(TTSPronunciationRule.original_text).desc()
            )
            .all()
        )
        return [(r.original_text, r.replacement_text, r.match_case) for r in rules]
    except Exception:
        return []




def _normalize_text_for_tts(text: str, db_session=None) -> str:
    """Expand common emergency-management acronyms and apply user pronunciation
    rules so TTS engines read the text correctly.

    ``db_session`` is an optional raw SQLAlchemy session forwarded to
    ``_load_pronunciation_rules`` so the database dictionary (layer 4) also
    works outside a Flask application context (CAP poller, OTA monitor).

    Five layers of replacement are applied in order:

    1. **Time expansion** – converts compact/digital time formats that TTS
       engines mispronounce into fully-spoken equivalents.
       e.g. "1100 PM" → "eleven o'clock PM", "11:30 AM" → "eleven thirty AM".

    2. **NWS-specific text normalizations** – cleans up formatting patterns
       unique to NOAA/NWS alert text before acronym expansion:
       - Alternate-timezone slash notation: "/5 PM CDT/" → "5 PM CDT" —
         stripped before time expansion so colon times inside slashes
         (e.g. "/5:00 PM CDT/") are intact when the time patterns run.
       - Whitespace/punctuation: "..." → ". ", double newlines → ". ",
         single newlines → ", " — applied before other steps so sentence
         structure is established early.
       - Multiple spaces/tabs → ", " — applied after Indiana disambiguation
         so county+state-code pairs ("CASS IN") are matched before their
         surrounding column padding is collapsed.
         NWS places the same deadline in a second timezone inside slashes;
         the slashes are stripped so TTS reads naturally.
       - "ST." abbreviation: "ST. JOSEPH" → "Saint JOSEPH" so TTS does not
         read it as "Street Joseph".
       - Indiana county disambiguation: NWS watches append the state code
         "IN" after a county name that appears in more than one watch state
         (e.g. "ALLEN IN" = Allen County, Indiana vs "ALLEN OH" = Allen
         County, Ohio).  "IN" is replaced with "Indiana" only when it is
         immediately preceded by a recognised Indiana county name AND is not
         followed by a directional word, state name, or common English word
         that would indicate it is acting as a preposition.

    3. **Built-in acronym table** – hard-coded, case-sensitive whole-word
       substitutions for uppercase tokens that TTS engines mispronounce
       (EAS → "Emergency Alert System", NWS → "National Weather Service",
       EDT → "Eastern Daylight Time", MI → "Michigan", OH → "Ohio", …).

    4. **Database pronunciation dictionary** – user-managed rows from the
       ``tts_pronunciation_rules`` table.  Each row supplies an
       ``original_text`` pattern, a ``replacement_text`` phonetic spelling,
       and a ``match_case`` flag.  Longer patterns are applied first so that
       multi-word entries (e.g. "Bellefontaine") are not accidentally masked
       by shorter ones (e.g. "Bell").

    5. **Lowercase normalisation** – converts the remaining all-caps NWS
       product text to lowercase so TTS engines treat tokens as words rather
       than as acronyms.  All acronym expansions have already been applied
       by this point.

    Only whole-word occurrences are replaced (regex ``\\b`` word boundaries).
    """
    if not text:
        return text

    # ── Layer 1: Time pronunciation expansion ────────────────────────────
    # TTS engines read "1100" as "eleven hundred" (military) and "11:00" can
    # also be mispronounced.  Convert to fully-spoken word form so that every
    # TTS backend gives a consistent, natural result.

    _ONES = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
             'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen',
             'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen',
             'nineteen']
    _TENS_WORDS = ['', '', 'twenty', 'thirty', 'forty', 'fifty']

    def _hour_word(h: int) -> str:
        h12 = h % 12 or 12
        return _ONES[h12]

    def _minute_phrase(m: int) -> str:
        """Return spoken minutes: 0→"o'clock", 1-9→"oh one", 10-19, 20+."""
        if m == 0:
            return "o'clock"
        if m < 10:
            return f"oh {_ONES[m]}"
        if m < 20:
            return _ONES[m]
        t, o = divmod(m, 10)
        return _TENS_WORDS[t] if o == 0 else f"{_TENS_WORDS[t]}-{_ONES[o]}"

    def _expand_time_match(mo) -> str:
        h = int(mo.group(1))
        m = int(mo.group(2))
        ampm = mo.group(3).upper()
        hw = _hour_word(h)
        mp = _minute_phrase(m)
        if mp == "o'clock":
            return f"{hw} o'clock {ampm}"
        return f"{hw} {mp} {ampm}"

    result = text

    # Slash alternate-timezone notation must be stripped BEFORE time expansion
    # so that colon-format times inside slashes (e.g. "/5:00 PM CDT/") are
    # intact when the time-expansion patterns run.  If time expansion ran first
    # it would convert "5:00 PM" to "five o'clock PM", leaving orphaned slashes
    # that the slash pattern can no longer match.
    result = re.sub(
        r'/\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s+[A-Z]{2,5})\s*/',
        r' \1 ',
        result,
    )

    # Pattern A: compact 4-digit time, e.g. "1100 PM", "0930 AM"
    # Matches HHMM immediately followed (possibly with space) by AM/PM.
    result = re.sub(
        r'\b([01]?\d|2[0-3])([0-5]\d)\s+(AM|PM)\b',
        _expand_time_match,
        result,
        flags=re.IGNORECASE,
    )

    # Pattern B: colon-separated time, e.g. "11:00 PM", "9:30 AM"
    result = re.sub(
        r'\b(\d{1,2}):([0-5]\d)\s*(AM|PM)\b',
        _expand_time_match,
        result,
        flags=re.IGNORECASE,
    )

    # ── Layer 2: NWS-specific text normalizations ────────────────────────
    # These clean up formatting conventions unique to NWS/NOAA alert text
    # before the acronym table runs.

    # Asterisk handling — NWS uses "* WHAT...", "* WHERE...", "* WHEN..." etc.
    # as bullet-point markers.  TTS engines read a bare asterisk as "asterisk"
    # which sounds unnatural.  Strip leading bullet asterisks first.
    result = re.sub(r'^\s*\*\s*', '', result, flags=re.MULTILINE)

    # ECIG §3.5.2 / §3.5.4: text deletions are marked with three asterisks
    # ("***") and MUST be followed by a one-second pause in TTS / audio.
    # Insert a sentence break (period + space) which every TTS backend in
    # this project — Azure, espeak-ng, the local fallback — renders as an
    # audible sentence-length pause comparable to one second.  Consume
    # adjacent spaces/tabs so the downstream multi-space → ", " rule does
    # not append a comma to the pause.  Run this BEFORE the remaining-
    # asterisk strip so the markers are not erased.
    result = re.sub(r'[ \t]*\*{3,}[ \t]*', '. ', result)

    # Strip any remaining stray asterisks so they are never spoken.
    result = result.replace('*', '')

    # Whitespace / punctuation — convert structural whitespace to spoken
    # pauses so TTS does not read the whole alert as a run-on sentence.

    # Ellipsis → sentence break.  NWS uses "..." throughout product text as
    # a clause/sentence separator (e.g. "...TORNADO WARNING IN EFFECT...").
    result = re.sub(r'\.{3,}', '. ', result)

    # Double newline (paragraph break) → sentence pause.
    result = re.sub(r'\n{2,}', '. ', result)

    # Single newline → comma pause.
    result = re.sub(r'\n', ', ', result)

    # "ST." (Saint abbreviation): expand before the main acronym loop so
    # that the trailing period does not confuse word-boundary matching.
    # e.g. "ST. JOSEPH" → "Saint JOSEPH", "ST. LOUIS" → "Saint LOUIS".
    result = re.sub(r'\bST\.(?=\s)', 'Saint', result, flags=re.IGNORECASE)

    # Indiana county-name disambiguation: NWS watches append the two-letter
    # state code "IN" immediately after a county name that also appears in
    # another watch state (e.g. "ALLEN IN" = Allen County, Indiana vs
    # "ALLEN OH" = Allen County, Ohio).  TTS reads the bare code "IN" as the
    # preposition "in" which is ambiguous; expanding it to "Indiana" makes the
    # reading unambiguous and natural.
    #
    # Safety constraints applied together:
    #   • Positive match  — the preceding word must be a recognised Indiana
    #     county name (all 92 counties, single-word spellings as used by NWS).
    #   • Negative lookahead — the word that follows "IN" must NOT be a
    #     directional word, state name, or common English function word that
    #     would indicate "IN" is acting as a preposition rather than a state
    #     code.  This prevents "GRANT IN NORTHERN INDIANA" from becoming
    #     "GRANT Indiana NORTHERN INDIANA".
    _INDIANA_COUNTIES = (
        r'ADAMS|ALLEN|BARTHOLOMEW|BENTON|BLACKFORD|BOONE|BROWN|CARROLL|CASS|'
        r'CLARK|CLAY|CLINTON|CRAWFORD|DAVIESS|DEARBORN|DECATUR|DELAWARE|'
        r'DUBOIS|ELKHART|FAYETTE|FLOYD|FOUNTAIN|FRANKLIN|FULTON|GIBSON|'
        r'GRANT|GREENE|HAMILTON|HANCOCK|HARRISON|HENDRICKS|HENRY|HOWARD|'
        r'HUNTINGTON|JACKSON|JASPER|JAY|JEFFERSON|JENNINGS|JOHNSON|KNOX|'
        r'KOSCIUSKO|LAGRANGE|LAKE|LAPORTE|LAWRENCE|MADISON|MARION|MARSHALL|'
        r'MARTIN|MIAMI|MONROE|MONTGOMERY|MORGAN|NEWTON|NOBLE|OHIO|ORANGE|'
        r'OWEN|PARKE|PERRY|PIKE|PORTER|POSEY|PULASKI|PUTNAM|RANDOLPH|'
        r'RIPLEY|RUSH|SCOTT|SHELBY|SPENCER|STARKE|STEUBEN|SULLIVAN|'
        r'SWITZERLAND|TIPPECANOE|TIPTON|UNION|VANDERBURGH|VERMILLION|VIGO|'
        r'WABASH|WARREN|WARRICK|WASHINGTON|WAYNE|WELLS|WHITE|WHITLEY'
    )
    # Words that follow "IN" when it is a preposition, not a state code.
    _IN_PREPOSITION_AFTER = (
        r'NORTH|SOUTH|EAST|WEST|CENTRAL|NORTHERN|SOUTHERN|EASTERN|WESTERN|'
        r'NORTHWEST|SOUTHWEST|NORTHEAST|SOUTHEAST|'
        r'INDIANA|MICHIGAN|OHIO|ILLINOIS|KENTUCKY|WISCONSIN|MINNESOTA|'
        r'THE|A|AN|THIS|THAT|THESE|THOSE|EFFECT|WATCH|COUNTIES|COUNTY|'
        r'CITIES|CITY|AREAS|AREA|FOLLOWING|ALL|SOME|MANY|FEW|EACH|EVERY'
    )
    result = re.sub(
        r'\b(' + _INDIANA_COUNTIES + r')\s+IN\b'
        r'(?!\s+(?:' + _IN_PREPOSITION_AFTER + r'))',
        r'\1 Indiana',
        result,
    )

    # Two or more spaces, or any number of tabs → comma pause.
    # NWS formats county lists in fixed-width columns separated by multiple
    # spaces or tabs, e.g. "KOSCIUSKO             ST. JOSEPH".
    # A lone tab counts as a separator; two+ spaces do too.
    # This runs after Indiana disambiguation so that "CASS IN" (single space)
    # is recognised as a county+state-code pair before any spaces are replaced.
    result = re.sub(r'\t+|[ \t]{2,}', ', ', result)

    # ── Layer 3: hard-coded acronym expansions ────────────────────────────
    # Order matters: longer / more-specific entries first.
    _ACRONYM_MAP = [
        # Compound EAS parameter tokens
        ('EAS-ORG',    'E.A.S. originator'),
        ('EAS-STN-ID', 'E.A.S. station ID'),
        # Agency / system names
        ('IPAWS',  'I.P.A.W.S.'),
        ('NOAA',   'N.O.A.A.'),
        ('FEMA',   'F.E.M.A.'),
        ('NWS',    'National Weather Service'),
        ('EBS',    'Emergency Broadcast System'),
        ('EAS',    'Emergency Alert System'),
        # Event codes that appear verbatim in auto-generated message text
        ('RWT',    'Required Weekly Test'),
        ('RMT',    'Required Monthly Test'),
        ('EOM',    'end of message'),
        # US timezone abbreviations — daylight saving time
        ('EDT',    'Eastern Daylight Time'),
        ('CDT',    'Central Daylight Time'),
        ('MDT',    'Mountain Daylight Time'),
        ('PDT',    'Pacific Daylight Time'),
        # US timezone abbreviations — standard time
        ('EST',    'Eastern Standard Time'),
        ('CST',    'Central Standard Time'),
        ('MST',    'Mountain Standard Time'),
        ('PST',    'Pacific Standard Time'),
        # Other common timezone abbreviations
        ('UTC',    'Coordinated Universal Time'),
        ('GMT',    'Greenwich Mean Time'),
        ('AKDT',   'Alaska Daylight Time'),
        ('AKST',   'Alaska Standard Time'),
        ('HST',    'Hawaii Standard Time'),
        ('HAST',   'Hawaii-Aleutian Standard Time'),
        ('HADT',   'Hawaii-Aleutian Daylight Time'),
        # US state codes used as county-name disambiguation markers in NWS
        # watches (e.g. "CASS MI" = Cass County, Michigan; "ALLEN OH" =
        # Allen County, Ohio).  TTS engines mispronounce bare two-letter
        # codes ("MI" → "my", "OH" → "oh").
        ('MI',     'Michigan'),
        ('OH',     'Ohio'),
        # Military / civil facility abbreviations in NWS city lists.
        ('AFB',    'Air Force Base'),
        ('ARB',    'Air Reserve Base'),
        ('AFD',    'Air Force Base'),
    ]

    for token, expansion in _ACRONYM_MAP:
        result = re.sub(r'\b' + re.escape(token) + r'\b', expansion, result)

    # ── Layer 4: database pronunciation dictionary ────────────────────────
    for original, replacement, match_case in _load_pronunciation_rules(db_session):
        flags = 0 if match_case else re.IGNORECASE
        try:
            result = re.sub(
                r'\b' + re.escape(original) + r'\b',
                replacement,
                result,
                flags=flags,
            )
        except re.error:
            pass  # Malformed pattern — skip silently

    # ── Layer 5: lowercase normalisation ─────────────────────────────────
    # NWS product text is entirely uppercase.  All acronym and pronunciation
    # expansions have already run, so lowercasing now lets every TTS backend
    # treat the remaining tokens as plain words rather than abbreviations.
    result = result.lower()

    return result
