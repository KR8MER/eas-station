"""Tests for the GPS HAT "refclocks aren't reaching chrony" suggestion.

Regression coverage for the false-positive where a station with PPS
disciplining chrony (stratum 1, reference clock) was told its refclocks
weren't reaching chrony and that it had fallen back to "internet NTP" —
when in fact only the coarse NMEA/GPS source gpsd would feed was starved.

The suggestion must now distinguish two states:

* chrony is synced to a reference clock (PPS/GPS/NMEA) but a *second*
  refclock is at Reach=0 — informational, never claims internet NTP; and
* no refclock is selected at all — chrony has genuinely fallen back to an
  internet peer, which keeps the original wording.
"""

from app_utils.gps_hat import _build_actions


def _report(sources, selected_source, stratum, unreached):
    """Minimal probe report exercising only the refclock action branch."""
    return {
        "expected_pps_pin": 18,
        "rtc": {
            "detected_chip": None,
            "expected_overlay": None,
            "chip_label": None,
            "porf_set": False,
        },
        "packages": {"items": []},
        "gpsd_config": {},
        "chrony_config": {"has_pps_refclock": True, "has_shm_refclock": True},
        "config_txt": {
            "path": "/boot/firmware/config.txt",
            "pps_gpio_overlay_line": "dtoverlay=pps-gpio,gpiopin=18",
            "i2c_rtc_overlay_line": None,
        },
        "pps": {"devices": [{"name": "pps0"}]},
        "serial": {"exists": True, "expected_baud": 9600},
        "chrony_runtime": {
            "tool_present": True,
            "tracking_ok": True,
            "stratum": stratum,
            "selected_source": selected_source,
            "sources": sources,
            "refclocks_unreached": unreached,
        },
    }


def _refclock_action(report):
    actions = _build_actions(report)
    return next(
        (a for a in actions if a["id"] == "refclocks_unreached"), None
    )


def test_pps_locked_does_not_claim_internet_ntp():
    """PPS reaching (stratum 1) + NMEA starved must not say 'internet NTP'."""
    sources = [
        {"mode": "#", "state": "*", "name": "PPS", "stratum": 0, "reach": 377},
        {"mode": "#", "state": "?", "name": "NMEA", "stratum": 0, "reach": 0},
        {"mode": "^", "state": "+", "name": "203.0.113.1", "stratum": 2, "reach": 377},
    ]
    action = _refclock_action(_report(sources, "PPS", 1, ["NMEA"]))

    assert action is not None, "an informational note should still surface"
    assert action["severity"] == "info"
    assert "internet NTP" not in action["label"]
    assert "stratum 1 via PPS" in action["label"]
    # The reason reassures the operator their clock is fine.
    assert "Your clock is fine" in action["reason"]


def test_no_refclock_selected_keeps_internet_ntp_wording():
    """When chrony has genuinely fallen back to a network peer, keep wording."""
    sources = [
        {"mode": "#", "state": "?", "name": "PPS", "stratum": 0, "reach": 0},
        {"mode": "#", "state": "?", "name": "GPS", "stratum": 0, "reach": 0},
        {"mode": "^", "state": "*", "name": "203.0.113.1", "stratum": 1, "reach": 377},
    ]
    action = _refclock_action(_report(sources, "203.0.113.1", 2, ["PPS", "GPS"]))

    assert action is not None
    assert "currently stratum 2 via internet NTP" in action["label"]


def test_refclock_match_falls_back_to_tracking_name():
    """A refclock selected by name (no '*' row) is still treated as locked."""
    sources = [
        {"mode": "#", "state": "+", "name": "PPS", "stratum": 0, "reach": 17},
        {"mode": "#", "state": "?", "name": "GPS", "stratum": 0, "reach": 0},
    ]
    action = _refclock_action(_report(sources, "PPS", 1, ["GPS"]))

    assert action is not None
    assert "internet NTP" not in action["label"]
    assert "stratum 1 via PPS" in action["label"]
