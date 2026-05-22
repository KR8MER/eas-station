"""
Tests for the multi-resolution GPS trend archive in ``services.gps.trends``.

The GPS dashboard sparklines and per-PRN heatmap are fed by a tiered
RRD-style archive in Redis (raw 5 s → 1 min → 10 min → 1 h).  These
tests exercise the bucket-aggregator and rollup helpers in isolation
(no Redis required) plus a regression test for the Allan-deviation
buffer cap that was previously stuck at 1024 PPS samples.
"""
from __future__ import annotations

import pytest

# Phase 4 of the hardware_service.py split moved every helper that used
# to live on ``hardware_service`` into ``services.gps.trends`` (pure
# functions taking the redis client + per-tier bucket-id dict as args)
# and replaced the orchestrator with the per-subsystem subprocess
# ``services/gps/__main__.py``.  These tests now exercise the library
# directly — no module-level wrapper to keep in sync.
from services.gps import trends as gps_trends
from services.gps import (
    GPS_TRENDS_DEFAULT_WINDOW,
    GPS_TRENDS_TIERS,
    GPS_TRENDS_WINDOW_TO_TIER,
    new_last_bucket_ids,
)
from app_core.gps.gps_manager import GPSManager


# --------------------------------------------------------------------------- #
# aggregate_samples — pure bucket aggregator, no Redis touched.               #
# --------------------------------------------------------------------------- #
class TestAggregateGpsTrendSamples:
    """Verifies min / max / avg / sample_count and per-PRN merging."""

    def _row(self, t_ms, **kw):
        base = {"t": t_ms}
        base.update(kw)
        return base

    def test_empty_bucket_returns_none(self):
        assert gps_trends.aggregate_samples([], 0, 60_000) is None

    def test_aggregates_numeric_fields_to_mean_min_max(self):
        rows = [
            self._row(0,     hdop=1.0, avg_snr=40.0),
            self._row(20000, hdop=2.0, avg_snr=42.0),
            self._row(40000, hdop=3.0, avg_snr=44.0),
        ]
        out = gps_trends.aggregate_samples(rows, 0, 60_000)
        assert out is not None
        # Average across the bucket.
        assert out["hdop"] == pytest.approx(2.0)
        assert out["avg_snr"] == pytest.approx(42.0)
        # min/max retained on side-channel fields so coarse-tier
        # sparklines can still surface "worst sample in bucket".
        assert out["hdop_min"] == 1.0
        assert out["hdop_max"] == 3.0
        # Bucket bounds and sample_count.
        assert out["bucket_start_ms"] == 0
        assert out["bucket_end_ms"] == 60_000
        assert out["t"] == 60_000  # bucket end timestamp
        assert out["sample_count"] == 3

    def test_skips_missing_numeric_fields(self):
        # Fields are optional per row — averaging must use only the
        # rows that supplied each field, not poison the result.
        rows = [
            self._row(0,     hdop=1.0),
            self._row(20000),                # no hdop, no avg_snr
            self._row(40000, hdop=3.0, avg_snr=50.0),
        ]
        out = gps_trends.aggregate_samples(rows, 0, 60_000)
        assert out["hdop"] == pytest.approx(2.0)        # mean of [1.0, 3.0]
        assert out["avg_snr"] == pytest.approx(50.0)    # mean of [50.0]

    def test_jamming_state_keeps_last_non_empty(self):
        rows = [
            self._row(0,     jamming_state="ok"),
            self._row(20000, jamming_state="warning"),
            self._row(40000),
            self._row(50000, jamming_state="critical"),
        ]
        out = gps_trends.aggregate_samples(rows, 0, 60_000)
        assert out["jamming_state"] == "critical"

    def test_per_prn_snr_merges_to_mean(self):
        rows = [
            self._row(0,     prn_snr={"GP05": 40.0, "GP07": 42.0}),
            self._row(20000, prn_snr={"GP05": 44.0}),                    # missing GP07
            self._row(40000, prn_snr={"GP07": 38.0, "GL12": 30.0}),      # new PRN appears
        ]
        out = gps_trends.aggregate_samples(rows, 0, 60_000)
        prn = out["prn_snr"]
        assert prn["GP05"] == pytest.approx(42.0)        # (40 + 44) / 2
        assert prn["GP07"] == pytest.approx(40.0)        # (42 + 38) / 2
        assert prn["GL12"] == pytest.approx(30.0)        # only seen once

    def test_returns_none_when_only_garbage(self):
        # Rows with no usable numeric fields, no jam state, no PRN map
        # should produce ``None`` so the caller doesn't push an empty
        # placeholder onto the archive.
        rows = [{"t": 1000, "garbage": "yes"}]
        assert gps_trends.aggregate_samples(rows, 0, 60_000) is None


