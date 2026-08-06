"""NMEA sentence → fix-dictionary mapping for the GPS manager.

This is the field-extraction half of what used to be
``GPSManager._handle_sentence`` (246 lines, 50 ``self`` references). The
functions here own the NMEA semantics — which field of which sentence lands
where in the fix dictionary, how multi-constellation GSV groups are bucketed,
how GSA PRNs are unioned across a cycle — and nothing else.

They deliberately do **not** own manager state. Everything a sentence implies
beyond the fix dictionary is returned in a :class:`SentenceEffects` for the
caller to apply:

* per-satellite history updates (``sats_seen`` / ``sats_used``)
* "this sentence reported a 3D fix" (``saw_3d_fix``)
* "this sentence carried a usable UTC datetime" (``utc_datetime``)

That keeps the Redis writes, the satellite-history bookkeeping and the
system-clock sync policy in ``GPSManager`` where they belong, while the parsing
becomes independently testable. The manager applies the effects *after* the
parse returns; this is safe because none of the three handlers involved
(``_record_sat_seen``, ``_record_sat_used``, ``_mark_3d_fix``) read the fix
dictionary, so there is no read-after-write ordering hazard.

The cross-sentence accumulators live in :class:`NMEAParseState`, which the
manager owns and passes in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# Sentence-level fix-quality codes as reported in GGA field 6. Moved here from
# gps_manager along with _safe_int — both were used only by the NMEA path.
_FIX_QUALITY = {
    0: "no_fix",
    1: "gps_fix",
    2: "dgps_fix",
    3: "pps_fix",
    4: "rtk_fix",
    5: "float_rtk",
    6: "estimated",
    7: "manual",
    8: "simulation",
}


def _safe_int(val) -> Optional[int]:
    """Convert a value to int, returning None for empty/None/invalid values."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


@dataclass
class NMEAParseState:
    """Cross-sentence accumulators owned by the manager, mutated here.

    ``gsv_buffer`` is keyed by talker so one constellation's GSV group does not
    wipe another's. ``gsa_accumulator`` unions the PRNs of every GSA in the
    current cycle; ``gsa_cycle_started`` is cleared by GGA to open a new cycle.
    """

    gsv_buffer: Dict[str, Dict[int, Dict[str, Any]]] = field(default_factory=dict)
    gsa_accumulator: Set[int] = field(default_factory=set)
    gsa_cycle_started: bool = False


@dataclass
class SentenceEffects:
    """Consequences of a sentence that live outside the fix dictionary."""

    sats_seen: List[Tuple[Optional[str], int, Optional[int]]] = field(default_factory=list)
    sats_used: List[Tuple[Optional[str], int]] = field(default_factory=list)
    saw_3d_fix: bool = False
    utc_datetime: Optional[datetime] = None


def _set_float(fix: Dict[str, Any], key: str, raw: Any) -> None:
    """Assign ``float(raw)`` to ``fix[key]``, ignoring blank/unparsable input."""
    if raw in (None, ""):
        return
    try:
        fix[key] = float(raw)
    except (ValueError, TypeError):
        pass


def apply_gga(
    fix: Dict[str, Any],
    msg: Any,
    *,
    min_satellites: int,
    state: NMEAParseState,
) -> SentenceEffects:
    """Global Positioning System Fix Data."""
    effects = SentenceEffects()

    # GGA marks the start of a new NMEA cycle. The next GSA we see will start a
    # fresh accumulation; we keep the previously published
    # active_satellite_prns until that GSA arrives so the UI doesn't briefly
    # flicker to "0 used" on every cycle.
    state.gsa_cycle_started = False

    fix_qual = int(msg.gps_qual) if msg.gps_qual else 0
    has_fix = fix_qual > 0
    num_sats = int(msg.num_sats) if msg.num_sats else 0

    fix["has_fix"] = has_fix
    fix["fix_quality"] = _FIX_QUALITY.get(fix_qual, "unknown")
    fix["satellites"] = num_sats
    if has_fix and num_sats >= min_satellites:
        new_status = "fix"
    elif has_fix:
        new_status = "acquiring"
    else:
        # No fix yet — show "acquiring" when we already have satellites in view
        # from the previous GSV cycle (typical NMEA order is GGA → GSA → GSV,
        # so satellites_in_view reflects last cycle).
        sats_tracked = len(fix.get("satellites_in_view", []))
        new_status = "acquiring" if sats_tracked > 0 else "no_fix"
    fix["status"] = new_status

    if has_fix and msg.latitude and msg.longitude:
        fix["latitude"] = msg.latitude
        fix["longitude"] = msg.longitude

    _set_float(fix, "altitude_m", msg.altitude if msg.altitude else None)
    _set_float(fix, "hdop", msg.horizontal_dil if msg.horizontal_dil else None)

    if msg.timestamp:
        fix["gps_utc_time"] = str(msg.timestamp)

    # Geoid separation (height of MSL above WGS-84 ellipsoid). Useful for users
    # converting our MSL-altitude to ellipsoid height without a geoid model.
    _set_float(fix, "geoid_separation_m", getattr(msg, "geo_sep", None))

    # DGPS correction age and reference station ID — only emitted when the
    # receiver is using DGPS/SBAS corrections.
    _set_float(fix, "dgps_age_s", getattr(msg, "age_gps_data", None))
    ref_id = getattr(msg, "ref_station_id", None)
    if ref_id not in (None, ""):
        fix["dgps_station_id"] = str(ref_id)

    return effects


