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

"""Regression tests for the System Health and GNSS dashboard UI fixes.

These guard a set of defects that are invisible to the existing suites
because they live in the templates' inline JavaScript rather than in
Python:

* ``formatUptime`` was declared twice in the same scope in
  ``system_health.html``. The later declaration silently won, so the
  uptime rendered server-side by ``format_uptime()`` reformatted itself
  on the first poll.
* The System Health page skipped polling while the tab was hidden but
  never refreshed on return, leaving stale readings on screen with no
  cue.
* The GNSS dashboard's trends timer lacked the ``document.hidden``
  guard its sibling ``fetchOnce`` already had.
* A failing GNSS telemetry feed was reported only to the console.
* None of the System Health canvases carried an accessible name.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app_utils.formatting import format_uptime

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_HEALTH = REPO_ROOT / "templates" / "system_health.html"
GPS_DASHBOARD = REPO_ROOT / "templates" / "admin" / "gps_dashboard.html"


def _script_block(path: Path) -> str:
    """Return only the ``{% block scripts %}`` region of a template."""
    source = path.read_text(encoding="utf-8")
    return source[source.index("{% block scripts %}"):]


def _extract_function(script: str, name: str) -> str:
    """Return the full source of a named JS function.

    Brace-matched rather than regex-terminated: a non-greedy match to the
    first ``\\n}`` truncates at the first nested block, which silently
    yields an unparseable fragment.
    """
    match = re.search(r"^\s*function\s+" + re.escape(name) + r"\s*\(", script, re.M)
    assert match, f"could not find function {name}()"
    start = match.start()
    depth = 0
    seen_body = False
    for index in range(match.end() - 1, len(script)):
        char = script[index]
        if char == "{":
            depth += 1
            seen_body = True
        elif char == "}":
            depth -= 1
            if seen_body and depth == 0:
                return script[start:index + 1]
    raise AssertionError(f"unbalanced braces while extracting {name}()")


class TestFormatUptimeSingleDefinition:
    """``formatUptime`` must exist exactly once, and match Python."""

    def test_declared_exactly_once(self):
        matches = re.findall(
            r"^\s*function\s+formatUptime\s*\(", _script_block(SYSTEM_HEALTH), re.M
        )
        assert len(matches) == 1, (
            f"Expected exactly one formatUptime declaration, found {len(matches)}. "
            "Two declarations in the same scope means the later one silently "
            "wins and the earlier is dead code."
        )

    def test_declarations_share_one_scope(self):
        """Guard the assumption behind the test above.

        Sibling declarations at brace depth 0 overwrite each other. If a
        future refactor nests them in separate closures the count check
        stops being meaningful, so assert the depth explicitly.
        """
        depth = 0
        depths = []
        for line in _script_block(SYSTEM_HEALTH).split("\n"):
            if re.match(r"\s*function\s+formatUptime\s*\(", line):
                depths.append(depth)
            stripped = re.sub(r"`[^`]*`|\"[^\"]*\"|'[^']*'|//.*", "", line)
            depth += stripped.count("{") - stripped.count("}")
        assert depths == [0], f"formatUptime found at brace depths {depths}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
class TestFormatUptimeMatchesPython:
    """The client formatter must agree with the server formatter.

    The server renders the first paint via ``format_uptime()``; the
    client rewrites the same field on every poll. If the two disagree
    the value visibly reformats itself a few seconds after load.
    """

    @staticmethod
    def _run_js(seconds_values):
        import json

        script_block = _script_block(SYSTEM_HEALTH)
        program = "\n".join([
            _extract_function(script_block, "toNumber"),
            _extract_function(script_block, "formatUptime"),
            "console.log(JSON.stringify("
            + json.dumps(list(seconds_values))
            + ".map(function (s) { return formatUptime(s); })));",
        ])
        out = subprocess.run(
            ["node", "-e", program],
            capture_output=True, text=True, check=True,
        )
        return json.loads(out.stdout)

    def test_matches_python_across_durations(self):
        durations = [
            59, 60, 61, 3599, 3600, 3661, 86399, 86400, 90061,
            123456, 604800, 2592000,
        ]
        js_results = self._run_js(durations)
        for seconds, js_value in zip(durations, js_results):
            assert js_value == format_uptime(seconds), (
                f"uptime {seconds}s: JS rendered {js_value!r} but Python "
                f"rendered {format_uptime(seconds)!r} — the value would "
                "visibly change format on the first poll."
            )

    def test_missing_values_render_as_em_dash(self):
        # '—' is the established empty state for the status strip tiles.
        assert self._run_js([0])[0] == "—"


class TestSystemHealthRefreshesOnRefocus:
    """Polling is skipped while hidden, so it must resume on return."""

    def test_visibilitychange_listener_registered(self):
        script = _script_block(SYSTEM_HEALTH)
        assert "visibilitychange" in script, (
            "System Health skips polling while document.hidden but never "
            "refreshes on refocus, so a backgrounded tab shows stale "
            "readings with no staleness cue."
        )

    def test_refocus_triggers_a_refresh(self):
        script = _script_block(SYSTEM_HEALTH)
        handler = re.search(
            r"visibilitychange.*?\n(?:.*?\n){0,6}?.*?refreshHealthData", script
        )
        assert handler, "visibilitychange handler does not call refreshHealthData"


class TestGpsDashboardHiddenTabGuard:
    """The trends timer must honour the same guard as fetchOnce."""

    def test_trends_interval_guards_on_document_hidden(self):
        script = _script_block(GPS_DASHBOARD)
        interval = re.search(
            r"setInterval\(function \(\) \{(?:[^}]*?)TS_CURRENT_TIER.*?\}\s*,",
            script, re.S,
        )
        assert interval, "could not locate the trends refresh interval"
        assert "document.hidden" in interval.group(0), (
            "The trends re-fetch keeps polling the Redis-backed trends "
            "endpoint in background tabs, which is exactly what the guard "
            "on its sibling fetchOnce() prevents."
        )


class TestGpsDashboardSurfacesFeedErrors:
    """A failing telemetry feed must be visible, not console-only."""

    def test_error_banner_element_exists(self):
        source = GPS_DASHBOARD.read_text(encoding="utf-8")
        body = source[source.index("{% block content %}"):source.index("{% block scripts %}")]
        assert 'id="gps-dash-error"' in body
        assert 'role="alert"' in body

    def test_fetch_failure_shows_the_banner(self):
        script = _script_block(GPS_DASHBOARD)
        assert "function showFeedError" in script
        assert "function hideFeedError" in script
        catch_block = re.search(
            r"GPS dashboard fetch failed.*?\}\s*\)\s*;", script, re.S
        )
        assert catch_block, "could not locate the fetch catch block"
        assert "showFeedError" in catch_block.group(0), (
            "A failing GNSS feed leaves every card frozen on its last good "
            "values with only the heartbeat dot as a cue."
        )

    def test_non_ok_responses_are_treated_as_failures(self):
        script = _script_block(GPS_DASHBOARD)
        assert "if (!r.ok) throw" in script, (
            "A 5xx from the telemetry endpoint would otherwise be parsed as "
            "JSON and rendered as if it were a valid snapshot."
        )

    def test_http_200_failure_envelope_keeps_the_banner_up(self):
        """The hardware-service outage path answers 200, not 5xx.

        ``gps_dashboard_data()`` deliberately returns HTTP 200 carrying
        ``gps._error`` when the hardware service is unreachable, so the
        chrony half of the dashboard keeps rendering. Treating every 200
        as success hides precisely the outage the banner exists for.
        """
        script = _script_block(GPS_DASHBOARD)
        # Anchor on the telemetry fetch specifically — the file has
        # several `.then(function (data) {` handlers (events, trends).
        success_handler = re.search(
            r"fetch\('/admin/api/gps-dashboard/data'.*?\.then\(function \(data\) \{"
            r"(.*?)\n\s*\}\)",
            script, re.S,
        )
        assert success_handler, "could not locate the telemetry success handler"
        body = success_handler.group(1)
        assert "_error" in body, (
            "The success handler does not inspect gps._error, so a "
            "hardware-service outage renders with the banner hidden."
        )
        # hideFeedError() must be reachable only when _error is absent.
        error_pos = body.index("_error")
        hide_pos = body.index("hideFeedError")
        assert error_pos < hide_pos, (
            "hideFeedError() runs before the gps._error check, so the "
            "banner is cleared regardless of the failure envelope."
        )

    def test_backend_still_emits_the_error_envelope(self):
        """Pin the contract the front-end check depends on.

        If the backend stops using ``_error`` (or starts returning a
        non-200), the guard above becomes dead code — this test fails
        loudly rather than letting the UI silently regress.
        """
        hardware = (REPO_ROOT / "webapp" / "admin" / "hardware.py").read_text(
            encoding="utf-8"
        )
        assert '"_error": "hardware_service_unavailable"' in hardware, (
            "webapp/admin/hardware.py no longer emits the _error envelope "
            "the GNSS dashboard's success handler checks for."
        )


class TestSystemHealthCanvasAccessibility:
    """Every canvas needs an accessible name."""

    def test_all_canvases_have_an_accessible_name(self):
        source = SYSTEM_HEALTH.read_text(encoding="utf-8")
        canvases = re.findall(r"<canvas\b[^>]*>", source)
        assert canvases, "no canvas elements found — did the template change?"
        unlabelled = [c for c in canvases if "aria-label" not in c]
        assert not unlabelled, (
            f"{len(unlabelled)} canvas element(s) without an accessible "
            f"name: {unlabelled}"
        )

    def test_canvases_carry_an_img_role(self):
        """``aria-label`` alone is unreliable on <canvas>.

        Canvas has no implicit ARIA role, and an aria-label on a
        roleless element may be ignored entirely, so pair it with
        role="img".
        """
        source = SYSTEM_HEALTH.read_text(encoding="utf-8")
        canvases = re.findall(r"<canvas\b[^>]*>", source)
        missing_role = [c for c in canvases if 'role="img"' not in c]
        assert not missing_role, (
            f"{len(missing_role)} canvas element(s) without role=\"img\": "
            f"{missing_role}"
        )


class TestSystemHealthLinksToGnssDashboard:
    """The GPS card should reach the full dashboard in one click."""

    def test_link_present_in_both_renderings(self):
        """The card is rendered twice — server-side and in JS.

        Both copies need the link or it disappears on the first poll.
        """
        source = SYSTEM_HEALTH.read_text(encoding="utf-8")
        occurrences = source.count("Full GNSS Dashboard")
        assert occurrences >= 2, (
            "Expected the GNSS dashboard link in both the Jinja-rendered "
            f"and JS-rendered GPS cards, found {occurrences}."
        )
        assert source.count("hardware.gps_dashboard_page") >= 2
