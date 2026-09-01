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

"""Regression tests for nginx-native error pages.

Some failures never reach the Flask app at all -- the backend being totally
unreachable (502/503/504), or a request nginx rejects on its own before
proxying (413, over client_max_body_size). Before these pages existed,
nginx served its bare stock error page for both, giving visitors no
information. This guards against the two failure modes that would silently
reintroduce that for either page:
  1. someone deletes/moves the page's HTML file
  2. someone edits the nginx config and drops the error_page wiring, or the
     alias path drifts out of sync with where the file actually lives
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent
NGINX_CONF_PATH = REPO_ROOT / 'config' / 'nginx-eas-station.conf'

# (html filename, error codes it's wired to, a substring expected in <title>)
ERROR_PAGES = [
    ('gateway-down.html', '502 503 504', 'Unavailable'),
    ('upload-too-large.html', '413', 'Too Large'),
]


@pytest.mark.parametrize('filename, codes, title_substring', ERROR_PAGES)
def test_error_page_exists_and_is_self_contained(filename, codes, title_substring):
    page_path = REPO_ROOT / 'static' / 'errors' / filename
    assert page_path.is_file(), (
        f"{page_path} is missing -- nginx's error_page directive references it "
        "by path, so a missing file means visitors fall back to nginx's bare "
        "stock error page."
    )
    html = page_path.read_text(encoding='utf-8')
    assert '<title>' in html
    assert title_substring in html

    # Must not depend on the Flask app being up: the whole point of these
    # pages is that they render while the backend is unreachable, or before
    # nginx even proxies to it. Only the wordmark image (also served
    # directly by nginx under /static/) is pulled in.
    assert 'src="/static/' in html
    assert '{{' not in html and '{%' not in html, (
        "Must be plain HTML, not a Jinja template -- nginx serves this file "
        "directly and cannot render Jinja syntax."
    )


@pytest.mark.parametrize('filename, codes, title_substring', ERROR_PAGES)
def test_nginx_config_wires_up_the_error_page(filename, codes, title_substring):
    conf = NGINX_CONF_PATH.read_text(encoding='utf-8')

    assert f'error_page {codes} /static/errors/{filename};' in conf, (
        f"nginx config must route {codes} responses to {filename}."
    )

    assert f'location = /static/errors/{filename}' in conf

    # The alias must point at the same file this test already confirmed
    # exists on disk (relative to how the app is deployed at
    # /opt/eas-station), not some other, possibly-stale path.
    assert f'alias /opt/eas-station/static/errors/{filename};' in conf


def test_error_page_locations_are_marked_internal():
    """Every /static/errors/*.html location block must be internal-only so
    none of these pages can be requested directly as a normal page."""
    conf = NGINX_CONF_PATH.read_text(encoding='utf-8')
    blocks = conf.split('location = /static/errors/')[1:]
    assert len(blocks) == len(ERROR_PAGES), (
        f"Expected {len(ERROR_PAGES)} /static/errors/ location blocks, found {len(blocks)}."
    )
    for block in blocks:
        # internal; must appear before this location block's closing brace
        body = block.split('}', 1)[0]
        assert 'internal;' in body
