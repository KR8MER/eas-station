"""Small sysfs probes used by the GPS manager.

Both functions read a path off ``/sys`` and swallow the failure, returning
``None`` when the file is absent or unreadable. Extracted verbatim from
``GPSManager``, where neither touched ``self``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

def read_cpu_temp_c() -> Optional[float]:
    """Best-effort host SoC temperature in °C from sysfs.

    Prefers a thermal zone whose type mentions the CPU/SoC (covers
    the Pi's ``cpu-thermal`` and x86's ``x86_pkg_temp``), falling
    back to the first zone present.  Returns ``None`` on hosts
    without a thermal zone (containers, some VMs) or on implausible
    readings so a broken sensor can't poison the trend archive.
    """
    try:
        from pathlib import Path
        zones = sorted(Path("/sys/class/thermal").glob("thermal_zone*"))
        chosen = None
        for zone in zones:
            try:
                ztype = (zone / "type").read_text().strip().lower()
            except OSError:
                continue
            if "cpu" in ztype or "soc" in ztype or "pkg" in ztype:
                chosen = zone
                break
        if chosen is None and zones:
            chosen = zones[0]
        if chosen is None:
            return None
        val = float((chosen / "temp").read_text().strip()) / 1000.0
        if -40.0 <= val <= 150.0:
            return round(val, 1)
    except Exception:
        pass
    return None

def safe_read(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except Exception:
        return None