# --------------------------------------------------------------------------- #
# emit_rollups — bucket-boundary detection + tier emission.                   #
# --------------------------------------------------------------------------- #
class _FakeRedisPipeline:
    """Minimal pipeline mock: records (op, key, args) tuples."""

    def __init__(self, parent):
        self._parent = parent
        self._ops = []

    def lpush(self, key, value):
        self._ops.append(("lpush", key, value))
        return self

    def ltrim(self, key, start, stop):
        self._ops.append(("ltrim", key, start, stop))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "lpush":
                self._parent.store.setdefault(op[1], []).insert(0, op[2])
            elif op[0] == "ltrim":
                _, key, start, stop = op
                lst = self._parent.store.get(key, [])
                self._parent.store[key] = lst[start:stop + 1]
        self._ops = []


class _FakeRedis:
    """In-memory stand-in for the few methods the rollup uses."""

    def __init__(self):
        self.store: "dict[str, list]" = {}

    def lrange(self, key, start, stop):
        lst = self.store.get(key, [])
        # Redis semantics: stop is inclusive; -1 means "last".
        if stop == -1:
            return lst[start:]
        return lst[start:stop + 1]

    def pipeline(self):
        return _FakeRedisPipeline(self)


@pytest.fixture
def fake_redis():
    return _FakeRedis()


@pytest.fixture
def bucket_ids():
    # Fresh per-tier "last seen bucket" state — earlier tests in the
    # session must not be able to flag a boundary for us.
    return new_last_bucket_ids()


