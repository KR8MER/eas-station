import pytest

from app_core.audio.fips_utils import determine_fips_matches


def test_direct_fips_match_returns_exact_codes():
    configured = ['039137', '039069']
    alert_codes = ['039137']

    matches = determine_fips_matches(alert_codes, configured)

    assert matches == ['039137']


def test_nationwide_wildcard_matches_all_configured_codes():
    configured = ['039137', '039069']
    alert_codes = ['000000']

    matches = determine_fips_matches(alert_codes, configured)

    assert matches == sorted(configured)


def test_statewide_wildcard_matches_configured_state_codes():
    configured = ['039137', '018001', '179123']
    alert_codes = ['039000']  # Ohio statewide

    matches = determine_fips_matches(alert_codes, configured)

    assert matches == ['039137']


def test_mixed_codes_include_direct_and_wildcard_matches():
    configured = ['039137', '039069', '018001']
    alert_codes = ['039000', '018001']

    matches = determine_fips_matches(alert_codes, configured)

    assert matches == sorted(['018001', '039137', '039069'])
