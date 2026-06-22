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

"""RBAC coverage regression tests.

The app enforces authentication globally (``app.before_request``) but
authorization is opt-in per route via the ``@require_permission`` family of
decorators. A route that changes state and forgets the decorator is reachable
by *every* authenticated account -- including the read-only ``demo`` and
``viewer`` roles. This test statically scans the ``webapp`` package and fails
if any state-changing route is missing a permission decorator, or if a
decorator references a permission that is not defined in
``PermissionDefinition``.

Static analysis (rather than importing the app) keeps the test fast and free of
database/hardware dependencies, and matches how routes declare their guards.
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEBAPP_DIR = PROJECT_ROOT / "webapp"
ROLES_FILE = PROJECT_ROOT / "app_core" / "auth" / "roles.py"


def _load_defined_permissions() -> set:
    """Parse the ``PermissionDefinition`` enum values straight from source.

    Done statically (no import) so this test carries no runtime dependency on
    Flask/SQLAlchemy and matches the rest of its static-analysis approach.
    """
    tree = ast.parse(ROLES_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "PermissionDefinition":
            values = set()
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                    if isinstance(stmt.value.value, str):
                        values.add(stmt.value.value)
            return values
    raise AssertionError("PermissionDefinition enum not found in roles.py")

PERMISSION_DECORATORS = {
    "require_permission",
    "require_any_permission",
    "require_all_permissions",
    "require_permission_or_setup_mode",
}
# The app has two parallel authorization systems; either one excludes the
# read-only demo/viewer roles from a route. ``require_auth`` alone only checks
# that *someone* is signed in, so it is deliberately NOT counted as protection.
ROLE_DECORATORS = {"require_role"}
MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# Routes that are intentionally reachable without a permission decorator.
# Each entry is justified -- do not add to this list without a reason.
ALLOWLISTED_PATHS = {
    "/login",            # auth: sign in
    "/logout",           # auth: sign out
    "/permissions/check",  # returns the *current* user's own permission status
}
ALLOWLISTED_PREFIXES = (
    "/setup",  # first-run wizard, gated by SETUP_MODE in before_request
    "/mfa",    # MFA self-enrollment/verification for the signed-in user
)

DEFINED_PERMISSIONS = _load_defined_permissions()


def _name_chain(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _iter_routes():
    """Yield (path, methods, has_authz, perm_strings, location) per route.

    ``has_authz`` is True when the route carries a permission decorator OR a
    role decorator -- both restrict access beyond mere authentication.
    """
    for py in WEBAPP_DIR.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - surfaced as a failure below
            pytest.fail(f"Could not parse {py}: {exc}")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            route_path = None
            methods = []
            has_authz = False
            perm_strings = []
            for deco in node.decorator_list:
                call = deco if isinstance(deco, ast.Call) else None
                func = call.func if call else deco
                short = _name_chain(func).split(".")[-1]
                if short == "route" and call:
                    if call.args and isinstance(call.args[0], ast.Constant):
                        route_path = call.args[0].value
                    for kw in call.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, ast.List):
                            methods = [
                                e.value for e in kw.value.elts
                                if isinstance(e, ast.Constant)
                            ]
                if short in PERMISSION_DECORATORS or short in ROLE_DECORATORS:
                    has_authz = True
                if short in PERMISSION_DECORATORS and call:
                    for arg in call.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            perm_strings.append(arg.value)
            if route_path is not None:
                yield route_path, (methods or ["GET"]), has_authz, perm_strings, f"{py.name}:{node.lineno}"


def test_all_mutating_routes_have_authorization():
    """Every POST/PUT/DELETE/PATCH route must carry an authorization decorator.

    A permission decorator (``@require_permission``) or a role decorator
    (``@require_role``) qualifies. ``@require_auth`` alone does not -- it admits
    every signed-in account, including the read-only demo/viewer roles.
    """
    offenders = []
    for path, methods, has_authz, _perms, loc in _iter_routes():
        if not any(m in MUTATING_METHODS for m in methods):
            continue
        if path in ALLOWLISTED_PATHS or path.startswith(ALLOWLISTED_PREFIXES):
            continue
        if not has_authz:
            offenders.append(f"{path} {methods} ({loc})")
    assert not offenders, (
        "State-changing routes without an authorization decorator (reachable by "
        "any authenticated user, including demo/viewer):\n  "
        + "\n  ".join(sorted(offenders))
    )


def test_permission_decorators_reference_defined_permissions():
    """No decorator may reference a permission absent from PermissionDefinition."""
    offenders = []
    for path, _methods, _has_perm, perms, loc in _iter_routes():
        for perm in perms:
            if perm not in DEFINED_PERMISSIONS:
                offenders.append(f"{perm!r} on {path} ({loc})")
    assert not offenders, (
        "Permission decorators referencing undefined permissions (these lock "
        "out everyone, including admins):\n  " + "\n  ".join(sorted(offenders))
    )
