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

"""Structural guards for the webapp.admin.maintenance package split.

``webapp/admin/maintenance.py`` (1,802 lines) became a package. Like certbot
it had no tests of its own, and it carries the same ``__file__`` hazard with a
wider blast radius: ``repo_root`` locates the backup and upgrade scripts *and*
the ``.env`` file the environment editor writes.

It also has a public surface that ``__all__`` does not fully describe —
``app_core/websocket_push.py`` imports ``get_operation_status``, which is not
listed there. That import sits inside a function whose caller logs and moves
on, so dropping it would have been silent. The audio_ingest split made exactly
that mistake with ``AudioSourceConfigDB``; the derived-import test below is
the fix that generalises.
"""

import ast
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
from flask import Flask

from webapp.admin import maintenance
from webapp.admin.maintenance import operations as operations_mod
from webapp.admin.maintenance import paths as paths_mod

PACKAGE_DIR = Path(maintenance.__file__).parent
REPO_ROOT = Path(__file__).resolve().parents[1]

_SKIP_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'build', 'dist'}

# Every rule the single-file module registered, read off its
# @maintenance_bp.route decorators before the split.
#
# Note the blueprint takes no url_prefix — the '/admin' is written into each
# route decorator. That is the opposite of the certbot blueprint, which is
# registered with url_prefix='/admin' and whose decorators must *not* repeat
# it. Do not "harmonise" the two without checking the resulting URL map.
EXPECTED_RULES = {
    '/admin/operations/status',
    '/admin/operations/backup',
    '/admin/operations/upgrade',
    '/admin/check_db_health',
    '/admin/optimize_db',
    '/admin/env_config',
    '/admin/trigger_poll',
    '/admin/location_settings',
    '/admin/alert_filtering',
    '/admin/location_reference',
    '/admin/lookup_county_fips',
    '/admin/import_alert',
    '/admin/alerts',
    '/admin/alerts/<int:alert_id>',
    '/admin/mark_expired',
    '/admin/clear_expired',
    '/admin/eas_settings',
}


def _package_modules() -> list[Path]:
    return sorted(p for p in PACKAGE_DIR.glob('*.py') if p.name != '__init__.py')


def _imports_from_maintenance() -> list[tuple[str, str]]:
    """Every ``from webapp.admin.maintenance import X`` in the tree."""
    found: list[tuple[str, str]] = []
    for path in REPO_ROOT.rglob('*.py'):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != 'webapp.admin.maintenance' or node.level:
                continue
            for alias in node.names:
                if alias.name != '*':
                    found.append((alias.name, str(path.relative_to(REPO_ROOT))))
    return sorted(set(found))


@pytest.mark.unit
def test_repo_root_is_the_repository_root():
    """The failure mode here is silent and destructive.

    ``repo_root`` locates ``tools/create_backup.py`` and
    ``bin/eas-station-run-update``, is passed as their ``cwd``, and resolves
    the ``.env`` the environment editor reads and writes. The single-file module
    was ``webapp/admin/maintenance.py`` and needed three ``.parent`` hops;
    ``webapp/admin/maintenance/paths.py`` needs four. With three it becomes
    ``<repo>/webapp`` — the backup would point at a script that does not
    exist, and the env editor would edit a ``.env`` nothing reads.
    """
    assert paths_mod.repo_root == REPO_ROOT
    assert (paths_mod.repo_root / 'tools').is_dir()


@pytest.mark.unit
def test_no_module_reaches_the_repo_root_with_the_wrong_parent_count():
    """Catch a *new* ``__file__`` walk added at the pre-split depth."""
    offenders = [
        path.name
        for path in _package_modules()
        if 'Path(__file__).resolve().parent.parent.parent\n' in path.read_text(encoding='utf-8')
    ]
    assert not offenders, (
        'these resolve one directory short of the repository root: ' + ', '.join(offenders)
    )


@pytest.mark.unit
def test_every_absolute_import_of_the_package_resolves():
    """Including the ones ``__all__`` does not mention.

    ``get_operation_status`` is a route handler, absent from ``__all__``, and
    imported by ``app_core/websocket_push.py`` inside a function whose caller
    swallows the failure. Deriving the list from the tree is what makes this
    guard immune to the drift that broke audio_ingest.
    """
    dangling = [
        (name, source)
        for name, source in _imports_from_maintenance()
        if not hasattr(maintenance, name)
    ]
    assert not dangling, 'imports that no longer resolve: ' + ', '.join(
        f'{name} (from {source})' for name, source in dangling
    )


@pytest.mark.unit
@pytest.mark.parametrize('name', [
    'NOAAImportError',
    'NOAA_API_BASE_URL',
    'NOAA_ALLOWED_QUERY_PARAMS',
    'NOAA_USER_AGENT',
    'build_noaa_alert_request',
    'format_noaa_timestamp',
    'normalize_manual_import_datetime',
    'register_maintenance_routes',
    'retrieve_noaa_alerts',
    'serialize_admin_alert',
])
def test_declared_public_surface_still_resolves(name):
    """``__all__`` is unchanged from the single-file module."""
    assert name in maintenance.__all__
    assert hasattr(maintenance, name)


