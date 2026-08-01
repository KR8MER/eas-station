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

"""Presentation helpers for ``GPIOActivationLog`` rows.

The Logs hub renders GPIO activations in three places (the unified ``All Logs``
view, the dedicated GPIO category, and the ``/api/logs/*`` JSON feed).  All
three used to hard-code ``level: 'INFO'``, so a *failed* activation — the row
``GPIOController.activate()`` writes when the hardware is unavailable and the
relay never moved — looked identical to a successful one.  An operator checking
whether the air chain keyed for an alert had no way to tell.

Kept free of any hardware imports so the web layer can use it without dragging
in ``app_utils.gpio`` (and, with it, gpiozero / lgpio).
"""

from typing import Any, Optional

__all__ = [
    "gpio_log_duration",
    "gpio_log_level",
    "gpio_log_message",
]


def gpio_log_level(log: Any) -> str:
    """Return the log level for an activation row.

    Failed activations are errors: the relay did not do what was asked of it.
    """
    return "INFO" if getattr(log, "success", True) else "ERROR"


def gpio_log_duration(log: Any) -> str:
    """Return a human-readable activation duration.

    ``"Active"`` while the relay is still energised (the row is written when the
    pin fires and updated when it releases), otherwise seconds rounded to a
    tenth — the raw float carries meaningless microsecond precision.

    A *failed* activation also has no duration, but the relay never moved, so it
    must not be reported as active — those rows read ``"N/A"``.
    """
    duration: Optional[float] = getattr(log, "duration_seconds", None)
    if duration is None:
        return "Active" if getattr(log, "success", True) else "N/A"
    try:
        return f"{float(duration):.1f}s"
    except (TypeError, ValueError):
        return str(duration)


def gpio_log_message(log: Any) -> str:
    """Return the one-line summary shown in the Logs hub for an activation."""
    parts = [
        f"Type: {getattr(log, 'activation_type', None) or 'unknown'}",
        f"Operator: {getattr(log, 'operator', None) or 'System'}",
        f"Duration: {gpio_log_duration(log)}",
    ]

    reason = getattr(log, "reason", None)
    if reason:
        parts.append(f"Reason: {reason}")

    if not getattr(log, "success", True):
        parts.append(f"FAILED: {getattr(log, 'error_message', None) or 'unknown error'}")

    return " | ".join(parts)
