"""Regression tests for the NMEA sentence handlers in ``app_core.gps.nmea``.

These behaviours were previously reachable only through
``GPSManager._handle_sentence`` — a 246-line method that needed a live manager
(lock, Redis client, serial config) before a single field could be asserted.
Now that the sentence-to-field mapping is a set of standalone handlers over an
explicit fix dictionary and parse state, each rule gets a direct test.

The multi-constellation cases are the ones worth guarding: both the GSV
per-talker bucketing and the GSA per-cycle union exist because a naive
implementation silently loses satellites, and neither failure raises.
"""

from __future__ import annotations

import pynmea2
import pytest

from app_core.gps.nmea import (
    NMEAParseState,
    apply_sentence,
)


def nmea(body: str) -> str:
    """Build a sentence with a correct checksum from its body."""
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return "$%s*%02X" % (body, checksum)


def parse(body: str):
    return pynmea2.parse(nmea(body))


@pytest.fixture
def fix():
    return {}


@pytest.fixture
def state():
    return NMEAParseState()


def feed(fix, state, body, *, min_satellites=4):
    return apply_sentence(fix, parse(body), min_satellites=min_satellites, state=state)


class TestGGA:
    def test_fix_quality_maps_to_label(self, fix, state):
        feed(fix, state, "GPGGA,000002.00,4807.038,N,01131.000,E,2,09,0.95,545.4,M,46.9,M,,")
        assert fix["fix_quality"] == "dgps_fix"
        assert fix["has_fix"] is True
        assert fix["satellites"] == 9

    def test_status_is_fix_only_at_or_above_min_satellites(self, fix, state):
        feed(fix, state, "GPGGA,000001.00,4807.038,N,01131.000,E,1,03,2.5,545.4,M,46.9,M,,",
             min_satellites=4)
        assert fix["status"] == "acquiring"
        feed(fix, state, "GPGGA,000001.00,4807.038,N,01131.000,E,1,04,2.5,545.4,M,46.9,M,,",
             min_satellites=4)
        assert fix["status"] == "fix"

    def test_no_fix_reports_acquiring_when_satellites_already_in_view(self, fix, state):
        fix["satellites_in_view"] = [{"prn": 1}]
        feed(fix, state, "GPGGA,000000.00,,,,,0,00,99.99,,,,,,")
        assert fix["status"] == "acquiring"

    def test_no_fix_and_nothing_in_view_reports_no_fix(self, fix, state):
        feed(fix, state, "GPGGA,000000.00,,,,,0,00,99.99,,,,,,")
        assert fix["status"] == "no_fix"

    def test_position_is_not_taken_without_a_fix(self, fix, state):
        feed(fix, state, "GPGGA,000000.00,4807.038,N,01131.000,E,0,00,99.99,,,,,,")
        assert "latitude" not in fix

    def test_blank_optional_fields_are_skipped_not_zeroed(self, fix, state):
        feed(fix, state, "GPGGA,000004.00,,,,,0,,,,,,,,")
        for key in ("altitude_m", "hdop", "geoid_separation_m", "dgps_age_s"):
            assert key not in fix


class TestRMC:
    def test_void_status_contributes_nothing(self, fix, state):
        feed(fix, state, "GPRMC,000004.00,V,4807.038,N,01131.000,E,1.0,2.0,060826,,")
        assert "latitude" not in fix
        assert "speed_knots" not in fix

    def test_active_status_populates_movement_fields(self, fix, state):
        feed(fix, state,
             "GPRMC,000001.00,A,4807.038,N,01131.000,E,0.50,54.70,060826,003.1,W")
        assert fix["speed_knots"] == pytest.approx(0.50)
        assert fix["track_angle"] == pytest.approx(54.70)
        assert fix["magnetic_variation"] == pytest.approx(3.1)
        assert fix["magnetic_variation_dir"] == "W"

    def test_datestamp_and_timestamp_yield_a_utc_datetime_effect(self, fix, state):
        effects = feed(fix, state,
                       "GPRMC,000001.00,A,4807.038,N,01131.000,E,0.5,54.7,060826,003.1,W")
        assert effects.utc_datetime is not None
        assert effects.utc_datetime.tzinfo is not None
        assert fix["gps_utc_time"].endswith("Z")


