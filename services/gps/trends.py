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

from __future__ import annotations

"""GPS / chrony trend sampler — multi-resolution archive.

The /admin/gps-dashboard page draws sparklines and a per-PRN SNR heatmap
from a JS-side ring buffer.  Historically that buffer only filled while
the page was open and was capped at 720 samples (1 h @ 5 s), which made
it useless for tracking long-term GNSS stability and meant the heatmap
reset on every page reload.

The sampler keeps a *tiered* RRD-style archive in Redis so the
dashboard can render an operator-selected window from minutes to months
at roughly constant client-side cost (~720–2400 samples per chart).
Tiers (each is a Redis list of JSON rows, newest-first):

  * raw  — 5 s cadence,    cap 800   →  ≈ 1.1 h
  * 1m   — 1 min buckets,  cap 1500  →  ≈ 25 h
  * 10m  — 10 min buckets, cap 1100  →  ≈ 7.6 d
  * 1h   — 1 h buckets,    cap 2200  →  ≈ 91 d

Higher tiers are produced by aggregating samples from the raw ring
whenever a wall-clock bucket boundary is crossed (see ``emit_rollups``).
The aggregation preserves min/max/avg (alongside the headline ``value``)
and the union of per-PRN SNR maps, so the heatmap survives both page
closures and tier transitions.

This module is a pure library — the trend ring state (``redis_client``,
``last_bucket_ids``) is owned by the caller and passed in explicitly so
the GPS subsystem subprocess (``services/gps/__main__.py``) can manage
process-wide lifetime without us reaching into its globals.  Phase 4
of the hardware_service.py split moved the only call site into that
subprocess.
"""

import json
import logging
import subprocess
import time
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

logger = logging.getLogger(__name__)


GPS_TRENDS_REDIS_KEY = "gps:dashboard:trends"            # back-compat alias for raw tier
GPS_TRENDS_RAW_MAX_SAMPLES = 800                          # ≈ 1.1 h at 5 s cadence
GPS_TRENDS_INTERVAL_S = 5

# Tier definitions: name → (bucket size in seconds, ring cap).
GPS_TRENDS_TIERS: "Dict[str, tuple]" = {
    "raw": (GPS_TRENDS_INTERVAL_S, GPS_TRENDS_RAW_MAX_SAMPLES),
    "1m":  (60,      1500),
    "10m": (600,     1100),
    "1h":  (3600,    2200),
}

# Window → tier the API returns when a client requests that data window.
# Keeps the resolution roughly constant (the whole point of the archive):
# 1 h shows raw 5 s ticks; 30 d shows 1 h buckets.
GPS_TRENDS_WINDOW_TO_TIER: "Dict[str, str]" = {
    "1h":  "raw",
    "6h":  "1m",
    "24h": "1m",
    "7d":  "10m",
    "30d": "1h",
    "90d": "1h",
}
GPS_TRENDS_DEFAULT_WINDOW = "1h"

# Back-compat: the old single-cap constant is still referenced in a few
# places; keep it pointing at the raw tier's cap so external callers
# don't break.
GPS_TRENDS_MAX_SAMPLES = GPS_TRENDS_RAW_MAX_SAMPLES


def redis_key_for_tier(tier: str) -> str:
    """Redis list key for a given tier; ``raw`` keeps the legacy key
    so existing seed data and other consumers keep working."""
    if tier == "raw":
        return GPS_TRENDS_REDIS_KEY
    return f"{GPS_TRENDS_REDIS_KEY}:{tier}"


def new_last_bucket_ids() -> Dict[str, Optional[int]]:
    """Build a fresh per-tier "last seen bucket id" dict.

    Bucket id (= floor(t/B)) of the most recent sample observed for
    each non-raw tier, used to detect boundary crossings.  None until
    the first sample lands; we never aggregate the *current* (still-
    filling) bucket — only the one that just closed.
    """
    return {name: None for name in GPS_TRENDS_TIERS if name != "raw"}


