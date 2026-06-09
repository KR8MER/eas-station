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

"""Authorization regression tests for the web setup wizard routes.

The setup wizard rewrites the .env file and can expose secrets (SECRET_KEY,
database credentials). Outside of first-run bootstrap it must be restricted to
administrators holding the ``system.configure`` permission -- a plain signed-in
account (demo/viewer/operator) must NOT be able to reach it.
"""

import logging
from types import SimpleNamespace

import pytest
from flask import Flask, g

import webapp.routes_setup as routes_setup


def _make_app(monkeypatch, *, setup_mode, user, has_perm):
    """Build a minimal app with routes_setup registered and auth state stubbed."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["SETUP_MODE"] = setup_mode
    app.config["SETUP_MODE_REASONS"] = ()

    # Control permission resolution deterministically; the real implementation
    # walks the user's role/permission graph, which we exercise elsewhere.
    monkeypatch.setattr(routes_setup, "has_permission", lambda perm, u=None: has_perm)

    # Provide the redirect targets the wizard references on denial so url_for()
    # can build them in this stripped-down app.
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.add_url_rule("/admin", endpoint="dashboard.admin", view_func=lambda: "admin")

    @app.before_request
    def _inject_user():
        g.current_user = user

    routes_setup.register(app, logging.getLogger("setup-authz-test"))
    return app


def _admin():
    return SimpleNamespace(
        id=1, is_authenticated=True, is_active=True,
        role=SimpleNamespace(name="admin"),
    )


def _demo():
    return SimpleNamespace(
        id=2, is_authenticated=True, is_active=True,
        role=SimpleNamespace(name="demo"),
    )


# --- The vulnerability: a signed-in non-admin must be blocked --------------

def test_non_admin_denied_generate_secret(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=False, user=_demo(), has_perm=False)
    resp = app.test_client().post("/setup/generate-secret")
    assert resp.status_code == 403
    assert b"secret_key" not in resp.data


def test_non_admin_denied_upload_env(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=False, user=_demo(), has_perm=False)
    # No multipart payload: if auth were bypassed we'd get a 400 instead of 403.
    resp = app.test_client().post("/setup/upload-env")
    assert resp.status_code == 403


def test_non_admin_denied_view_env(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=False, user=_demo(), has_perm=False)
    resp = app.test_client().get("/setup/view-env")
    # HTML route: redirected away from the secret-bearing page.
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]


def test_non_admin_denied_setup_get(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=False, user=_demo(), has_perm=False)
    resp = app.test_client().get("/setup")
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]


def test_non_admin_denied_fips_helper(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=False, user=_demo(), has_perm=False)
    resp = app.test_client().get("/setup/get-states")
    assert resp.status_code == 403


# --- Anonymous users are redirected to login (not silently allowed) --------

def test_anonymous_redirected_to_login(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=False, user=None, has_perm=False)
    resp = app.test_client().get("/setup")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_anonymous_json_endpoint_401(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=False, user=None, has_perm=False)
    resp = app.test_client().post("/setup/generate-secret")
    assert resp.status_code == 401


# --- Admins (system.configure) retain access -------------------------------

def test_admin_allowed_generate_secret(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=False, user=_admin(), has_perm=True)
    resp = app.test_client().post("/setup/generate-secret")
    assert resp.status_code == 200
    assert "secret_key" in resp.get_json()


# --- Bootstrap: first-run setup mode stays open without auth ---------------

def test_setup_mode_allows_unauthenticated_bootstrap(monkeypatch):
    app = _make_app(monkeypatch, setup_mode=True, user=None, has_perm=False)
    resp = app.test_client().post("/setup/generate-secret")
    assert resp.status_code == 200
    assert "secret_key" in resp.get_json()
