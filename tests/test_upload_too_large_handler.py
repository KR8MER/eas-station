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

"""Regression tests for the app-level 413 (Request Entity Too Large) handler.

nginx's own client_max_body_size rejection doesn't render a custom page over
HTTP/2 -- a documented nginx limitation where the oversized-body check
happens at the protocol/framing layer, bypassing error_page/location
entirely. Confirmed live: a 110 MB multipart upload over forced HTTP/1.1
correctly rendered static/errors/upload-too-large.html, but the same
request negotiated as HTTP/2 (nginx's default for HTTPS, and what most
browsers prefer) got nginx's bare, unstyled stock 413 page instead.

Fixed by enforcing the real limit at the Flask/WSGI layer instead
(MAX_CONTENT_LENGTH in app.py) -- a normal application response is
unaffected by that HTTP/2 quirk regardless of protocol, since it isn't an
early protocol-level rejection. nginx's own client_max_body_size is kept
higher as a hard backstop (see config/nginx-eas-station.conf), so this
Flask-level page is what real users on any protocol actually see.
"""

import pytest

pytestmark = pytest.mark.unit


def test_max_content_length_is_configured(app):
    assert app.config.get('MAX_CONTENT_LENGTH'), (
        'MAX_CONTENT_LENGTH must be set so Flask itself enforces an upload '
        'limit -- see the comment on it in app.py for why relying on '
        "nginx's client_max_body_size alone isn't sufficient (HTTP/2)."
    )


def test_oversized_body_gets_app_level_413_not_nginx_default(app_client, app, monkeypatch):
    # Shrink the limit for the test instead of transmitting a real 100 MB+
    # payload -- proves the same handler logic without the slow allocation.
    monkeypatch.setitem(app.config, 'MAX_CONTENT_LENGTH', 1024)

    response = app_client.post(
        '/', data=b'0' * 2048, content_type='application/octet-stream',
    )

    assert response.status_code == 413
    body = response.get_data(as_text=True)
    # Must be our branded error.html render, not Werkzeug/nginx's bare
    # "413 Request Entity Too Large" stock text.
    assert 'Upload Too Large' in body


def test_oversized_body_on_api_path_gets_json_error(app_client, app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAX_CONTENT_LENGTH', 1024)

    response = app_client.post(
        '/api/does-not-matter', data=b'0' * 2048, content_type='application/octet-stream',
    )

    assert response.status_code == 413
    payload = response.get_json()
    assert payload is not None
    assert 'error' in payload


def test_body_under_the_limit_does_not_trigger_413(app_client, app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAX_CONTENT_LENGTH', 1024)

    response = app_client.post(
        '/', data=b'0' * 100, content_type='application/octet-stream',
    )

    assert response.status_code != 413
