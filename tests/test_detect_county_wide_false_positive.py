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

# Regression tests for the _detect_county_wide false-positive bug.
#
# The county_and_state heuristic previously matched any alert that
# contained the generic word "county" and the configured state name,
# regardless of which county the alert targeted.
#
# For a station in Putnam County, Ohio an alert for "Henry County, Ohio"
# would contain both "county" (generic) and "ohio" (state code), and was
# therefore incorrectly flagged as county-wide.
#
# The fix: county_short must also appear in area_lower before the
# heuristic fires.

import re


# ---------------------------------------------------------------------------
# Helpers that mirror the exact logic from webapp/admin/api.py so the test
# can run without Flask or a database.
# ---------------------------------------------------------------------------

def _county_and_state_check(area_lower, county_short, configured_state_code):
    """Reproduce the county_and_state heuristic from _detect_county_wide."""
    return bool(
        county_short
        and configured_state_code
        and county_short in area_lower
        and 'county' in area_lower
        and configured_state_code in area_lower
    )


# ---------------------------------------------------------------------------
# Static source checks
# ---------------------------------------------------------------------------

def test_county_and_state_requires_county_short_in_source():
    """The source of _detect_county_wide must include county_short in the
    county_and_state condition so that alerts for different counties in the
    same state are not falsely flagged."""
    with open('webapp/admin/api.py', 'r') as f:
        content = f.read()

    # Locate the county_and_state block
    pattern = re.compile(
        r'county_and_state\s*=\s*bool\([^)]+\)',
        re.DOTALL,
    )
    match = pattern.search(content)
    assert match is not None, "county_and_state expression not found in api.py"

    block = match.group(0)
    assert 'county_short in area_lower' in block, (
        "county_and_state must require 'county_short in area_lower' to prevent "
        "false positives for alerts targeting a different county in the same state. "
        "Found block:\n" + block
    )


# ---------------------------------------------------------------------------
# Logic-level regression tests (no Flask / DB needed)
# ---------------------------------------------------------------------------

def test_other_county_same_state_is_not_county_wide():
    """Henry County, Ohio must NOT match for a Putnam County station."""
    area = "henry county, ohio"
    result = _county_and_state_check(area, county_short="putnam",
                                     configured_state_code="ohio")
    assert result is False, (
        "Alert for Henry County, Ohio should NOT be detected as county-wide "
        "for a Putnam County station"
    )


def test_configured_county_and_state_is_county_wide():
    """Putnam County, Ohio correctly matches for a Putnam County station."""
    area = "putnam county, ohio"
    result = _county_and_state_check(area, county_short="putnam",
                                     configured_state_code="ohio")
    assert result is True


def test_other_county_only_not_county_wide():
    """Henry County (no state) must not match."""
    area = "henry county"
    result = _county_and_state_check(area, county_short="putnam",
                                     configured_state_code="ohio")
    assert result is False


def test_multiple_other_counties_same_state_not_county_wide():
    """Several counties in the same state, none the configured one."""
    area = "henry county; fulton county; williams county; ohio"
    result = _county_and_state_check(area, county_short="putnam",
                                     configured_state_code="ohio")
    assert result is False


def test_configured_county_in_multi_county_list():
    """Configured county in a multi-county list should still match."""
    area = "putnam county; van wert county; henry county; ohio"
    result = _county_and_state_check(area, county_short="putnam",
                                     configured_state_code="ohio")
    assert result is True


# ---------------------------------------------------------------------------
# short_with_list regression tests (multi-county NWS polygon alerts)
# ---------------------------------------------------------------------------

def _short_with_list_check(area_lower, county_short, configured_state_code):
    """Mirror the short_with_list heuristic from _detect_county_wide."""
    multi_county_list = bool(
        configured_state_code
        and area_lower.count(f', {configured_state_code}') > 1
    )
    return bool(
        county_short
        and county_short in area_lower
        and (area_lower.count(';') >= 2 or area_lower.count(',') >= 2)
        and not multi_county_list
    )


def test_short_with_list_source_has_multi_county_guard():
    """short_with_list in api.py must include the _multi_county_list guard."""
    with open('webapp/admin/api.py', 'r') as f:
        content = f.read()
    assert '_multi_county_list' in content, (
        "short_with_list must reference _multi_county_list to prevent false "
        "positives for multi-county NWS polygon alerts"
    )
    assert 'not _multi_county_list' in content, (
        "short_with_list must exclude multi-county alerts via 'not _multi_county_list'"
    )


def test_multi_county_nws_alert_not_county_wide():
    """'Allen, OH; Putnam, OH; Van Wert, OH' must NOT be detected as county-wide.

    This is the exact area_desc from the SVR alert that triggered the 99.4%
    / Allen County false-positive bug.  The polygon covers only SE Putnam
    County (15.7%), not the whole county.
    """
    area = "allen, oh; putnam, oh; van wert, oh"
    result = _short_with_list_check(area, county_short="putnam",
                                    configured_state_code="oh")
    assert result is False, (
        "'Allen, OH; Putnam, OH; Van Wert, OH' is a multi-county polygon alert "
        "and must NOT be detected as county-wide for a Putnam County station"
    )


def test_single_county_semicolon_list_is_county_wide():
    """A list of sub-areas within the configured county IS county-wide."""
    # e.g. NWS area_desc enumerating townships/villages within one county
    area = "ottawa; blanchard township; putnam; ohio"
    result = _short_with_list_check(area, county_short="putnam",
                                    configured_state_code="oh")
    assert result is True, (
        "A sub-area list for a single county should still be detected as county-wide"
    )


def test_two_county_alert_not_county_wide():
    """Two counties from the same state in area_desc is a multi-county alert."""
    area = "putnam, oh; allen, oh"
    result = _short_with_list_check(area, county_short="putnam",
                                    configured_state_code="oh")
    assert result is False, (
        "Two-county alert 'Putnam, OH; Allen, OH' must NOT be county-wide"
    )
