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

"""Tests for the shared outbound User-Agent helper.

Every outbound "health check" (the uptime heartbeat, Icecast connectivity
checks) used to go out with the bare python-requests default instead of
identifying the station -- this covers the fallback chain
(DB -> env var -> hardcoded default) and that the actual call sites route
their outbound requests through it rather than hardcoding a UA (or none).
"""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.http_defaults import get_default_user_agent


def _install_poller_settings(monkeypatch, settings):
    import app_core.models as models_module
    monkeypatch.setattr(
        models_module, "PollerSettings",
        SimpleNamespace(query=SimpleNamespace(first=lambda: settings)),
    )


def test_prefers_db_configured_value(monkeypatch):
    _install_poller_settings(monkeypatch, SimpleNamespace(noaa_user_agent="Custom Station UA/1.0"))
    monkeypatch.setenv("NOAA_USER_AGENT", "env-value-should-be-ignored")

    assert get_default_user_agent() == "Custom Station UA/1.0"


def test_falls_back_to_env_var_when_no_db_row(monkeypatch):
    _install_poller_settings(monkeypatch, None)
    monkeypatch.setenv("NOAA_USER_AGENT", "EnvConfigured/1.0")

    assert get_default_user_agent() == "EnvConfigured/1.0"


def test_falls_back_to_env_var_when_db_value_blank(monkeypatch):
    _install_poller_settings(monkeypatch, SimpleNamespace(noaa_user_agent=""))
    monkeypatch.setenv("NOAA_USER_AGENT", "EnvConfigured/1.0")

    assert get_default_user_agent() == "EnvConfigured/1.0"


def test_falls_back_to_hardcoded_default(monkeypatch):
    _install_poller_settings(monkeypatch, None)
    monkeypatch.delenv("NOAA_USER_AGENT", raising=False)

    result = get_default_user_agent()
    assert "EAS Station" in result
    assert "github.com/KR8MER/eas-station" in result


def test_db_lookup_failure_falls_back_gracefully(monkeypatch):
    """No app/request context, DB unreachable, etc. -- must never raise."""
    import app_core.models as models_module

    def _raise():
        raise RuntimeError("Working outside of application context.")

    monkeypatch.setattr(
        models_module, "PollerSettings",
        SimpleNamespace(query=SimpleNamespace(first=_raise)),
    )
    monkeypatch.setenv("NOAA_USER_AGENT", "EnvFallback/1.0")

    assert get_default_user_agent() == "EnvFallback/1.0"


# ---------------------------------------------------------------------------
# Call-site wiring: the actual outbound requests.get() calls pass the
# helper's value as the User-Agent header, rather than going out bare.
# ---------------------------------------------------------------------------


def test_heartbeat_ping_sends_user_agent(monkeypatch):
    import app_core.heartbeat_worker as heartbeat_module

    monkeypatch.setattr(
        "app_core.http_defaults.get_default_user_agent", lambda: "Test-Agent/1.0",
    )

    captured = {}

    class _FakeResponse:
        status_code = 200

    def fake_post(url, timeout=None, headers=None):
        captured['headers'] = headers
        return _FakeResponse()

    monkeypatch.setattr(heartbeat_module.requests, "post", fake_post)

    success, error = heartbeat_module.send_heartbeat_ping("https://example.test/ping")

    assert success is True
    assert captured['headers'] == {'User-Agent': 'Test-Agent/1.0'}
