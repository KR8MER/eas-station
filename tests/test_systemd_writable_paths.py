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

"""Every sandboxed Python service must be able to write the shared log.

Under ``ProtectSystem=strict`` the whole filesystem is read-only except for
``ReadWritePaths``.  The poller listed only ``/tmp``, so its
``eas_station.log`` handler failed with EROFS on every start and its
broadcast WAV/text files under ``/opt/eas-station/static/eas_messages`` were
silently kept in the database only.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SYSTEMD_DIR = Path(__file__).resolve().parents[1] / "systemd"

# Units that run EAS Station Python code under ProtectSystem=strict and use
# the shared file log.  pgweb (a Go binary) and hwsetup (not strict) are out.
PYTHON_SERVICES = [
    "eas-station-audio.service",
    "eas-station-demod.service",
    "eas-station-displays.service",
    "eas-station-endec-feeds.service",
    "eas-station-gpio.service",
    "eas-station-gps.service",
    "eas-station-network.service",
    "eas-station-poller.service",
    "eas-station-web.service",
    "eas-station-zigbee.service",
]


def _writable_paths(unit: str) -> set:
    paths = set()
    for line in (SYSTEMD_DIR / unit).read_text().splitlines():
        line = line.strip()
        if line.startswith("ReadWritePaths="):
            paths.update(p.lstrip("-") for p in line.split("=", 1)[1].split())
    return paths


@pytest.mark.parametrize("unit", PYTHON_SERVICES)
def test_strict_service_can_write_log_and_install_dirs(unit):
    text = (SYSTEMD_DIR / unit).read_text()
    assert "ProtectSystem=strict" in text
    paths = _writable_paths(unit)
    assert "/var/log/eas-station" in paths, f"{unit} cannot write eas_station.log"
    assert "/opt/eas-station" in paths, f"{unit} cannot write under /opt/eas-station"
