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

"""Panels whose JavaScript wrote into containers that did not exist.

Both of these shipped as scripts that looked correct in review and failed
silently at runtime, because each was written defensively:

  * ``system_health.html`` called ``renderSystemdDetails()`` and assigned the
    result to ``getElementById('systemd-details').innerHTML`` behind an
    ``if (container)`` guard. No element carried that id, so the per-service
    breakdown was built and thrown away on every refresh.
  * ``admin/radio.html`` called ``showConfigSummary()`` whenever a service
    type was picked. It guards on ``if (summary)`` and then populates six
    fields; none of the seven ids existed, so the whole call was a no-op.

A guarded write to a missing element produces no console error and no visual
hint — the feature is simply absent. These tests pin the markup to the ids the
scripts address.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RADIO_TEMPLATE = PROJECT_ROOT / "templates" / "admin" / "radio.html"
HEALTH_TEMPLATE = PROJECT_ROOT / "templates" / "system_health.html"


def _element_ids(markup: str) -> set:
    """Ids present as literal ``id="..."`` attributes."""
    return set(re.findall(r'\bid\s*=\s*"([\w-]+)"', markup))


# ---------------------------------------------------------------------------
# Radio service configuration summary
# ---------------------------------------------------------------------------

RADIO_SUMMARY_IDS = {
    "configSummary",
    "summaryModulation",
    "summarySampleRate",
    "summaryBandwidth",
    "summaryAudio",
    "summaryStereo",
    "summaryRBDS",
}


def test_radio_config_summary_elements_exist():
    """Every id showConfigSummary() addresses must exist in the template."""
    markup = RADIO_TEMPLATE.read_text(encoding="utf-8")
    missing = sorted(RADIO_SUMMARY_IDS - _element_ids(markup))
    assert not missing, (
        "admin/radio.html: showConfigSummary() writes to element ids that do "
        f"not exist, so the summary silently never renders: {missing}"
    )


def test_radio_config_summary_starts_hidden():
    """The panel must be hidden until a service type is selected.

    showConfigSummary() reveals it with ``style.display = 'block'``; if the
    markup did not start hidden, an empty summary of em-dashes would show on
    every open of the Add Receiver modal.
    """
    markup = RADIO_TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r'id="configSummary"[^>]*>', markup)
    assert match, "configSummary element is missing"
    assert "display: none" in match.group(0) or "display:none" in match.group(0), (
        "configSummary must start hidden — showConfigSummary() is what reveals it"
    )


def test_radio_template_has_no_unbacked_get_element_by_id():
    """Guard the whole template against the same class of bug.

    Ids built dynamically in JS template literals are excluded; this only
    flags plain string targets with no matching ``id=`` attribute.
    """
    markup = RADIO_TEMPLATE.read_text(encoding="utf-8")
    ids = _element_ids(markup)
    ids |= set(re.findall(r'''id=\\?["']([\w-]+)''', markup))

    missing = sorted(
        {
            m.group(1)
            for m in re.finditer(r"""getElementById\(\s*['"]([\w-]+)['"]""", markup)
            if m.group(1) not in ids
        }
    )
    assert not missing, (
        "admin/radio.html calls getElementById() for ids that do not exist in "
        f"the template — those calls silently do nothing: {missing}"
    )


# ---------------------------------------------------------------------------
# System health service details
# ---------------------------------------------------------------------------

SYSTEMD_FIXTURE = {
    "available": True,
    "services": [
        {
            "name": "eas-station-web.service",
            "display_name": "EAS Station Web",
            "active_state": "active",
            "sub_state": "running",
            "is_eas_service": True,
        },
        {
            "name": "nginx.service",
            "display_name": "Nginx",
            "active_state": "failed",
            "sub_state": "dead",
            "is_eas_service": False,
        },
        {
            "name": "redis.service",
            "display_name": "Redis",
            "active_state": "activating",
            "sub_state": "start",
            "is_eas_service": False,
        },
    ],
}


def test_health_template_declares_systemd_details_container():
    """The refresh script's target container must exist in the markup."""
    markup = HEALTH_TEMPLATE.read_text(encoding="utf-8")
    assert 'id="systemd-details"' in markup, (
        "system_health.html assigns renderSystemdDetails() output into "
        "#systemd-details, but no element declares that id — the rendered "
        "card is discarded on every refresh."
    )


def _render_health(systemd):
    """Render system_health.html exactly as ``system_health_page()`` does.

    Going through the route would mean satisfying the global ``before_request``
    gate, which loads a real ``AdminUser`` row straight from the session — a
    heavier setup that would test the auth chain rather than this markup. The
    context assembled here mirrors the route's line for line, with only the
    systemd payload substituted.
    """
    from app import app
    from app_core.system_health import get_system_health
    from app_utils import format_bytes, format_uptime
    from flask import render_template

    health_data = dict(get_system_health())
    health_data["systemd"] = systemd
    context = dict(health_data)
    context["format_bytes"] = format_bytes
    context["format_uptime"] = format_uptime
    # The route passes the raw payload, not the context: the context also
    # carries the two helper functions, and the template runs it through
    # `|tojson`, which cannot serialise them.
    context["health_data_raw"] = health_data

    with app.test_request_context("/system_health"):
        return render_template("system_health.html", **context)


def _systemd_section(html: str) -> str:
    start = html.find('id="systemd-details"')
    assert start > 0, "#systemd-details container not rendered"
    end = html.find("Hardware Subsystems", start)
    return html[start:end if end > start else len(html)]


def test_systemd_details_renders_every_service():
    """Each service becomes a row with the right status badge and category."""
    section = _systemd_section(_render_health(SYSTEMD_FIXTURE))

    for name in ("EAS Station Web", "Nginx", "Redis"):
        assert name in section, f"{name} missing from Service Details"

    # Badge mapping must match renderSystemdDetails() in the refresh script.
    assert "bg-success" in section and ">Active<" in section
    assert "bg-danger" in section and ">Failed<" in section
    assert "bg-warning" in section and ">Starting<" in section

    assert "EAS Station™" in section, "EAS services must be categorised"
    assert "Dependency" in section, "non-EAS services must be categorised"

    # Mobile requirement: wide tables scroll inside their own container.
    assert "table-responsive" in section


def test_systemd_details_reports_unavailable_reason():
    section = _systemd_section(
        _render_health(
            {"available": False, "error": "systemd not reachable"}
        )
    )
    assert "Service details unavailable: systemd not reachable" in section


def test_systemd_details_handles_no_services():
    section = _systemd_section(
        _render_health({"available": True, "services": []})
    )
    assert "No systemd services detected." in section
