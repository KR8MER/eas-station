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

"""Raspberry Pi-specific health telemetry.

None of this applies to a generic/bare-metal or VM deployment -- every
collector here is gated on actually running on a Pi (see
``collect_raspberry_pi_health``) and the whole section is simply omitted
otherwise, the same way ``_collect_platform_details`` in hardware.py falls
back cleanly between DMI (generic x86) and device-tree (ARM/Pi) metadata.

Covers four things nothing else in this package surfaces:

* Under-voltage / throttling history (``vcgencmd get_throttled``) -- the
  single most common root cause of "flaky Pi" reports in the field. Reports
  both the *current* state and whether it has *ever* happened since boot,
  which a point-in-time reading can't tell you.
* Bootloader/EEPROM update availability (``rpi-eeprom-update``).
* Case fan RPM (``psutil.sensors_fans()`` -- already free, just never wired
  up anywhere in this codebase).
* RP1 (Pi 5's I/O southbridge) ADC voltage channels, for the rare case
  those are worth a second look during hardware troubleshooting. Exposed as
  plain labelled channels rather than guessing which rail is which -- the
  kernel driver doesn't publish per-channel labels and getting that wrong
  would be worse than not showing it.
"""

import re
import subprocess
from typing import Any, Dict, List, Optional

import psutil

from .common import _coerce_int

# vcgencmd get_throttled bit -> (key, human label). Bits 0-3 are the current
# state; the same bits shifted up to 16-19 mean "has happened since boot".
# Documented at https://www.raspberrypi.com/documentation/computers/os.html#get_throttled
_THROTTLE_BITS = (
    (0, "under_voltage", "Under-voltage detected"),
    (1, "frequency_capped", "ARM frequency capped"),
    (2, "throttled", "Currently throttled"),
    (3, "soft_temp_limit", "Soft temperature limit active"),
)


def _is_raspberry_pi(platform_details: Optional[Dict[str, Any]]) -> bool:
    """Gate for every collector in this module.

    Checked against both the device-tree "compatible" list and the
    product/board name string, since which one is populated depends on
    whether hardware.py found the info via device-tree or DMI.
    """

    if not platform_details:
        return False

    compatible = platform_details.get("compatible")
    if isinstance(compatible, list) and any(
        "raspberrypi" in str(entry).lower() for entry in compatible
    ):
        return True

    for key in ("product_name", "board_name", "sys_vendor"):
        value = platform_details.get(key)
        if value and "raspberry" in str(value).lower():
            return True

    return False


def _run(command: List[str], logger, timeout: float = 5.0) -> Optional[str]:
    """Run a short-lived read-only command, returning stdout or None."""

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if logger:
            logger.debug("%s timed out", " ".join(command))
        return None
    except (OSError, PermissionError) as exc:
        if logger:
            logger.debug("%s failed: %s", " ".join(command), exc)
        return None
    return completed.stdout or None


def _collect_throttle_status(logger) -> Optional[Dict[str, Any]]:
    """Parse ``vcgencmd get_throttled`` into named current/historical flags."""

    stdout = _run(["vcgencmd", "get_throttled"], logger)
    if not stdout:
        return None

    match = re.search(r"throttled=(0x[0-9a-fA-F]+)", stdout)
    if not match:
        return None

    mask = _coerce_int(match.group(1))
    if mask is None:
        return None

    current: Dict[str, bool] = {}
    ever: Dict[str, bool] = {}
    any_current = False
    any_ever = False
    for bit, key, _label in _THROTTLE_BITS:
        now_flag = bool(mask & (1 << bit))
        ever_flag = bool(mask & (1 << (bit + 16)))
        current[key] = now_flag
        ever[key] = ever_flag
        any_current = any_current or now_flag
        any_ever = any_ever or ever_flag

    return {
        "raw_mask": f"0x{mask:x}",
        "current": current,
        "ever_since_boot": ever,
        "healthy": not any_ever,
        "currently_degraded": any_current,
    }


def _collect_bootloader_status(logger) -> Optional[Dict[str, Any]]:
    """Parse ``rpi-eeprom-update``'s plain-text report.

    Read-only by default (no ``-a``); never applies anything. Runs fine as
    an unprivileged user -- it only reads the current EEPROM version and
    the bundled firmware image under /usr/lib/firmware, both world-readable.
    """

    stdout = _run(["rpi-eeprom-update"], logger, timeout=10.0)
    if not stdout:
        return None

    update_available = "UPDATE AVAILABLE" in stdout

    current_match = re.search(r"CURRENT:\s*(.+?)\s*\(\d+\)", stdout)
    latest_match = re.search(r"LATEST:\s*(.+?)\s*\(\d+\)", stdout)

    return {
        "update_available": update_available,
        "current_date": current_match.group(1).strip() if current_match else None,
        "latest_date": latest_match.group(1).strip() if latest_match else None,
    }


def _collect_fan_status(logger) -> Optional[Dict[str, Any]]:
    """Case/board fan RPM, if one is present (already free via psutil)."""

    try:
        fans = psutil.sensors_fans()
    except Exception as exc:  # pragma: no cover - depends on psutil support
        if logger:
            logger.debug("psutil fan query failed: %s", exc)
        return None

    if not fans:
        return None

    entries = []
    for name, readings in fans.items():
        for reading in readings:
            rpm = getattr(reading, "current", None)
            if rpm is None:
                continue
            entries.append({
                "label": getattr(reading, "label", None) or name,
                "rpm": rpm,
            })

    return entries or None


def _collect_rp1_voltages(logger) -> Optional[List[Dict[str, Any]]]:
    """RP1 (Pi 5 I/O controller) ADC channels, in millivolts.

    Exposed as plain labelled channels -- the rp1_adc hwmon driver doesn't
    publish per-channel in*_label files, so which physical rail each one
    reads isn't something we can state with confidence.
    """

    from pathlib import Path

    hwmon_root = Path("/sys/class/hwmon")
    if not hwmon_root.exists():
        return None

    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        name_path = hwmon_dir / "name"
        try:
            name = name_path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if name != "rp1_adc":
            continue

        channels = []
        for in_path in sorted(hwmon_dir.glob("in*_input")):
            value_mv = _coerce_int(_run_read(in_path))
            if value_mv is None:
                continue
            channel_match = re.match(r"in(\d+)_input$", in_path.name)
            channel_num = channel_match.group(1) if channel_match else in_path.name
            channels.append({
                "label": f"RP1 ADC channel {channel_num}",
                "millivolts": value_mv,
            })
        return channels or None

    return None


def _run_read(path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def collect_raspberry_pi_health(
    logger, platform_details: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Bundle every Pi-specific collector, or None on non-Pi hardware."""

    if not _is_raspberry_pi(platform_details):
        return None

    return {
        "throttle_status": _collect_throttle_status(logger),
        "bootloader": _collect_bootloader_status(logger),
        "fans": _collect_fan_status(logger),
        "rp1_voltages": _collect_rp1_voltages(logger),
    }
