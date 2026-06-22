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

"""Tests for build_same_header FIPS code handling in app_utils/eas.py."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app_utils.eas import build_same_header


def _make_alert(event="Required Weekly Test", sent=None, expires=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        event=event,
        status="Actual",
        message_type="Alert",
        sent=sent or now,
        expires=expires or (now + timedelta(hours=1)),
        severity="Unknown",
        urgency="Unknown",
        certainty="Observed",
    )


def _make_payload(same_codes, event_code=None):
    payload = {
        "raw_json": {
            "properties": {
                "geocode": {
                    "SAME": list(same_codes),
                }
            }
        },
        "message_type": "Alert",
    }
    if event_code:
        payload["resolved_event_code"] = event_code
    return payload


_CONFIG = {
    "originator": "EAS",
    "station_id": "EASTEST",
    "enabled": True,
}

_LOCATION_SETTINGS_WITH_COUNTIES = {
    "fips_codes": ["000003", "000039", "000063", "000069", "000125", "000137", "000161", "000173"],
}


def test_nationwide_000000_preserved_in_same_header():
    """A received 000000 (nationwide) alert must not be replaced by all configured
    FIPS codes.  The generated broadcast SAME header should contain 000000."""
    alert = _make_alert()
    payload = _make_payload(["000000"])

    header, location_codes, event_code = build_same_header(
        alert, payload, _CONFIG, _LOCATION_SETTINGS_WITH_COUNTIES
    )

    assert "000000" in location_codes, (
        "000000 nationwide wildcard should be preserved in the generated SAME header, "
        f"but got location_codes={location_codes}"
    )
    # Must NOT expand 000000 into all configured county codes
    assert location_codes == ["000000"], (
        f"Generated header should contain only 000000, not expanded county codes: {location_codes}"
    )


def test_statewide_wildcard_preserved_in_same_header():
    """A statewide SS000 code must pass through the FIPS filter and not be replaced
    by the fallback to all configured FIPS codes."""
    alert = _make_alert()
    payload = _make_payload(["039000"])  # Ohio statewide

    location_settings = {
        "fips_codes": ["039137", "039069"],
    }

    header, location_codes, event_code = build_same_header(
        alert, payload, _CONFIG, location_settings
    )

    assert "039000" in location_codes, (
        f"Statewide wildcard 039000 should be preserved, got: {location_codes}"
    )


def test_specific_county_code_filtered_to_configured():
    """A specific county code that matches a configured FIPS code should be kept;
    non-matching codes should be removed."""
    alert = _make_alert()
    # Alert covers two counties; only one is configured
    payload = _make_payload(["039137", "018001"])

    location_settings = {
        "fips_codes": ["039137", "039069"],
    }

    header, location_codes, event_code = build_same_header(
        alert, payload, _CONFIG, location_settings
    )

    assert "039137" in location_codes
    assert "018001" not in location_codes