def apply_rmc(fix: Dict[str, Any], msg: Any) -> SentenceEffects:
    """Recommended Minimum Navigation Information."""
    effects = SentenceEffects()

    if msg.status != "A":  # not Active — no valid fix to take fields from
        return effects

    if msg.latitude and msg.longitude:
        fix["latitude"] = msg.latitude
        fix["longitude"] = msg.longitude
    _set_float(fix, "speed_knots", msg.spd_over_grnd if msg.spd_over_grnd else None)
    _set_float(fix, "track_angle", msg.true_course if msg.true_course else None)

    # Magnetic variation (degrees + E/W direction). Diagnostic-only — useful
    # for users with a magnetic compass to derive true-vs-magnetic offset at
    # the current location.
    _set_float(fix, "magnetic_variation", getattr(msg, "mag_variation", None))
    mag_var_dir = getattr(msg, "mag_var_dir", None)
    if mag_var_dir not in (None, ""):
        fix["magnetic_variation_dir"] = str(mag_var_dir)

    if msg.datestamp and msg.timestamp:
        try:
            dt = datetime.combine(msg.datestamp, msg.timestamp)
            fix["gps_utc_time"] = dt.isoformat() + "Z"
            effects.utc_datetime = dt.replace(tzinfo=timezone.utc)
        except Exception:
            fix["gps_utc_time"] = str(msg.timestamp)

    return effects


def apply_gsv(
    fix: Dict[str, Any],
    msg: Any,
    *,
    state: NMEAParseState,
) -> SentenceEffects:
    """Satellites in View — per-satellite PRN/elevation/azimuth/SNR.

    Multi-GNSS receivers send one GSV group per constellation (e.g.
    ``$GPGSV,3,1..`` → ``3,2`` → ``3,3`` then ``$GLGSV,1,1..``). We bucket per
    talker so the start of one constellation's group doesn't wipe another's,
    and union the buckets when publishing so ``satellites_in_view`` reflects
    every visible satellite.

    A satellite's identity is ``(talker, PRN)``, never the PRN alone — PRN
    numbering restarts per constellation, so the same number means different
    satellites under different talkers. ``satellites_in_view`` can therefore
    carry two entries sharing a ``prn`` with different ``constellation``
    values; consumers must key on both. The gpsd ingest path
    (``GPSManager._handle_gpsd_sky``) has always published that shape.
    """
    effects = SentenceEffects()
    try:
        talker = getattr(msg, "talker", None) or "GN"
        total_msgs = int(msg.num_messages) if msg.num_messages else 1
        msg_num = int(msg.msg_num) if msg.msg_num else 1
        if msg_num == 1:
            state.gsv_buffer[talker] = {}
        bucket = state.gsv_buffer.setdefault(talker, {})
        for i in range(1, 5):
            prn_raw = getattr(msg, "sv_prn_num_%d" % i, None)
            if not prn_raw:
                break
            try:
                prn = int(prn_raw)
            except (ValueError, TypeError):
                continue
            snr_val = _safe_int(getattr(msg, "snr_%d" % i, None))
            bucket[prn] = {
                "prn": prn,
                "constellation": talker,
                "elevation": _safe_int(getattr(msg, "elevation_deg_%d" % i, None)),
                "azimuth": _safe_int(getattr(msg, "azimuth_%d" % i, None)),
                "snr": snr_val,
            }
            # Per-PRN history — the dashboard's "Almanac & Ephemeris staleness"
            # panel reads this to show how long each satellite has been visible
            # and when it last contributed to a fix.
            effects.sats_seen.append((talker, prn, snr_val))
        if msg_num >= total_msgs:
            # Key the cross-talker merge by (talker, PRN), not PRN alone.
            # PRN numbering is per-constellation and overlaps: Galileo and
            # BeiDou both number from 1, so a $GAGSV reporting PRN 5 collides
            # with the $GPGSV PRN 5 and one satellite silently disappears from
            # the view. This mirrors the GSA path, which disambiguates the same
            # way via GPSManager._sat_key, and services/gps/trends.py, which
            # already keys its per-PRN SNR map by "<talker><PRN02>".
            merged: Dict[Tuple[str, int], Dict[str, Any]] = {}
            for tname, tbucket in state.gsv_buffer.items():
                for bprn, sat in tbucket.items():
                    merged[(tname, bprn)] = sat
            # Sort by PRN first so the published order is unchanged in the
            # common case where every PRN is unique; talker only breaks ties.
            fix["satellites_in_view"] = sorted(
                merged.values(),
                key=lambda s: (s["prn"], s.get("constellation") or ""),
            )
    except Exception:
        pass
    return effects


