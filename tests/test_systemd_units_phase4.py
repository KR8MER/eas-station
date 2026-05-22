"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Smoke tests for the Phase 4 hardware-subsystem systemd units.

Phase 4 of the hardware_service.py split replaced the monolithic
``eas-station-hardware.service`` with five per-subsystem units bundled
under ``eas-station-hardware.target``.  These tests parse each unit's
text file and assert the invariants that have to hold for the units to
actually run on a host:

  * ExecStart calls ``python -m services.<subsystem>``
  * EnvironmentFile=/opt/eas-station/.env is loaded
  * glibc malloc tuning (MALLOC_ARENA_MAX=2, MALLOC_TRIM_THRESHOLD_=131072)
    is pinned so RSS stays honest with multi-threaded workers
  * The target's Wants= and After= each list all five subsystem units
    so a ``systemctl restart eas-station-hardware.target`` bounces
    every subprocess.
"""

import re
from pathlib import Path

import pytest

SUBSYSTEMS = ["network", "zigbee", "gps", "displays", "gpio"]
SYSTEMD_DIR = Path(__file__).resolve().parents[1] / "systemd"


def _read_unit(name: str) -> str:
    path = SYSTEMD_DIR / name
    assert path.is_file(), f"Expected systemd unit at {path}"
    return path.read_text(encoding="utf-8")


def _collapse_continuations(text: str) -> str:
    """Join lines ending with ``\\`` so multi-line directives parse cleanly."""
    return re.sub(r"\\\s*\n\s*", " ", text)


@pytest.mark.parametrize("subsystem", SUBSYSTEMS)
def test_unit_execstart_runs_subsystem_module(subsystem: str) -> None:
    text = _read_unit(f"eas-station-{subsystem}.service")
    pattern = rf"^ExecStart=\S*python\S*\s+-m\s+services\.{subsystem}\b"
    assert re.search(pattern, text, re.MULTILINE), (
        f"eas-station-{subsystem}.service must ExecStart `python -m services.{subsystem}`"
    )


@pytest.mark.parametrize("subsystem", SUBSYSTEMS)
def test_unit_loads_env_file(subsystem: str) -> None:
    text = _read_unit(f"eas-station-{subsystem}.service")
    assert "EnvironmentFile=/opt/eas-station/.env" in text, (
        f"eas-station-{subsystem}.service must load /opt/eas-station/.env"
    )


@pytest.mark.parametrize("subsystem", SUBSYSTEMS)
def test_unit_pins_glibc_malloc_tuning(subsystem: str) -> None:
    text = _read_unit(f"eas-station-{subsystem}.service")
    # Accept either Environment="KEY=VAL" or Environment=KEY=VAL (both legal).
    assert re.search(r'^Environment=["]?MALLOC_ARENA_MAX=2["]?\s*$', text, re.MULTILINE), (
        f"eas-station-{subsystem}.service must pin MALLOC_ARENA_MAX=2"
    )
    assert re.search(
        r'^Environment=["]?MALLOC_TRIM_THRESHOLD_=131072["]?\s*$',
        text,
        re.MULTILINE,
    ), (
        f"eas-station-{subsystem}.service must pin MALLOC_TRIM_THRESHOLD_=131072"
    )


def test_hardware_target_wants_and_orders_every_subsystem() -> None:
    text = _collapse_continuations(_read_unit("eas-station-hardware.target"))

    wants_match = re.search(r"^Wants=(.+)$", text, re.MULTILINE)
    after_match = re.search(r"^After=(.+)$", text, re.MULTILINE)
    assert wants_match, "eas-station-hardware.target must declare Wants="
    assert after_match, "eas-station-hardware.target must declare After="

    wants_units = set(wants_match.group(1).split())
    after_units = set(after_match.group(1).split())

    for subsystem in SUBSYSTEMS:
        unit = f"eas-station-{subsystem}.service"
        assert unit in wants_units, f"target Wants= must include {unit}"
        assert unit in after_units, f"target After= must include {unit}"
