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

"""SDR receiver trend sampler — a lightweight, per-receiver Redis archive.

The SDR Diagnostics page (``/admin/radio/diagnostics``) has always shown
live *instantaneous* health (signal strength, lock state, ring-buffer fill)
but nothing historical — there is no way to tell "was this receiver
dropping samples an hour ago?" without having had the page open at the
time. This module keeps a small tiered archive in Redis, modeled directly
on ``services/gps/trends.py``'s bucket/rollup approach but right-sized for
what an SDR receiver actually exposes (no GPS-style DOP/PRN telemetry
here) — 2 tiers instead of GPS's 4, since the page only needs to cover
1h/6h/24h/7d, not GPS's 90-day view:

  * raw — 10 s cadence, cap 360  →  1 h
  * 5m  — 5 min buckets, cap 2016 →  7 d

Higher tiers are produced by aggregating the raw ring whenever a
wall-clock 5-minute bucket boundary is crossed (see ``emit_rollups``),
exactly like the GPS sampler.

Sampled fields per receiver:
  * ``signal_strength`` — from ``ReceiverStatus.signal_strength``
  * ``locked`` — bool, rolled up as lock fraction (``locked_pct``)
  * ``sample_rate_ratio`` — effective / configured sample rate (1.0 is
    healthy; a silent decimation drift shows up as a departure from 1.0)
  * ``overflow_count`` / ``underflow_count`` — *deltas* since the previous
    sample (not the raw monotonic counters), so the archive directly
    answers "how many drops happened in this window" rather than making
    the dashboard subtract two arbitrary-resolution points itself

This module is a pure library — the trend ring state (``redis_client``,
``last_bucket_ids``, previous-counter snapshots) is owned by the caller
and passed in explicitly, matching the GPS module's convention. The call
site is ``sdr_hardware_service.py``'s existing ``publish_samples_and_metrics()``
loop, on its own 10 s wall-clock throttle — no new thread, no new polling
loop, mirroring how that same function already throttles spectrum (100 ms)
and aggregated metrics (``_state.metrics_interval``) independently.
"""

import json
import logging
import time
from typing import Any, Dict, Mapping, MutableMapping, Optional

logger = logging.getLogger(__name__)


SDR_TRENDS_REDIS_KEY_PREFIX = "sdr:trends:"
SDR_TRENDS_RAW_MAX_SAMPLES = 360           # 1 h at 10 s cadence
SDR_TRENDS_INTERVAL_S = 10

# Tier definitions: name -> (bucket size in seconds, ring cap).
SDR_TRENDS_TIERS: "Dict[str, tuple]" = {
    "raw": (SDR_TRENDS_INTERVAL_S, SDR_TRENDS_RAW_MAX_SAMPLES),
    "5m":  (300, 2016),   # 5 min buckets, 7 d cap
}

# Window -> tier the API reads for that window. Only two tiers, so raw
# covers the shortest window and 5m covers everything coarser.
SDR_TRENDS_WINDOW_TO_TIER: "Dict[str, str]" = {
    "1h":  "raw",
    "6h":  "5m",
    "24h": "5m",
    "7d":  "5m",
}
SDR_TRENDS_DEFAULT_WINDOW = "1h"

# Numeric fields averaged across a rollup bucket (min/max also retained
# per field, e.g. "signal_strength_min").
NUM_FIELDS = (
    "signal_strength",
    "sample_rate_ratio",
    "overflow_count",
    "underflow_count",
)


def redis_key_for_tier(receiver_id: str, tier: str) -> str:
    """Redis list key for a given receiver + tier."""
    base = f"{SDR_TRENDS_REDIS_KEY_PREFIX}{receiver_id}"
    if tier == "raw":
        return base
    return f"{base}:{tier}"


def new_last_bucket_ids() -> "Dict[str, Optional[int]]":
    """Fresh per-receiver-tier "last seen bucket id" store.

    Keyed by ``f"{receiver_id}:{tier}"`` since a single process tracks
    every receiver's rollup state. ``None`` until the first sample for
    that receiver lands.
    """
    return {}


