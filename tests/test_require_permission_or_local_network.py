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

from __future__ import annotations

"""Tests for require_permission_or_local_network (app_core/auth/roles.py).

Reproduces the live bug this decorator fixes: /api/gpio/status is the
vfd_gpio_status default screen's data source (see the route's own
docstring, "...with summary data for OLED"), so
scripts.screen_renderer.ScreenRenderer must reach it unauthenticated from
localhost -- but it carried a plain @require_permission('gpio.view') with
no local-network exemption, so the screen renderer 401'd on the endpoint
continuously, confirmed live in eas-station-displays.service's own logs.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.auth import roles as roles_mod


@pytest.fixture
def rp_app(monkeypatch):
    """A minimal Flask app with one route gated by the decorator under
    test. get_current_user/has_permission and the lazily-imported
    app._is_local_network_client are all monkeypatched -- this exercises
    the decorator's own branching logic without booting the full app.py
    (and its DB/Redis/hardware-service dependency chain)."""
    app = Flask("rp-or-local-test")
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-not-for-production-use-only"

    @app.route("/protected")
    @roles_mod.require_permission_or_local_network("gpio.view")
    def protected():
        return "ok", 200

    return app


def _patch(monkeypatch, *, user, is_local, has_perm):
    monkeypatch.setattr(roles_mod, "get_current_user", lambda: user)
    monkeypatch.setattr(roles_mod, "has_permission", lambda perm: has_perm)

    # require_permission_or_local_network does `from app import
    # _is_local_network_client` lazily inside the decorated function --
    # inject a fake `app` module into sys.modules so that import resolves
    # to our stub instead of booting the real one.
    import types
    fake_app_module = types.ModuleType("app")
    fake_app_module._is_local_network_client = lambda addr: is_local
    monkeypatch.setitem(sys.modules, "app", fake_app_module)


def test_anonymous_local_caller_is_allowed_through(rp_app, monkeypatch):
    """The whole point of this decorator: an anonymous request from this
    box or its local network reaches the view, same as a route with no
    permission decorator at all."""
    _patch(monkeypatch, user=None, is_local=True, has_perm=False)
    client = rp_app.test_client()

    resp = client.get("/protected")

    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "ok"


def test_anonymous_remote_caller_is_denied(monkeypatch, rp_app):
    """An anonymous caller NOT on the local network must still be
    rejected -- this decorator only relaxes the check for the same
    local-network case LOCAL_API_GET_PATHS already covers, it doesn't
    make the route public."""
    _patch(monkeypatch, user=None, is_local=False, has_perm=False)
    client = rp_app.test_client()

    # Accept: application/json takes _build_login_redirect's clean JSON
    # branch instead of an HTML redirect -- avoids needing this minimal
    # test app to also define a real auth.login route.
    resp = client.get("/protected", headers={"Accept": "application/json"})

    assert resp.status_code == 401


def test_authenticated_user_without_permission_is_denied(monkeypatch, rp_app):
    """A signed-in session still gets the real permission check -- unlike
    a route with no decorator at all, this one must not let a logged-in
    user without gpio.view through just because they're also local."""
    _patch(monkeypatch, user=object(), is_local=True, has_perm=False)
    client = rp_app.test_client()

    resp = client.get("/protected", headers={"Accept": "application/json"})

    assert resp.status_code == 403


def test_authenticated_user_with_permission_is_allowed(monkeypatch, rp_app):
    _patch(monkeypatch, user=object(), is_local=False, has_perm=True)
    client = rp_app.test_client()

    resp = client.get("/protected")

    assert resp.status_code == 200


def test_stamps_eas_auth_requirement_for_api_reference_tooling():
    """The live /api-reference page reads this attribute to show a
    route's access requirement -- see app_core/api_reference.py."""
    app = Flask("stamp-test")

    @app.route("/x")
    @roles_mod.require_permission_or_local_network("gpio.view")
    def x():
        return "ok"

    view = app.view_functions["x"]
    assert view.eas_auth_requirement == {
        "mode": "single_or_local_network", "permissions": ("gpio.view",),
    }
