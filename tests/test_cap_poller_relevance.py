"""Unit tests for CAP poller relevance decisions."""
import logging

from poller.cap_poller import CAPPoller


def _make_test_poller() -> CAPPoller:
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_cap_poller")
    poller.zone_codes = {"OHZ016", "OHC137"}
    poller.same_codes = {"039137"}
    poller.county_upper = "PUTNAM COUNTY"
    return poller


def test_same_code_match_accepts_alert():
    poller = _make_test_poller()
    alert = {
        "properties": {
            "event": "Test Alert",
            "geocode": {"SAME": ["039137"]},
            "areaDesc": "Putnam",
        }
    }

    result = poller.get_alert_relevance_details(alert)

    assert result["is_relevant"] is True
    assert result["reason"] == "SAME_MATCH"
    assert result["relevance_matches"] == ["039137"]


def test_statewide_same_code_is_accepted():
    poller = _make_test_poller()
    alert = {
        "properties": {
            "event": "Statewide Alert",
            "geocode": {"SAME": ["039000"]},
            "areaDesc": "Ohio",
        }
    }

    result = poller.get_alert_relevance_details(alert)

    assert result["is_relevant"] is True
    assert result["reason"] == "SAME_MATCH"
    assert result["relevance_matches"] == ["039000"]


def test_area_match_blocked_when_other_same_codes_present():
    poller = _make_test_poller()
    alert = {
        "properties": {
            "event": "Neighbor Alert",
            "geocode": {"SAME": ["039063"]},
            "areaDesc": "Lucas; Wood; Ottawa; Hancock",
        }
    }

    result = poller.get_alert_relevance_details(alert)

    assert result["is_relevant"] is False
    assert result["reason"] == "NO_MATCH"


def test_alert_without_geocode_is_rejected():
    poller = _make_test_poller()
    alert = {
        "properties": {
            "event": "Geometry Only Alert",
            "geocode": {},
            "areaDesc": "Putnam County",
        }
    }

    result = poller.get_alert_relevance_details(alert)

    assert result["is_relevant"] is False
    assert result["reason"] == "NO_MATCH"