@pytest.mark.unit
def test_every_route_survives_registration():
    """A route module that stops being imported vanishes without an error."""
    app = Flask('maintenance-package-test')
    maintenance.register_maintenance_routes(
        app, logging.getLogger('maintenance-package-test')
    )

    registered = {
        rule.rule for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith('maintenance.')
    }
    assert EXPECTED_RULES <= registered, (
        f'missing routes after the split: {sorted(EXPECTED_RULES - registered)}'
    )


@pytest.mark.unit
def test_blueprint_import_name_is_the_package():
    assert maintenance.maintenance_bp.import_name == 'webapp.admin.maintenance'


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
def test_operation_state_is_shared_not_copied():
    """The background threads mutate this dict in place.

    Every module must see the same object. A module that rebound
    ``_OPERATION_STATE`` — rather than mutating it — would silently give the
    status endpoint a private copy that never updates.
    """
    assert operations_mod._OPERATION_STATE is not None
    for key in ('backup', 'upgrade'):
        assert key in operations_mod._OPERATION_STATE

    rebinding = []
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == '_OPERATION_STATE' for t in node.targets
            ):
                if path.name != 'operations.py':
                    rebinding.append(path.name)
    assert not rebinding, f'_OPERATION_STATE rebound outside operations.py: {rebinding}'


@pytest.mark.unit
def test_background_operation_runs_without_an_application_context():
    """The worker thread must log through the injected logger, not current_app.

    ``_start_background_operation`` spawns a bare daemon thread. Flask contexts
    are per-thread, so ``current_app`` is unavailable there. Using it meant the
    very first statement in the worker raised ``RuntimeError``, the ``except``
    handler raised again on its own ``current_app`` call, and the subprocess
    was never launched — one-click backup and one-click upgrade both reported a
    failed operation with an empty message and did nothing.

    The caller already resolves ``current_app.logger`` inside the request
    context and passes it in; the worker just has to use it.
    """
    marker = Path(tempfile.gettempdir()) / f'eas-op-test-{os.getpid()}'
    if marker.exists():
        marker.unlink()

    operations_state = operations_mod._OPERATION_STATE['backup']
    operations_state['running'] = False

    operations_mod._start_background_operation(
        'backup',
        [sys.executable, '-c', f'open({str(marker)!r}, "w").write("ran")'],
        cwd=Path.cwd(),
        logger=logging.getLogger('maintenance-op-test'),
        description='Backup',
    )

    deadline = time.time() + 15
    while time.time() < deadline and operations_state['running']:
        time.sleep(0.05)

    try:
        assert not operations_state['running'], 'operation never finished'
        assert marker.exists(), (
            'the subprocess never ran — the worker raised before reaching it'
        )
        assert operations_state['last_status'] == 'success', (
            operations_state['last_status'], operations_state['last_message']
        )
    finally:
        if marker.exists():
            marker.unlink()


@pytest.mark.unit
def test_no_module_uses_current_app_inside_a_background_thread():
    """Guard the shape, not just the one instance.

    ``operations.py`` is the only module here that runs code off the request
    thread, so ``current_app`` must not appear in it at all.
    """
    source = (PACKAGE_DIR / 'operations.py').read_text(encoding='utf-8')
    assert 'current_app' not in source, (
        'operations.py runs work in a daemon thread, where current_app raises'
    )


@pytest.mark.unit
def test_noaa_query_parameters_stay_allow_listed():
    """The manual-import form forwards user input into the query string.

    ``build_noaa_alert_request`` drops anything not in the allow-list; that is
    the only thing standing between a form field and an arbitrary upstream
    query parameter.
    """
    from webapp.admin.maintenance.noaa import NOAA_ALLOWED_QUERY_PARAMS

    assert 'area' in NOAA_ALLOWED_QUERY_PARAMS
    assert isinstance(NOAA_ALLOWED_QUERY_PARAMS, frozenset)

    # Keyword-only: an unexpected name is a TypeError, not a smuggled param.
    with pytest.raises(TypeError):
        maintenance.build_noaa_alert_request(not_a_real_param='injected')

    url, params = maintenance.build_noaa_alert_request(area='OH')
    assert url == 'https://api.weather.gov/alerts'
    assert params == {'area': 'OH'}

    # `limit` is allow-listed but deliberately not sent upstream — it is
    # applied client-side by slicing in retrieve_noaa_alerts. Asserting it
    # here records that, so a future change that starts forwarding it is a
    # visible decision rather than a silent one.
    _url, params = maintenance.build_noaa_alert_request(area='OH', limit=5)
    assert 'limit' not in params

    # The identifier path builds a path segment, not a query, and quotes it.
    url, params = maintenance.build_noaa_alert_request(identifier='urn:oid:2.49/../x')
    assert params is None
    assert url.startswith('https://api.weather.gov/alerts/')
    assert '/../' not in url


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
    assert not (REPO_ROOT / 'webapp' / 'admin' / 'maintenance.py').exists()
