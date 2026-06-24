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

"""Redis command + state channel for the GPIO subsystem.

Only the ``eas-station-gpio`` subprocess (``services.gpio``) owns the physical
GPIO lines.  lgpio's ``gpio_claim_output`` is **exclusive per process**, so any
other process that builds a ``GPIOController`` for the same pins fails to claim
them and silently falls back to the no-op backend — the relay never moves.
Importing lgpio inside the gunicorn gevent web workers also stalls the event
loop.  For both reasons the web app, the poller, the RWT scheduler, and the
resend helper must **not** drive GPIO directly.

Two flows replace direct keying:

* **Broadcast relay keying** happens automatically in the subprocess off the
  ``eas:broadcast_active`` marker every producer already publishes
  (see ``services/gpio/alert_indicators.py``).  No command is needed.

* **Operator-initiated manual control** (the GPIO Control page "test" buttons)
  publishes a command on :data:`GPIO_COMMAND_CHANNEL`; the subprocess consumes
  it and acts on its single owned controller.

The subprocess also publishes a snapshot of live pin states to
:data:`GPIO_PIN_STATE_KEY` so the web UI can render current state without ever
constructing a controller of its own.
"""

import json
import time
from typing import Any, Dict, List, Optional

#: Pub/sub channel the GPIO subprocess listens on for manual control commands.
GPIO_COMMAND_CHANNEL = "eas:gpio_commands"

#: Redis key holding the latest pin-state snapshot published by the subprocess.
GPIO_PIN_STATE_KEY = "eas:gpio_pin_states"

#: TTL (seconds) for the pin-state snapshot.  Longer than the subprocess
#: heartbeat so a single missed publish doesn't blank the UI, short enough that
#: a dead subprocess is detectable (stale snapshot -> "GPIO service offline").
GPIO_PIN_STATE_TTL = 30

#: Supported command verbs.
VALID_ACTIONS = frozenset(
    {"activate", "deactivate", "activate_all", "deactivate_all"}
)


def publish_gpio_command(
    action: str,
    *,
    pin: Optional[int] = None,
    operator: Optional[str] = None,
    reason: Optional[str] = None,
    force: bool = False,
    activation_type: str = "manual",
) -> int:
    """Publish a manual GPIO command for the subprocess to execute.

    Returns the number of subscribers that received the command.  ``0`` means
    the GPIO subprocess is not listening (it's down, or GPIO is disabled), which
    the caller should surface to the operator rather than reporting success.
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unsupported GPIO command action: {action!r}")

    try:
        from app_core.redis_client import get_redis_client

        client = get_redis_client()
        if client is None:
            return 0
        payload = json.dumps(
            {
                "action": action,
                "pin": pin,
                "operator": operator or "",
                "reason": reason or "",
                "force": bool(force),
                "activation_type": activation_type or "manual",
                "ts": time.time(),
            }
        )
        return int(client.publish(GPIO_COMMAND_CHANNEL, payload) or 0)
    except Exception:
        return 0


def dispatch_gpio_command(controller, command: Dict[str, Any], logger=None) -> bool:
    """Execute a parsed GPIO command against an owned controller.

    Pure dispatch helper (no Redis) so it can be unit-tested in isolation and
    reused by the subprocess listener.  Returns ``True`` when the underlying
    controller call reported success.
    """
    from app_utils.gpio import GPIOActivationType

    action = str(command.get("action") or "")
    if action not in VALID_ACTIONS:
        if logger:
            logger.warning("Ignoring unknown GPIO command: %r", action)
        return False

    if controller is None:
        if logger:
            logger.warning("GPIO command %r received but no controller is available", action)
        return False

    try:
        activation_type = GPIOActivationType[str(command.get("activation_type", "manual")).upper()]
    except KeyError:
        activation_type = GPIOActivationType.MANUAL

    operator = command.get("operator") or None
    reason = command.get("reason") or "Manual GPIO command"
    force = bool(command.get("force", False))

    if action == "activate":
        pin = command.get("pin")
        if pin is None:
            return False
        return bool(
            controller.activate(
                pin=int(pin),
                activation_type=activation_type,
                operator=operator,
                reason=reason,
            )
        )

    if action == "deactivate":
        pin = command.get("pin")
        if pin is None:
            return False
        return bool(controller.deactivate(pin=int(pin), force=force))

    if action == "activate_all":
        results = controller.activate_all(
            activation_type=activation_type,
            operator=operator,
            reason=reason,
        )
        return any(results.values())

    if action == "deactivate_all":
        results = controller.deactivate_all(force=force)
        return any(results.values()) or not results

    return False


def publish_pin_states(redis_client, states: List[Dict[str, Any]]) -> None:
    """Publish a snapshot of GPIO pin states for the web UI to read."""
    if redis_client is None:
        return
    try:
        redis_client.set(
            GPIO_PIN_STATE_KEY,
            json.dumps({"pins": states, "ts": time.time()}),
            ex=GPIO_PIN_STATE_TTL,
        )
    except Exception:
        pass


def get_pin_states() -> Dict[str, Any]:
    """Return the latest pin-state snapshot published by the subprocess.

    Returns ``{"available": bool, "pins": [...], "ts": float|None}``.
    ``available`` is ``False`` when no fresh snapshot exists (the GPIO
    subprocess is down or GPIO is disabled).
    """
    try:
        from app_core.redis_client import get_redis_client

        client = get_redis_client()
        if client is None:
            return {"available": False, "pins": [], "ts": None}
        raw = client.get(GPIO_PIN_STATE_KEY)
        if not raw:
            return {"available": False, "pins": [], "ts": None}
        data = json.loads(raw)
        return {
            "available": True,
            "pins": data.get("pins", []),
            "ts": data.get("ts"),
        }
    except Exception:
        return {"available": False, "pins": [], "ts": None}


__all__ = [
    "GPIO_COMMAND_CHANNEL",
    "GPIO_PIN_STATE_KEY",
    "GPIO_PIN_STATE_TTL",
    "VALID_ACTIONS",
    "publish_gpio_command",
    "dispatch_gpio_command",
    "publish_pin_states",
    "get_pin_states",
]
