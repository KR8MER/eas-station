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

Guards for the two browser-rendered clocks in the page chrome.

``static/js/core/utils.js`` drives the footer clock and the navbar clock on
every page. Two faults lived here:

1. The clocks hardcoded ``America/New_York`` even though the station timezone
   is configurable (the setup wizard offers 22 US zones). A Honolulu station
   read six hours off, labelled "EDT" by ``timeZoneName: 'short'``.
2. ``system_health.html`` reused the footer clock's ``current-time`` ID for its
   "Last Updated" metric. Content renders before the footer, so
   ``getElementById`` returned the metric and two one-second timers fought over
   it while the footer clock never left "Loading...".
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
BASE_TEMPLATE = TEMPLATES_DIR / "base.html"
UTILS_JS = PROJECT_ROOT / "static" / "js" / "core" / "utils.js"

ID_PATTERN = re.compile(r'id="([\w-]+)"')
EXTENDS_BASE_PATTERN = re.compile(r"""{%\s*extends\s*["']base\.html["']""")


def _templates_extending_base():
    """Yield (path, source) for every template that inherits from base.html."""
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        if path == BASE_TEMPLATE:
            continue
        source = path.read_text(encoding="utf-8")
        if EXTENDS_BASE_PATTERN.search(source):
            yield path, source


def test_no_template_reuses_an_id_defined_in_base():
    """A child template must not redefine an ID that base.html already owns.

    Both elements end up in the same document, and ``getElementById`` silently
    returns whichever comes first — so the collision shows up as two scripts
    overwriting one node, never as an error.
    """
    base_ids = set(ID_PATTERN.findall(BASE_TEMPLATE.read_text(encoding="utf-8")))
    assert "current-time" in base_ids, "base.html should still own the footer clock ID"

    collisions = {}
    for path, source in _templates_extending_base():
        shared = set(ID_PATTERN.findall(source)) & base_ids
        if shared:
            collisions[path.relative_to(PROJECT_ROOT)] = sorted(shared)

    assert not collisions, (
        "Templates redefine an ID that base.html already uses: "
        f"{collisions}. Rename the child element."
    )


def test_system_health_last_updated_has_its_own_id():
    """The System Health metric must not reclaim the footer clock's ID."""
    source = (TEMPLATES_DIR / "system_health.html").read_text(encoding="utf-8")

    assert 'id="health-last-updated"' in source
    assert "getElementById('health-last-updated')" in source
    # Match real usage, not prose — the comment explaining the fix names the
    # old ID, and that should not fail the test.
    assert 'id="current-time"' not in source
    assert "getElementById('current-time')" not in source


def test_base_template_publishes_the_station_timezone():
    """base.html stamps the configured zone where client scripts can read it."""
    source = BASE_TEMPLATE.read_text(encoding="utf-8")

    assert 'data-timezone="{{ station_timezone() }}"' in source


def test_chrome_clocks_do_not_hardcode_a_timezone():
    """The footer/navbar clocks must follow the configured station timezone."""
    source = UTILS_JS.read_text(encoding="utf-8")

    assert "getStationTimeZone" in source, "utils.js should resolve the zone at runtime"
    # A hardcoded IANA name here silently overrides the station's setting.
    hardcoded = re.findall(r"timeZone:\s*['\"][A-Za-z]+/[A-Za-z_]+['\"]", source)
    assert not hardcoded, f"utils.js hardcodes a timezone: {hardcoded}"


def test_station_timezone_is_registered_as_a_template_global():
    """``station_timezone()`` must exist, or base.html renders an empty attr."""
    from flask import Flask

    from webapp import template_helpers

    app = Flask(__name__)
    template_helpers.register(app)

    assert "station_timezone" in app.jinja_env.globals

    with app.app_context():
        rendered = app.jinja_env.from_string("{{ station_timezone() }}").render()

    # Any valid IANA name is fine; an empty string would mean the attribute is
    # published but useless, which is the failure this guards.
    assert "/" in rendered, f"expected an IANA zone name, got {rendered!r}"
