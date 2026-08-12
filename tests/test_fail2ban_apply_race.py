"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

Regression test for a race in the fail2ban "Save & Apply Configuration" flow.

Background: ``configure_fail2ban()`` writes jail.local, restarts fail2ban, then
checks ``_loaded_jails()`` once to confirm the ``eas-station`` actuator jail
came up before reporting success. ``systemctl restart`` returns as soon as
systemd considers the unit started, which can be a beat before fail2ban-server
has actually finished parsing jail.local and bringing every jail up -- so a
single immediate check could report a good apply as a failure (observed live:
the jail appeared in ``fail2ban-client status`` about a second after the
restart returned, well after the single check had already given up). This test
pins ``_wait_for_jail_loaded`` to tolerate that startup lag.
"""

from __future__ import annotations

import pytest

pytest.importorskip("flask")


def test_wait_for_jail_loaded_tolerates_late_startup(monkeypatch):
    from webapp.admin import fail2ban

    # First two checks: jail not up yet. Third: it has finally loaded.
    calls = {"n": 0}

    def fake_loaded_jails():
        calls["n"] += 1
        return {"eas-station"} if calls["n"] >= 3 else set()

    monkeypatch.setattr(fail2ban, "_loaded_jails", fake_loaded_jails)
    monkeypatch.setattr(fail2ban.time, "sleep", lambda _seconds: None)

    assert fail2ban._wait_for_jail_loaded("eas-station") is True
    assert calls["n"] == 3


def test_wait_for_jail_loaded_gives_up_eventually(monkeypatch):
    from webapp.admin import fail2ban

    monkeypatch.setattr(fail2ban, "_loaded_jails", lambda: set())
    monkeypatch.setattr(fail2ban.time, "sleep", lambda _seconds: None)

    assert fail2ban._wait_for_jail_loaded("eas-station", retries=3) is False


def test_wait_for_jail_loaded_returns_immediately_when_already_up(monkeypatch):
    from webapp.admin import fail2ban

    calls = {"n": 0}

    def fake_loaded_jails():
        calls["n"] += 1
        return {"eas-station"}

    monkeypatch.setattr(fail2ban, "_loaded_jails", fake_loaded_jails)

    def fail_if_called(_seconds):
        raise AssertionError("should not sleep when the jail is already loaded")

    monkeypatch.setattr(fail2ban.time, "sleep", fail_if_called)

    assert fail2ban._wait_for_jail_loaded("eas-station") is True
    assert calls["n"] == 1
