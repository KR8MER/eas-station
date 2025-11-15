"""Static metadata for the Raspberry Pi 40-pin header."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class PinDefinition:
    """Represents a physical pin on the Raspberry Pi header."""

    physical: int
    name: str
    pin_type: str  # power, ground, gpio
    bcm: Optional[int] = None
    description: Optional[str] = None
    reserved_for: Optional[str] = None
    reserved_detail: Optional[str] = None

    @property
    def is_gpio(self) -> bool:
        return self.pin_type == "gpio" and self.bcm is not None


# Physical layout rows (odd pins on the left, even pins on the right when looking
# at the Pi with the USB ports facing down).
PIN_ROWS: List[Tuple[PinDefinition, PinDefinition]] = [
    (
        PinDefinition(
            1,
            "3V3",
            "power",
            description="+3.3V power",
            reserved_for="Argon OLED module",
            reserved_detail="Primary power feed",
        ),
        PinDefinition(
            2,
            "5V",
            "power",
            description="+5V power",
            reserved_for="Argon OLED module",
            reserved_detail="Supplemental power",
        ),
    ),
    (
        PinDefinition(
            3,
            "GPIO 2 / SDA1",
            "gpio",
            bcm=2,
            description="I2C SDA1",
            reserved_for="Argon OLED module",
            reserved_detail="I²C data bus",
        ),
        PinDefinition(
            4,
            "5V",
            "power",
            description="+5V power",
            reserved_for="Argon OLED module",
            reserved_detail="Supplemental power",
        ),
    ),
    (
        PinDefinition(
            5,
            "GPIO 3 / SCL1",
            "gpio",
            bcm=3,
            description="I2C SCL1",
            reserved_for="Argon OLED module",
            reserved_detail="I²C clock",
        ),
        PinDefinition(
            6,
            "GND",
            "ground",
            description="Ground",
            reserved_for="Argon OLED module",
            reserved_detail="Ground return",
        ),
    ),
    (
        PinDefinition(
            7,
            "GPIO 4",
            "gpio",
            bcm=4,
            description="GPCLK0 / General I/O",
            reserved_for="Argon OLED module",
            reserved_detail="Front-panel button",
        ),
        PinDefinition(
            8,
            "GPIO 14 / TXD0",
            "gpio",
            bcm=14,
            description="UART TXD0",
            reserved_for="Argon OLED module",
            reserved_detail="Display heartbeat",
        ),
    ),
    (
        PinDefinition(9, "GND", "ground", description="Ground"),
        PinDefinition(10, "GPIO 15 / RXD0", "gpio", bcm=15, description="UART RXD0"),
    ),
    (
        PinDefinition(11, "GPIO 17", "gpio", bcm=17, description="General purpose I/O"),
        PinDefinition(12, "GPIO 18", "gpio", bcm=18, description="PWM0 / I2S CLK"),
    ),
    (
        PinDefinition(13, "GPIO 27", "gpio", bcm=27, description="General purpose I/O"),
        PinDefinition(14, "GND", "ground", description="Ground"),
    ),
    (
        PinDefinition(15, "GPIO 22", "gpio", bcm=22, description="General purpose I/O"),
        PinDefinition(16, "GPIO 23", "gpio", bcm=23, description="General purpose I/O"),
    ),
    (
        PinDefinition(17, "3V3", "power", description="+3.3V power"),
        PinDefinition(18, "GPIO 24", "gpio", bcm=24, description="General purpose I/O"),
    ),
    (
        PinDefinition(19, "GPIO 10 / MOSI", "gpio", bcm=10, description="SPI MOSI"),
        PinDefinition(20, "GND", "ground", description="Ground"),
    ),
    (
        PinDefinition(21, "GPIO 9 / MISO", "gpio", bcm=9, description="SPI MISO"),
        PinDefinition(22, "GPIO 25", "gpio", bcm=25, description="General purpose I/O"),
    ),
    (
        PinDefinition(23, "GPIO 11 / SCLK", "gpio", bcm=11, description="SPI SCLK"),
        PinDefinition(24, "GPIO 8 / CE0", "gpio", bcm=8, description="SPI CE0"),
    ),
    (
        PinDefinition(25, "GND", "ground", description="Ground"),
        PinDefinition(26, "GPIO 7 / CE1", "gpio", bcm=7, description="SPI CE1"),
    ),
    (
        PinDefinition(27, "GPIO 0 / SDA0", "gpio", bcm=0, description="ID EEPROM SDA"),
        PinDefinition(28, "GPIO 1 / SCL0", "gpio", bcm=1, description="ID EEPROM SCL"),
    ),
    (
        PinDefinition(29, "GPIO 5", "gpio", bcm=5, description="General purpose I/O"),
        PinDefinition(30, "GND", "ground", description="Ground"),
    ),
    (
        PinDefinition(31, "GPIO 6", "gpio", bcm=6, description="General purpose I/O"),
        PinDefinition(32, "GPIO 12", "gpio", bcm=12, description="PWM0"),
    ),
    (
        PinDefinition(33, "GPIO 13", "gpio", bcm=13, description="PWM1"),
        PinDefinition(34, "GND", "ground", description="Ground"),
    ),
    (
        PinDefinition(35, "GPIO 19", "gpio", bcm=19, description="PCM FS / SPI"),
        PinDefinition(36, "GPIO 16", "gpio", bcm=16, description="General purpose I/O"),
    ),
    (
        PinDefinition(37, "GPIO 26", "gpio", bcm=26, description="General purpose I/O"),
        PinDefinition(38, "GPIO 20", "gpio", bcm=20, description="PCM DIN / SPI"),
    ),
    (
        PinDefinition(39, "GND", "ground", description="Ground"),
        PinDefinition(40, "GPIO 21", "gpio", bcm=21, description="PCM DOUT / SPI"),
    ),
]


ARGON_OLED_RESERVED_PHYSICAL = {
    pin.physical
    for pin in (
        pin_def
        for row in PIN_ROWS
        for pin_def in row
        if pin_def.reserved_for == "Argon OLED module"
    )
}

ARGON_OLED_RESERVED_BCM = {
    pin.bcm
    for pin in (
        pin_def
        for row in PIN_ROWS
        for pin_def in row
        if pin_def.reserved_for == "Argon OLED module" and pin_def.bcm is not None
    )
}


def iter_pins() -> Iterable[PinDefinition]:
    """Yield each :class:`PinDefinition` in physical order."""

    for left, right in PIN_ROWS:
        yield left
        yield right


def map_bcm_to_physical() -> Dict[int, int]:
    """Return a mapping of BCM pin numbers to physical header positions."""

    mapping: Dict[int, int] = {}
    for pin in iter_pins():
        if pin.is_gpio:
            mapping[pin.bcm] = pin.physical
    return mapping


__all__ = [
    "PinDefinition",
    "PIN_ROWS",
    "iter_pins",
    "map_bcm_to_physical",
    "ARGON_OLED_RESERVED_BCM",
    "ARGON_OLED_RESERVED_PHYSICAL",
]
