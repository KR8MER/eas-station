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

Repository: https://github.com/KR8MER/eas-station"""

from __future__ import annotations

"""Structural guards for the webapp.routes.alert_verification package split.

687 of this module's 1,668 lines were a single ``register(app, logger)`` with
eight helpers and seven handlers nested inside it. Splitting that means
reproducing a *closure*, not just moving text, so what needs pinning here is
different from the flat 3d-3f splits:

* the handlers still close over ``route_logger`` and ``repo_root``,
* the four helpers that were dedented to module scope captured nothing, and
* the mutable globals the tests patch must NOT be reachable from the package,
  so a mis-aimed ``monkeypatch.setattr`` raises instead of quietly doing
  nothing.

That last one is the interesting case. With the globals re-exported and the
patch aimed at the package, the async tests still *pass* — they just stop
isolating anything and start writing to the real temp directory. A green test
that tests nothing is worse than a red one, which is why the non-re-export is
deliberate and asserted below.
"""

import ast
import logging
from pathlib import Path

import pytest
from flask import Flask

from webapp.routes import alert_verification
from webapp.routes.alert_verification import helpers as helpers_mod
from webapp.routes.alert_verification import progress as progress_mod

PACKAGE_DIR = Path(alert_verification.__file__).parent
REPO_ROOT = Path(__file__).resolve().parents[1]

# Every rule the single-file register() attached, with its endpoint name.
EXPECTED_RULES = {
    ('/admin/alert-verification', 'alert_verification'),
    ('/admin/alert-verification/operations', 'start_alert_verification_operation'),
    ('/admin/alert-verification/progress/<operation_id>', 'alert_verification_progress'),
    ('/admin/alert-verification/export.csv', 'alert_verification_export'),
    (
        '/admin/alert-verification/decodes/<int:decode_id>/audio/<string:segment>',
        'alert_verification_decode_audio',
    ),
    ('/api/alert-self-test/run', 'run_alert_self_test'),
    ('/api/decode-same-header', 'decode_same_header_api'),
}

# Mutable module globals the tests replace. Reachable from the package, a
# patch aimed there rebinds a copy and the readers never see it.
PATCH_ONLY_ON_SUBMODULE = {
    '_progress_dir': 'progress',
    '_progress_lock': 'progress',
    '_result_dir': 'progress',
    '_result_lock': 'progress',
}


def _package_modules() -> list[Path]:
    return sorted(p for p in PACKAGE_DIR.glob('*.py') if p.name != '__init__.py')


def _unwrap(view):
    """Peel ``require_auth``/``require_role`` off to reach the real handler.

    ``app.view_functions[...]`` is the outermost decorator, whose only free
    variable is the function it wraps — inspecting it tells you nothing about
    the handler's closure.
    """
    seen = 0
    while hasattr(view, '__wrapped__') and seen < 10:
        view = view.__wrapped__
        seen += 1
    return view


@pytest.mark.unit
def test_every_route_survives_registration():
    """Five topic modules each register their own handlers now.

    One dropped from ``_ROUTE_MODULES`` loses its routes with no error.
    """
    app = Flask('alert-verification-package-test')
    alert_verification.register(app, logging.getLogger('av-package-test'))

    registered = {
        (rule.rule, rule.endpoint) for rule in app.url_map.iter_rules()
    }
    assert EXPECTED_RULES <= registered, (
        f'missing routes after the split: {sorted(EXPECTED_RULES - registered)}'
    )


@pytest.mark.unit
def test_handlers_still_close_over_route_logger():
    """The handlers log through ``logger.getChild('alert_verification')``.

    Each topic module rebuilds that local inside its own ``register``. If one
    stopped doing so the name would resolve to something else — or fail — only
    on the error path, which is exactly where nobody looks.
    """
    app = Flask('alert-verification-closure-test')
    alert_verification.register(app, logging.getLogger('av-closure-test'))

    view = _unwrap(app.view_functions['alert_verification_export'])
    closed_over = dict(zip(view.__code__.co_freevars, view.__closure__ or ()))
    assert 'route_logger' in closed_over, view.__code__.co_freevars
    assert closed_over['route_logger'].cell_contents.name.endswith('alert_verification')


@pytest.mark.unit
def test_the_page_handler_closes_over_repo_root():
    """``repo_root`` is derived from ``app.root_path``, not ``__file__``.

    That is why this split had no path hazard, unlike 3e and 3f — but the
    handlers that use it still need it rebuilt in their own module.
    """
    app = Flask('alert-verification-reporoot-test')
    alert_verification.register(app, logging.getLogger('av-reporoot-test'))

    view = _unwrap(app.view_functions['alert_verification'])
    freevars = set(view.__code__.co_freevars)
    assert 'route_logger' in freevars, view.__code__.co_freevars
    # It reaches repo_root indirectly, through the helper that captured it.
    assert '_describe_bundled_samples' in freevars, view.__code__.co_freevars

    describe = dict(zip(view.__code__.co_freevars, view.__closure__ or ()))[
        '_describe_bundled_samples'
    ].cell_contents
    assert 'repo_root' in describe.__code__.co_freevars


