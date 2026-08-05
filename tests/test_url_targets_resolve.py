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

"""Every URL the code builds must point at a route that exists.

The existing route tests pin down *specific* known-bad strings, so each new
instance of the same mistake ships undetected until a user hits it. These
tests are generic: they walk the whole tree and check every literal
``url_for()`` target and every literal ``fetch()`` path against the real URL
map.

Written after a sweep found four live instances at once:

  * ``url_for("admin")`` in the role-denial path — the admin dashboard is on
    the ``dashboard`` blueprint, so every role denial on an HTML request
    raised BuildError and returned 500 instead of a redirect-with-flash;
  * a per-row "Delete boundary" button calling ``/admin/delete_boundary/<id>``,
    which no route answered;
  * the audio detail page's Delete button calling ``/admin/eas_messages/<id>``
    after that route had moved to ``/eas/messages/<id>``;
  * three ``url_for()`` calls in a module that had been silently shadowed by a
    same-named package and was dead code entirely.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Paths that legitimately reference URLs this app does not serve.
#
# The EAS decoder stream is served by eas_monitoring_service.py on port 5002
# and reverse-proxied into this URL space by nginx (see
# config/nginx-eas-station.conf), so it never appears in this app's URL map.
EXTERNAL_URL_PREFIXES = ("/api/eas/decoder-stream",)

# Directories whose url_for() strings are built dynamically or belong to
# fixtures rather than the running app.
SKIP_DIRS = {"venv", ".venv", "node_modules", "tests", "__pycache__", ".git"}


@pytest.fixture(scope="module")
def flask_app():
    from app import app as flask_application

    return flask_application


def _iter_source_files():
    for path in PROJECT_ROOT.rglob("*.py"):
        if not SKIP_DIRS.isdisjoint(path.parts):
            continue
        yield path
    for path in (PROJECT_ROOT / "templates").rglob("*.html"):
        yield path


def test_url_for_targets_are_registered_endpoints(flask_app):
    """Every literal url_for('endpoint') must resolve.

    A bare function name for an endpoint that lives on a named blueprint
    raises BuildError at render time — a 500 on a page that otherwise looks
    fine in review.
    """
    endpoints = {rule.endpoint for rule in flask_app.url_map.iter_rules()}
    endpoints.add("static")

    violations = []
    for path in _iter_source_files():
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in re.finditer(r"""url_for\(\s*['"]([a-zA-Z0-9_.]+)['"]""", source):
            endpoint = match.group(1)
            if endpoint in endpoints:
                continue
            line = source[: match.start()].count("\n") + 1
            rel = path.relative_to(PROJECT_ROOT)
            suggestion = sorted(
                e for e in endpoints if e.rsplit(".", 1)[-1] == endpoint
            )
            hint = f" (did you mean {suggestion[0]!r}?)" if suggestion else ""
            violations.append(f"  {rel}:{line}: url_for({endpoint!r}){hint}")

    assert not violations, (
        "url_for() targets that are not registered endpoints — these raise "
        "BuildError at runtime:\n" + "\n".join(sorted(violations))
    )


def _fetch_url_pattern(raw: str):
    """Compile a fetch() URL literal into a regex.

    Interpolated segments become wildcards. Substituting a concrete value
    instead would be wrong: an interpolation often stands in for a literal
    route segment rather than a converter — ``/api/traffic/privacy/${action}``
    is really ``/anonymize`` or ``/purge`` — so a placeholder like "1" fails
    to match a route that is in fact perfectly reachable.
    """
    url = raw.split("?")[0].split("#")[0]
    parts = re.split(r"\$\{[^}]*\}|\{\{[^}]*\}\}", url)
    return re.compile("[^/]+".join(re.escape(p) for p in parts) + "$")


def _rule_sample_paths(url_map):
    """Yield (methods, concrete-sample-path) for every registered rule."""
    for rule in url_map.iter_rules():
        sample = re.sub(r"<[^>]+>", "sample", rule.rule)
        yield rule.methods, sample


def test_fetch_urls_hit_registered_routes(flask_app):
    """Every literal fetch('/path') in the UI must hit a real route.

    A frontend calling a route that has moved fails silently: the 404 body is
    HTML, ``response.json()`` throws, and the catch block reports a generic
    "operation failed" that looks like a backend error.
    """
    rules = list(_rule_sample_paths(flask_app.url_map))

    sources = list((PROJECT_ROOT / "templates").rglob("*.html"))
    sources += list((PROJECT_ROOT / "static" / "js").rglob("*.js"))

    violations = []
    for path in sources:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in re.finditer(r"""fetch\(\s*[`'"]([^`'"]+)[`'"]""", source):
            raw = match.group(1)
            if not raw.startswith("/"):
                continue
            if raw.startswith(EXTERNAL_URL_PREFIXES):
                continue

            tail = source[match.end() : match.end() + 200]
            method_match = re.search(r"""method:\s*['"](\w+)['"]""", tail)
            method = (method_match.group(1) if method_match else "GET").upper()

            # A trailing-interpolation URL like '/eas/messages/' + id + '/resend'
            # cannot be reconstructed from the literal alone; skip those rather
            # than report a false positive.
            if raw.endswith("/"):
                continue

            pattern = _fetch_url_pattern(raw)
            path_hits = [methods for methods, sample in rules if pattern.match(sample)]
            if not path_hits:
                line = source[: match.start()].count("\n") + 1
                rel = path.relative_to(PROJECT_ROOT)
                violations.append(f"  {rel}:{line}: {method} {raw} — no such route")
            elif not any(method in methods for methods in path_hits):
                line = source[: match.start()].count("\n") + 1
                rel = path.relative_to(PROJECT_ROOT)
                violations.append(
                    f"  {rel}:{line}: {method} {raw} — route exists but rejects {method}"
                )

    assert not violations, (
        "Frontend fetch() calls pointing at routes that do not exist:\n"
        + "\n".join(sorted(violations))
    )


def test_no_module_is_shadowed_by_a_same_named_package():
    """A module and package with the same name silently loses the module.

    ``webapp/admin/audio.py`` sat next to ``webapp/admin/audio/`` for some
    time. Python resolves the package, so the 1276-line module was never
    imported — including a batch of authorization decorators applied to it by
    a security fix, which gave a false impression those routes were hardened.
    """
    collisions = []
    for package_init in PROJECT_ROOT.rglob("__init__.py"):
        if not SKIP_DIRS.isdisjoint(package_init.parts):
            continue
        package_dir = package_init.parent
        sibling_module = package_dir.with_suffix(".py")
        if sibling_module.exists():
            collisions.append(
                f"  {sibling_module.relative_to(PROJECT_ROOT)} is shadowed by "
                f"{package_dir.relative_to(PROJECT_ROOT)}/"
            )

    assert not collisions, (
        "These modules are dead code — a same-named package wins the import:\n"
        + "\n".join(sorted(collisions))
    )
