"""Unit tests for the GPS manager NMEA logging and PMTK helpers.

EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

These tests do not touch real hardware — they only exercise the parts of
GPSManager that are pure data manipulation (sentence buffering, checksum
computation, status payload shape).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_gps_module():
    """Load gps_manager.py without going through the app_core package init,
    which pulls in flask/sqlalchemy that aren't required for these tests."""
    path = Path(__file__).resolve().parents[1] / "app_core" / "gps" / "gps_manager.py"
    spec = importlib.util.spec_from_file_location("gps_manager_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gps_module():
    return _load_gps_module()


@pytest.fixture
def manager(gps_module):
    return gps_module.GPSManager(
        config={"serial_port": "/dev/null", "baudrate": 9600, "pps_gpio_pin": 4},
    )


def test_pmtk_checksum_is_correct(gps_module):
    """The PMTK314 enable-all-sentences command must carry checksum 2D.

    A wrong checksum would cause the MTK3339 to silently ignore the command,
    leaving the receiver in its default RMC+GGA-only mode and the sky view
    permanently empty — which is the exact bug we're fixing.
    """
    cmd = gps_module.PMTK_SET_NMEA_OUTPUT
    assert cmd.startswith("$PMTK314,0,1,1,1,1,5,")
    assert "*2D" in cmd, f"Wrong PMTK checksum, got: {cmd!r}"
    assert cmd.endswith("\r\n")


def test_record_raw_sentence_classifies_by_type(manager):
    manager._record_raw_sentence(
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    )
    manager._record_raw_sentence(
        "$GPGSV,1,1,03,01,40,083,42,02,17,308,41,03,07,344,39*7B"
    )
    manager._record_raw_sentence(
        "$GLGSV,1,1,02,65,28,124,32,66,18,068,28*64"
    )
    counts = dict(manager._nmea_counts)
    assert counts["GGA"] == 1
    assert counts["GSV"] == 2  # both GP and GL talker prefixes collapse to GSV
    assert manager._nmea_total == 3
    assert manager._nmea_parse_errors == 0


def test_record_raw_sentence_tracks_parse_errors(manager):
    manager._record_raw_sentence("$BOGUS,not,nmea", parse_ok=False)
    assert manager._nmea_parse_errors == 1
    log = list(manager._nmea_log)
    assert log[-1]["ok"] is False


def test_get_nmea_log_returns_recent_sentences(manager):
    for i in range(5):
        manager._record_raw_sentence(f"$GPRMC,{i},A,,,,,,,,,*00")
    payload = manager.get_nmea_log(limit=3)
    assert payload["total_sentences"] == 5
    assert payload["counts_by_type"]["RMC"] == 5
    assert len(payload["sentences"]) == 3
    # Most recent sample should be the last one we appended
    assert payload["sentences"][-1]["text"].startswith("$GPRMC,4,")


def test_get_status_includes_nmea_summary(manager):
    manager._record_raw_sentence("$GPGGA,,,,,,0,,,,,,,,*48")
    status = manager.get_status()
    # The new keys must be present so the diagnostics + UI can render them
    for key in (
        "nmea_counts",
        "nmea_total",
        "nmea_parse_errors",
        "nmea_recent",
        "pps_backend",
        "pps_error",
        "pps_gpio_active",
    ):
        assert key in status, f"missing key {key!r} in status payload"
    assert status["nmea_counts"]["GGA"] == 1
    assert status["pps_gpio_active"] is False


def test_empty_fix_exposes_pps_metadata(manager):
    fix = manager._empty_fix()
    assert fix["pps_backend"] is None
    assert fix["pps_error"] is None
    assert fix["pps_gpio_active"] is False
    assert fix["pps_pulse_count"] == 0