@pytest.mark.unit
@pytest.mark.parametrize('name,owner', sorted(PATCH_ONLY_ON_SUBMODULE.items()))
def test_mutable_globals_are_not_reachable_from_the_package(name, owner):
    """A patch aimed at the package must raise, not silently no-op.

    Verified by experiment, not assumption: with these re-exported and the
    async tests patching the package, all six still pass while writing to the
    real temp directory instead of ``tmp_path``.
    """
    assert not hasattr(alert_verification, name), (
        f'{name} must not be reachable from the package — a '
        f'monkeypatch.setattr aimed here would rebind a copy while '
        f'{owner}.py kept reading the original'
    )
    assert hasattr(getattr(alert_verification, owner), name)


@pytest.mark.unit
def test_patched_names_live_where_their_readers_are():
    """The two imported names the route tests replace."""
    # helpers._load_configured_fips calls it
    assert hasattr(helpers_mod, 'get_location_settings')
    # routes_self_test constructs it
    from webapp.routes.alert_verification import routes_self_test
    assert hasattr(routes_self_test, 'AlertSelfTestHarness')


@pytest.mark.unit
def test_dedented_helpers_reference_nothing_register_used_to_provide():
    """The four helpers were only safe to dedent because they capture nothing.

    Checking ``co_freevars`` here would be tautological — a module-level
    function always has an empty tuple. The invariant that can actually break
    is textual: a future edit inside one of these that reaches for
    ``route_logger``, ``repo_root`` or ``app`` compiles fine and raises
    ``NameError`` only when that branch runs.
    """
    provided_by_register = {'route_logger', 'repo_root', 'app'}
    tree = ast.parse((PACKAGE_DIR / 'helpers.py').read_text(encoding='utf-8'))

    offenders = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in provided_by_register:
                offenders.append(f'{node.name} references {sub.id}')

    assert not offenders, (
        'helpers.py is module scope — these names no longer exist there: '
        + ', '.join(offenders)
    )

    # And they really are the four that moved.
    module_level = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert module_level == {
        '_load_configured_fips',
        '_result_to_dict',
        '_resolve_window_days',
        '_serialize_csv_rows',
    }


@pytest.mark.unit
def test_no_import_cycles_between_package_modules():
    """The call chain crosses three modules and is easy to group wrongly.

    ``_process_temp_audio_file`` -> ``_detect_comprehensive_eas_segments`` ->
    ``_build_composite_audio_segment``. A first pass put the two ends in one
    module, which sandwiched ``eas_detection`` into a cycle.
    """
    edges: dict[str, set[str]] = {}
    for path in _package_modules():
        deps = set()
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                deps.add(node.module.split('.')[0])
        edges[path.stem] = deps

    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str):
        if state.get(node) == 1:
            return stack[stack.index(node):] + [node]
        if state.get(node) == 2:
            return None
        state[node] = 1
        stack.append(node)
        for dep in sorted(edges.get(node, ())):
            if dep in edges:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in sorted(edges):
        cycle = visit(node)
        assert cycle is None, 'import cycle: ' + ' -> '.join(cycle)


@pytest.mark.unit
def test_progress_and_result_stores_use_separate_directories():
    """``_result_dir`` is nested inside ``_progress_dir``.

    Both are computed once at import. Splitting them into different modules
    would have broken that derivation silently.
    """
    assert progress_mod._result_dir.startswith(progress_mod._progress_dir)
    assert progress_mod._result_dir != progress_mod._progress_dir


@pytest.mark.unit
def test_every_module_is_imported_by_the_package_init():
    init_tree = ast.parse((PACKAGE_DIR / '__init__.py').read_text(encoding='utf-8'))
    imported: set[str] = set()
    for node in ast.walk(init_tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module is None:
                imported.update(alias.name for alias in node.names)
            else:
                imported.add(node.module.split('.')[0])

    missing = {p.stem for p in _package_modules()} - imported
    assert not missing, f'modules never imported by the package __init__: {sorted(missing)}'


@pytest.mark.unit
def test_package_modules_stay_within_the_size_guidance():
    oversized = {
        path.name: len(path.read_text(encoding='utf-8').splitlines())
        for path in _package_modules() + [PACKAGE_DIR / '__init__.py']
        if len(path.read_text(encoding='utf-8').splitlines()) > 400
    }
    assert not oversized, f'modules over the 400-line guidance: {oversized}'


@pytest.mark.unit
def test_the_single_file_module_is_gone():
    assert not (REPO_ROOT / 'webapp' / 'routes' / 'alert_verification.py').exists()
