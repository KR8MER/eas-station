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

"""The Services diagnostic must not fail units it could not actually query.

``check_services_running()`` shells out to ``systemctl is-active`` per unit.
When systemd cannot be reached, every one of those probes returns an empty
state, which the per-unit branch reported as a hard failure — so the
diagnostics page showed every service red regardless of whether it was
running. Testing for the presence of the ``systemctl`` binary is not enough to
detect this: the binary ships in plenty of images where the bus does not, and
there it exits non-zero on every query.
"""

import pytest

import webapp.routes_diagnostics as diagnostics


@pytest.fixture
def fake_systemctl(monkeypatch):
    """Drive ``_run_command`` with scripted systemctl responses."""

    def install(responses, default=(1, "", "")):
        def fake_run(cmd, timeout=15):
            for prefix, response in responses:
                if cmd[: len(prefix)] == prefix:
                    return response
            return default

        monkeypatch.setattr(diagnostics, "_run_command", fake_run, raising=True)

    return install


def test_unreachable_bus_reports_info_not_failures(fake_systemctl):
    """systemd present but not PID 1: report once, fail nothing."""
    fake_systemctl(
        [
            (
                ["systemctl", "is-system-running"],
                (
                    1,
                    "offline\n",
                    "System has not been booted with systemd as init system "
                    "(PID 1). Can't operate.\n",
                ),
            )
        ]
    )

    result = diagnostics.check_services_running()

    assert result["failed"] == [], (
        "units that could not be queried must not be reported as failed"
    )
    assert result["passed"] == []
    assert len(result["info"]) == 1
    assert "Cannot verify service state" in result["info"][0]


def test_missing_systemctl_reports_info_not_failures(fake_systemctl):
    """``_run_command`` returns 127 when the binary is absent."""
    fake_systemctl([(["systemctl", "is-system-running"], (127, "", "not found"))])

    result = diagnostics.check_services_running()

    assert result["failed"] == []
    assert any("not installed" in message for message in result["info"])


def test_active_units_still_pass(fake_systemctl):
    """A healthy host must be unaffected by the availability probe."""
    fake_systemctl(
        [
            (["systemctl", "is-system-running"], (0, "running\n", "")),
            (["systemctl", "is-active"], (0, "active\n", "")),
        ]
    )

    result = diagnostics.check_services_running()

    assert result["failed"] == []
    assert result["passed"], "active units should be reported as passing"


def test_degraded_host_is_still_queried(fake_systemctl):
    """``is-system-running`` exits non-zero for 'degraded' — a usable state.

    Keying the probe off the exit code alone would skip the per-unit checks on
    exactly the hosts that have a failed unit worth reporting.
    """
    fake_systemctl(
        [
            (["systemctl", "is-system-running"], (1, "degraded\n", "")),
            (["systemctl", "is-active", "eas-station.target"], (1, "inactive\n", "")),
            (["systemctl", "is-active"], (3, "failed\n", "")),
            (["systemctl", "show"], (0, "loaded\n", "")),
        ]
    )

    result = diagnostics.check_services_running()

    assert result["failed"], "a genuinely failed unit must still be reported"
    assert not any(
        "Cannot verify service state" in message for message in result["info"]
    )


def test_uninstalled_unit_warns_rather_than_fails(fake_systemctl):
    fake_systemctl(
        [
            (["systemctl", "is-system-running"], (0, "running\n", "")),
            (["systemctl", "is-active", "eas-station.target"], (0, "active\n", "")),
            (["systemctl", "is-active"], (3, "inactive\n", "")),
            (["systemctl", "show"], (0, "not-found\n", "")),
        ]
    )

    result = diagnostics.check_services_running()

    assert result["failed"] == []
    assert any("not installed" in message for message in result["warnings"])