class TestGSVBucketing:
    def test_second_constellation_does_not_wipe_the_first(self, fix, state):
        """The bug this bucketing exists for: GLGSV msg_num==1 resetting GPGSV."""
        feed(fix, state, "GPGSV,1,1,04,01,05,040,20,02,10,090,22,03,20,140,25,04,30,190,28")
        assert len(fix["satellites_in_view"]) == 4
        feed(fix, state, "GLGSV,1,1,02,65,45,220,33,66,55,270,36")
        prns = [s["prn"] for s in fix["satellites_in_view"]]
        assert prns == [1, 2, 3, 4, 65, 66], "GLONASS group wiped the GPS bucket"

    def test_multi_part_group_publishes_only_on_the_last_message(self, fix, state):
        feed(fix, state, "GPGSV,2,1,05,01,05,040,21,02,10,090,23,03,20,140,26,04,30,190,29")
        assert "satellites_in_view" not in fix or len(fix["satellites_in_view"]) == 0
        feed(fix, state, "GPGSV,2,2,05,05,40,240,31")
        assert len(fix["satellites_in_view"]) == 5

    def test_reports_each_satellite_seen_as_an_effect(self, fix, state):
        effects = feed(fix, state, "GPGSV,1,1,02,01,05,040,20,02,10,090,22")
        assert [(t, p) for t, p, _ in effects.sats_seen] == [("GP", 1), ("GP", 2)]
        assert [snr for _, _, snr in effects.sats_seen] == [20, 22]

    def test_same_prn_from_two_constellations_keeps_both(self, fix, state):
        """PRN numbering is per-constellation and overlaps.

        Galileo and BeiDou both number from 1, so a $GAGSV PRN 5 and a $GPGSV
        PRN 5 are different satellites. Merging on PRN alone dropped one of
        them from the view — silently, because nothing raises.
        """
        feed(fix, state, "GPGSV,1,1,02,05,45,220,40,12,30,100,35")
        feed(fix, state, "GAGSV,1,1,02,05,60,300,44,09,20,050,30")
        identities = {(s["constellation"], s["prn"]) for s in fix["satellites_in_view"]}
        assert identities == {("GP", 5), ("GP", 12), ("GA", 5), ("GA", 9)}, (
            "a satellite was lost to a cross-constellation PRN collision"
        )

    def test_colliding_prns_keep_their_own_sky_position_and_snr(self, fix, state):
        """The collision didn't just drop a row — it corrupted the survivor.

        Whichever talker parsed last overwrote the other's elevation, azimuth
        and SNR, so the remaining PRN-5 row showed Galileo's sky position under
        a single undifferentiated entry.
        """
        feed(fix, state, "GPGSV,1,1,01,05,45,220,40")
        feed(fix, state, "GAGSV,1,1,01,05,60,300,44")
        by_id = {(s["constellation"], s["prn"]): s for s in fix["satellites_in_view"]}
        assert by_id[("GP", 5)]["elevation"] == 45
        assert by_id[("GP", 5)]["azimuth"] == 220
        assert by_id[("GP", 5)]["snr"] == 40
        assert by_id[("GA", 5)]["elevation"] == 60
        assert by_id[("GA", 5)]["azimuth"] == 300
        assert by_id[("GA", 5)]["snr"] == 44

    def test_publish_order_is_unchanged_when_every_prn_is_unique(self, fix, state):
        """The common case must not reorder — PRN stays the primary sort key."""
        feed(fix, state, "GPGSV,1,1,04,01,05,040,20,02,10,090,22,03,20,140,25,04,30,190,28")
        feed(fix, state, "GLGSV,1,1,02,65,45,220,33,66,55,270,36")
        assert [s["prn"] for s in fix["satellites_in_view"]] == [1, 2, 3, 4, 65, 66]

    def test_colliding_prns_are_ordered_deterministically_by_talker(self, fix, state):
        """Ties break on constellation so the published order is stable."""
        feed(fix, state, "GPGSV,1,1,01,05,45,220,40")
        feed(fix, state, "GAGSV,1,1,01,05,60,300,44")
        assert [
            (s["prn"], s["constellation"]) for s in fix["satellites_in_view"]
        ] == [(5, "GA"), (5, "GP")]

    def test_a_talkers_own_repeat_of_a_prn_still_replaces_in_place(self, fix, state):
        """Within one constellation a PRN is unique — a refresh must not duplicate."""
        feed(fix, state, "GPGSV,1,1,01,05,45,220,40")
        feed(fix, state, "GPGSV,1,1,01,05,50,225,42")
        assert len(fix["satellites_in_view"]) == 1
        assert fix["satellites_in_view"][0]["snr"] == 42


