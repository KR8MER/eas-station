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

"""GPS / chrony state-change event detection with Redis persistence.

The GPS dashboard's "Events & Alarms" panel used to be populated by a
JS function that compared each fresh snapshot against the previously
observed one and pushed transitions into an in-memory array.  That log
vanished on page reload and didn't capture any transitions that
happened while no browser was open.

This module ports that detector to the GPS subprocess so it runs on
every trend-sampler tick (5 s) and writes transitions to a capped
Redis list.  The dashboard hydrates from the list on load and refreshes
on each poll, so the operator sees alarms regardless of whether they
were watching when they fired.

Redis layout mirrors the trend ring (newest first, capped LPUSH/LTRIM):

    LPUSH gps:events {"id": ms, "ts": "HH:MM:SS", "sev": "fault", "msg": "…"}
    LTRIM gps:events 0 EVENTS_MAX-1
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EVENTS_REDIS_KEY = "gps:events"
EVENTS_MAX = 500
_ALLOWED_SEV = frozenset({"ok", "warn", "fault", "info"})


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _extract_state(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Distil the fields the transition rules care about into a flat dict.

    Mirrors the JS detectEvents() so server- and client-side detection
    fire on the same triggers.  Missing fields collapse to ``None`` /
    ``False`` rather than raising — the snapshot can be incomplete
    during startup or while chrony is restarting.
    """
    gps = snapshot.get("gps") or {}
    tracking = ((snapshot.get("chrony") or {}).get("tracking")) or {}
    pps_backend = gps.get("pps_backend")
    pps_age = _num(gps.get("pps_pulse_age_s"))
    holdover = _num(gps.get("holdover_s"))
    return {
        "pps_locked": bool(
            pps_backend and pps_backend != "none"
            and pps_age is not None and pps_age <= 2
        ),
        "has_fix": bool(gps.get("has_fix")),
        "fix_mode": int(gps.get("fix_mode") or 0),
        "holdover": holdover,
        "jamming": gps.get("jamming_state") or None,
        "stratum": tracking.get("stratum"),
        "antenna": gps.get("antenna_status") or None,
        "leap_pending": bool(gps.get("leap_pending")),
        "running": bool(gps.get("running")),
    }


def _ts_hms(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc).strftime("%H:%M:%S")


class EventDetector:
    """Holds the last observed state so transitions can be fired.

    Construct once per subprocess; call ``detect(snapshot)`` each tick.
    The first call only seeds the state — no events fire — so a fresh
    process doesn't burst the log with "transitions" that are really
    just initial reads.
    """

    def __init__(self) -> None:
        self._prev: Optional[Dict[str, Any]] = None

    def detect(self, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        state = _extract_state(snapshot)
        if self._prev is None:
            self._prev = state
            return []
        prev = self._prev
        now_ms = int(time.time() * 1000)
        events: List[Dict[str, Any]] = []

        def add(sev: str, msg: str) -> None:
            if sev not in _ALLOWED_SEV:
                sev = "info"
            events.append({
                "id": now_ms,
                "ts": _ts_hms(now_ms),
                "sev": sev,
                "msg": msg,
            })

        if state["pps_locked"] != prev["pps_locked"]:
            add("ok" if state["pps_locked"] else "fault",
                "PPS LOCK RESTORED" if state["pps_locked"] else "PPS LOST")

        if state["has_fix"] != prev["has_fix"]:
            add("ok" if state["has_fix"] else "fault",
                "GPS RECOVERED" if state["has_fix"] else "GPS FIX LOST")

        if (state["fix_mode"] != prev["fix_mode"]
                and prev["fix_mode"] != 0 and state["fix_mode"] != 0):
            add("warn", f"FIX MODE CHANGED {prev['fix_mode']}D → {state['fix_mode']}D")

        # Holdover: 0/None → >0 is "entered"; >0 → 0 is "cleared".
        entered_holdover = (
            (prev["holdover"] in (0, None))
            and state["holdover"] is not None and state["holdover"] > 0
        )
        exited_holdover = (
            prev["holdover"] is not None and prev["holdover"] > 0
            and state["holdover"] == 0
        )
        if entered_holdover:
            add("warn", "HOLDOVER ENTERED")
        if exited_holdover:
            add("ok", "HOLDOVER CLEARED")

        if state["jamming"] != prev["jamming"] and state["jamming"]:
            if state["jamming"] == "ok" and prev["jamming"] and prev["jamming"] != "ok":
                add("ok", "RF INTERFERENCE CLEARED")
            elif state["jamming"] != "ok":
                sev = "fault" if state["jamming"] == "critical" else "warn"
                add(sev, f"RF INTERFERENCE: {state['jamming'].upper()}")

        if state["antenna"] != prev["antenna"] and state["antenna"]:
            if state["antenna"] == "ok" and prev["antenna"] and prev["antenna"] != "ok":
                add("ok", "ANTENNA OK")
            elif state["antenna"] in ("short", "open"):
                add("fault", f"ANTENNA FAULT: {state['antenna'].upper()}")

        if state["leap_pending"] and not prev["leap_pending"]:
            add("info", "LEAP SECOND PENDING")
        elif not state["leap_pending"] and prev["leap_pending"]:
            add("info", "LEAP SECOND CLEARED")

        if (state["stratum"] != prev["stratum"]
                and state["stratum"] is not None):
            s = state["stratum"]
            if isinstance(s, (int, float)) and not isinstance(s, bool):
                sev = "ok" if s == 1 else ("warn" if s <= 4 else "fault")
                prev_s = prev["stratum"] if prev["stratum"] is not None else "—"
                add(sev, f"STRATUM {prev_s} → {s}")

        if state["running"] != prev["running"]:
            add("ok" if state["running"] else "fault",
                "GPS SERVICE STARTED" if state["running"] else "GPS SERVICE STOPPED")

        self._prev = state
        return events


def publish_events(redis_client, events: List[Dict[str, Any]]) -> None:
    """Append events to the Redis ring (newest first) and trim to cap.

    Silent no-op when ``events`` is empty so callers don't have to
    branch.  A failed Redis round-trip is logged at debug and dropped:
    losing one tick of state-change events is better than wedging the
    sampler loop.
    """
    if not events or not redis_client:
        return
    try:
        pipe = redis_client.pipeline()
        for ev in events:
            pipe.lpush(EVENTS_REDIS_KEY, json.dumps(ev))
        pipe.ltrim(EVENTS_REDIS_KEY, 0, EVENTS_MAX - 1)
        pipe.execute()
    except Exception as exc:
        logger.debug("Event publisher: failed to write to Redis: %s", exc)


def read_events(redis_client, limit: int = 200) -> List[Dict[str, Any]]:
    """Return the most-recent events, newest first (matching list order).

    ``limit`` is clamped to ``EVENTS_MAX``; non-numeric / negative limits
    fall back to 200 so a malformed query string can't accidentally
    return the entire ring.
    """
    if not redis_client:
        return []
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 200
    if limit <= 0:
        limit = 200
    if limit > EVENTS_MAX:
        limit = EVENTS_MAX
    try:
        raw_items = redis_client.lrange(EVENTS_REDIS_KEY, 0, limit - 1) or []
    except Exception as exc:
        logger.debug("Event reader: lrange failed: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    for raw in raw_items:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            row = json.loads(raw)
            if isinstance(row, dict):
                out.append(row)
        except Exception:
            continue
    return out
