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

"""Regression test for the nginx gateway-down page.

Before this fix, nginx served its bare stock "502 Bad Gateway" page whenever
the Flask app was unreachable, giving visitors no information. This guards
against the two failure modes that would silently reintroduce that:
  1. someone deletes/moves static/errors/gateway-down.html
  2. someone edits the nginx config and drops the error_page wiring, or the
     alias path drifts out of sync with where the file actually lives
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent
PAGE_PATH = REPO_ROOT / 'static' / 'errors' / 'gateway-down.html'
NGINX_CONF_PATH = REPO_ROOT / 'config' / 'nginx-eas-station.conf'


def test_gateway_down_page_exists_and_is_self_contained():
    assert PAGE_PATH.is_file(), (
        f"{PAGE_PATH} is missing -- nginx's error_page directive references it "
        "by path, so a missing file means visitors fall back to nginx's bare "
        "stock 502 page."
    )
    html = PAGE_PATH.read_text(encoding='utf-8')
    assert '<title>' in html
    assert 'Unavailable' in html

    # Must not depend on the Flask app being up: the whole point of this page
    # is that it renders while the backend is down. Only the wordmark image
    # (also served directly by nginx under /static/) is pulled in.
    assert 'src="/static/' in html
    assert '{{' not in html and '{%' not in html, (
        "Must be plain HTML, not a Jinja template -- nginx serves this file "
        "directly and cannot render Jinja syntax."
    )


def test_nginx_config_wires_up_the_error_page():
    conf = NGINX_CONF_PATH.read_text(encoding='utf-8')

    assert 'error_page 502 503 504 /static/errors/gateway-down.html;' in conf, (
        "nginx config must route 502/503/504 responses to the gateway-down page."
    )

    assert 'location = /static/errors/gateway-down.html' in conf
    assert 'internal;' in conf, (
        "The gateway-down page's location block must be marked internal so "
        "it can't be requested directly as a normal page."
    )

    # The alias inside that location block must point at the same file this
    # test already confirmed exists on disk (relative to how the app is
    # deployed at /opt/eas-station), not some other, possibly-stale path.
    assert 'alias /opt/eas-station/static/errors/gateway-down.html;' in conf
