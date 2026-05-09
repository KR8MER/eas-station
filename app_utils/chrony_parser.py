"""
Chrony CSV output parsers used by the GPS & Time dashboard.

``chronyc -c <subcommand>`` emits machine-readable CSV — one comma-separated
line per record (or per source, in the case of ``sources``).  This module
provides pure parsers (no subprocess, no Flask) for the two subcommands the
dashboard depends on:

* ``tracking`` — the currently selected reference plus offset / frequency
  / dispersion tracking state, as a single CSV row.  See ``chronyc(1)``.
* ``sources`` — one CSV row per configured time source, with state /
  reach / offset.

Splitting these helpers out of the route module keeps the format logic
testable in isolation (no Flask app context, no database) and makes them
reusable from any future timing-related view.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# `chronyc -c tracking` field schema.
#
# The CSV format is documented in chrony.conf(5) / chronyc(1) and has been
# stable across chrony 4.x.  Field positions are:
#
#   0  reference id (hex)         9   skew                       (ppm)
#   1  reference id (name)        10  root delay                 (sec)
#   2  stratum                    11  root dispersion            (sec)
#   3  ref time                   12  update interval            (sec)
#   4  system time offset (sec)   13  leap status
#   5  last offset            (sec)
#   6  rms offset             (sec)
#   7  frequency             (ppm)
#   8  residual frequency    (ppm)
#
# We name everything explicitly so the dashboard template can reference
# the parsed fields without remembering positional indices.
# ---------------------------------------------------------------------------
CHRONY_TRACKING_FIELDS = (
    ("reference_id_hex",         0,  str),
    ("reference_id_name",        1,  str),
    ("stratum",                  2,  int),
    ("ref_time",                 3,  str),
    ("system_time_offset_s",     4,  float),
    ("last_offset_s",            5,  float),
    ("rms_offset_s",             6,  float),
    ("frequency_ppm",            7,  float),
    ("residual_freq_ppm",        8,  float),
    ("skew_ppm",                 9,  float),
    ("root_delay_s",            10,  float),
    ("root_dispersion_s",       11,  float),
    ("update_interval_s",       12,  float),
    ("leap_status",             13,  str),
)


def parse_chronyc_tracking_csv(stdout: str) -> Dict[str, Any]:
    """Parse the CSV output of ``chronyc -c tracking`` into a typed dict.

    Empty fields and unparseable values map to ``None`` rather than
    raising — this keeps the dashboard rendering meaningfully when chrony
    is mid-startup or hasn't yet locked onto a reference.
    """
    parts = [p.strip() for p in (stdout or "").strip().split(",")]
    out: Dict[str, Any] = {}
    for name, idx, caster in CHRONY_TRACKING_FIELDS:
        if idx >= len(parts):
            out[name] = None
            continue
        raw = parts[idx]
        if raw == "" or raw is None:
            out[name] = None
            continue
        try:
            out[name] = caster(raw)
        except (TypeError, ValueError):
            out[name] = raw if caster is str else None
    return out


def parse_chronyc_sources_csv(stdout: str) -> List[Dict[str, Any]]:
    """Parse the CSV output of ``chronyc -c sources`` into a list of dicts.

    Each row represents one time source (server / peer / refclock) with
    its mode, state, name, stratum, polling cadence, reach bitmap,
    seconds since the last sample, and the most recent offset estimates.
    Numeric columns that chrony emits as ``-`` or ``?`` (typically
    "never sampled") map to ``None`` so the UI can show a placeholder
    rather than printing ``0``.
    """
    def _maybe_int(v: str):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _maybe_float(v: str):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    sources: List[Dict[str, Any]] = []
    for raw in (stdout or "").strip().splitlines():
        cols = [c.strip() for c in raw.split(",")]
        # Need at least the seven leading columns (mode, state, name,
        # stratum, poll, reach, last_rx) to be a valid row; anything
        # shorter is malformed and we skip it rather than guessing.
        if len(cols) < 7:
            continue
        sources.append({
            "mode": cols[0] or None,
            "state": cols[1] or None,
            "name": cols[2] or None,
            "stratum": _maybe_int(cols[3]),
            "poll": _maybe_int(cols[4]),
            "reach": _maybe_int(cols[5]),
            "last_rx_s": _maybe_int(cols[6]),
            # chrony emits two offset estimates and an error bound:
            # "adjusted" (after measurement processing) and "original"
            # (raw sample), both in seconds.  All three columns are
            # optional in older chrony builds.
            "last_sample_offset_s": _maybe_float(cols[7]) if len(cols) > 7 else None,
            "last_sample_orig_s":   _maybe_float(cols[8]) if len(cols) > 8 else None,
            "last_sample_error_s":  _maybe_float(cols[9]) if len(cols) > 9 else None,
        })
    return sources


__all__ = [
    "CHRONY_TRACKING_FIELDS",
    "parse_chronyc_tracking_csv",
    "parse_chronyc_sources_csv",
]
