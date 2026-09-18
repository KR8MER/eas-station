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

"""Parsing SAME headers and CAP alert fields for the FCC compliance log."""

from typing import Any, Dict, List, Optional

from app_utils.alert_sources import (
    ALERT_SOURCE_EAS_RF,
    ALERT_SOURCE_EAS_STREAM,
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_NOAA,
)


# ---------------------------------------------------------------------------
# FCC Part 11 log helpers
#
# 47 CFR § 11.35(a) and § 11.54(a)(3) require EAS Participants to record the
# originator (ORG), event code (EEE), location codes (PSSCCC), issue time
# (JJJHHMM), purge time (+TTTT), and station identifier (LLLLLLLL) for every
# received and originated EAS message.  The helpers below extract those
# fields from raw SAME headers and CAP ingest metadata so each entry in the
# compliance log carries the full FCC-required record set.
# ---------------------------------------------------------------------------


# Best-effort CAP source → SAME originator code.  CAP messages do not carry a
# SAME ORG directly; this mirrors the mapping the forwarder uses when it
# composes outgoing SAME audio (see app_core/audio/auto_forward.py).
_CAP_SOURCE_ORIGINATORS: Dict[str, str] = {
    ALERT_SOURCE_NOAA: "WXR",
    ALERT_SOURCE_IPAWS: "EAS",
    ALERT_SOURCE_EAS_RF: "EAS",
    ALERT_SOURCE_EAS_STREAM: "EAS",
}

def _parse_same_header_fields(header: Optional[str]) -> Dict[str, Any]:
    """Return ``{originator, event_code, fips, issue_time, purge_minutes, station}``
    extracted from a SAME header, or an empty dict if the header does not parse.

    Format: ``ZCZC-ORG-EEE-PSSCCC[-PSSCCC...]+TTTT-JJJHHMM-LLLLLLLL-``
    """
    if not header:
        return {}
    text_value = header.strip()
    if not text_value.startswith("ZCZC"):
        return {}
    parts = text_value.split("-")
    if len(parts) < 6:
        return {}
    try:
        originator = parts[1].strip().upper() or None
        event_code = parts[2].strip().upper() or None
        station = parts[-2].strip() or None  # LLLLLLLL
        issue_time = parts[-3].strip() or None  # JJJHHMM
        purge_field = parts[-4]  # last FIPS, carries "+TTTT"
        purge_minutes: Optional[int] = None
        if "+" in purge_field:
            tttt = purge_field.split("+", 1)[1]
            if tttt.isdigit() and len(tttt) == 4:
                purge_minutes = int(tttt[:2]) * 60 + int(tttt[2:])
        fips_codes: List[str] = []
        for raw in parts[3:-3]:
            code = raw.split("+", 1)[0]
            code = "".join(ch for ch in code if ch.isdigit())
            if code:
                fips_codes.append(code.zfill(6)[:6])
        return {
            "originator": originator,
            "event_code": event_code,
            "fips": fips_codes,
            "issue_time": issue_time,
            "purge_minutes": purge_minutes,
            "station": station,
        }
    except (IndexError, ValueError):
        return {}

def _format_purge_minutes(minutes: Optional[int]) -> Optional[str]:
    if minutes is None:
        return None
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h{mins:02d}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"

def _cap_originator_from_source(source: Optional[str]) -> Optional[str]:
    """Map a CAP alert's ingest source to a best-effort SAME originator code."""
    if not source:
        return None
    return _CAP_SOURCE_ORIGINATORS.get(source.strip().upper())

def _cap_fips_codes(raw_json: Any) -> List[str]:
    """Pull SAME-style 6-digit FIPS codes out of a CAP alert's raw_json."""
    if not isinstance(raw_json, dict):
        return []
    seen: List[str] = []
    info_blocks = raw_json.get("info")
    if isinstance(info_blocks, dict):
        info_blocks = [info_blocks]
    if not isinstance(info_blocks, list):
        return []
    for info in info_blocks:
        if not isinstance(info, dict):
            continue
        areas = info.get("area")
        if isinstance(areas, dict):
            areas = [areas]
        if not isinstance(areas, list):
            continue
        for area in areas:
            if not isinstance(area, dict):
                continue
            geocodes = area.get("geocode")
            if isinstance(geocodes, dict):
                geocodes = [geocodes]
            if not isinstance(geocodes, list):
                continue
            for geo in geocodes:
                if not isinstance(geo, dict):
                    continue
                name = (geo.get("valueName") or "").strip().upper()
                value = (geo.get("value") or "").strip()
                if name in {"SAME", "FIPS", "FIPS6"} and value:
                    digits = "".join(ch for ch in value if ch.isdigit())
                    if digits:
                        code = digits.zfill(6)[:6]
                        if code not in seen:
                            seen.append(code)
    return seen
