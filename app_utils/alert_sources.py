"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Canonical alert source identifiers and helpers."""

from __future__ import annotations

from typing import Iterable, Optional, Set


ALERT_SOURCE_NOAA = "NOAA"
ALERT_SOURCE_IPAWS = "IPAWS"
ALERT_SOURCE_MANUAL = "MANUAL"
ALERT_SOURCE_UNKNOWN = "UNKNOWN"

_VALID_SOURCES: Set[str] = {
    ALERT_SOURCE_NOAA,
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_MANUAL,
    ALERT_SOURCE_UNKNOWN,
}


def normalize_alert_source(value: Optional[str]) -> str:
    """Return a canonical alert source label for persistence/UI."""

    if not value:
        return ALERT_SOURCE_UNKNOWN

    candidate = value.strip().upper()
    if candidate in _VALID_SOURCES:
        return candidate

    # Allow callers to preface additional context (e.g. "NOAA REST")
    # while still keeping the canonical prefix for downstream grouping.
    for known in _VALID_SOURCES:
        if candidate.startswith(f"{known} "):
            return known

    return ALERT_SOURCE_UNKNOWN


def summarise_sources(values: Iterable[str]) -> str:
    """Serialise a collection of sources for poll history tracking."""

    normalised = {normalize_alert_source(item) for item in values if item}
    normalised.discard(ALERT_SOURCE_UNKNOWN)
    if not normalised:
        return ALERT_SOURCE_UNKNOWN
    return "|".join(sorted(normalised))


def expand_source_summary(summary: Optional[str]) -> Set[str]:
    """Expand a poll history summary string back to individual sources."""

    if not summary:
        return set()
    parts = {part.strip() for part in summary.split("|") if part}
    return {normalize_alert_source(part) for part in parts if part}

