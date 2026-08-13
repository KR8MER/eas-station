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

"""Enums, dataclasses and constants describing GPIO pins and behaviours."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional



# Flash pattern configuration constants
MIN_FLASH_INTERVAL_MS = 50  # Minimum flash interval (20Hz)
MAX_FLASH_INTERVAL_MS = 5000  # Maximum flash interval (0.2Hz)

class GPIOState(Enum):
    """GPIO pin state enumeration."""
    INACTIVE = "inactive"
    ACTIVE = "active"
    ERROR = "error"
    WATCHDOG_TIMEOUT = "watchdog_timeout"


class GPIOActivationType(Enum):
    """Type of GPIO activation."""
    MANUAL = "manual"  # Manual operator activation
    AUTOMATIC = "automatic"  # Triggered by alert processing
    TEST = "test"  # Test activation
    OVERRIDE = "override"  # Override/emergency activation


class GPIOBehavior(Enum):
    """Lifecycle triggers that can drive GPIO relays."""

    DURATION_OF_ALERT = "duration_of_alert"
    PLAYOUT = "playout"
    FLASH = "flash"
    FIVE_SECONDS = "five_seconds"
    INCOMING_ALERT = "incoming_alert"
    FORWARDING_ALERT = "forwarding_alert"
    # Transmitter keying (PTT). Held active for the full broadcast so the
    # external transmitter / control system stays keyed while EAS audio plays.
    TRANSMITTER_PTT = "transmitter_ptt"
    # Audio mute / program-audio ducking relay. Held active during playout so
    # station program audio is muted (or switched to the EAS source) while the
    # alert is on air, then released when playout finishes.
    AUDIO_MUTE = "audio_mute"
    # Gated-alerts hold-off timer indicator. Held active for as long as at
    # least one alert is sitting in the Pending Alerts queue awaiting
    # operator approval/cancel or timer release. Not tied to a single alert
    # (unlike the other behaviors above) -- driven by queue depth, not a
    # broadcast lifecycle event.
    GATE_PENDING = "gate_pending"

    @classmethod
    def from_value(cls, value: str) -> Optional["GPIOBehavior"]:
        """Convert a raw string into a :class:`GPIOBehavior` member."""

        if not value:
            return None

        try:
            return cls(value)
        except ValueError:
            normalized = str(value).strip().lower()
            for member in cls:
                if member.value == normalized:
                    return member
        return None


GPIO_BEHAVIOR_LABELS = {
    GPIOBehavior.DURATION_OF_ALERT: "Duration of Alert",
    GPIOBehavior.PLAYOUT: "Audio Playout",
    GPIOBehavior.FLASH: "Flash Beacon",
    GPIOBehavior.FIVE_SECONDS: "5 Second Pulse",
    GPIOBehavior.INCOMING_ALERT: "Incoming Alert",
    GPIOBehavior.FORWARDING_ALERT: "Forwarding Alert",
    GPIOBehavior.TRANSMITTER_PTT: "Transmitter PTT",
    GPIOBehavior.AUDIO_MUTE: "Audio Mute",
    GPIOBehavior.GATE_PENDING: "Gated Alert Pending",
}


# Behaviors that key the station transmitter / hold the airchain for the full
# broadcast.  Used by :meth:`GPIOBehaviorManager.validate_configuration` to warn
# operators when no pin will key the transmitter during an alert.
TRANSMIT_CAPABLE_BEHAVIORS = frozenset(
    {
        GPIOBehavior.TRANSMITTER_PTT,
        GPIOBehavior.DURATION_OF_ALERT,
        GPIOBehavior.PLAYOUT,
    }
)


GPIO_BEHAVIOR_PULSE_DEFAULTS = {
    GPIOBehavior.INCOMING_ALERT: 3.0,
    GPIOBehavior.FORWARDING_ALERT: 5.0,
    GPIOBehavior.FIVE_SECONDS: 5.0,
    GPIOBehavior.FLASH: 0.35,
}


@dataclass
class GPIOActivationEvent:
    """Record of a GPIO activation event for audit trail."""
    pin: int
    activation_type: GPIOActivationType
    activated_at: datetime
    deactivated_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    operator: Optional[str] = None  # Username if manual/override
    alert_id: Optional[str] = None  # Alert identifier if automatic
    reason: Optional[str] = None  # Human-readable reason
    success: bool = True
    error_message: Optional[str] = None
    #: Primary key of the ``gpio_activation_logs`` row this event was persisted
    #: to.  Set when the row is written at activation time so the matching
    #: deactivation updates that row (filling in the duration) instead of
    #: inserting a second one.  Not part of :meth:`to_dict` — it is storage
    #: bookkeeping, not audit content.
    record_id: Optional[int] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage."""
        return {
            'pin': self.pin,
            'activation_type': self.activation_type.value,
            'activated_at': self.activated_at.isoformat(),
            'deactivated_at': self.deactivated_at.isoformat() if self.deactivated_at else None,
            'duration_seconds': self.duration_seconds,
            'operator': self.operator,
            'alert_id': self.alert_id,
            'reason': self.reason,
            'success': self.success,
            'error_message': self.error_message,
        }


@dataclass
class GPIOPinConfig:
    """Configuration for a single GPIO pin."""
    pin: int
    name: str  # Descriptive name (e.g., "Transmitter PTT", "Emergency Relay")
    active_high: bool = True
    debounce_ms: int = 50  # Debounce time in milliseconds
    hold_seconds: float = 5.0  # Minimum hold time before release
    watchdog_seconds: float = 300.0  # Maximum activation time (5 minutes default)
    enabled: bool = True
    # Flash pattern configuration for stack lights
    flash_enabled: bool = False  # Enable flash/alternating pattern
    flash_interval_ms: int = 500  # Flash interval in milliseconds (default 500ms = 2Hz)
    flash_partner_pin: Optional[int] = None  # Partner pin for two-phase alternating pattern
