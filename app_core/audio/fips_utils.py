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

from __future__ import annotations

"""Utilities for working with SAME/EAS FIPS location codes."""

from typing import Dict, Iterable, List, Optional, Set

__all__ = ["determine_fips_matches"]


def _normalize_fips_code(value: Optional[str]) -> Optional[str]:
    """Normalize a SAME location code to its six-digit numeric representation."""

    if not value:
        return None

    digits = ''.join(ch for ch in str(value).strip() if ch.isdigit())
    if not digits:
        return None

    if len(digits) > 6:
        digits = digits[-6:]

    return digits.zfill(6)


def determine_fips_matches(
    alert_fips_codes: Iterable[str],
    configured_fips_codes: Iterable[str],
) -> List[str]:
    """Determine which configured FIPS codes match alert codes, honoring wildcards."""

    configured_map: Dict[str, str] = {}
    configured_states: Dict[str, Set[str]] = {}

    for code in configured_fips_codes:
        normalized = _normalize_fips_code(code)
        if not normalized:
            continue
        configured_map[normalized] = code
        state = normalized[1:3]
        configured_states.setdefault(state, set()).add(code)

    alert_normalized: Set[str] = set()
    statewide_alerts: Set[str] = set()
    matches: Set[str] = set()

    for code in alert_fips_codes:
        normalized = _normalize_fips_code(code)
        if not normalized:
            continue
        alert_normalized.add(normalized)
        if normalized.endswith('000') and normalized != '000000':
            statewide_alerts.add(normalized[1:3])

    for code in alert_normalized:
        configured_value = configured_map.get(code)
        if configured_value:
            matches.add(configured_value)

    if '000000' in alert_normalized:
        matches.update(configured_map.values())

    for state in statewide_alerts:
        matches.update(configured_states.get(state, set()))

    return sorted(matches)
