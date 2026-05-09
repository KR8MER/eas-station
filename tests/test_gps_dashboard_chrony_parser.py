"""
Tests for the chrony CSV parsers used by the GPS & Time dashboard.

The dashboard's backend invokes ``chronyc -c tracking`` and ``chronyc -c
sources`` and parses the machine-readable CSV responses with two helper
functions in ``app_utils.chrony_parser``.  Those helpers are pure (no
subprocess, no Flask, no database) and exactly the kind of code that
benefits from a small focused unit test — chrony's CSV format is stable
but field order matters, blank fields must round-trip to ``None`` rather
than crash, and state-character → status mapping in the UI depends on
this parser producing the documented field names.
"""
from __future__ import annotations

import pytest

from app_utils.chrony_parser import (
    parse_chronyc_tracking_csv,
    parse_chronyc_sources_csv,
)


class TestParseChronycTrackingCsv:
    """``parse_chronyc_tracking_csv`` — chronyc 4.x CSV tracking format."""

    def test_full_record_round_trips_all_fields(self):
        # Real-world-shaped sample: stratum-1 lock with PPS reference.
        # Columns: refid_hex,refid_name,stratum,reftime,sysoff,lastoff,
        # rmsoff,freq,residfreq,skew,rootdelay,rootdisp,updateint,leap
        sample = (
            "50535053,PPS,1,1735689600.123,"
            "0.000000125,0.000000089,0.000000234,"
            "3.345,-0.000,0.002,0.000000150,0.000009816,16.0,Normal"
        )
        out = parse_chronyc_tracking_csv(sample)
        assert out["reference_id_hex"] == "50535053"
        assert out["reference_id_name"] == "PPS"
        assert out["stratum"] == 1
        assert out["ref_time"] == "1735689600.123"
        assert out["system_time_offset_s"] == pytest.approx(1.25e-7)
        assert out["last_offset_s"] == pytest.approx(8.9e-8)
        assert out["rms_offset_s"] == pytest.approx(2.34e-7)
        assert out["frequency_ppm"] == pytest.approx(3.345)
        assert out["residual_freq_ppm"] == pytest.approx(0.0)
        assert out["skew_ppm"] == pytest.approx(0.002)
        assert out["root_delay_s"] == pytest.approx(1.5e-7)
        assert out["root_dispersion_s"] == pytest.approx(9.816e-6)
        assert out["update_interval_s"] == pytest.approx(16.0)
        assert out["leap_status"] == "Normal"

    def test_blank_fields_become_none_not_crashes(self):
        # Some chrony states (cold start, unsynchronized) have empty cells.
        # The parser must coerce them to None rather than ValueError.
        sample = "0,,,, , , , , , , , , ,"
        out = parse_chronyc_tracking_csv(sample)
        assert out["reference_id_hex"] == "0"
        assert out["reference_id_name"] is None
        assert out["stratum"] is None
        assert out["system_time_offset_s"] is None
        assert out["leap_status"] is None

    def test_short_record_pads_missing_fields_with_none(self):
        # A truncated/malformed CSV (e.g. older chrony) yields None for
        # the missing fields rather than IndexError.
        out = parse_chronyc_tracking_csv("ABCD,GPS,2")
        assert out["reference_id_hex"] == "ABCD"
        assert out["reference_id_name"] == "GPS"
        assert out["stratum"] == 2
        assert out["ref_time"] is None
        assert out["frequency_ppm"] is None
        assert out["leap_status"] is None

    def test_negative_offset_preserves_sign(self):
        # Sign matters — the dashboard colours offset cells red/green
        # based on whether the system clock is ahead or behind.
        sample = "ABCD,GPS,1,t,-0.005,-0.003,0.001,-1.2,0,0.01,0,0,16,Normal"
        out = parse_chronyc_tracking_csv(sample)
        assert out["system_time_offset_s"] == pytest.approx(-0.005)
        assert out["last_offset_s"] == pytest.approx(-0.003)
        assert out["frequency_ppm"] == pytest.approx(-1.2)


class TestParseChronycSourcesCsv:
    """``parse_chronyc_sources_csv`` — chronyc 4.x CSV sources format."""

    def test_multiple_rows_with_mixed_modes_and_states(self):
        # ^* = currently selected internet server, #* = best refclock,
        # ^- = combined-not-selected, #? = unreachable refclock.
        # Columns: M,S,Name,Stratum,Poll,Reach,LastRx,Adj,Orig,Err
        sample = (
            "#,*,PPS,0,4,377,25,-0.000000255,-0.000000313,0.000000223\n"
            "#,?,NMEA,0,4,0,300,0.0,0.0,0.0\n"
            "^,-,time3.example.com,2,10,377,38,0.003392,0.003380,0.000068"
        )
        out = parse_chronyc_sources_csv(sample)
        assert len(out) == 3

        pps = out[0]
        assert pps["mode"] == "#" and pps["state"] == "*"
        assert pps["name"] == "PPS"
        assert pps["stratum"] == 0
        assert pps["poll"] == 4
        # Reach is conventionally shown in octal (377 octal = 255 decimal),
        # but chrony emits it as a decimal in CSV mode — the UI will
        # convert.  We just store what chrony gave us.
        assert pps["reach"] == 377
        assert pps["last_rx_s"] == 25
        assert pps["last_sample_offset_s"] == pytest.approx(-2.55e-7)

        nmea = out[1]
        assert nmea["mode"] == "#" and nmea["state"] == "?"
        assert nmea["reach"] == 0  # classic "refclock not getting samples"
        assert nmea["last_rx_s"] == 300

        peer = out[2]
        assert peer["mode"] == "^" and peer["state"] == "-"
        assert peer["name"] == "time3.example.com"
        assert peer["stratum"] == 2
        assert peer["last_sample_offset_s"] == pytest.approx(0.003392)

    def test_short_row_is_skipped_not_crashed(self):
        # Defensive against a malformed line slipping in — the parser
        # must keep going and parse the rest.
        sample = "garbage\n#,*,PPS,0,4,377,25,0,0,0"
        out = parse_chronyc_sources_csv(sample)
        assert len(out) == 1
        assert out[0]["name"] == "PPS"

    def test_empty_input_returns_empty_list(self):
        assert parse_chronyc_sources_csv("") == []
        assert parse_chronyc_sources_csv("   \n  \n") == []

    def test_non_numeric_columns_become_none(self):
        # If chrony emits "-" or "?" in a numeric column (it does for
        # never-yet-sampled sources), we must store None rather than 0.
        sample = "#,?,GPS,-,4,-,-,-,-,-"
        out = parse_chronyc_sources_csv(sample)
        assert len(out) == 1
        row = out[0]
        assert row["mode"] == "#"
        assert row["state"] == "?"
        assert row["name"] == "GPS"
        assert row["stratum"] is None
        assert row["reach"] is None
        assert row["last_rx_s"] is None
        assert row["last_sample_offset_s"] is None
