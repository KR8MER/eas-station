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

"""Tests for the live API Reference page.

There was previously no backend API reference at all -- docs/README.md
pointed at docs/frontend/JAVASCRIPT_API.md and labelled it "REST API
reference", but that file documents frontend JS globals, not the ~300
/api/* Flask routes. This computes the reference from the live
app.url_map on every request instead of a hand-maintained (and
immediately stale) file, the same idiom app_utils/repo_stats already
uses for its own route count.
"""

from pathlib import Path

import pytest
from flask import Flask, jsonify

from app_utils.api_reference import compute_api_reference

ROOT = Path(__file__).resolve().parent.parent


def _build_test_app() -> Flask:
    app = Flask('api-reference-test')

    @app.route('/api/plain')
    def plain():
        """A plain, undecorated route."""
        return jsonify({})

    @app.route('/api/no-docstring')
    def no_docstring():
        return jsonify({})

    @app.route('/not-api/thing')
    def not_api():
        """Should be excluded -- not under /api/."""
        return jsonify({})

    @app.route('/api/auth-only')
    def auth_only():
        """Requires a logged-in session only."""
        return jsonify({})
    auth_only.eas_auth_requirement = {'mode': 'auth_only', 'permissions': ()}

    @app.route('/api/permission-gated', methods=['POST'])
    def permission_gated():
        """Requires a specific permission.

        This second line must not leak into the one-line summary.
        """
        return jsonify({})
    permission_gated.eas_auth_requirement = {
        'mode': 'single', 'permissions': ('eas.cancel',),
    }

    return app


def test_excludes_non_api_and_static_routes():
    ref = compute_api_reference(_build_test_app())
    paths = {r['path'] for group in ref['groups'].values() for r in group}
    assert '/not-api/thing' not in paths
    assert not any(p.startswith('/static') for p in paths)


def test_includes_api_routes_with_methods_and_summary():
    ref = compute_api_reference(_build_test_app())
    entries = {r['path']: r for group in ref['groups'].values() for r in group}
    assert 'GET' in entries['/api/plain']['methods']
    assert entries['/api/plain']['summary'] == 'A plain, undecorated route.'


def test_summary_is_only_the_first_docstring_line():
    ref = compute_api_reference(_build_test_app())
    entries = {r['path']: r for group in ref['groups'].values() for r in group}
    assert entries['/api/permission-gated']['summary'] == 'Requires a specific permission.'
    assert 'second line' in entries['/api/permission-gated']['docstring']


def test_undocumented_route_has_empty_summary():
    ref = compute_api_reference(_build_test_app())
    entries = {r['path']: r for group in ref['groups'].values() for r in group}
    assert entries['/api/no-docstring']['summary'] == ''


def test_auth_requirement_read_from_view_function_attribute():
    ref = compute_api_reference(_build_test_app())
    entries = {r['path']: r for group in ref['groups'].values() for r in group}
    assert entries['/api/auth-only']['auth'] == {'mode': 'auth_only', 'permissions': ()}
    assert entries['/api/permission-gated']['auth']['permissions'] == ('eas.cancel',)
    assert entries['/api/plain']['auth'] is None


def test_totals_are_consistent_with_the_group_contents():
    ref = compute_api_reference(_build_test_app())
    all_routes = [r for group in ref['groups'].values() for r in group]
    assert ref['total'] == len(all_routes) == 4
    assert ref['documented'] == sum(1 for r in all_routes if r['summary'])
    assert ref['gated'] == sum(1 for r in all_routes if r['auth'])
    assert ref['documented'] == 3  # all but /api/no-docstring
    assert ref['gated'] == 2  # auth-only + permission-gated


def test_result_is_json_serialisable():
    import json

    ref = compute_api_reference(_build_test_app())
    round_tripped = json.loads(json.dumps(ref))
    assert round_tripped['total'] == ref['total']


# ---------------------------------------------------------------------------
# Decorator markers -- app_core.auth.decorators / app_core.auth.roles
# ---------------------------------------------------------------------------