def collect_receiver_sample(
    identifier: str,
    status: Any,
    ring_stats: Optional[Mapping[str, Any]],
    configured_sample_rate: Optional[float],
    effective_sample_rate: Optional[float],
    prev_counters: MutableMapping[str, Dict[str, int]],
) -> Optional[Dict[str, Any]]:
    """Build one raw trend row for a receiver, or ``None`` if there's
    nothing worth recording yet (e.g. receiver not running).

    ``prev_counters`` is a caller-owned ``{receiver_id: {"overflow": n,
    "underflow": n}}`` map used to turn the ring buffer's monotonic
    overflow/underflow counters into per-interval deltas. Mutated in
    place.
    """
    if status is None:
        return None

    def _num(v):
        return float(v) if isinstance(v, (int, float)) else None

    sample_rate_ratio = None
    if configured_sample_rate and effective_sample_rate:
        try:
            sample_rate_ratio = float(effective_sample_rate) / float(configured_sample_rate)
        except (TypeError, ZeroDivisionError):
            sample_rate_ratio = None

    overflow_total = 0
    underflow_total = 0
    if isinstance(ring_stats, Mapping):
        overflow_total = int(ring_stats.get("overflow_count") or 0)
        underflow_total = int(ring_stats.get("underflow_count") or 0)

    prev = prev_counters.get(identifier, {"overflow": overflow_total, "underflow": underflow_total})
    overflow_delta = max(0, overflow_total - prev.get("overflow", overflow_total))
    underflow_delta = max(0, underflow_total - prev.get("underflow", underflow_total))
    prev_counters[identifier] = {"overflow": overflow_total, "underflow": underflow_total}

    return {
        "t": int(time.time() * 1000),
        "signal_strength": _num(getattr(status, "signal_strength", None)),
        "locked": 1.0 if getattr(status, "locked", False) else 0.0,
        "sample_rate_ratio": sample_rate_ratio,
        "overflow_count": float(overflow_delta),
        "underflow_count": float(underflow_delta),
    }


def aggregate_samples(
    rows: "list",
    bucket_start_ms: int,
    bucket_end_ms: int,
) -> Optional[Dict[str, Any]]:
    """Collapse raw rows within a closed bucket into one rollup row.

    ``locked`` is summarised as ``locked_pct`` (fraction of samples in
    the bucket where the receiver was locked). ``overflow_count`` /
    ``underflow_count`` are *summed* (they're already per-interval
    deltas, so the bucket total is the sum, not the mean) while the
    other numeric fields are averaged. Mirrors
    ``services/gps/trends.py::aggregate_samples`` in shape.
    """
    if not rows:
        return None

    sums: "Dict[str, float]" = {}
    counts: "Dict[str, int]" = {}
    mins: "Dict[str, float]" = {}
    maxs: "Dict[str, float]" = {}
    locked_sum = 0.0
    locked_n = 0
    overflow_sum = 0.0
    underflow_sum = 0.0

    for row in rows:
        if not isinstance(row, dict):
            continue
        for f in ("signal_strength", "sample_rate_ratio"):
            v = row.get(f)
            if isinstance(v, (int, float)):
                sums[f] = sums.get(f, 0.0) + float(v)
                counts[f] = counts.get(f, 0) + 1
                fv = float(v)
                if f not in mins or fv < mins[f]:
                    mins[f] = fv
                if f not in maxs or fv > maxs[f]:
                    maxs[f] = fv
        lock_v = row.get("locked")
        if isinstance(lock_v, (int, float)):
            locked_sum += float(lock_v)
            locked_n += 1
        ov = row.get("overflow_count")
        if isinstance(ov, (int, float)):
            overflow_sum += float(ov)
        uf = row.get("underflow_count")
        if isinstance(uf, (int, float)):
            underflow_sum += float(uf)

    if not counts and locked_n == 0:
        return None

    out: "Dict[str, Any]" = {
        "t": int(bucket_end_ms),
        "bucket_start_ms": int(bucket_start_ms),
        "bucket_end_ms": int(bucket_end_ms),
        "sample_count": max(counts.values()) if counts else len(rows),
        "overflow_count": overflow_sum,
        "underflow_count": underflow_sum,
    }
    for f in ("signal_strength", "sample_rate_ratio"):
        n = counts.get(f, 0)
        if n > 0:
            out[f] = sums[f] / n
            out[f + "_min"] = mins[f]
            out[f + "_max"] = maxs[f]
    if locked_n > 0:
        out["locked_pct"] = (locked_sum / locked_n) * 100.0
    return out


