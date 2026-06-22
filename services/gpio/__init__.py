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

"""GPIO subsystem (relay control, NeoPixel strip, USB tower light).

The hardware-side alert indicator updater (tower light + NeoPixel
state machine driven by ``eas:broadcast_active`` and
``eas:incoming_alert``) also lives here because it owns the lifecycle
of those controllers.
"""

from services.gpio.alert_indicators import (
    AlertIndicatorMonitor,
    update_alert_indicators,
)
from services.gpio.init import (
    initialize_gpio_controller,
    initialize_neopixel_controller,
    initialize_tower_light_controller,
)

__all__ = [
    "initialize_gpio_controller",
    "initialize_neopixel_controller",
    "initialize_tower_light_controller",
    "update_alert_indicators",
    "AlertIndicatorMonitor",
]
