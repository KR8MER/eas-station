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

"""Static analysis tests to verify all route modules and admin blueprints are registered.

These tests guard against the recurring bug where a new route file is added but
forgotten in the registration chain (e.g., eas_decoder_monitor returning 404).
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEBAPP_DIR = PROJECT_ROOT / "webapp"
ADMIN_DIR = WEBAPP_DIR / "admin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _module_names_in_iter_route_modules() -> set:
    """Parse webapp/__init__.py and return all string literals passed as the
    first argument to RouteModule(...)."""
    source = _read(WEBAPP_DIR / "__init__.py")
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "RouteModule"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            names.add(node.args[0].value)
    return names


def _admin_init_text() -> str:
    return _read(ADMIN_DIR / "__init__.py")


# ---------------------------------------------------------------------------
# Test 1: every routes_*.py file in webapp/ is yielded by iter_route_modules
# ---------------------------------------------------------------------------

def test_all_routes_modules_registered_in_iter():
    """Every routes_*.py file in webapp/ must appear in iter_route_modules()."""
    registered = _module_names_in_iter_route_modules()

    missing = []
    for path in sorted(WEBAPP_DIR.glob("routes_*.py")):
        module_name = path.stem  # e.g. "routes_eas_monitor_status"
        if module_name not in registered:
            missing.append(path.name)

    assert not missing, (
        f"The following route modules exist in webapp/ but are NOT yielded by "
        f"iter_route_modules() in webapp/__init__.py:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# Test 2: every admin sub-module that defines a blueprint or register function
#         is referenced in webapp/admin/__init__.py
# ---------------------------------------------------------------------------

# Modules that legitimately have no registration in admin/__init__.py:
#  - __init__.py itself is the registry
#  - coverage.py is a pure utility with no blueprint or routes
#  - audio.py is legacy code intentionally shadowed by the audio/ package;
#    its routes were refactored into audio/ sub-modules and the eas/ blueprint
_ADMIN_MODULE_EXCEPTIONS = {"__init__", "coverage", "audio"}


def _admin_modules_with_blueprints_or_registers() -> list:
    """Return stem names of .py files in webapp/admin/ (non-package, top-level)
    that define at least one Blueprint or a register* function."""
    candidates = []
    for path in sorted(ADMIN_DIR.glob("*.py")):
        stem = path.stem
        if stem in _ADMIN_MODULE_EXCEPTIONS:
            continue
        source = _read(path)
        tree = ast.parse(source)
        has_blueprint = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Blueprint"
            for node in ast.walk(tree)
        )
        has_register = any(
            isinstance(node, ast.FunctionDef) and node.name.startswith("register")
            for node in ast.walk(tree)
        )
        if has_blueprint or has_register:
            candidates.append(stem)
    return candidates


def test_all_admin_modules_registered_in_admin_init():
    """Every admin sub-module with a Blueprint or register* function must be
    referenced (imported or called) in webapp/admin/__init__.py."""
    admin_init = _admin_init_text()
    candidates = _admin_modules_with_blueprints_or_registers()

    missing = []
    for stem in candidates:
        # Check for any reference: import or call using the module name
        if stem not in admin_init:
            missing.append(stem + ".py")

    assert not missing, (
        f"The following admin modules define a Blueprint or register function but "
        f"are NOT referenced in webapp/admin/__init__.py:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# Test 3: eas_decoder_monitor specifically (regression guard for the 404 fix)
# ---------------------------------------------------------------------------

def test_eas_decoder_monitor_is_registered():
    """Regression test: eas_decoder_monitor blueprint must be registered."""
    admin_init = _admin_init_text()
    assert "eas_decoder_monitor" in admin_init, (
        "eas_decoder_monitor is not referenced in webapp/admin/__init__.py; "
        "the /admin/eas_decoder_monitor route would return 404."
    )


# ---------------------------------------------------------------------------
# Test 4: routes/__init__.py sub-modules are registered
# ---------------------------------------------------------------------------

def test_routes_subdir_modules_registered():
    """Modules in webapp/routes/ with a register() function must appear in
    iter_route_modules() in webapp/__init__.py."""
    registered = _module_names_in_iter_route_modules()
    routes_dir = WEBAPP_DIR / "routes"

    missing = []
    for path in sorted(routes_dir.glob("*.py")):
        if path.stem == "__init__":
            continue
        source = _read(path)
        tree = ast.parse(source)
        has_register = any(
            isinstance(node, ast.FunctionDef) and node.name == "register"
            for node in ast.walk(tree)
        )
        if not has_register:
            continue
        # The RouteModule name for routes/foo.py is "routes_foo"
        expected_name = f"routes_{path.stem}"
        if expected_name not in registered:
            missing.append(path.name)

    assert not missing, (
        f"The following webapp/routes/ modules have a register() function but are "
        f"NOT yielded by iter_route_modules() in webapp/__init__.py:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# Test 5: url_for() calls in Python code use blueprint-qualified endpoint names
# ---------------------------------------------------------------------------

# Map of (file_path_relative_to_project, bare_function_name) pairs that are
# known blueprint endpoints and MUST be referenced with their blueprint prefix.
_BLUEPRINT_QUALIFIED_CHECKS = [
    # (relative file, wrong bare name, expected qualified name)
    ("webapp/eas/workflow.py", "url_for('login'", "url_for('auth.login'"),
    ("webapp/admin/environment.py", 'url_for("environment_settings")', 'url_for("environment.environment_settings")'),
]


def test_blueprint_url_for_uses_qualified_names():
    """url_for() calls in Python code must use 'blueprint.endpoint' notation
    for endpoints that live on a named blueprint, not bare function names."""
    violations = []
    for rel_path, wrong_pattern, correct_pattern in _BLUEPRINT_QUALIFIED_CHECKS:
        source = _read(PROJECT_ROOT / rel_path)
        if wrong_pattern in source:
            violations.append(
                f"  {rel_path}: found `{wrong_pattern}` — should be `{correct_pattern}`"
            )

    assert not violations, (
        "The following url_for() calls use a bare endpoint name instead of the "
        "blueprint-qualified form and will raise BuildError at runtime:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Test 6: hardcoded href paths in templates point to registered routes
# ---------------------------------------------------------------------------

# Known-broken href → correct href mappings (regression guard).
_HREF_REGRESSIONS = [
    # (template file relative path, bad href, correct href)
    ("templates/admin.html", 'href="/admin/audio_sources"', 'href="/admin/audio-sources"'),
    ("templates/admin.html", 'href="/admin/rwt-schedule"', 'href="/rwt-schedule"'),
    ("templates/audio_monitoring.html", 'href="/admin/diagnostics"', 'href="/diagnostics"'),
]


def test_known_broken_hrefs_are_fixed():
    """Regression guard: templates must not contain the previously-broken
    hardcoded href values that were corrected in this PR."""
    violations = []
    for rel_path, bad_href, correct_href in _HREF_REGRESSIONS:
        source = _read(PROJECT_ROOT / rel_path)
        if bad_href in source:
            violations.append(
                f"  {rel_path}: found `{bad_href}` — should be `{correct_href}`"
            )

    assert not violations, (
        "The following templates still contain broken href paths:\n"
        + "\n".join(violations)
    )
