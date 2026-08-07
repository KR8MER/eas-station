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

"""Hardware subsystem and GPS status probes."""

import json
from typing import Any, Dict

_HARDWARE_SUBSYSTEMS = ("network", "zigbee", "gps", "displays", "gpio")


def _collect_hardware_subsystems(logger) -> Dict[str, Any]:
    """Read the Phase 4 per-subsystem heartbeat slices from Redis.

    Each hardware subsystem process (network/zigbee/gps/displays/gpio)
    publishes its own slice into ``hardware:metrics:<subsystem>`` every
    5 s with a 60 s TTL.  ``services.common.metrics._publish_slice``
    also refreshes a roll-up at ``hardware:metrics`` keyed by subsystem
    so a single Redis GET tells us which subprocesses are alive.

    Returns a dict suitable for the system-health page::

        {
          "subsystems": {
            "network":  {"alive": True,  "last_seen": "...", "data": {...}},
            "zigbee":   {"alive": False, "last_seen": None,  "data": {}},
            ...
          },
          "alive_count": 4,
          "total": 5,
          "status": "degraded",   # "healthy" / "degraded" / "down" / "unknown"
        }

    A missing slice for a subsystem means that subprocess is down —
    the whole point of the Phase 4 split.
    """
    result: Dict[str, Any] = {
        "subsystems": {
            name: {"alive": False, "last_seen": None, "data": {}}
            for name in _HARDWARE_SUBSYSTEMS
        },
        "alive_count": 0,
        "total": len(_HARDWARE_SUBSYSTEMS),
        "status": "unknown",
    }

    try:
        from app_core.redis_client import get_redis_client
    except Exception as exc:
        if logger:
            logger.debug("hardware_subsystems: redis client unavailable: %s", exc)
        return result

    try:
        client = get_redis_client(max_retries=1)
    except Exception as exc:
        if logger:
            logger.debug("hardware_subsystems: redis connect failed: %s", exc)
        return result
    if client is None:
        return result

    summary: Dict[str, Any] = {}
    try:
        raw = client.get("hardware:metrics")
    except Exception as exc:
        if logger:
            logger.debug("hardware_subsystems: redis GET failed: %s", exc)
        raw = None

    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                summary = parsed
        except Exception as exc:
            if logger:
                logger.debug("hardware_subsystems: bad JSON in hardware:metrics: %s", exc)

    for name in _HARDWARE_SUBSYSTEMS:
        slice_payload = summary.get(name)
        if isinstance(slice_payload, dict):
            result["subsystems"][name] = {
                "alive": True,
                "last_seen": slice_payload.get("timestamp"),
                "data": {k: v for k, v in slice_payload.items() if k != "timestamp"},
            }
            result["alive_count"] += 1

    if result["alive_count"] == result["total"]:
        result["status"] = "healthy"
    elif result["alive_count"] == 0:
        result["status"] = "down"
    else:
        result["status"] = "degraded"

    return result


def _collect_gps_status(logger) -> Dict[str, Any]:
    """Read GPS fix status from Redis (published by the hardware service).

    Returns a best-effort dict that is always safe to serialise.  When the
    hardware service is not running or GPS is disabled the dict will contain
    ``enabled=False`` / ``running=False`` so the health page can render a
    graceful "not configured" state.
    """
    try:
        from app_core.redis_client import get_redis_client

        client = get_redis_client(max_retries=1)
        if client is None:
            return {"enabled": False, "running": False, "status": "redis_unavailable"}

        raw = client.get("gps:status")
        if not raw:
            # No key means GPS either disabled or hardware service not running
            return {"enabled": False, "running": False, "status": "not_started"}

        data: Dict[str, Any] = json.loads(raw)
        # Strip the large recent_sentences list — not needed in health snapshot
        data.pop("recent_sentences", None)
        return data
    except Exception as exc:
        if logger:
            logger.debug("Failed to read GPS status from Redis: %s", exc)
        return {"enabled": False, "running": False, "status": "error", "error": str(exc)}