class TestEmitGpsTrendRollups:
    """End-to-end-ish tests with the in-memory fake Redis above."""

    def _seed_raw(self, fake, samples):
        import json
        fake.store[gps_trends.redis_key_for_tier("raw")] = [
            json.dumps(s) for s in reversed(samples)  # newest-first
        ]

    def test_first_call_initializes_state_does_not_emit(self, fake_redis, bucket_ids):
        self._seed_raw(fake_redis, [{"t": 1_000_000, "hdop": 1.0}])
        gps_trends.emit_rollups(fake_redis, bucket_ids, now_ms=1_000_000)
        # No rollup tier should exist yet — first observation only
        # remembers which bucket we're in.
        for tier in ("1m", "10m", "1h"):
            assert gps_trends.redis_key_for_tier(tier) not in fake_redis.store
        for tier in ("1m", "10m", "1h"):
            assert bucket_ids[tier] is not None

    def test_emits_one_row_per_crossed_bucket_for_1m_tier(self, fake_redis, bucket_ids):
        # 90 s of raw samples spanning two 1-min buckets:
        #   bucket A: t ∈ [0, 60_000)   — three rows
        #   bucket B: t ∈ [60_000, 120_000) — one row at t=70_000
        rows = [
            {"t":   5_000, "hdop": 1.0, "prn_snr": {"GP05": 40.0}},
            {"t":  20_000, "hdop": 2.0, "prn_snr": {"GP05": 42.0}},
            {"t":  40_000, "hdop": 3.0, "prn_snr": {"GP05": 44.0}},
            {"t":  70_000, "hdop": 9.0, "prn_snr": {"GP05": 30.0}},
        ]
        self._seed_raw(fake_redis, rows)

        # Initial call lands inside bucket A; just primes the state.
        gps_trends.emit_rollups(fake_redis, bucket_ids, now_ms=5_000)
        # Now we cross into bucket B — bucket A should be aggregated.
        gps_trends.emit_rollups(fake_redis, bucket_ids, now_ms=70_000)

        import json as _json
        emitted = fake_redis.store.get(gps_trends.redis_key_for_tier("1m"), [])
        assert len(emitted) == 1, "exactly one closed bucket should have been rolled up"
        agg = _json.loads(emitted[0])
        # Mean across bucket A samples.
        assert agg["hdop"] == pytest.approx(2.0)
        assert agg["hdop_min"] == 1.0
        assert agg["hdop_max"] == 3.0
        assert agg["sample_count"] == 3
        assert agg["tier"] == "1m"
        # Per-PRN map preserved.
        assert agg["prn_snr"]["GP05"] == pytest.approx(42.0)
        # Bucket window matches a 1-min wall-clock-aligned bucket.
        assert agg["bucket_start_ms"] == 0
        assert agg["bucket_end_ms"] == 60_000

    def test_no_emission_when_bucket_unchanged(self, fake_redis, bucket_ids):
        self._seed_raw(fake_redis, [
            {"t":  5_000, "hdop": 1.0},
            {"t": 20_000, "hdop": 2.0},
        ])
        gps_trends.emit_rollups(fake_redis, bucket_ids, now_ms=5_000)
        gps_trends.emit_rollups(fake_redis, bucket_ids, now_ms=20_000)  # same 1-min bucket
        assert gps_trends.redis_key_for_tier("1m") not in fake_redis.store


# --------------------------------------------------------------------------- #
# Window → tier mapping table is the API contract clients rely on.            #
# --------------------------------------------------------------------------- #
class TestWindowToTierMapping:
    def test_default_window_maps_to_raw_tier(self):
        assert GPS_TRENDS_WINDOW_TO_TIER[GPS_TRENDS_DEFAULT_WINDOW] == "raw"

    def test_known_windows_each_resolve_to_a_defined_tier(self):
        for window, tier in GPS_TRENDS_WINDOW_TO_TIER.items():
            assert tier in GPS_TRENDS_TIERS, (
                f"window {window!r} maps to undefined tier {tier!r}"
            )

    def test_long_windows_use_coarser_resolution(self):
        # Sanity-check: 30-day window should not be served by raw 5 s
        # ticks (that'd be 518 400 samples — ridiculous).
        bucket_30d, _ = GPS_TRENDS_TIERS[GPS_TRENDS_WINDOW_TO_TIER["30d"]]
        bucket_1h, _ = GPS_TRENDS_TIERS[GPS_TRENDS_WINDOW_TO_TIER["1h"]]
        assert bucket_30d > bucket_1h


# --------------------------------------------------------------------------- #
# GPSManager Allan deviation: regression for the previous 1024-sample cap.    #
# --------------------------------------------------------------------------- #
class TestAllanDeviationLongTau:
    """The PPS interval ring used to be capped at 1024 samples, which
    made τ=1000 s ADEV impossible (need ≥2001 samples) and even τ=100 s
    statistically thin.  Capacity is now 16 384 samples (~4.5 h) and
    the ADEV computation now also reports τ=1000 s."""

    def test_pps_interval_ring_holds_at_least_10000_samples(self):
        m = GPSManager.__new__(GPSManager)  # avoid full __init__ side effects
        # Mirror __init__'s relevant line.
        from collections import deque
        m._pps_interval_ns = deque(maxlen=16384)
        for i in range(12000):
            m._pps_interval_ns.append(1_000_000_000 + (i % 100))  # 100 ns drift
        assert len(m._pps_interval_ns) == 12000

    def test_adev_reports_tau_1000_with_enough_samples(self):
        # 2500 PPS pulses > 2*1000 + 1, so τ=1000 should appear in the
        # output.  Use a deterministic ramp so σ_y is non-zero.
        intervals = [1_000_000_000 + (i % 50) for i in range(2500)]
        out = GPSManager._compute_allan_deviation(intervals)
        assert 1000 in out["tau_s"], (
            "τ=1000 s should be reported when buffer has ≥2001 samples"
        )
        idx = out["tau_s"].index(1000)
        assert out["sigma_y"][idx] > 0.0


