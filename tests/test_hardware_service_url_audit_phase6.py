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

from __future__ import annotations

"""Phase 6 caller-audit regressions for the hardware_service.py split.

Phase 4 replaced the monolithic ``HARDWARE_SERVICE_URL`` (port 5001) with
five per-subsystem URLs on ports 5101-5105.  Phase 5 deployed the new
systemd target.  These tests guard the audit done in Phase 6:

  * ``HARDWARE_SERVICE_URL`` is not exported from ``app_core.config``.
  * No webapp / app_core / app_utils source file imports it.
  * Nothing still hardcodes ``http://...:5001`` as a hardware URL.
  * The logs picker (``get_all_log_services``) lists every Phase 4 unit
    by name, so operators can stream any subsystem's journal from the UI.
  * ``webapp.admin.network.call_hardware_service`` routes ``/api/hardware
    /gps/*`` to the GPS subsystem (5103) and everything else to the
    network subsystem (5101) — i.e. nothing collapses back to a single
    port if someone re-imports the helper.

Adding a backwards-compat ``HARDWARE_SERVICE_URL`` shim or a port-5001
caller will fail these tests.
"""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDITED_DIRS = ("webapp", "app_core", "app_utils")
EXPECTED_SUBSYSTEMS = ("network", "zigbee", "gps", "displays", "gpio")


def _iter_python_sources():
    for base in AUDITED_DIRS:
        for root, _dirs, files in os.walk(REPO_ROOT / base):
            for fname in files:
                if fname.endswith(".py"):
                    yield Path(root) / fname


def test_hardware_service_url_constant_is_gone() -> None:
    """app_core/config/services.py must not define the legacy constant.

    Read the source rather than importing the module so the assertion
    works even when the wider ``app_core`` package's runtime dependencies
    are not installed in the test environment.
    """
    services_py = (REPO_ROOT / "app_core" / "config" / "services.py").read_text(
        encoding="utf-8"
    )
    # Match a top-level binding like ``HARDWARE_SERVICE_URL = ...`` (with
    # or without a type annotation).  A bare mention in a comment or
    # docstring is allowed — only the live name is a problem.
    binding = re.compile(r"^HARDWARE_SERVICE_URL\s*[:=]", re.MULTILINE)
    assert not binding.search(services_py), (
        "HARDWARE_SERVICE_URL should have been removed in Phase 4 — "
        "callers must use the five per-subsystem URLs (NETWORK_SERVICE_URL, "
        "ZIGBEE_SERVICE_URL, GPS_SERVICE_URL, DISPLAYS_SERVICE_URL, "
        "GPIO_SERVICE_URL) instead."
    )


def test_no_source_imports_hardware_service_url() -> None:
    """No live code may import ``HARDWARE_SERVICE_URL``.

    Docstring/comment mentions of the legacy name are fine (they explain
    the migration); ``from ... import HARDWARE_SERVICE_URL`` or
    ``config.HARDWARE_SERVICE_URL`` references are not.
    """
    import_pattern = re.compile(r"\bimport\b[^\n]*\bHARDWARE_SERVICE_URL\b")
    attr_pattern = re.compile(r"\bconfig\.HARDWARE_SERVICE_URL\b")
    offenders = []

    for path in _iter_python_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        if import_pattern.search(text) or attr_pattern.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "HARDWARE_SERVICE_URL is still referenced in: " + ", ".join(offenders)
    )


def test_no_source_hardcodes_legacy_hardware_port() -> None:
    """No caller may hardcode the legacy hardware-service port (5001).

    The five per-subsystem ports (5101-5105) replaced it in Phase 4.
    """
    legacy_url = re.compile(r"http://[^\"' ]*:5001\b")
    offenders = []

    for path in _iter_python_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        if legacy_url.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Legacy hardware-service port 5001 hardcoded in: "
        + ", ".join(offenders)
    )