def collect_chrony_tracking() -> Dict[str, Optional[float]]:
    """Run ``chronyc -c tracking`` and return the fields the trend
    charts care about.  Missing/unparseable fields come back as ``None``;
    if chronyc isn't installed at all we return an empty dict so callers
    can detect "no chrony data this tick" without faking values.
    """
    try:
        from shutil import which as _which
        if not _which("chronyc"):
            return {}
        from app_utils.chrony_parser import parse_chronyc_tracking_csv
        rc = subprocess.run(
            ["chronyc", "-c", "tracking"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if rc.returncode != 0:
            return {}
        parsed = parse_chronyc_tracking_csv(rc.stdout) or {}
        return {
            "last_offset_s":     parsed.get("last_offset_s"),
            "rms_offset_s":      parsed.get("rms_offset_s"),
            "frequency_ppm":     parsed.get("frequency_ppm"),
            "residual_freq_ppm": parsed.get("residual_freq_ppm"),
            # Skew is chrony's own estimate of frequency-measurement
            # uncertainty — the most honest single-number "oscillator
            # stability" signal we have, so the dashboard trends it.
            "skew_ppm":          parsed.get("skew_ppm"),
            "root_dispersion_s": parsed.get("root_dispersion_s"),
        }
    except Exception as exc:
        logger.debug("Trend sampler: chronyc tracking failed: %s", exc)
        return {}


def collect_gps_status(gps_manager) -> Dict[str, Any]:
    """Pull the DOP / SNR fields the dashboard plots from the live GPS
    manager.  Returns an empty dict when no manager is running so the
    sampler can decide whether the row is worth publishing at all.
    """
    if gps_manager is None:
        return {}
    try:
        status = gps_manager.get_status() or {}
    except Exception as exc:
        logger.debug("Trend sampler: gps_manager.get_status failed: %s", exc)
        return {}

    def _num(v):
        return float(v) if isinstance(v, (int, float)) else None

    sats_in_view = status.get("satellites_in_view") or []
    snrs = [
        s.get("snr") for s in sats_in_view
        if isinstance(s, dict) and isinstance(s.get("snr"), (int, float))
    ]
    avg_snr = (sum(snrs) / len(snrs)) if snrs else None

    # Per-PRN SNR map keyed by ``"<talker><PRN02>"`` (e.g. "GP05") so
    # the dashboard's per-PRN heatmap can repaint history regardless of
    # whether the page was open while samples were collected.  Empty
    # SNRs are dropped so the row stays compact when the receiver hasn't
    # locked yet.  Each tier preserves the per-PRN average across its
    # bucket, so this map shape is identical at every resolution.
    prn_snr: "Dict[str, float]" = {}
    for s in sats_in_view:
        if not isinstance(s, dict):
            continue
        prn = s.get("prn")
        snr = s.get("snr")
        if not isinstance(prn, int) or not isinstance(snr, (int, float)):
            continue
        talker = (s.get("constellation") or "GN").upper()
        key = f"{talker}{int(prn):02d}"
        prn_snr[key] = float(snr)

    # PPS jitter (1σ in nanoseconds) — included in the trend ring so
    # the GPS dashboard can plot a "Receiver Stability" sparkline
    # alongside chrony's RMS offset.  Empty when the manager hasn't
    # accumulated enough PPS pulses yet for a stddev to mean anything.
    jitter = status.get("pps_jitter") or {}
    jitter_stddev_ns = jitter.get("stddev_ns") if isinstance(jitter, dict) else None

    # Holdover seconds for the holdover-timer trend.  ``0`` while we
    # have a 3D fix; counts upward when we don't.
    holdover_s = status.get("holdover_s")

    # RF / jamming-spoof telemetry from UBX-MON-HW.  Stored alongside the
    # DOP/SNR fields so the GPS dashboard can plot a "Jamming & Spoofing"
    # time-series across the same 1-hour ring buffer.  ``jamming_state``
    # is a short string (ok|warning|critical|unknown) — preserved as-is
    # so the chart can colour-code each sample.
    jamming_state = status.get("jamming_state")
    if jamming_state is not None:
        jamming_state = str(jamming_state)

    # Short-term Allan deviation slices for the stability-trend chart.
    # A single σ_y reading only says "now"; archiving τ=10 s / τ=100 s
    # over days is what actually catches a slowly degrading oscillator.
    adev = status.get("allan_deviation") or {}
    adev_10s = adev_100s = None
    tau_list = adev.get("tau_s")
    sigma_list = adev.get("sigma_y")
    if isinstance(tau_list, list) and isinstance(sigma_list, list):
        for tau, sigma in zip(tau_list, sigma_list):
            if tau == 10:
                adev_10s = _num(sigma)
            elif tau == 100:
                adev_100s = _num(sigma)

    active_prns = status.get("active_satellite_prns") or []

    return {
        "hdop":            _num(status.get("hdop")),
        "vdop":            _num(status.get("vdop")),
        "pdop":            _num(status.get("pdop")),
        # TDOP is only present in gpsd mode (NMEA GSA omits it); _num
        # passes the None through cleanly on direct-NMEA receivers.
        "tdop":            _num(status.get("tdop")),
        "avg_snr":         avg_snr,
        "fix_age_s":       _num(status.get("fix_age_s")),
        "holdover_s":      _num(holdover_s),
        "pps_jitter_ns":   _num(jitter_stddev_ns),
        "noise_level":     _num(status.get("noise_level")),
        "agc_count":       _num(status.get("agc_count")),
        "jamming_state":   jamming_state,
        # Satellite counts — "used in fix" vs "in view" history makes
        # slow constellation losses visible without the SNR heatmap.
        "sats_used":       float(len(active_prns)) if isinstance(active_prns, list) else None,
        "sats_visible":    float(len(sats_in_view)),
        # Stability + thermal correlation series.
        "adev_10s":        adev_10s,
        "adev_100s":       adev_100s,
        "cpu_temp_c":      _num(status.get("cpu_temp_c")),
        # Position for the wander/CEP scatter — multipath and spoofing
        # both show up as the fix walking away from the site's median.
        "lat":             _num(status.get("latitude")),
        "lon":             _num(status.get("longitude")),
        # Per-PRN SNR map.  Always present (possibly empty) so the
        # dashboard can distinguish "no data this tick" from "row
        # predates the per-PRN feature".
        "prn_snr":         prn_snr,
    }


def aggregate_samples(
    rows: List[Mapping[str, Any]],
    bucket_start_ms: int,
    bucket_end_ms: int,
) -> Optional[Dict[str, Any]]:
    """Collapse a list of raw trend rows into a single bucket row.

    Numeric fields are reduced to their arithmetic mean across the
    bucket (with ``min``/``max`` retained on a per-field side-channel
    so the dashboard's "min" / "max" badges remain meaningful at coarse
    resolutions).  ``jamming_state`` keeps the *last* (most recent)
    non-empty value in the bucket — the categorical worst-state would
    arguably be more conservative but the dashboard already colour-
    codes per-sample, so "what state did we end the bucket in" is the
    most useful summary.  Per-PRN SNR maps are merged: each PRN's
    value is the mean of its sightings within the bucket; PRNs not
    seen in this bucket are simply omitted.

    Returns ``None`` when ``rows`` carries no usable signal so callers
    don't push empty rollup placeholders into the archive.
    """
    if not rows:
        return None

    # Numeric fields we want to average across the bucket.
    NUM_FIELDS = (
        "last_offset_s", "rms_offset_s", "frequency_ppm", "residual_freq_ppm",
        "skew_ppm", "root_dispersion_s",
        "hdop", "vdop", "pdop", "tdop", "avg_snr", "fix_age_s", "holdover_s",
        "pps_jitter_ns", "noise_level", "agc_count",
        "sats_used", "sats_visible", "adev_10s", "adev_100s",
        "cpu_temp_c", "lat", "lon",
    )

    sums: "Dict[str, float]" = {}
    counts: "Dict[str, int]" = {}
    mins: "Dict[str, float]" = {}
    maxs: "Dict[str, float]" = {}
    last_jam: Optional[str] = None
    prn_sums: "Dict[str, float]" = {}
    prn_counts: "Dict[str, int]" = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        for f in NUM_FIELDS:
            v = row.get(f)
            if isinstance(v, (int, float)):
                sums[f] = sums.get(f, 0.0) + float(v)
                counts[f] = counts.get(f, 0) + 1
                fv = float(v)
                if f not in mins or fv < mins[f]:
                    mins[f] = fv
                if f not in maxs or fv > maxs[f]:
                    maxs[f] = fv
        js = row.get("jamming_state")
        if isinstance(js, str) and js:
            last_jam = js
        prn_map = row.get("prn_snr")
        if isinstance(prn_map, dict):
            for prn, snr in prn_map.items():
                if isinstance(prn, str) and isinstance(snr, (int, float)):
                    prn_sums[prn] = prn_sums.get(prn, 0.0) + float(snr)
                    prn_counts[prn] = prn_counts.get(prn, 0) + 1

    if not counts and not prn_counts and last_jam is None:
        return None

    out: "Dict[str, Any]" = {
        # Use the bucket's *end* timestamp so the chart positions the
        # bucket at the moment the data was complete.  Keeps the
        # right-edge of coarse-tier sparklines aligned with the live
        # tail.
        "t": int(bucket_end_ms),
        "bucket_start_ms": int(bucket_start_ms),
        "bucket_end_ms": int(bucket_end_ms),
        "sample_count": max(counts.values()) if counts else len(rows),
    }
    for f in NUM_FIELDS:
        n = counts.get(f, 0)
        if n > 0:
            out[f] = sums[f] / n
            out[f + "_min"] = mins[f]
            out[f + "_max"] = maxs[f]
    if last_jam is not None:
        out["jamming_state"] = last_jam
    if prn_counts:
        out["prn_snr"] = {
            prn: prn_sums[prn] / prn_counts[prn] for prn in prn_counts
        }
    else:
        out["prn_snr"] = {}
    return out


def emit_rollups(
    redis_client,
    last_bucket_ids: MutableMapping[str, Optional[int]],
    now_ms: int,
) -> None:
    """Produce one aggregate row per closed bucket on each non-raw tier.

    Reads the raw ring (newest-first) once per tier-boundary crossing,
    filters to samples in the just-closed bucket window, aggregates,
    and pushes the result onto the tier's ring with ``LPUSH`` +
    ``LTRIM``.  No-ops while the raw ring is unreachable so a Redis
    outage doesn't drop the live tail.  ``last_bucket_ids`` is mutated
    in place so the caller's per-tier state stays current.
    """
    if not redis_client:
        return

    now_s = now_ms / 1000.0
    raw_rows: Optional[list] = None  # lazy fetch — only when a boundary trips

    for tier, (bucket_s, cap) in GPS_TRENDS_TIERS.items():
        if tier == "raw":
            continue
        current_id = int(now_s // bucket_s)
        last_id = last_bucket_ids.get(tier)
        # Initialise on first observation; we never roll up the bucket
        # we landed in mid-fill because we don't know what samples are
        # still coming.
        if last_id is None:
            last_bucket_ids[tier] = current_id
            continue
        if current_id <= last_id:
            continue

        # Lazily decode the raw ring once across all tiers that fired.
        if raw_rows is None:
            try:
                raw_items = redis_client.lrange(
                    redis_key_for_tier("raw"), 0, GPS_TRENDS_RAW_MAX_SAMPLES - 1
                ) or []
            except Exception as exc:
                logger.debug("Trend rollup: lrange(raw) failed: %s", exc)
                last_bucket_ids[tier] = current_id
                continue
            raw_rows = []
            for raw in raw_items:
                try:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    raw_rows.append(json.loads(raw))
                except Exception:
                    continue

        # Roll up every bucket between last_id (exclusive) and
        # current_id (exclusive).  Usually that's just one bucket —
        # but if the service was paused (e.g. SIGSTOP, a long GC, a
        # Pi sleep) we'll catch up by emitting one row per skipped
        # bucket so the gap is honest history rather than a single
        # smeared average.
        for finished_id in range(last_id, current_id):
            bucket_start_ms = finished_id * bucket_s * 1000
            bucket_end_ms = (finished_id + 1) * bucket_s * 1000
            in_bucket = [
                r for r in raw_rows
                if isinstance(r, dict)
                and isinstance(r.get("t"), (int, float))
                and bucket_start_ms <= r["t"] < bucket_end_ms
            ]
            agg = aggregate_samples(in_bucket, bucket_start_ms, bucket_end_ms)
            if agg is None:
                continue
            agg["tier"] = tier
            try:
                pipe = redis_client.pipeline()
                pipe.lpush(redis_key_for_tier(tier), json.dumps(agg))
                pipe.ltrim(redis_key_for_tier(tier), 0, cap - 1)
                pipe.execute()
            except Exception as exc:
                logger.debug("Trend rollup: failed to publish %s tier: %s", tier, exc)
                break  # don't try further buckets if Redis is unhappy

        last_bucket_ids[tier] = current_id


def publish_sample(
    redis_client,
    gps_manager,
    last_bucket_ids: MutableMapping[str, Optional[int]],
) -> None:
    """Append one trend sample to the Redis ring buffer.

    Skips publication entirely when neither GPS nor chrony returned any
    usable fields, so the buffer doesn't fill with placeholder rows
    while the hardware service is still starting up.
    """
    if not redis_client:
        return

    chrony_fields = collect_chrony_tracking()
    gps_fields = collect_gps_status(gps_manager)
    if not chrony_fields and not gps_fields:
        return

    sample = {"t": int(time.time() * 1000)}
    sample.update(chrony_fields)
    sample.update(gps_fields)

    try:
        pipe = redis_client.pipeline()
        pipe.lpush(redis_key_for_tier("raw"), json.dumps(sample))
        pipe.ltrim(redis_key_for_tier("raw"), 0, GPS_TRENDS_RAW_MAX_SAMPLES - 1)
        pipe.execute()
    except Exception as exc:
        logger.debug("Trend sampler: failed to publish to Redis: %s", exc)
        return

    # Aggregate raw → 1m / 10m / 1h whenever the wall-clock crosses a
    # bucket boundary.  Cheap when no boundary fired (just three
    # arithmetic comparisons); does one Redis round-trip per crossed
    # boundary the rest of the time.
    emit_rollups(redis_client, last_bucket_ids, sample["t"])
