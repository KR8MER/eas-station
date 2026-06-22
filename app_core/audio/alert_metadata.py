from __future__ import annotations
"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed under AGPL-3.0 and a Commercial License.
See LICENSE and LICENSE-COMMERCIAL for details.

Repository: https://github.com/KR8MER/eas-station

Alert Metadata Coordinator

Holds a global handle to the active AutoStreamingService and exposes
``set_alert_metadata`` / ``clear_alert_metadata`` helpers used by the
auto-forwarder. While an alert is being forwarded, the stream metadata on
every active Icecast mount is overridden with the alert text so listeners
see the alert headline instead of the upstream source's now-playing info.

Usage
-----
At app startup (after AutoStreamingService is created)::

    from app_core.audio import alert_metadata
    alert_metadata.set_service(auto_streaming_service)

When an alert is being forwarded::

    from app_core.audio.alert_metadata import (
        set_alert_metadata, clear_alert_metadata,
    )
    set_alert_metadata("Tornado Warning — Logan County")
    try:
        broadcaster.handle_alert(...)
    finally:
        clear_alert_metadata()
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_service = None  # AutoStreamingService


def set_service(service) -> None:
    """Register the global AutoStreamingService (called once at startup)."""
    global _service
    with _lock:
        _service = service
    logger.info("Alert metadata coordinator: service registered")


def set_alert_metadata(title: str, artist: Optional[str] = "EAS Alert") -> int:
    """Push *title* (and optional *artist*) onto every active Icecast stream
    as an override.

    Returns the number of streamers that accepted the override (0 when no
    service is registered or no streams are active).
    """
    if not title:
        return 0
    with _lock:
        service = _service
    if service is None:
        return 0
    try:
        return service.update_alert_metadata(title, artist)
    except Exception as exc:
        logger.warning("Alert metadata override failed: %s", exc)
        return 0


def clear_alert_metadata() -> None:
    """Clear the alert metadata override on every active Icecast stream."""
    with _lock:
        service = _service
    if service is None:
        return
    try:
        service.clear_alert_metadata()
    except Exception as exc:
        logger.warning("Alert metadata clear failed: %s", exc)


__all__ = ["set_service", "set_alert_metadata", "clear_alert_metadata"]
