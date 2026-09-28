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

"""Pure SAME-header comparison used by the air-check matcher.

No database or Flask access here, so the comparison rules can be unit
tested on their own.
"""

from typing import Any, Dict, List, Optional, Sequence

#: Header fields compared between what was sent and what was decoded, in
#: the order they appear in a SAME header.
COMPARED_FIELDS: Sequence[str] = (
    "originator",
    "event_code",
    "locations",
    "purge",
    "issue_time",
    "station",
)

FIELD_LABELS: Dict[str, str] = {
    "originator": "Originator (ORG)",
    "event_code": "Event (EEE)",
    "locations": "Locations (PSSCCC)",
    "purge": "Purge time (+TTTT)",
    "issue_time": "Issue time (JJJHHMM)",
    "station": "Station ID (LLLLLLLL)",
}

#: A decoded header must agree with a sent one on at least this many of the
#: compared fields to be treated as the same transmission (and reported as a
#: mismatch on the rest) rather than as an unrelated, unexpected header.
MIN_FIELDS_FOR_CANDIDATE = 3


def normalize_header(header: Optional[str]) -> str:
    """Canonical form of a SAME header for exact comparison.

    Upper-cases, strips whitespace/padding and guarantees exactly one
    trailing ``-`` (decoders differ on whether they keep it).
    """
    if not header:
        return ""
    text = str(header).strip().upper()
    start = text.find("ZCZC")
    if start < 0:
        return ""
    text = text[start:].rstrip("-").rstrip()
    return text + "-"


def parse_header(header: Optional[str]) -> Optional[Dict[str, Any]]:
    """Split a SAME header into its comparable fields, or ``None``.

    Format: ``ZCZC-ORG-EEE-PSSCCC[-PSSCCC...]+TTTT-JJJHHMM-LLLLLLLL-``
    """
    text = normalize_header(header)
    if not text:
        return None
    parts = text.rstrip("-").split("-")
    # ZCZC, ORG, EEE, >=1 location (the last one carrying +TTTT), JJJHHMM, LLLLLLLL
    if len(parts) < 6 or "+" not in parts[-3]:
        return None
    location_fields = parts[3:-2]
    last_location, _, purge = location_fields[-1].partition("+")
    locations = [field.strip() for field in location_fields[:-1]] + [last_location.strip()]
    return {
        "originator": parts[1].strip(),
        "event_code": parts[2].strip(),
        "locations": sorted(loc for loc in locations if loc),
        "purge": purge.strip(),
        "issue_time": parts[-2].strip(),
        "station": parts[-1].strip(),
    }


def compare_headers(expected: Optional[str], received: Optional[str]) -> Dict[str, Any]:
    """Compare a sent header with one decoded off the air.

    Returns ``{"exact": bool, "matched": [...], "mismatched": [...],
    "parsed": bool}``. ``exact`` is true only when every compared field
    agrees. When either header fails to parse, nothing matches.
    """
    exp = parse_header(expected)
    rec = parse_header(received)
    if exp is None or rec is None:
        return {"exact": False, "matched": [], "mismatched": list(COMPARED_FIELDS), "parsed": False}

    matched: List[str] = []
    mismatched: List[str] = []
    for field in COMPARED_FIELDS:
        (matched if exp[field] == rec[field] else mismatched).append(field)
    return {
        "exact": not mismatched,
        "matched": matched,
        "mismatched": mismatched,
        "parsed": True,
    }


def is_candidate(comparison: Dict[str, Any]) -> bool:
    """True when a comparison is close enough to be the same transmission."""
    return comparison.get("parsed", False) and (
        len(comparison.get("matched", [])) >= MIN_FIELDS_FOR_CANDIDATE
    )


def describe_mismatch(fields: Sequence[str]) -> str:
    """Human-readable list of the fields that differ."""
    return ", ".join(FIELD_LABELS.get(field, field) for field in fields)


__all__ = [
    "COMPARED_FIELDS",
    "FIELD_LABELS",
    "MIN_FIELDS_FOR_CANDIDATE",
    "compare_headers",
    "describe_mismatch",
    "is_candidate",
    "normalize_header",
    "parse_header",
]