def test_require_auth_stamps_auth_only_marker(monkeypatch):
    from app_core.auth import decorators

    monkeypatch.setattr(decorators, 'get_current_user', lambda: None)

    @decorators.require_auth
    def view():
        """doc"""
        return 'ok'

    assert view.eas_auth_requirement == {'mode': 'auth_only', 'permissions': ()}


def test_require_role_stamps_role_marker(monkeypatch):
    from app_core.auth import decorators

    monkeypatch.setattr(decorators, 'get_current_user', lambda: None)

    @decorators.require_role('Admin', 'Operator')
    def view():
        """doc"""
        return 'ok'

    assert view.eas_auth_requirement == {
        'mode': 'role', 'permissions': (), 'roles': ('Admin', 'Operator'),
    }


def test_require_permission_stamps_single_marker(monkeypatch):
    from app_core.auth import roles

    monkeypatch.setattr(roles, 'has_permission', lambda name: True)

    @roles.require_permission('eas.cancel')
    def view():
        """doc"""
        return 'ok'

    assert view.eas_auth_requirement == {'mode': 'single', 'permissions': ('eas.cancel',)}


def test_require_any_permission_stamps_any_marker():
    from app_core.auth import roles

    @roles.require_any_permission('alerts.view', 'alerts.create')
    def view():
        """doc"""
        return 'ok'

    assert view.eas_auth_requirement == {
        'mode': 'any', 'permissions': ('alerts.view', 'alerts.create'),
    }


def test_require_all_permissions_stamps_all_marker():
    from app_core.auth import roles

    @roles.require_all_permissions('alerts.delete', 'system.configure')
    def view():
        """doc"""
        return 'ok'

    assert view.eas_auth_requirement == {
        'mode': 'all', 'permissions': ('alerts.delete', 'system.configure'),
    }


def test_require_permission_or_setup_mode_stamps_marker():
    from webapp.admin.environment import require_permission_or_setup_mode

    @require_permission_or_setup_mode('system.configure')
    def view():
        """doc"""
        return 'ok'

    assert view.eas_auth_requirement == {
        'mode': 'single_or_setup_mode', 'permissions': ('system.configure',),
    }


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_api_reference_is_registered_in_navigation():
    from webapp.navigation import registry

    hrefs = []
    for section in registry.NAVIGATION:
        for group in section.groups:
            for item in group.items:
                hrefs.append(item.href)

    assert '/api-reference' in hrefs, 'the page must be reachable from the nav registry'


def test_page_template_extends_base():
    page = (ROOT / 'templates' / 'api_reference.html').read_text(encoding='utf-8')
    content = (ROOT / 'templates' / 'api_reference' / '_content.html').read_text(encoding='utf-8')

    assert '{% extends "base.html" %}' in page
    assert "{% include 'components/page_header.html' %}" in content
    assert '{% block scripts %}' in page, 'page JS must use the real block name'
    assert '{% block extra_js %}' not in page


def test_docs_readme_no_longer_mislabels_the_js_globals_doc_as_rest_api():
    readme = (ROOT / 'docs' / 'README.md').read_text(encoding='utf-8')
    assert 'JavaScript API](frontend/JAVASCRIPT_API.md) | REST API reference' not in readme
    assert '/api-reference' in readme

# End-to-end rendering against the real app (real url_map, real Postgres +
# PostGIS, a real logged-in AdminUser session) was verified manually rather
# than committed here: this suite's shared `app`/`app_client` fixture
# (tests/conftest.py) hardcodes `DATABASE_URL=sqlite:///:memory:`, and
# initialize_database() creates several JSONB columns SQLite cannot render
# -- the same reason tests/test_support_smoke.py's one app_client-based test
# is a pre-registered known failure, and why /repo-stats (the page this one
# copies its idiom from) has no app_client render test either. Against a
# real Postgres 17 + PostGIS instance with a real AdminUser session, the
# live page returned 259 /api/* routes (231 documented, 182 access-gated),
# correctly listing itself and /api/repo-stats.
