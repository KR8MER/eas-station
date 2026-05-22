"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Per-subsystem Redis metrics publishers.

In Phase 3 of the hardware_service.py split this module hosted a single
``publish_hardware_metrics()`` that walked screen_manager + zigbee +
gpio_controller in one pass.  Phase 4 split the hardware service into
five subprocesses, so each subprocess now publishes only its own slice
of ``hardware:metrics:*``:

  * displays subprocess  -> ``hardware:metrics:displays``
                          + ``hardware:display_state``
  * zigbee subprocess    -> ``hardware:metrics:zigbee``
                          + ``zigbee:coordinator``
  * gps subprocess       -> ``hardware:metrics:gps``
                          + ``gps:status`` (owned by GPSManager)
                          + ``gps:dashboard:trends*`` (owned by the
                            sampler in ``services.gps.trends``)
  * gpio subprocess      -> ``hardware:metrics:gpio``
  * network subprocess   -> ``hardware:metrics:network``

The legacy ``hardware:metrics`` key is preserved as a *summary* row
written by each publisher with ``hardware:metrics:<subsystem>`` so the
existing web-UI health banner ("is hardware-service alive?") keeps
working.  Each subsystem refreshes only its own slice of that summary,
so a wedged zigbee subprocess no longer keeps the displays slice fresh
in Redis (which is the whole point of the split).
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# 60 s TTL keeps the legacy "is hardware up?" semantics: if every
# subprocess has been dead for a minute, every slice expires and the
# web banner shows "hardware unavailable".  Per-subprocess publishers
# tick at 5 s so the slice is comfortably alive while the unit is up.
_METRICS_TTL_S = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _publish_slice(redis_client, subsystem: str, slice_data: dict) -> None:
    """Publish ``hardware:metrics:<subsystem>`` and refresh the summary.

    The summary key (``hardware:metrics``) is a JSON dict keyed by
    subsystem so callers that just want "is hardware healthy?" can
    decode one key and inspect ``len(metrics) > 0``.
    """
    if not redis_client:
        return

    slice_payload = {"timestamp": _now_iso(), **slice_data}
    try:
        redis_client.setex(
            f"hardware:metrics:{subsystem}",
            _METRICS_TTL_S,
            json.dumps(slice_payload),
        )
    except Exception as exc:
        logger.debug("Failed to publish hardware:metrics:%s: %s", subsystem, exc)
        return

    # Read-modify-write the summary key.  Each subprocess only touches
    # its own slice; races are tolerated because the slice payload is
    # also published at the per-subsystem key (the canonical copy).
    try:
        raw = redis_client.get("hardware:metrics")
        summary = {}
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                summary = json.loads(raw) or {}
                if not isinstance(summary, dict):
                    summary = {}
            except Exception:
                summary = {}
        summary[subsystem] = slice_payload
        summary["timestamp"] = slice_payload["timestamp"]
        redis_client.setex("hardware:metrics", _METRICS_TTL_S, json.dumps(summary))
    except Exception as exc:
        logger.debug("Failed to update hardware:metrics summary: %s", exc)


def publish_displays_metrics(*, redis_client, flask_app, screen_manager) -> None:
    """Publish the displays subprocess's slice of ``hardware:metrics``.

    Also refreshes ``hardware:display_state`` (the detailed payload
    containing the OLED preview image) which the web UI reads to
    render the live display preview.
    """
    if not redis_client:
        return

    ctx = None
    if flask_app:
        # publish_display_state() queries HardwareSettings via
        # Flask-SQLAlchemy, which needs an app context.
        ctx = flask_app.app_context()
        ctx.push()

    try:
        slice_data = {
            "screen_manager_running": (
                screen_manager is not None
                and getattr(screen_manager, "_running", False)
            ),
        }
        if screen_manager:
            try:
                slice_data["screens"] = {
                    "oled_active": getattr(screen_manager, "_oled_rotation", None) is not None,
                    "led_active": getattr(screen_manager, "_led_rotation", None) is not None,
                    "vfd_active": getattr(screen_manager, "_vfd_rotation", None) is not None,
                }
            except Exception:
                pass

        _publish_slice(redis_client, "displays", slice_data)

        # Detailed display state (with preview image, scroll offset, etc.)
        from services.displays import publish_display_state
        publish_display_state(redis_client, screen_manager)

    except Exception as e:
        logger.debug(f"Failed to publish displays metrics: {e}")
    finally:
        if ctx is not None:
            ctx.pop()


def publish_zigbee_metrics(*, redis_client, flask_app, zigpy_controller) -> None:
    """Publish the zigbee subprocess's slice of ``hardware:metrics``.

    Also refreshes ``zigbee:coordinator`` (the Redis key the web UI
    polls for join-window status).
    """
    if not redis_client:
        return

    ctx = None
    if flask_app:
        ctx = flask_app.app_context()
        ctx.push()

    try:
        slice_data = {
            "coordinator_running": bool(
                zigpy_controller is not None
                and getattr(zigpy_controller, "running", False)
            ),
            "permit_join_active": bool(
                zigpy_controller is not None
                and getattr(zigpy_controller, "permit_join_active", False)
            ),
        }
        _publish_slice(redis_client, "zigbee", slice_data)

        from services.zigbee import publish_zigbee_status
        publish_zigbee_status(redis_client)
    except Exception as e:
        logger.debug(f"Failed to publish zigbee metrics: {e}")
    finally:
        if ctx is not None:
            ctx.pop()


def publish_gps_metrics(*, redis_client, gps_manager) -> None:
    """Publish the gps subprocess's slice of ``hardware:metrics``."""
    if not redis_client:
        return

    slice_data = {
        "manager_running": bool(
            gps_manager is not None
            and getattr(gps_manager, "running", False)
        ),
        "has_fix": False,
    }
    if gps_manager is not None:
        try:
            status = gps_manager.get_status() or {}
            slice_data["has_fix"] = bool(status.get("has_fix"))
        except Exception:
            pass

    _publish_slice(redis_client, "gps", slice_data)


def publish_gpio_metrics(
    *, redis_client, gpio_controller, neopixel_controller, tower_light_controller
) -> None:
    """Publish the gpio subprocess's slice of ``hardware:metrics``."""
    if not redis_client:
        return

    slice_data = {
        "gpio_controller_available": gpio_controller is not None,
        "neopixel_available": neopixel_controller is not None,
        "tower_light_available": (
            tower_light_controller is not None
            and getattr(tower_light_controller, "is_available", False)
        ),
    }
    _publish_slice(redis_client, "gpio", slice_data)


def publish_network_metrics(*, redis_client) -> None:
    """Publish the network subprocess's slice of ``hardware:metrics``.

    The network subsystem has no long-lived controllers — every API
    call shells out to nmcli on demand — so the slice payload is
    intentionally minimal.  It exists so the web UI's "is the network
    subprocess up?" indicator can distinguish "process down" from
    "process up but nmcli failed".
    """
    _publish_slice(redis_client, "network", {"healthy": True})
