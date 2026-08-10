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

"""Recovering the outline NWS hides inside a CAP ``description``.

Modern NWS products are written to a tagged "bullet" outline — WHAT is
happening, WHERE, WHEN, what the IMPACTS are — but CAP delivers the whole
thing as one free-text field:

    * WHAT...Flooding caused by excessive rainfall is expected.
    * WHERE...A portion of northwest Ohio, including ...
    * WHEN...Until 1245 PM EDT.
    * IMPACTS...Minor flooding in low-lying and poor drainage areas.
    * ADDITIONAL DETAILS...
    - At 935 AM EDT, Doppler radar indicated heavy rain ...

Flattening that to a paragraph (collapse newlines, drop the leading
asterisk) throws the outline away and leaves a share card carrying a
nine-line run-on wall with stray ``*`` and ``-`` glyphs in the middle of
sentences.  These helpers put the structure back so the renderer can lay
the segments out as labelled rows, and drop the parts that a share card
already says somewhere else.

Severe-thunderstorm and tornado warnings use the same convention without
the asterisks (``HAZARD...``, ``SOURCE...``, ``IMPACT...``), so both
forms are recognised.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ─── Segment parsing ─────────────────────────────────────────────────────────

# A tag is an ALL-CAPS label terminated by the NWS ``...`` separator, sitting
# at the start of the text, at the start of a line, or just after a ``*``
# bullet marker.  Digits are excluded from the label so a shouted legacy
# sentence like "AT 935 AM EDT...DOPPLER RADAR INDICATED" cannot masquerade
# as a tag.
_TAG_RE = re.compile(r"(?:\A|\n|\*)[ \t]*([A-Z][A-Z /&'-]{1,44}?)[ \t]*\.\.\.")

# Labels NWS actually uses.  At least one match must land in this set before
# the text is treated as tagged — a single unrecognised ALL-CAPS fragment is
# far more likely to be shouted prose than an outline.
_KNOWN_LABELS = frozenset([
    'WHAT', 'WHERE', 'WHEN', 'IMPACTS', 'IMPACT', 'HAZARD', 'SOURCE',
    'ADDITIONAL DETAILS', 'PRECAUTIONARY/PREPAREDNESS ACTIONS',
    'TARGET AREA', 'TIMING', 'SNOW', 'ICE ACCUMULATIONS', 'WINDS',
    'VISIBILITY', 'TEMPERATURE', 'TEMPERATURES', 'RAINFALL', 'SURF',
    'SWIM RISK', 'WAVES', 'WINDS AND SEAS', 'ADDITIONAL INFORMATION',
])

# Display names for labels whose official form is too long for a label
# column, plus the singular/plural normalisation NWS is inconsistent about.
_LABEL_DISPLAY = {
    'ADDITIONAL DETAILS': 'DETAILS',
    'ADDITIONAL INFORMATION': 'DETAILS',
    'IMPACT': 'IMPACTS',
    'TEMPERATURES': 'TEMPERATURE',
    'ICE ACCUMULATIONS': 'ICE',
    'WINDS AND SEAS': 'SEAS',
}

# Segments that never earn their space on a share card.  The preparedness
# block is the CAP ``instruction`` field verbatim, which the card already
# renders under its own ACTION banner.
_DROP_LABELS = frozenset(['PRECAUTIONARY/PREPAREDNESS ACTIONS'])

_URL_RE = re.compile(r'(?:https?://|www\.)\S+', re.IGNORECASE)


# A lede shorter than this is a stray fragment rather than a sentence worth
# giving a row to.
_MIN_PREAMBLE_CHARS = 24


@dataclass(frozen=True)
class NWSSegment:
    """One tagged bullet from an NWS description: its label and its prose.

    An empty *label* marks the untagged lede that opens some products —
    "At 900 PM EDT, a severe thunderstorm was located near Lima, moving
    east at 40 mph" — which carries no tag but is the single most
    informative sentence in a severe-thunderstorm or tornado warning.
    Renderers should print it without a label gutter.
    """
    label: str
    body: str


def strip_urls(text: str) -> str:
    """Remove bare URLs from *text*.

    A share card is a picture — a printed ``http://www.weather.gov/safety/
    flood`` cannot be clicked, wraps badly, and costs a line of copy that a
    reader could have spent on the hazard itself.
    """
    if not text:
        return ''
    return _URL_RE.sub('', text)


def _clean_body(body: str) -> str:
    """Normalise one segment body into a single readable paragraph."""
    body = strip_urls(body)
    # Bullet markers at the start of a line ("- At 935 AM EDT, ...").  Each
    # NWS sub-bullet is already a complete sentence, so joining them reads
    # correctly without the dashes.
    body = re.sub(r'[\r\n]+[ \t]*[-•·][ \t]*', ' ', body)
    body = re.sub(r'\s*[\r\n]+\s*', ' ', body)
    # The same markers, in feeds that have already collapsed their newlines.
    # Requiring a following capitalised word keeps numeric ranges ("1 - 2.5
    # inches") intact.
    body = re.sub(r'\s+[-•·]\s+(?=[A-Z][a-z])', ' ', body)
    body = re.sub(r'^\s*[-•·]\s*', '', body)
    body = re.sub(r'\s{2,}', ' ', body)
    # Trailing debris left behind by URL removal ("... include - ").
    body = re.sub(r'[\s\-•·*]+$', '', body)
    return body.strip()


def parse_nws_segments(text: str) -> List[NWSSegment]:
    """Split *text* into its tagged NWS bullets.

    Returns an empty list when the text carries no recognisable outline, in
    which case callers should fall back to rendering it as a paragraph.
    Labels are normalised to their display form and segments with an empty
    body (or a body that was nothing but a URL) are dropped.  A substantive
    untagged lede ahead of the first tag is returned first, with an empty
    label.
    """
    if not text:
        return []

    matches: List[Tuple[str, int, int]] = []
    for m in _TAG_RE.finditer(text):
        label = ' '.join(m.group(1).split())
        # Real labels are short — one to four words.  Anything longer is a
        # shouted sentence that happens to end in an ellipsis.
        if len(label.split()) > 4:
            continue
        matches.append((label, m.start(), m.end()))

    if not matches:
        return []
    if not any(label in _KNOWN_LABELS for label, _, _ in matches):
        return []

    segments: List[NWSSegment] = []

    # The lede that opens severe-thunderstorm / tornado warnings sits ahead
    # of the first tag and is the most informative line in the product, so
    # it leads the list rather than being discarded with the tag scaffolding.
    preamble = _clean_body(text[:matches[0][1]])
    if len(preamble) >= _MIN_PREAMBLE_CHARS:
        segments.append(NWSSegment('', preamble))

    for i, (label, _start, end) in enumerate(matches):
        body_end = matches[i + 1][1] if i + 1 < len(matches) else len(text)
        body = _clean_body(text[end:body_end])
        if not body:
            continue
        segments.append(NWSSegment(_LABEL_DISPLAY.get(label, label), body))

    return segments


def select_share_segments(text: str, *, drop_where: bool = False,
                          drop_when: bool = False) -> List[NWSSegment]:
    """Return the segments of *text* worth printing on a share card.

    Source order is preserved — NWS already orders its bullets sensibly —
    but three kinds of segment are filtered out:

    * the preparedness block, which duplicates the ACTION banner;
    * ``WHERE``, when *drop_where* is set because the card drew its own
      AFFECTED AREAS section from ``area_desc`` (the WHERE bullet is that
      same county list written out as a sentence);
    * ``WHEN``, when *drop_when* is set because the card's footer already
      carries the issued/expires stamp.
    """
    segments = parse_nws_segments(text)
    if not segments:
        return []

    skip = set(_DROP_LABELS)
    if drop_where:
        skip.add('WHERE')
    if drop_when:
        skip.add('WHEN')

    return [s for s in segments if s.label not in skip]


# ─── Affected-area compaction ────────────────────────────────────────────────

# "Allen, OH" — a place name closed by a two-letter state code.
_AREA_STATE_RE = re.compile(r'^(.*?),\s*([A-Za-z]{2})\.?$')


def compact_area_desc(area_desc: str) -> str:
    """Collapse the repeated state code out of a CAP ``areaDesc`` list.

    NWS repeats the state on every entry::

        Allen, OH; Defiance, OH; Henry, OH; Paulding, OH; Putnam, OH

    On a card that costs a whole extra wrapped row to say "OH" four more
    times than necessary.  Entries are grouped by state in first-appearance
    order and the code is factored out once per group::

        Allen, Defiance, Henry, Paulding, Putnam (OH)

    Entries that do not carry a state code are passed through untouched (and
    keep their position relative to the groups), so marine and zone-based
    products — "Coastal Volusia; Northern Brevard" — are unaffected.
    """
    if not area_desc:
        return ''

    entries = [seg.strip() for seg in area_desc.split(';') if seg.strip()]
    if len(entries) < 2:
        return area_desc.strip()

    # Ordered groups: state code (or None for "no state") → member names.
    order: List[Optional[str]] = []
    groups: dict = {}
    for entry in entries:
        m = _AREA_STATE_RE.match(entry)
        if m:
            name, state = m.group(1).strip(), m.group(2).upper()
        else:
            name, state = entry, None
        if not name:
            continue
        if state not in groups:
            groups[state] = []
            order.append(state)
        groups[state].append(name)

    if not order:
        return area_desc.strip()

    # Nothing to factor out — a single ungrouped bucket means no entry had a
    # state code, so leave the original text alone.
    if order == [None]:
        return '; '.join(entries)

    parts: List[str] = []
    for state in order:
        names = ', '.join(groups[state])
        parts.append(f'{names} ({state})' if state else names)
    return '; '.join(parts)