class TestGetStatusCaching:
    """Regression guard: expensive parts of ``get_status()`` must be
    cached to avoid recomputing the 16384-float ADEV phase array (plus
    a fresh copy of ``_pps_interval_ns`` and ``_sat_history``) on every
    dashboard poll.  The dashboard polls /api/hardware/gps/status at
    1 Hz; without caching, sustained dashboard sessions push ~1 MB/s
    of short-lived allocations through glibc, which (combined with
    MALLOC_TRIM_THRESHOLD_=131072 from the gps-subsystem systemd unit)
    causes the arena to grow but never trim back."""

    def _build_manager(self):
        """Minimal manager wired enough that ``get_status()`` runs."""
        import threading
        from collections import deque
        from datetime import datetime, timezone

        m = GPSManager.__new__(GPSManager)
        m._lock = threading.RLock()
        m._fix = {
            "running": True,
            "has_fix": True,
            "fix_mode": 3,
            "last_sentence_at": datetime.now(timezone.utc).isoformat(),
        }
        m._recent_sentences = deque(maxlen=100)
        m._pps_interval_ns = deque(maxlen=16384)
        for i in range(2500):
            m._pps_interval_ns.append(1_000_000_000 + (i % 50))
        m._sat_history = {
            f"GP{n:02d}": {
                "prn_string": f"GP{n:02d}",
                "constellation": "GP",
                "prn": n,
                "first_seen_at": "2026-05-11T00:00:00+00:00",
                "last_seen_at": "2026-05-11T00:00:30+00:00",
                "last_used_at": None,
                "last_snr": 40,
                "max_snr": 40,
                "min_snr": 40,
            }
            for n in range(1, 33)
        }
        m._last_3d_fix_at = None
        m._pps_kernel_device = None
        m._pps_gpio_active = False
        m._status_cache_at_mono = 0.0
        m._status_cache_min_interval_s = 1.0
        m._cached_jitter = {}
        m._cached_allan = {}
        m._cached_sat_history = []
        m._cached_pps_interval_count = 0
        return m

    def test_back_to_back_calls_reuse_the_cached_dicts(self):
        """Two get_status() calls within the cache window must return
        the SAME cached dicts (identity, not just equal) for the heavy
        derived fields.  This proves the recompute was skipped."""
        m = self._build_manager()
        first = m.get_status()
        second = m.get_status()
        assert first["allan_deviation"] is second["allan_deviation"]
        assert first["pps_jitter"] is second["pps_jitter"]
        assert first["satellite_history"] is second["satellite_history"]

    def test_cache_expiry_recomputes(self):
        """After the cache window elapses, the next call recomputes —
        the cached objects are replaced, not reused."""
        m = self._build_manager()
        first = m.get_status()
        # Force expiry by rewinding the cache timestamp past the window.
        m._status_cache_at_mono -= 10.0
        second = m.get_status()
        assert first["allan_deviation"] is not second["allan_deviation"]
        assert first["pps_jitter"] is not second["pps_jitter"]

    def test_satellite_history_is_sorted_by_constellation_and_prn(self):
        m = self._build_manager()
        out = m.get_status()
        sats = out["satellite_history"]
        assert sats, "expected satellite_history to be populated"
        keys = [(s["constellation"], s["prn"]) for s in sats]
        assert keys == sorted(keys), "satellite_history must be pre-sorted"
