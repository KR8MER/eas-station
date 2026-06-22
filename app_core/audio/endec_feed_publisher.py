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

"""Publish ENDEC "device feed" events onto Redis for the TCP fan-out service.

The detection/forwarding pipeline calls :func:`publish_from_alert` at four
decision points (``local`` / ``match`` / ``nomatch`` / ``dup``). Each call
emits a small JSON payload on :data:`ENDEC_FEED_CHANNEL`; the
:mod:`services.endec_feeds` daemon subscribes, renders the configured wire
formats (see :mod:`app_utils.endec_feeds`), and fans the bytes out to
connected TCP clients.

Every function here is best-effort and never raises into the alert pipeline —
a Redis hiccup must not break a broadcast.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Redis pub/sub channel carrying rendered-on-demand feed events.
ENDEC_FEED_CHANNEL = "eas:endec_feed"

#: Redis pub/sub channel that tells the feed service to reload its config.
ENDEC_FEED_RELOAD_CHANNEL = "eas:endec_feed:reload"


def publish_feed_reload(logger_instance: Optional[logging.Logger] = None) -> bool:
    """Tell the running feed service to re-read its configuration. Best-effort."""
    log = logger_instance or logger
    try:
        from app_core.redis_client import get_redis_client

        client = get_redis_client()
        if client is None:
            return False
        client.publish(ENDEC_FEED_RELOAD_CHANNEL, "1")
        return True
    except Exception as exc:
        log.debug("ENDEC feed reload publish skipped: %s", exc)
        return False


def _compose_text(alert: Dict[str, Any], event_code: str) -> str:
    """Build a concise plain-language line when the alert carries no summary."""
    try:
        from app_utils.event_codes import EVENT_CODE_REGISTRY
        entry = EVENT_CODE_REGISTRY.get(event_code)
        event_name = str(entry.get("name")) if entry else (event_code or "alert")
    except Exception:
        event_name = event_code or "alert"

    originator = str(alert.get("originator") or "An originator").strip() or "An originator"
    locations = alert.get("location_codes") or []
    summary = f"{originator} has issued a {event_name}"
    if locations:
        summary += f" for {len(locations)} area(s) ({', '.join(str(x) for x in locations[:8])})"
    return summary + "."


def publish_feed_event(
    status: str,
    *,
    header: str = "",
    text: str = "",
    event_code: str = "",
    station_id: str = "",
    timestamp: Optional[datetime] = None,
    logger_instance: Optional[logging.Logger] = None,
) -> bool:
    """Publish a single feed event to Redis. Returns True on publish.

    Best-effort: any failure is logged at debug level and swallowed.
    """
    log = logger_instance or logger
    try:
        from app_core.redis_client import get_redis_client

        client = get_redis_client()
        if client is None:
            return False

        payload = {
            "status": str(status).strip().lower(),
            "event_code": str(event_code or "").strip().upper(),
            "header": header or "",
            "text": text or "",
            "station_id": station_id or "",
            "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        }
        client.publish(ENDEC_FEED_CHANNEL, json.dumps(payload))
        log.debug("Published ENDEC feed event '%s' (%s)", payload["status"], payload["event_code"])
        return True
    except Exception as exc:  # never break the alert pipeline
        log.debug("ENDEC feed publish skipped: %s", exc)
        return False


def publish_from_alert(
    status: str,
    alert: Dict[str, Any],
    *,
    text: Optional[str] = None,
    logger_instance: Optional[logging.Logger] = None,
) -> bool:
    """Publish a feed event derived from an alert dict.

    Pulls the SAME header, event code, station id and a display text from the
    alert (falling back to a composed one-liner), then delegates to
    :func:`publish_feed_event`.
    """
    try:
        event_code = str(alert.get("event_code") or "").strip().upper()
        header = (
            alert.get("raw_header")
            or alert.get("header")
            or alert.get("same_header")
            or ""
        )
        resolved_text = (
            text
            or alert.get("summary")
            or alert.get("plain_language")
            or alert.get("description")
            or _compose_text(alert, event_code)
        )
        station_id = (
            alert.get("station_id")
            or alert.get("callsign")
            or alert.get("sender")
            or ""
        )
        return publish_feed_event(
            status,
            header=str(header),
            text=str(resolved_text),
            event_code=event_code,
            station_id=str(station_id),
            logger_instance=logger_instance,
        )
    except Exception as exc:
        (logger_instance or logger).debug("ENDEC feed publish_from_alert skipped: %s", exc)
        return False


__all__ = [
    "ENDEC_FEED_CHANNEL", "ENDEC_FEED_RELOAD_CHANNEL",
    "publish_feed_event", "publish_from_alert", "publish_feed_reload",
]
