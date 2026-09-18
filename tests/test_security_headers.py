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

"""Regression guard: app.py must not re-add the headers nginx now owns.

Strict-Transport-Security, X-Frame-Options, X-Content-Type-Options, and
X-XSS-Protection used to be set both here and in nginx
(config/nginx-eas-station.conf) -- confirmed live via curl to send two
Strict-Transport-Security header fields with different max-age values.
Per RFC 6797 section 8.1, a browser that sees more than one STS header
field must ignore all of them, so HSTS was silently unenforced despite
looking configured in both places. nginx is the actual TLS-terminating
edge, so it's the single source of truth for these now; app.py only sets
Content-Security-Policy, which nginx never touches.
"""


def test_flask_does_not_set_headers_nginx_owns(app_client):
    resp = app_client.get('/health')
    for header in (
        'Strict-Transport-Security',
        'X-Frame-Options',
        'X-Content-Type-Options',
        'X-XSS-Protection',
    ):
        assert header not in resp.headers, (
            f"app.py must not set {header} -- nginx "
            "(config/nginx-eas-station.conf) is the single source of truth, "
            "and setting it here too reintroduces the duplicate-header bug "
            "that silently disabled HSTS enforcement."
        )


def test_flask_still_sets_content_security_policy(app_client):
    resp = app_client.get('/health')
    assert 'Content-Security-Policy' in resp.headers