def apply_gsa(
    fix: Dict[str, Any],
    msg: Any,
    *,
    state: NMEAParseState,
) -> SentenceEffects:
    """GPS DOP and Active Satellites.

    Multi-GNSS receivers emit one GSA per constellation per cycle, so we
    accumulate PRNs across all GSAs in the current cycle (reset on each GGA)
    and publish the union as ``active_satellite_prns``. Without this the last
    GSA of the cycle silently overwrites the earlier ones — and if it happens
    to carry no active sats (e.g. an empty GLGSA with no GLONASS lock), the UI
    shows "0 used" even though GPGSA reported 8+ active sats moments earlier.
    """
    effects = SentenceEffects()
    try:
        this_gsa = []
        for i in range(1, 13):
            prn_raw = getattr(msg, "sv_id%02d" % i, None)
            if prn_raw and str(prn_raw).strip():
                try:
                    this_gsa.append(int(prn_raw))
                except (ValueError, TypeError):
                    pass
        if not state.gsa_cycle_started:
            state.gsa_accumulator = set()
            state.gsa_cycle_started = True
        state.gsa_accumulator.update(this_gsa)
        fix["active_satellite_prns"] = sorted(state.gsa_accumulator)

        # Mark each PRN reported in this GSA as currently used-in-fix. GSA
        # carries the talker that sourced it (GPGSA, GLGSA, …) so we can
        # disambiguate in the rare case where two constellations re-use the
        # same PRN number.
        gsa_talker = getattr(msg, "talker", None) or "GN"
        for used_prn in this_gsa:
            effects.sats_used.append((gsa_talker, used_prn))

        # Fix mode: 1=no fix, 2=2D, 3=3D
        fix_mode_raw = getattr(msg, "mode_fix_type", None)
        if fix_mode_raw is not None:
            try:
                mode_int = int(fix_mode_raw)
                fix["fix_mode"] = mode_int
                # Holdover anchor — the wall-clock instant of the most recent
                # 3D fix. Captured at any 3D fix in the stream so even brief
                # reacquisitions reset the timer.
                if mode_int == 3:
                    effects.saw_3d_fix = True
            except (ValueError, TypeError):
                pass

        _set_float(fix, "pdop", getattr(msg, "pdop", None) or None)
        _set_float(fix, "vdop", getattr(msg, "vdop", None) or None)
    except Exception:
        pass
    return effects


def apply_sentence(
    fix: Dict[str, Any],
    msg: Any,
    *,
    min_satellites: int,
    state: NMEAParseState,
) -> SentenceEffects:
    """Dispatch one parsed NMEA sentence onto ``fix``.

    Bumps the per-type counter (cumulative; the UI computes arrival rates from
    poll-to-poll deltas), then routes to the per-sentence handler. Unknown
    sentence types still count, they just carry no fields we consume.
    """
    sentence_type = msg.sentence_type

    counts = fix.get("sentence_counts") or {}
    counts[sentence_type] = counts.get(sentence_type, 0) + 1
    fix["sentence_counts"] = counts

    if sentence_type == "GGA":
        return apply_gga(fix, msg, min_satellites=min_satellites, state=state)
    if sentence_type == "RMC":
        return apply_rmc(fix, msg)
    if sentence_type == "GSV":
        return apply_gsv(fix, msg, state=state)
    if sentence_type == "GSA":
        return apply_gsa(fix, msg, state=state)
    return SentenceEffects()
