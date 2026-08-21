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

"""Unified GPIO control for transmitter keying and peripheral hardware.

This package provides reliable, auditable control over GPIO pins with features including:
- Active-high/low configuration
- Debounce logic
- Watchdog timers for stuck relay detection
- Activation history and audit trails
- Multiple relay/pin management
- Thread-safe operations

It was split out of the former single-file ``app_utils/gpio.py``, which had
grown to hold four independent subsystems. The layering is one-directional:

    pin_types       enums, dataclasses and constants (leaf)
    backends        lgpio / sysfs / null backends, pin-factory setup (leaf)
    tower_light     USB stack-light protocols and controller (leaf)
    neopixel        -> pin_types
    controller      -> backends, pin_types
    behavior        -> controller, pin_types
    config_loaders  -> neopixel, pin_types, tower_light

Every name the single-file module exposed is re-exported here, so
``from app_utils.gpio import ...`` keeps working unchanged. Import from the
submodules directly in new code.

NOTE for tests: a name must be patched on the module that *uses* it, not on
this package. ``_GPIO_SETTINGS_AVAILABLE`` and ``get_gpio_settings`` are read
by ``config_loaders``; ``_NEOPIXEL_LIB_AVAILABLE`` and ``NeopixelColor`` by
``neopixel``. Rebinding them here would not change what those modules resolve
from their own globals.
"""


from .pin_types import (  # noqa: F401
    GPIOActivationEvent, GPIOActivationType, GPIOBehavior, GPIOInterlockGroup,
    GPIOPinConfig, GPIOState, GPIO_BEHAVIOR_LABELS, GPIO_BEHAVIOR_PULSE_DEFAULTS,
    MAX_FLASH_INTERVAL_MS, MIN_FLASH_INTERVAL_MS,
    TRANSMIT_CAPABLE_BEHAVIORS,
)

from .backends import (  # noqa: F401
    Device, GPIOBackend, MockFactory, OutputDevice, _BackendPinDevice,
    _LGPIOBackend, _NullGPIOBackend, _PIN_FACTORY_ATTEMPTED,
    _PIN_FACTORY_READY, _SysfsGPIOBackend, _create_gpio_backend,
    _ensure_pin_factory, _explain_environment_issue,
    ensure_gpiozero_pin_factory,
)

from .controller import (  # noqa: F401
    GPIOController,
)

from .config_loaders import (  # noqa: F401
    _GPIO_SETTINGS_AVAILABLE, _stringify_behavior_matrix,
    get_gpio_settings, load_gpio_behavior_matrix_from_db,
    load_gpio_interlock_groups_from_db,
    load_gpio_pin_configs_from_db, load_neopixel_config_from_db,
    load_tower_light_config_from_db, serialize_gpio_behavior_matrix,
)

from .behavior import (  # noqa: F401
    GPIOBehaviorManager,
)

from .neopixel import (  # noqa: F401
    NeopixelColor, NeopixelConfig, NeopixelController, PixelStrip,
    WS2811_STRIP_GRB, WS2811_STRIP_RGB, _NEOPIXEL_LIB_AVAILABLE,
    _NEO_CHANNEL, _NEO_DMA, _NEO_FREQ_HZ, _NEO_INVERT, _NEO_STRIP_TYPES,
    _NullNeopixelStrip, _make_neo_color,
)

from .tower_light import (  # noqa: F401
    TOWER_LIGHT_COLORS, TOWER_LIGHT_PROTOCOLS, TowerLightConfig,
    TowerLightController, _ANDONT_BUZZER_OFF, _ANDONT_BUZZER_ON,
    _ANDONT_COLOR_CODES, _ANDONT_FLASH_FAST, _ANDONT_FLASH_NONE,
    _ANDONT_FRAME_END, _ANDONT_FRAME_START, _TOWER_CMD_BUZ_BLINK,
    _TOWER_CMD_BUZ_OFF, _TOWER_CMD_BUZ_ON, _TOWER_CMD_GRN_BLINK,
    _TOWER_CMD_GRN_OFF, _TOWER_CMD_GRN_ON, _TOWER_CMD_RED_BLINK,
    _TOWER_CMD_RED_OFF, _TOWER_CMD_RED_ON, _TOWER_CMD_YEL_BLINK,
    _TOWER_CMD_YEL_OFF, _TOWER_CMD_YEL_ON, _TOWER_SEGMENT_CMDS,
)
