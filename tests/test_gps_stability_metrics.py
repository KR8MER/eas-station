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

---

Tests for the PPS-derived stability metrics on ``GPSManager``.

Covers the additions made for the noise-floor-compensated stability
grading on the GPS dashboard:

* jitter percentiles (p95/p99 of |Δ|) in ``_compute_jitter_summary``
* the white-PM measurement floor (``sigma_x_wpm_s`` +
  ``floor_sigma_y``) shipped alongside the overlapping ADEV

The synthetic-signal tests lean on the standard relationships for
white phase modulation: with iid timestamping noise of σ_x per pulse,
interval deltas spread as σ_Δ = √2·σ_x and the overlapping Allan
deviation follows σ_y(τ) ≈ √3·σ_x/τ — i.e. the measured curve should
sit right on the computed floor.
"""
import math
import random

import pytest

from app_core.gps.gps_manager import GPSManager

NOMINAL_NS = 1_000_000_000


def _white_pm_intervals(n: int, sigma_x_ns: float, seed: int = 42) -> list:
    """Synthesise PPS intervals whose only imperfection is white
    timestamping noise of ``sigma_x_ns`` per pulse edge."""
    rng = random.Random(seed)
    phase = [rng.gauss(0.0, sigma_x_ns) for _ in range(n + 1)]
    return [
        int(round(NOMINAL_NS + (phase[i + 1] - phase[i])))
        for i in range(n)
    ]


class TestJitterPercentiles:
    def test_percentiles_present_and_ordered(self):
        intervals = _white_pm_intervals(2000, sigma_x_ns=2000.0)
        out = GPSManager._compute_jitter_summary(intervals)
        assert out["p95_ns"] is not None
        assert out["p99_ns"] is not None
        # |Δ| percentiles must be ordered and bounded by the peak.
        assert 0 <= out["p95_ns"] <= out["p99_ns"] <= out["peak_ns"]

    def test_percentiles_expose_heavy_tail(self):
        # 985 clean pulses + 15 outliers at 50 µs: σ and peak blow up,
        # but p95 must stay near the clean population — that's the whole
        # point of reporting percentiles alongside σ.  p99 (nearest-rank)
        # lands inside the 1.5 % outlier tail and exposes it.
        intervals = [NOMINAL_NS + 100] * 985 + [NOMINAL_NS + 50_000] * 15
        out = GPSManager._compute_jitter_summary(intervals)
        assert out["peak_ns"] == 50_000
        assert out["p95_ns"] <= 1_000
        assert out["p99_ns"] == 50_000

    def test_too_few_samples_returns_placeholders(self):
        out = GPSManager._compute_jitter_summary([NOMINAL_NS])
        assert out["sample_count"] == 1
        # New keys must not appear partially-populated on the empty path.
        assert "p95_ns" not in out or out.get("p95_ns") is None


class TestAdevNoiseFloor:
    def test_empty_input_carries_floor_keys(self):
        out = GPSManager._compute_allan_deviation([])
        assert out["tau_s"] == []
        assert out["floor_sigma_y"] == []
        assert out["sigma_x_wpm_s"] is None

    def test_floor_matches_formula(self):
        intervals = _white_pm_intervals(1500, sigma_x_ns=2000.0)
        out = GPSManager._compute_allan_deviation(intervals)
        sigma_x = out["sigma_x_wpm_s"]
        assert sigma_x is not None and sigma_x > 0
        assert len(out["floor_sigma_y"]) == len(out["tau_s"])
        for tau, floor in zip(out["tau_s"], out["floor_sigma_y"]):
            assert floor == pytest.approx(math.sqrt(3.0) * sigma_x / tau)

    def test_sigma_x_recovers_injected_noise(self):
        sigma_x_ns = 2000.0
        intervals = _white_pm_intervals(4000, sigma_x_ns=sigma_x_ns)
        out = GPSManager._compute_allan_deviation(intervals)
        # σ_x = σ_Δ/√2 should land near the injected per-pulse noise.
        assert out["sigma_x_wpm_s"] == pytest.approx(sigma_x_ns / 1e9, rel=0.10)

    def test_white_pm_adev_sits_on_the_floor(self):
        # For pure white PM the measured σ_y(τ) must track √3·σ_x/τ —
        # this is the regression guard for the dashboard's "noise-floor
        # limited" grading: a healthy clock with µs timestamp jitter
        # must produce sigma_y ≈ floor at every τ, not above it.
        intervals = _white_pm_intervals(4000, sigma_x_ns=3000.0, seed=7)
        out = GPSManager._compute_allan_deviation(intervals)
        assert out["tau_s"], "expected at least τ=1 with 4000 samples"
        for tau, sigma, floor in zip(
            out["tau_s"], out["sigma_y"], out["floor_sigma_y"]
        ):
            # Statistical estimator scatter grows with τ (fewer terms),
            # so allow a generous but still discriminating band.
            assert sigma == pytest.approx(floor, rel=0.35), (
                f"σ_y(τ={tau}) should hug the white-PM floor"
            )

    def test_frequency_offset_rises_above_floor(self):
        # A clock running 1 ppm fast with *tiny* timestamp noise must
        # NOT be classified as floor-limited: σ_y should sit well above
        # the white-PM floor.  (Constant frequency offset alone gives
        # zero ADEV, so add a slow square-wave toggle ±1 ppm.)
        intervals = []
        for i in range(3000):
            ppm = 1.0 if (i // 300) % 2 == 0 else -1.0
            intervals.append(int(NOMINAL_NS + ppm * 1000))  # ±1 ppm = ±1000 ns
        out = GPSManager._compute_allan_deviation(intervals)
        by_tau = dict(zip(out["tau_s"], out["sigma_y"]))
        floor_by_tau = dict(zip(out["tau_s"], out["floor_sigma_y"]))
        assert 100 in by_tau
        assert by_tau[100] > 3 * floor_by_tau[100], (
            "real frequency wander must clear the 3× floor warn threshold"
        )


class TestTdevMtie:
    def test_arrays_parallel_to_tau(self):
        intervals = _white_pm_intervals(1500, sigma_x_ns=2000.0)
        out = GPSManager._compute_allan_deviation(intervals)
        assert len(out["tdev_s"]) == len(out["tau_s"])
        assert len(out["mtie_s"]) == len(out["tau_s"])

    def test_empty_input_carries_keys(self):
        out = GPSManager._compute_allan_deviation([])
        assert out["tdev_s"] == []
        assert out["mtie_s"] == []

    def test_tdev_at_tau1_recovers_sigma_x_for_white_pm(self):
        # For white PM, Mod σ²_y(1) equals AVAR(1) = 3σ_x²/τ², so
        # TDEV(1) = τ·Modσ_y/√3 = σ_x.  Direct calibration check.
        sigma_x_ns = 2500.0
        intervals = _white_pm_intervals(4000, sigma_x_ns=sigma_x_ns, seed=3)
        out = GPSManager._compute_allan_deviation(intervals)
        by_tau = dict(zip(out["tau_s"], out["tdev_s"]))
        assert by_tau[1] == pytest.approx(sigma_x_ns / 1e9, rel=0.10)

    def test_mtie_of_constant_frequency_offset_is_linear_in_tau(self):
        # A clock running exactly +1 µs/s draws a clean phase ramp, so
        # the worst excursion inside a τ-second window is exactly τ µs.
        offset_ns = 1000
        intervals = [NOMINAL_NS + offset_ns] * 1200
        out = GPSManager._compute_allan_deviation(intervals)
        by_tau = dict(zip(out["tau_s"], out["mtie_s"]))
        assert by_tau[1] == pytest.approx(offset_ns / 1e9, rel=1e-6)
        assert by_tau[10] == pytest.approx(10 * offset_ns / 1e9, rel=1e-6)
        assert by_tau[100] == pytest.approx(100 * offset_ns / 1e9, rel=1e-6)

    def test_mtie_catches_a_single_step(self):
        # A one-off 5 µs phase step inside an otherwise clean run must
        # dominate MTIE at every τ — that's the property masks rely on.
        intervals = [NOMINAL_NS] * 600
        intervals[300] = NOMINAL_NS + 5_000
        out = GPSManager._compute_allan_deviation(intervals)
        for tau, mtie in zip(out["tau_s"], out["mtie_s"]):
            if mtie is None:
                continue
            assert mtie == pytest.approx(5_000 / 1e9, rel=1e-6), (
                f"MTIE(τ={tau}) should equal the 5 µs step"
            )

    def test_tdev_none_when_buffer_too_short_for_tau(self):
        # 250 samples: ADEV needs 2m+1 (τ=100 → 201 ✓) but TDEV needs
        # 3m+1 (τ=100 → 301 ✗) — the slot must be None, not missing.
        intervals = _white_pm_intervals(250, sigma_x_ns=1000.0)
        out = GPSManager._compute_allan_deviation(intervals)
        assert 100 in out["tau_s"]
        idx = out["tau_s"].index(100)
        assert out["tdev_s"][idx] is None
        assert out["mtie_s"][idx] is not None


class TestTrendCollection:
    """The trend sampler must pick up the new stability/thermal/position
    fields from ``get_status()`` so the dashboard's history panels have
    something to draw."""

    class _StubManager:
        def __init__(self, status):
            self._status = status

        def get_status(self):
            return self._status

    def test_collect_gps_status_extracts_new_fields(self):
        from services.gps import trends as gps_trends

        status = {
            "hdop": 1.0,
            "satellites_in_view": [
                {"prn": 5, "snr": 40, "constellation": "GP"},
                {"prn": 7, "snr": 0, "constellation": "GP"},
                {"prn": 12, "snr": 35, "constellation": "GL"},
            ],
            "active_satellite_prns": [5, 12],
            "allan_deviation": {
                "tau_s": [1, 10, 100],
                "sigma_y": [3.8e-6, 3.8e-7, 4.2e-8],
            },
            "cpu_temp_c": 52.3,
            "latitude": 41.0105,
            "longitude": -84.0458,
        }
        out = gps_trends.collect_gps_status(self._StubManager(status))
        assert out["sats_used"] == 2.0
        assert out["sats_visible"] == 3.0
        assert out["adev_10s"] == pytest.approx(3.8e-7)
        assert out["adev_100s"] == pytest.approx(4.2e-8)
        assert out["cpu_temp_c"] == pytest.approx(52.3)
        assert out["lat"] == pytest.approx(41.0105)
        assert out["lon"] == pytest.approx(-84.0458)

    def test_collect_gps_status_tolerates_missing_new_fields(self):
        from services.gps import trends as gps_trends

        out = gps_trends.collect_gps_status(self._StubManager({"hdop": 2.0}))
        assert out["sats_used"] == 0.0
        assert out["sats_visible"] == 0.0
        assert out["adev_10s"] is None
        assert out["adev_100s"] is None
        assert out["cpu_temp_c"] is None
        assert out["lat"] is None
        assert out["lon"] is None

    def test_new_fields_aggregate_through_rollups(self):
        from services.gps import trends as gps_trends

        rows = [
            {"t": 0,     "skew_ppm": 0.010, "cpu_temp_c": 50.0, "adev_10s": 3.0e-7,
             "sats_used": 10.0, "lat": 41.0, "lon": -84.0},
            {"t": 20000, "skew_ppm": 0.014, "cpu_temp_c": 52.0, "adev_10s": 5.0e-7,
             "sats_used": 12.0, "lat": 41.0, "lon": -84.0},
        ]
        out = gps_trends.aggregate_samples(rows, 0, 60_000)
        assert out["skew_ppm"] == pytest.approx(0.012)
        assert out["cpu_temp_c"] == pytest.approx(51.0)
        assert out["adev_10s"] == pytest.approx(4.0e-7)
        assert out["sats_used"] == pytest.approx(11.0)
        assert out["sats_used_max"] == 12.0
        assert out["lat"] == pytest.approx(41.0)
        assert out["lon"] == pytest.approx(-84.0)


class TestCpuTempHelper:
    def test_read_cpu_temp_never_raises(self):
        # Environment-dependent (containers have no thermal zones) —
        # the contract is simply "float in a sane range, or None".
        val = GPSManager._read_cpu_temp_c()
        assert val is None or (-40.0 <= val <= 150.0)
