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
    """Determine which configured FIPS codes match alert codes, honoring wildcards.

    SAME/EAS FIPS codes use PSSCCC format:
    - P: Subdivision indicator (0=entire county, 1-9=subdivision)
    - SS: State code (00=nationwide, 01-95=specific state)
    - CCC: County code (000=state-wide, 001-999=specific county)

    Matching rules:
    - 000000 (nationwide) matches ALL configured codes
    - SS000 (state-wide) matches all configured codes in that state
    - PSSCCC matches configured codes for the same county regardless of P digit
      (e.g., alert 539137 matches configured 039137 - same county, different subdivision)
    """

    configured_map: Dict[str, str] = {}  # normalized -> original
    configured_states: Dict[str, Set[str]] = {}  # state code -> set of original codes
    configured_counties: Dict[str, Set[str]] = {}  # SSCCC (without P) -> set of original codes

    for code in configured_fips_codes:
        normalized = _normalize_fips_code(code)
        if not normalized:
            continue
        configured_map[normalized] = code
        state = normalized[1:3]  # SS from PSSCCC
        county = normalized[1:6]  # SSCCC (strip P digit for county matching)
        configured_states.setdefault(state, set()).add(code)
        configured_counties.setdefault(county, set()).add(code)

    alert_normalized: Set[str] = set()
    statewide_alerts: Set[str] = set()
    matches: Set[str] = set()

    for code in alert_fips_codes:
        normalized = _normalize_fips_code(code)
        if not normalized:
            continue
        alert_normalized.add(normalized)
        # Check for state-wide alert (ends in 000 but not nationwide)
        if normalized.endswith('000') and normalized != '000000':
            statewide_alerts.add(normalized[1:3])

    # Check for nationwide alert (000000) - matches everything
    if '000000' in alert_normalized:
        matches.update(configured_map.values())
        return sorted(matches)

    # Check for state-wide alerts (SS000) - matches all counties in that state
    for state in statewide_alerts:
        matches.update(configured_states.get(state, set()))

    # Check for county-level matches (PSSCCC)
    # Match by SSCCC (ignoring P digit) so 539137 matches configured 039137
    for code in alert_normalized:
        # Skip nationwide and state-wide codes (already handled)
        if code == '000000' or code.endswith('000'):
            continue
        # Extract SSCCC (county identifier without subdivision)
        county = code[1:6]
        matches.update(configured_counties.get(county, set()))

    return sorted(matches)