class TestGSAAccumulation:
    def test_empty_second_constellation_gsa_does_not_clear_the_union(self, fix, state):
        """An empty GLGSA must not reset active_satellite_prns to []."""
        feed(fix, state, "GPGGA,000003.00,4807.038,N,01131.000,E,1,09,0.95,545.4,M,46.9,M,,")
        feed(fix, state, "GPGSA,A,3,01,02,03,04,05,,,,,,,,1.80,0.95,1.20")
        assert fix["active_satellite_prns"] == [1, 2, 3, 4, 5]
        feed(fix, state, "GLGSA,A,1,,,,,,,,,,,,,99.99,99.99,99.99")
        assert fix["active_satellite_prns"] == [1, 2, 3, 4, 5], "empty GLGSA wiped the union"

    def test_next_gga_opens_a_fresh_cycle(self, fix, state):
        feed(fix, state, "GPGGA,000003.00,4807.038,N,01131.000,E,1,09,0.95,545.4,M,46.9,M,,")
        feed(fix, state, "GPGSA,A,3,01,02,03,,,,,,,,,1.80,0.95,1.20")
        assert fix["active_satellite_prns"] == [1, 2, 3]
        feed(fix, state, "GPGGA,000004.00,4807.038,N,01131.000,E,1,09,0.95,545.4,M,46.9,M,,")
        feed(fix, state, "GPGSA,A,3,20,21,,,,,,,,,,2.00,1.10,1.40")
        assert fix["active_satellite_prns"] == [20, 21], "cycle did not reset on GGA"

    def test_3d_mode_raises_the_3d_fix_effect(self, fix, state):
        effects = feed(fix, state, "GPGSA,A,3,01,02,,,,,,,,,,1.80,0.95,1.20")
        assert effects.saw_3d_fix is True
        assert fix["fix_mode"] == 3

    def test_2d_mode_does_not_raise_the_3d_fix_effect(self, fix, state):
        effects = feed(fix, state, "GPGSA,A,2,01,02,,,,,,,,,,3.20,2.50,2.00")
        assert effects.saw_3d_fix is False
        assert fix["fix_mode"] == 2

    def test_reports_used_satellites_with_their_talker(self, fix, state):
        effects = feed(fix, state, "GLGSA,A,3,65,66,,,,,,,,,,1.80,0.95,1.20")
        assert effects.sats_used == [("GL", 65), ("GL", 66)]


class TestDispatch:
    def test_sentence_counts_accumulate_per_type(self, fix, state):
        feed(fix, state, "GPGGA,000000.00,,,,,0,00,99.99,,,,,,")
        feed(fix, state, "GPGGA,000001.00,,,,,0,00,99.99,,,,,,")
        feed(fix, state, "GPGSA,A,1,,,,,,,,,,,,,99.99,99.99,99.99")
        assert fix["sentence_counts"] == {"GGA": 2, "GSA": 1}

    def test_unconsumed_sentence_types_still_count(self, fix, state):
        feed(fix, state, "GPVTG,054.7,T,034.4,M,005.5,N,010.2,K")
        assert fix["sentence_counts"]["VTG"] == 1
