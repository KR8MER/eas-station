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

"""Real-time clock status."""

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..time import UTC_TZ
from .common import _safe_int, _safe_read_text


def _collect_rtc_status(logger) -> Dict[str, Any]:
    """Inspect any battery-backed real-time clock exposed via ``/sys/class/rtc``.

    Targets the on-board RTC of the Uputronics Raspberry Pi GPS/RTC Expansion
    Board — DS3231 at I²C ``0x68`` on older revisions (``dtoverlay=i2c-rtc,ds3231``)
    and RV-3028-C7 at I²C ``0x52`` on current revisions
    (``dtoverlay=i2c-rtc,rv3028``) — but works for any Linux RTC. All reads
    come from sysfs — ``hwclock`` is never invoked, so the function is safe
    to run without root, never blocks, and does not depend on the
    ``util-linux-extra`` package being installed.

    Returns a best-effort dict that is always safe to serialise. When no RTC
    is present the dict will contain ``available=False`` so the health page
    can simply omit the section.
    """
    result: Dict[str, Any] = {"available": False}
    try:
        rtc_root = Path("/sys/class/rtc/rtc0")
        if not rtc_root.exists():
            result["status"] = "not_present"
            return result

        result["available"] = True
        result["device"] = "/dev/rtc0"
        result["sysfs_path"] = str(rtc_root)

        name = _safe_read_text(rtc_root / "name")
        if name:
            # The kernel reports e.g. "rtc-ds3231 1-0068" for the DS3231 driver
            # bound on I²C bus 1 address 0x68, or "rtc-rv3028 1-0052" for the
            # RV-3028-C7 used on current Uputronics boards. Normalise for
            # downstream UI.
            result["name"] = name
            lowered = name.lower()
            result["is_ds3231"] = "ds3231" in lowered
            result["is_rv3028"] = "rv3028" in lowered
            result["is_battery_backed"] = (
                result["is_ds3231"]
                or result["is_rv3028"]
                or "ds1307" in lowered
                or "pcf85" in lowered
            )

        # Current RTC time. ``since_epoch`` is exported in seconds (UTC) and
        # is the most reliable source — the textual ``date``/``time`` files
        # are local-time on some kernels.
        since_epoch = _safe_int(_safe_read_text(rtc_root / "since_epoch"))
        system_epoch = time.time()
        result["system_time_iso"] = datetime.fromtimestamp(system_epoch, UTC_TZ).isoformat()

        if since_epoch is not None and since_epoch > 0:
            # Sanity-clip against absurd values (e.g. driver returned 0).
            result["rtc_epoch"] = since_epoch
            result["rtc_time_iso"] = datetime.fromtimestamp(since_epoch, UTC_TZ).isoformat()
            drift = float(since_epoch) - float(system_epoch)
            result["drift_seconds"] = drift
            abs_drift = abs(drift)
            if abs_drift < 2.0:
                result["drift_status"] = "in_sync"
            elif abs_drift < 60.0:
                result["drift_status"] = "minor"
            elif abs_drift < 3600.0:
                result["drift_status"] = "moderate"
            else:
                # Large drift after a power cycle is the classic "RTC battery
                # failed and the clock reset" symptom on both the DS3231 and
                # the RV-3028-C7.
                result["drift_status"] = "severe"
        else:
            # An unreadable ``since_epoch`` typically means the OSF
            # (Oscillator Stop Flag) tripped — i.e. the backup battery is
            # exhausted and the chip lost time entirely.
            result["drift_status"] = "unreadable"

        # The DS3231 driver also exposes its die temperature via hwmon. This
        # is a useful side-signal because the battery-backup voltage is not
        # surfaced via sysfs; an unusually warm reading (>60 °C) can indicate
        # the part is being heated by an adjacent regulator.
        for hwmon_dir in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            hwmon_name = _safe_read_text(hwmon_dir / "name")
            if not hwmon_name or "ds3231" not in hwmon_name.lower():
                continue
            raw = _safe_read_text(hwmon_dir / "temp1_input")
            milli = _safe_int(raw)
            if milli is not None:
                result["temperature_c"] = round(milli / 1000.0, 1)
            break

        return result
    except Exception as exc:
        if logger:
            logger.debug("Failed to read RTC status from sysfs: %s", exc)
        result["status"] = "error"
        result["error"] = str(exc)
        return result
