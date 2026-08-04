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

"""Guard the systemd MemoryMax ceilings against unreachable values.

``MemoryMax=`` is a hard cgroup limit.  A unit whose Python process needs more
than the ceiling is OOM-killed by the kernel, and with ``Restart=always`` that
turns into a silent crash loop: ``systemctl is-enabled`` looks fine, the web UI
just reports the subsystem as "not reporting state", and nothing the service is
responsible for ever happens.

That is exactly how the GPIO relay stopped firing for automated RWTs and
forwarded alerts: ``eas-station-gpio`` is the only process allowed to claim the
relay lines (lgpio claims are exclusive per process), and it was capped at 128M
while needing roughly 240 MB — importing ``app_core.models`` transitively pulls
in the DSP stack (``app_utils.eas_decode`` -> ``eas_demod`` -> numba -> scipy
and numpy) before the service does any work at all.

These tests keep the ceilings honest.  If a service genuinely gets lighter,
lower the floor here deliberately — don't lower a unit's MemoryMax and leave
this file behind.
"""

import re
from pathlib import Path
from typing import Optional

import pytest

SYSTEMD_DIR = Path(__file__).resolve().parents[1] / "systemd"

#: Minimum ceiling (MiB) for units whose entry point imports app_core.models.
#: The measured import-time footprint is ~240 MB; 384 MiB leaves headroom for
#: query buffers and the controller's own state without being unbounded.
APP_IMPORT_FLOOR_MIB = 384

#: Units that import the full application model layer at startup.
APP_IMPORT_UNITS = [
    "eas-station-gpio.service",
    "eas-station-displays.service",
    "eas-station-gps.service",
    "eas-station-network.service",
    "eas-station-zigbee.service",
    "eas-station-endec-feeds.service",
]

_SUFFIX_MULTIPLIERS = {
    "": 1 / (1024 * 1024),  # bare bytes
    "K": 1 / 1024,
    "M": 1,
    "G": 1024,
}


def _parse_memory_max(unit_path: Path) -> Optional[float]:
    """Return the unit's MemoryMax in MiB, or ``None`` when unset."""
    value = None
    for line in unit_path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        match = re.fullmatch(r"MemoryMax=(\d+)([KMG]?)", stripped)
        if match:
            value = float(match.group(1)) * _SUFFIX_MULTIPLIERS[match.group(2)]
    return value


@pytest.mark.parametrize("unit_name", APP_IMPORT_UNITS)
def test_app_importing_units_have_reachable_memory_ceiling(unit_name):
    """Every model-importing unit must be allowed more memory than it needs."""
    unit_path = SYSTEMD_DIR / unit_name
    assert unit_path.exists(), f"missing unit file: {unit_path}"

    limit_mib = _parse_memory_max(unit_path)
    assert limit_mib is not None, (
        f"{unit_name} has no MemoryMax; either set one at or above "
        f"{APP_IMPORT_FLOOR_MIB}M or remove this unit from APP_IMPORT_UNITS"
    )
    assert limit_mib >= APP_IMPORT_FLOOR_MIB, (
        f"{unit_name} caps memory at {limit_mib:.0f}M, below the "
        f"{APP_IMPORT_FLOOR_MIB}M this service needs to start. The kernel will "
        f"OOM-kill it during import and Restart=always will hide that as a "
        f"crash loop."
    )


def test_gpio_unit_still_restarts_and_owns_the_relay_pins():
    """Sanity-check the GPIO unit's identity so the floor above stays relevant."""
    text = (SYSTEMD_DIR / "eas-station-gpio.service").read_text()
    assert "ExecStart=" in text and "services.gpio" in text
    assert "Restart=always" in text
