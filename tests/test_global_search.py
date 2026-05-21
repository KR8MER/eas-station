"""Tests for the navbar global search router.

Verifies that the ``/search?q=…`` endpoint routes operators to the
right destination based on what they typed: exact identifier → trail,
numeric DB id → alert detail, partial match → disambiguation page or
single-match trail, otherwise fall through to /logs text search.

The router queries multiple tables, several of which use PostGIS /
JSONB columns that SQLite can't realize.  These tests therefore set up
just the tables the search code reads from and mock the rest by making
sure SQLAlchemy queries return empty lists when the table is absent.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")


def _build_app():
    """Minimal Flask app with the global_search route registered.

    We avoid spinning up the full webapp.register_routes because that
    pulls in Flask-Caching, Flask-SocketIO, and the entire admin
    blueprint tree — none of which are exercised here.
    """
    import logging
    from flask import Flask
    from app_core.extensions import db

    app = Flask(__name__, template_folder='/home/user/eas-station/templates')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'test'
    db.init_app(app)

    # Importing models triggers listener registration; it also imports
    # the EASMessage etc. classes we need to query.
    from app_core import models  # noqa: F401

    # Stub the public_index endpoint so url_for in the route doesn't
    # blow up on the empty-query branch.
    @app.route('/')
    def public_index():
        return 'home'

    # base.html and the navbar partial reach for several context
    # helpers that production wires up via Flask-WTF, Flask-Login, and
    # the auth blueprint.  Stub the minimum surface area so the
    # template can render without those packages.
    class _StubUser:
        is_authenticated = False
        username = ''
    @app.context_processor
    def _inject_test_stubs():
        return {
            'csrf_token': '',
            'has_permission': lambda *_args, **_kw: False,
            'current_user': _StubUser(),
            'is_authenticated': False,
            'can_view_alerts': False,
            'can_manage_receivers': False,
            'can_view_logs': False,
            'can_manage_config': False,
            'can_manage_analytics': False,
            'can_export_alerts': False,
            'show_settings_dropdown': False,
        }

    # Import the module by path to avoid pulling in webapp/__init__'s
    # full route-registration tree (Flask-SocketIO, openpyxl, etc).
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'global_search_under_test',
        '/home/user/eas-station/webapp/routes/global_search.py',
    )
    global_search = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(global_search)
    global_search.register(app, logging.getLogger('test'))
    return app, db, global_search


def test_empty_query_redirects_home():
    app, _, global_search = _build_app()
    client = app.test_client()
    resp = client.get('/search?q=')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/')


def test_unknown_identifier_falls_through_to_logs(monkeypatch):
    """Anything that doesn't match an alert should bounce to
    /logs?type=all&search=… so the operator still finds something."""
    app, _, global_search = _build_app()

    # Make every DB query return empty/None so no match is found.

    monkeypatch.setattr(global_search, '_exact_alert_trail_redirect', lambda q: None)
    monkeypatch.setattr(global_search, '_numeric_alert_detail_redirect', lambda q: None)
    monkeypatch.setattr(global_search, '_partial_identifier_matches', lambda q, limit=10: [])

    resp = app.test_client().get('/search?q=nothing-here')
    assert resp.status_code == 302
    loc = resp.headers['Location']
    assert '/logs' in loc
    assert 'search=nothing-here' in loc
    assert 'type=all' in loc


def test_exact_identifier_routes_to_trail(monkeypatch):
    """When the query exactly matches a CAP identifier we shortcut
    straight to /alerts/<id>/trail without showing a disambiguation."""
    from flask import redirect
    app, _, global_search = _build_app()

    target_id = 'NWS-IPAWS-2026-001'
    monkeypatch.setattr(
        global_search,
        '_exact_alert_trail_redirect',
        lambda q: redirect(f'/alerts/{q}/trail', code=302) if q == target_id else None,
    )

    resp = app.test_client().get(f'/search?q={target_id}')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'/alerts/{target_id}/trail')


def test_numeric_query_routes_to_alert_detail(monkeypatch):
    """A purely numeric query should be treated as a CAPAlert row id."""
    from flask import redirect
    app, _, global_search = _build_app()

    monkeypatch.setattr(global_search, '_exact_alert_trail_redirect', lambda q: None)
    monkeypatch.setattr(
        global_search,
        '_numeric_alert_detail_redirect',
        lambda q: redirect(f'/alerts/{q}', code=302) if q.isdigit() else None,
    )

    resp = app.test_client().get('/search?q=42')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/alerts/42')


def test_single_partial_match_jumps_to_trail(monkeypatch):
    """If exactly one alert's identifier contains the query as a
    substring, route straight to its trail (rare to want a
    disambiguation page for one option)."""
    app, _, global_search = _build_app()

    monkeypatch.setattr(global_search, '_exact_alert_trail_redirect', lambda q: None)
    monkeypatch.setattr(global_search, '_numeric_alert_detail_redirect', lambda q: None)
    monkeypatch.setattr(
        global_search,
        '_partial_identifier_matches',
        lambda q, limit=10: [{
            'identifier': 'NWS-IPAWS-2026-XYZ-' + q,
            'label': 'Severe Thunderstorm Warning',
            'sent': datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc),
            'kind': 'cap',
        }],
    )

    resp = app.test_client().get('/search?q=2026')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/alerts/NWS-IPAWS-2026-XYZ-2026/trail')


def test_multiple_partial_matches_render_disambiguation_page(monkeypatch):
    """Two or more substring matches → render the disambiguation page
    with both options.  We assert on what gets passed to the template
    rather than rendering the full base.html chain (which pulls in
    Flask-WTF/Flask-Login dependencies that aren't installed in the
    test environment)."""
    app, _, global_search = _build_app()

    monkeypatch.setattr(global_search, '_exact_alert_trail_redirect', lambda q: None)
    monkeypatch.setattr(global_search, '_numeric_alert_detail_redirect', lambda q: None)
    monkeypatch.setattr(
        global_search,
        '_partial_identifier_matches',
        lambda q, limit=10: [
            {'identifier': 'NWS-A-' + q, 'label': 'A', 'sent': None, 'kind': 'cap'},
            {'identifier': 'NWS-B-' + q, 'label': 'B', 'sent': None, 'kind': 'cap'},
        ],
    )

    captured = {}

    def fake_render(template_name, **ctx):
        captured['template'] = template_name
        captured['ctx'] = ctx
        return 'rendered'

    monkeypatch.setattr(global_search, 'render_template', fake_render)

    resp = app.test_client().get('/search?q=storm')
    assert resp.status_code == 200
    assert captured['template'] == 'search/results.html'
    assert captured['ctx']['query'] == 'storm'
    assert len(captured['ctx']['matches']) == 2
    identifiers = [m['identifier'] for m in captured['ctx']['matches']]
    assert 'NWS-A-storm' in identifiers
    assert 'NWS-B-storm' in identifiers
    assert 'search=storm' in captured['ctx']['logs_fallback_url']


def test_long_query_is_truncated(monkeypatch):
    """A pasted log line shouldn't blow up — the query is capped."""
    app, _, global_search = _build_app()

    seen = []
    monkeypatch.setattr(
        global_search, '_exact_alert_trail_redirect',
        lambda q: seen.append(q) or None,
    )
    monkeypatch.setattr(global_search, '_numeric_alert_detail_redirect', lambda q: None)
    monkeypatch.setattr(global_search, '_partial_identifier_matches', lambda q, limit=10: [])

    long_q = 'x' * 1000
    app.test_client().get(f'/search?q={long_q}')
    assert seen, "exact-match lookup should have been called"
    assert len(seen[0]) <= 255, f"query not truncated: {len(seen[0])} chars"