def test_logs_picker_lists_every_hardware_subsystem() -> None:
    """The in-app logs picker must surface all five Phase 4 units.

    ``get_all_log_services`` is the whitelist for ``/api/logs/<service>``
    *and* the source for the ``available_services`` template variable on
    the logs page, so a missing unit means operators cannot pick that
    subsystem's journal at all.

    Verifies at the source level: ``EAS_SERVICES`` in
    ``app_core/config/services.py`` must list every per-subsystem unit
    by its prefix-derived name.  Source-level so the test passes even
    when the wider package's runtime deps (cryptography, psutil, …) are
    not present in the test container.
    """
    services_py = (REPO_ROOT / "app_core" / "config" / "services.py").read_text(
        encoding="utf-8"
    )
    # ``EAS_SERVICES`` is a literal list of f-strings; assert each
    # subsystem appears as ``f'{SERVICE_PREFIX}-<name>.service'``.
    eas_block = re.search(r"EAS_SERVICES\s*=\s*\[(.+?)\]", services_py, re.DOTALL)
    assert eas_block, "EAS_SERVICES list literal not found in services.py"
    block = eas_block.group(1)
    for subsystem in EXPECTED_SUBSYSTEMS:
        needle = f"-{subsystem}.service"
        assert needle in block, (
            f"EAS_SERVICES missing {{prefix}}{needle} — the logs picker "
            f"will not let operators stream {subsystem}'s journal."
        )


def test_network_caller_routes_gps_endpoints_to_gps_subsystem() -> None:
    """``_route_to_subsystem`` must split GPS calls off the network URL.

    Phase 4 fused the old monolithic ``call_hardware_service`` callers
    onto two ports — network (5101) for nmcli endpoints and gps (5103)
    for GPS endpoints.  If anyone collapses the helper back to one
    constant, the GPS dashboard will silently 404 against the network
    subsystem.

    Verifies at the source level (no webapp import needed): the helper
    must branch on ``/api/hardware/gps/`` and return ``GPS_SERVICE_URL``
    for that prefix, ``NETWORK_SERVICE_URL`` otherwise.
    """
    network_py = (REPO_ROOT / "webapp" / "admin" / "network.py").read_text(
        encoding="utf-8"
    )

    # Slice from ``def _route_to_subsystem`` up to the next top-level
    # ``def`` so we cover the docstring and the full function body.
    func_start = network_py.find("def _route_to_subsystem(")
    assert func_start >= 0, "_route_to_subsystem helper has been removed or renamed"
    next_def = network_py.find("\ndef ", func_start + 1)
    body = network_py[func_start : next_def if next_def != -1 else len(network_py)]

    assert "/api/hardware/gps/" in body, (
        "_route_to_subsystem must branch on the '/api/hardware/gps/' prefix "
        "so GPS endpoints route to GPS_SERVICE_URL (port 5103)."
    )
    assert "GPS_SERVICE_URL" in body, (
        "_route_to_subsystem must return GPS_SERVICE_URL for GPS endpoints."
    )
    assert "NETWORK_SERVICE_URL" in body, (
        "_route_to_subsystem must default to NETWORK_SERVICE_URL for nmcli "
        "endpoints (port 5101)."
    )

    # The helper imports both URLs from app_core.config; if anyone drops
    # one of those imports the routing collapses.
    assert re.search(
        r"from\s+app_core\.config\s+import\s+[^\n]*GPS_SERVICE_URL",
        network_py,
    ), "webapp/admin/network.py must import GPS_SERVICE_URL"
    assert re.search(
        r"from\s+app_core\.config\s+import\s+[^\n]*NETWORK_SERVICE_URL",
        network_py,
    ), "webapp/admin/network.py must import NETWORK_SERVICE_URL"


@pytest.mark.parametrize("subsystem,port", [
    ("network", 5101),
    ("zigbee", 5102),
    ("gps", 5103),
    ("displays", 5104),
    ("gpio", 5105),
])
def test_subsystem_url_default_points_at_expected_port(subsystem: str, port: int) -> None:
    """Each per-subsystem URL must default to its documented port.

    The systemd units bind to these ports; if the URL drifts from the
    unit, every caller fails fast on connect.  Source-level check so the
    test passes without the rest of the ``app_core`` runtime deps.
    """
    services_py = (REPO_ROOT / "app_core" / "config" / "services.py").read_text(
        encoding="utf-8"
    )
    attr = f"{subsystem.upper()}_SERVICE_URL"
    # Match ``ATTR = os.environ.get('ATTR', 'http://...:PORT')``.
    pattern = re.compile(
        rf"^{attr}\s*=\s*os\.environ\.get\(\s*['\"]{attr}['\"]\s*,\s*"
        rf"['\"]http://[^'\"]*:{port}['\"]\s*\)\s*$",
        re.MULTILINE,
    )
    assert pattern.search(services_py), (
        f"{attr} must default to a URL on port {port} "
        f"(matches systemd/eas-station-{subsystem}.service)."
    )