def emit_rollups(
    redis_client,
    receiver_id: str,
    last_bucket_ids: MutableMapping[str, Optional[int]],
    now_ms: int,
) -> None:
    """Produce one aggregate row per closed 5m bucket for one receiver.

    Same boundary-crossing logic as ``services/gps/trends.py::emit_rollups``,
    generalised for a per-receiver key namespace. ``last_bucket_ids`` is
    keyed by ``f"{receiver_id}:{tier}"`` so one shared dict can track
    every receiver's rollup state.
    """
    if not redis_client:
        return

    now_s = now_ms / 1000.0

    for tier, (bucket_s, cap) in SDR_TRENDS_TIERS.items():
        if tier == "raw":
            continue
        state_key = f"{receiver_id}:{tier}"
        current_id = int(now_s // bucket_s)
        last_id = last_bucket_ids.get(state_key)
        if last_id is None:
            last_bucket_ids[state_key] = current_id
            continue
        if current_id <= last_id:
            continue

        try:
            raw_items = redis_client.lrange(
                redis_key_for_tier(receiver_id, "raw"), 0, SDR_TRENDS_RAW_MAX_SAMPLES - 1
            ) or []
        except Exception as exc:
            logger.debug("SDR trend rollup: lrange(raw) failed for %s: %s", receiver_id, exc)
            last_bucket_ids[state_key] = current_id
            continue

        raw_rows = []
        for raw in raw_items:
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                raw_rows.append(json.loads(raw))
            except Exception:
                continue

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
                pipe.lpush(redis_key_for_tier(receiver_id, tier), json.dumps(agg))
                pipe.ltrim(redis_key_for_tier(receiver_id, tier), 0, cap - 1)
                pipe.execute()
            except Exception as exc:
                logger.debug("SDR trend rollup: failed to publish %s/%s: %s", receiver_id, tier, exc)
                break

        last_bucket_ids[state_key] = current_id


def publish_sample(
    redis_client,
    identifier: str,
    status: Any,
    ring_stats: Optional[Mapping[str, Any]],
    configured_sample_rate: Optional[float],
    effective_sample_rate: Optional[float],
    prev_counters: MutableMapping[str, Dict[str, int]],
    last_bucket_ids: MutableMapping[str, Optional[int]],
) -> None:
    """Append one trend sample for a receiver and roll up any closed
    5-minute buckets. No-ops (and doesn't touch ``prev_counters``) when
    ``status`` is falsy so a receiver that hasn't started yet doesn't
    fill the archive with placeholder rows.
    """
    if not redis_client or status is None:
        return

    sample = collect_receiver_sample(
        identifier, status, ring_stats, configured_sample_rate,
        effective_sample_rate, prev_counters,
    )
    if sample is None:
        return

    try:
        pipe = redis_client.pipeline()
        pipe.lpush(redis_key_for_tier(identifier, "raw"), json.dumps(sample))
        pipe.ltrim(redis_key_for_tier(identifier, "raw"), 0, SDR_TRENDS_RAW_MAX_SAMPLES - 1)
        pipe.execute()
    except Exception as exc:
        logger.debug("SDR trend sampler: failed to publish %s: %s", identifier, exc)
        return

    emit_rollups(redis_client, identifier, last_bucket_ids, sample["t"])


def read_window(redis_client, receiver_id: str, window: str) -> Dict[str, Any]:
    """Read the trend archive for one receiver + window, newest-first
    rows reversed to chronological order for charting.

    Returns ``{"window": ..., "tier": ..., "samples": [...]}``. Falls
    back to ``SDR_TRENDS_DEFAULT_WINDOW`` for an unrecognised window
    value instead of raising, since this is called directly from a web
    route argument.
    """
    tier = SDR_TRENDS_WINDOW_TO_TIER.get(window)
    if tier is None:
        window = SDR_TRENDS_DEFAULT_WINDOW
        tier = SDR_TRENDS_WINDOW_TO_TIER[window]

    if not redis_client:
        return {"window": window, "tier": tier, "samples": []}

    bucket_s, cap = SDR_TRENDS_TIERS[tier]
    try:
        raw_items = redis_client.lrange(
            redis_key_for_tier(receiver_id, tier), 0, cap - 1
        ) or []
    except Exception as exc:
        logger.debug("SDR trend read: lrange failed for %s/%s: %s", receiver_id, tier, exc)
        return {"window": window, "tier": tier, "samples": []}

    # Trim to the requested window's duration even within a shared tier
    # (e.g. 6h and 24h both read the 5m tier but 6h should only return
    # the most recent ~72 buckets, not the full 7 d cap).
    window_seconds = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}.get(window)
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - (window_seconds * 1000) if window_seconds else 0

    samples = []
    for raw in raw_items:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            row = json.loads(raw)
        except Exception:
            continue
        if isinstance(row, dict) and isinstance(row.get("t"), (int, float)):
            if row["t"] >= cutoff_ms:
                samples.append(row)

    samples.reverse()  # chronological order for charting
    return {"window": window, "tier": tier, "samples": samples}
