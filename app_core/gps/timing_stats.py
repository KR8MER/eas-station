"""Stateless PPS timing statistics for the GPS manager.

Pure functions extracted verbatim from ``GPSManager``: pulse-interval jitter
summarisation, overlapping Allan deviation, holdover accounting and leap-second
state derivation. None of them touched ``self`` — they were ``@staticmethod``
in all but name, which is why they move out cleanly ahead of the stateful
parts of the manager.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

def holdover_seconds(
    last_3d: Optional[datetime],
    fix_mode: Any,
    now_utc: datetime,
) -> Optional[float]:
    """Seconds since the last 3D fix for the dashboard holdover timer.

    ``None`` when we have never seen a 3D fix (nothing to measure from),
    ``0.0`` while a 3D fix is currently held, otherwise the elapsed time
    since the anchor.  Centralised so the live ``get_status()`` view and
    the Redis-published blob never disagree.
    """
    if last_3d is None:
        return None
    if fix_mode == 3:
        return 0.0
    return round((now_utc - last_3d).total_seconds(), 2)

def compute_jitter_summary(intervals_ns: List[int]) -> Dict[str, Any]:
    """Summarise inter-pulse intervals as a histogram + scalars.

    Bucket layout is adaptive: 14 inner buckets centred on zero
    plus one under/over-flow bucket on each side (16 total).  The
    inner bucket width is chosen from a 1-2-5 sequence so the bulk
    of observed samples fill 5-10 buckets — that matches what
    operators expect of a histogram and avoids the sparse 2-bar
    appearance you get when the static ±100 µs / 20 µs grid is
    much wider than the receiver's actual jitter.

    Returns ``{}`` when the buffer holds fewer than two samples.
    """
    if not intervals_ns or len(intervals_ns) < 2:
        return {
            "sample_count": len(intervals_ns or []),
            "histogram": [],
            "mean_ns": None,
            "stddev_ns": None,
            "peak_ns": None,
            "median_ns": None,
        }

    nominal_ns = 1_000_000_000  # 1 second
    deltas_ns = [v - nominal_ns for v in intervals_ns]

    n = len(deltas_ns)
    mean = sum(deltas_ns) / n
    var = sum((d - mean) * (d - mean) for d in deltas_ns) / n
    stddev = math.sqrt(var)
    peak = max(abs(d) for d in deltas_ns)
    sorted_deltas = sorted(deltas_ns)
    median = sorted_deltas[n // 2]

    # Robust tail percentiles of |Δ| (nearest-rank).  σ and peak are
    # both dominated by a handful of scheduler-latency outliers on a
    # heavily-loaded host; p95/p99 tell the operator how bad the tail
    # actually is without a single rogue pulse defining the headline.
    sorted_abs = sorted(abs(d) for d in deltas_ns)
    p95 = sorted_abs[min(n - 1, max(0, math.ceil(0.95 * n) - 1))]
    p99 = sorted_abs[min(n - 1, max(0, math.ceil(0.99 * n) - 1))]

    # Pick a bucket width so the bulk of the data spans most of the
    # 14 inner buckets.  Target the larger of:
    #   - half a sigma (so ±4σ fills ±8 buckets — the visible core)
    #   - peak/14 (so a one-off outlier still lands inside the grid
    #     rather than getting silently lumped into overflow)
    # Then snap up to a 1-2-5 step so the X-axis tick labels stay
    # tidy.  Floor at 100 ns to avoid zero-width buckets on
    # exceptionally clean receivers.
    raw_step = max(stddev / 2.0, peak / 14.0, 1.0)
    exp10 = math.floor(math.log10(raw_step))
    base = 10 ** exp10
    ratio = raw_step / base
    if ratio <= 1:
        mult = 1
    elif ratio <= 2:
        mult = 2
    elif ratio <= 5:
        mult = 5
    else:
        mult = 10
    width_ns = max(100, int(mult * base))

    N_INNER = 14
    half = N_INNER // 2  # = 7
    edges_ns = [(i - half) * width_ns for i in range(N_INNER + 1)]

    bucket_count = N_INNER + 2  # + 1 underflow, + 1 overflow
    counts = [0] * bucket_count
    for d in deltas_ns:
        if d < edges_ns[0]:
            counts[0] += 1
        elif d >= edges_ns[-1]:
            counts[-1] += 1
        else:
            # Inner-bucket index derived directly from width — no
            # linear edge scan needed.
            idx = (d - edges_ns[0]) // width_ns
            if idx < 0:
                counts[0] += 1
            elif idx >= N_INNER:
                counts[-1] += 1
            else:
                counts[int(idx) + 1] += 1

    def _fmt_edge(ns: int) -> str:
        if abs(ns) >= 1000 and ns % 1000 == 0:
            return f"{ns // 1000} µs"
        return f"{ns} ns"

    def _label(lo: Optional[int], hi: Optional[int]) -> str:
        if lo is None:
            return f"< {_fmt_edge(hi)}"
        if hi is None:
            return f"≥ {_fmt_edge(lo)}"
        return f"{_fmt_edge(lo)} to {_fmt_edge(hi)}"

    histogram: List[Dict[str, Any]] = []
    for i, c in enumerate(counts):
        if i == 0:
            lo, hi = None, edges_ns[0]
        elif i == bucket_count - 1:
            lo, hi = edges_ns[-1], None
        else:
            lo, hi = edges_ns[i - 1], edges_ns[i]
        histogram.append({
            "label": _label(lo, hi),
            "lo_ns": lo,
            "hi_ns": hi,
            "count": c,
        })

    return {
        "sample_count": n,
        "histogram": histogram,
        "bucket_width_ns": width_ns,
        "mean_ns": round(mean, 1),
        "stddev_ns": round(stddev, 1),
        "peak_ns": int(peak),
        "median_ns": int(median),
        "p95_ns": int(p95),
        "p99_ns": int(p99),
    }

def compute_allan_deviation(intervals_ns: List[int]) -> Dict[str, Any]:
    """Overlapping Allan deviation σ_y(τ) at τ = 1, 10, 100, 1000 s.

    Reconstructs the phase sequence from inter-pulse intervals
    (x_i = cumulative interval error vs. the 1 s nominal) and
    applies the standard overlapping ADEV estimator:

        σ²_y(τ) = sum_i (x_{i+2m} - 2·x_{i+m} + x_i)²
                  ───────────────────────────────────────
                          2 · τ² · (N − 2m)

    where m = τ / τ₀ and τ₀ = 1 s.  Returned as a flat
    ``{tau_s: σ_y}`` dict; entries are omitted when the buffer is
    too short to estimate ADEV at that τ (e.g. τ=1000 s needs at
    least 2001 PPS samples in the ring).

    Alongside σ_y the result carries the white-phase-modulation
    measurement floor so consumers can tell "the oscillator is
    wandering" apart from "the PPS timestamping chain is noisy":

    * ``sigma_x_wpm_s`` — the per-pulse phase-noise estimate σ_x.
      The interval deltas are first differences of phase, so for
      white timestamping noise σ_x = σ_Δ / √2.
    * ``floor_sigma_y`` — √3·σ_x/τ per returned τ (parallel array).
      When σ_y(τ) hugs this curve the reading is measurement-noise
      limited and says nothing about the disciplined clock itself;
      the dashboard's stability grade uses it to avoid flagging
      perfectly healthy clocks on hosts with µs-level PPS jitter.

    Two further telecom-standard time-domain metrics ride along as
    parallel arrays (``None`` where the buffer is too short for
    that τ, since their sample requirements differ from ADEV's):

    * ``tdev_s`` — time deviation, TDEV(τ) = τ·Mod σ_y(τ)/√3 via
      the overlapping modified Allan variance.  This is the metric
      the ITU-T G.811 wander masks are written against for time
      transfer.
    * ``mtie_s`` — maximum time interval error: the largest
      peak-to-peak phase excursion inside any observation window of
      length τ, computed with monotonic deques in O(N) per τ.
    """
    if not intervals_ns or len(intervals_ns) < 4:
        return {
            "tau_s": [],
            "sigma_y": [],
            "floor_sigma_y": [],
            "tdev_s": [],
            "mtie_s": [],
            "sigma_x_wpm_s": None,
            "sample_count": len(intervals_ns or []),
        }

    nominal_ns = 1_000_000_000
    # Phase samples in seconds (cumulative timing error vs. ideal).
    phase = []
    running = 0.0
    for v in intervals_ns:
        running += (v - nominal_ns) / 1e9
        phase.append(running)

    n = len(phase)

    # White-PM measurement floor from the interval-delta spread.
    deltas_s = [(v - nominal_ns) / 1e9 for v in intervals_ns]
    mean_d = sum(deltas_s) / n
    var_d = sum((d - mean_d) * (d - mean_d) for d in deltas_s) / n
    sigma_x = math.sqrt(var_d) / math.sqrt(2.0)

    results_tau: List[int] = []
    results_sigma: List[float] = []
    results_floor: List[float] = []
    results_tdev: List[Optional[float]] = []
    results_mtie: List[Optional[float]] = []

    for tau_s in (1, 10, 100, 1000):
        m = tau_s  # τ₀ = 1 s
        # Need at least 2m + 1 samples for a single ADEV term.
        if n < 2 * m + 1:
            continue
        tau = float(m)
        acc = 0.0
        count = 0
        second_diff: List[float] = []
        for i in range(n - 2 * m):
            d = phase[i + 2 * m] - 2.0 * phase[i + m] + phase[i]
            second_diff.append(d)
            acc += d * d
            count += 1
        if count <= 0:
            continue
        sigma_sq = acc / (2.0 * tau * tau * count)
        if sigma_sq < 0:
            continue
        results_tau.append(tau_s)
        results_sigma.append(math.sqrt(sigma_sq))
        results_floor.append(math.sqrt(3.0) * sigma_x / tau)

        # TDEV — overlapping modified Allan variance.  The inner
        # m-point average of second differences is maintained as a
        # sliding sum so the whole estimator stays O(N) per τ:
        #
        #   Mod σ²_y(τ) = Σ_j (Σ_{i=j}^{j+m-1} D_i)²
        #                 ─────────────────────────────
        #                   2 · m² · τ² · (N − 3m + 1)
        #
        #   TDEV(τ)     = τ · Mod σ_y(τ) / √3
        if n >= 3 * m + 1:
            window_sum = sum(second_diff[0:m])
            acc_mod = window_sum * window_sum
            terms = 1
            for j in range(1, n - 3 * m + 1):
                window_sum += second_diff[j + m - 1] - second_diff[j - 1]
                acc_mod += window_sum * window_sum
                terms += 1
            mod_avar = acc_mod / (2.0 * m * m * tau * tau * terms)
            results_tdev.append(math.sqrt(max(0.0, mod_avar) / 3.0) * tau)
        else:
            results_tdev.append(None)

        # MTIE — worst peak-to-peak phase excursion across every
        # observation window of τ seconds (m+1 consecutive phase
        # samples).  Windowed max/min tracked with monotonic deques
        # so a 16384-sample ring stays cheap even at τ=1000 s.
        window = m + 1
        if n >= window:
            max_dq: Deque[int] = deque()
            min_dq: Deque[int] = deque()
            mtie = 0.0
            for idx in range(n):
                val = phase[idx]
                while max_dq and phase[max_dq[-1]] <= val:
                    max_dq.pop()
                max_dq.append(idx)
                while min_dq and phase[min_dq[-1]] >= val:
                    min_dq.pop()
                min_dq.append(idx)
                lo = idx - window + 1
                while max_dq and max_dq[0] < lo:
                    max_dq.popleft()
                while min_dq and min_dq[0] < lo:
                    min_dq.popleft()
                if idx >= window - 1:
                    span = phase[max_dq[0]] - phase[min_dq[0]]
                    if span > mtie:
                        mtie = span
            results_mtie.append(mtie)
        else:
            results_mtie.append(None)

    return {
        "tau_s": results_tau,
        "sigma_y": results_sigma,
        "floor_sigma_y": results_floor,
        "tdev_s": results_tdev,
        "mtie_s": results_mtie,
        "sigma_x_wpm_s": sigma_x,
        "sample_count": n,
    }

def derive_leap_state(fix: Dict[str, Any]) -> str:
    """Best-effort leap-second annunciator from current fix state.

    Resolution order:

    1. ``UBX-NAV-TIMELS`` (Phase 2) — when ``leap_pending`` is True
       the receiver knows about a scheduled insert/delete and we
       surface it directly.  When it's False but ``leap_seconds`` is
       populated, the receiver has confirmed "no event imminent"
       and we render that as "normal".
    2. ``has_fix`` — without UBX data, hold "normal" while we have
       a fix so the tile isn't permanently grey.
    3. Otherwise "unknown".
    """
    leap_seconds = fix.get("leap_seconds")
    leap_pending = fix.get("leap_pending")
    if leap_pending:
        change = fix.get("leap_change") or 0
        return "insert_pending" if change > 0 else "delete_pending"
    if leap_seconds is not None:
        return "normal"
    if not fix.get("has_fix"):
        return "unknown"
    return "normal"
