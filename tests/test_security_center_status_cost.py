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

"""Opening the Security Center must not do privileged firewall work.

The fail2ban status read used to run ``import_ssh_bans`` and
``heal_firewall_bans`` inside the HTTP request. The second of those re-pushes
the entire ban list into the firewall with one ``sudo fail2ban-client set …
banip`` subprocess *per banned IP*, so after any fail2ban restart the first page
load paid for hundreds of privileged round trips before rendering. Both already
run on a 60-second background schedule (``app_core.fail2ban_sync``).
"""

import webapp.admin.fail2ban as f2b


def test_status_read_does_not_touch_the_firewall(monkeypatch):
    """_cached_status() reports state without importing or healing bans."""
    called = []

    monkeypatch.setattr(
        f2b, "import_ssh_bans", lambda: called.append("import_ssh_bans")
    )
    monkeypatch.setattr(
        f2b, "heal_firewall_bans", lambda: called.append("heal_firewall_bans")
    )
    monkeypatch.setattr(f2b, "_status", lambda: {"installed": False})

    f2b.invalidate_status_cache()
    assert f2b._cached_status() == {"installed": False}
    assert called == [], f"status read performed firewall mutations: {called}"


def test_status_is_cached_between_reads(monkeypatch):
    """Repeat reads inside the TTL reuse one snapshot.

    Each _status() call costs roughly a dozen privileged `fail2ban-client`
    subprocess round trips, and the Security Center polls it.
    """
    calls = []

    def fake_status():
        calls.append(1)
        return {"installed": True, "n": len(calls)}

    monkeypatch.setattr(f2b, "_status", fake_status)

    f2b.invalidate_status_cache()
    first = f2b._cached_status()
    second = f2b._cached_status()

    assert len(calls) == 1, "status was recomputed inside the cache TTL"
    assert first == second


def test_invalidation_forces_a_fresh_read(monkeypatch):
    """A mutating action must not leave the UI showing the pre-change snapshot."""
    calls = []

    def fake_status():
        calls.append(1)
        return {"n": len(calls)}

    monkeypatch.setattr(f2b, "_status", fake_status)

    f2b.invalidate_status_cache()
    assert f2b._cached_status() == {"n": 1}

    f2b.invalidate_status_cache()
    assert f2b._cached_status() == {"n": 2}


def test_background_sync_still_does_the_work(monkeypatch):
    """The mutating path moved to the scheduler — it must not have been dropped."""
    called = []

    monkeypatch.setattr(
        f2b, "import_ssh_bans", lambda: called.append("import_ssh_bans") or 0
    )
    monkeypatch.setattr(
        f2b, "heal_firewall_bans", lambda: called.append("heal_firewall_bans") or False
    )
    monkeypatch.setattr(f2b, "_status", lambda: {"ok": True})

    assert f2b.run_background_sync() == {"ok": True}
    assert called == ["import_ssh_bans", "heal_firewall_bans"]
