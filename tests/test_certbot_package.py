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

"""Structural guards for the webapp.admin.certbot package split.

``webapp/admin/certbot.py`` (1,946 lines) became a package. It had **no test
coverage at all** beforehand, so these are the first tests it has ever had, and
they are aimed at the three things the split could break silently:

* the writable ``certbot_data`` tree is located from ``__file__``, and the
  module now sits one directory deeper,
* every log record was named ``webapp.admin.certbot`` and would have gained a
  submodule suffix, and
* a route module dropped from the ``__init__`` imports vanishes from the URL
  map without raising anything.

None of the three raises on failure. The path one is the worst: certbot would
have quietly built a second tree under ``webapp/`` and the real certificates
would appear to have gone missing.
"""

import ast
import importlib
import logging
from pathlib import Path

import pytest
from flask import Flask

from webapp.admin import certbot
from webapp.admin.certbot import paths as paths_mod

PACKAGE_DIR = Path(certbot.__file__).parent
REPO_ROOT = Path(__file__).resolve().parents[1]

# Every rule the single-file module registered, read off its @certbot_bp.route
# decorators before the split. The blueprint carries url_prefix='/admin'.
EXPECTED_RULES = {
    '/admin/certbot',
    '/admin/api/certbot/settings',
    '/admin/api/certbot/certificate-status',
    '/admin/api/certbot/status',
    '/admin/api/certbot/renew-certificate',
    '/admin/api/certbot/obtain-certificate',
    '/admin/api/certbot/test-domain',
    '/admin/api/certbot/obtain-certificate-execute',
    '/admin/api/certbot/renew-certificate-execute',
    '/admin/api/certbot/enable-auto-renewal',
    '/admin/api/certbot/download-certificate',
    '/admin/api/certbot/logs',
    '/admin/api/certbot/install-certificate',
}


def _package_modules() -> list[Path]:
    return sorted(p for p in PACKAGE_DIR.glob('*.py') if p.name != '__init__.py')


@pytest.mark.unit
def test_certbot_directories_resolve_to_the_repository_root():
    """The one failure mode that produces no error at all.

    ``CERTBOT_BASE_DIR`` is ``Path(__file__).parent…``. The single-file module
    was ``webapp/admin/certbot.py`` and needed three ``.parent`` hops to reach
    the repository root; ``webapp/admin/certbot/paths.py`` needs four. With
    three, this silently becomes ``<repo>/webapp/certbot_data`` — certbot then
    builds a fresh empty tree there and every existing certificate looks like
    it has vanished.
    """
    assert paths_mod.CERTBOT_BASE_DIR == REPO_ROOT / 'certbot_data'
    assert paths_mod.CERTBOT_CONFIG_DIR == REPO_ROOT / 'certbot_data' / 'config'
    assert paths_mod.CERTBOT_WORK_DIR == REPO_ROOT / 'certbot_data' / 'work'
    assert paths_mod.CERTBOT_LOGS_DIR == REPO_ROOT / 'certbot_data' / 'logs'


@pytest.mark.unit
def test_no_module_reaches_the_repo_root_with_the_wrong_parent_count():
    """Catch a *new* ``__file__``-relative path added at the wrong depth.

    Every module in this package sits three directories below the repository
    root, so any ``Path(__file__)`` walk that means "the repo root" needs four
    ``.parent`` hops. This asserts nobody adds one with three.
    """
    offenders = []
    for path in _package_modules():
        text = path.read_text(encoding='utf-8')
        if 'Path(__file__).parent.parent.parent /' in text:
            offenders.append(path.name)
    assert not offenders, (
        'these resolve one directory short of the repository root: '
        + ', '.join(offenders)
    )


@pytest.mark.unit
def test_every_module_logs_under_the_pre_split_name():
    """All 92 call sites logged as ``webapp.admin.certbot`` before the split.

    Per-module ``getLogger(__name__)`` loggers would have renamed the records
    to ``webapp.admin.certbot.routes_obtain`` and friends, breaking any log
    filter or journald grep keyed on the old name.
    """
    from webapp.admin.certbot import log as log_mod

    assert log_mod.logger.name == 'webapp.admin.certbot'

    # And no module may quietly introduce its own.
    offenders = []
    for path in _package_modules():
        if path.name == 'log.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == 'logger' for t in node.targets):
                continue
            offenders.append(path.name)
    assert not offenders, (
        'these define their own logger instead of importing it from .log, '
        'which changes the record name: ' + ', '.join(offenders)
    )


@pytest.mark.unit
def test_every_route_survives_registration():
    """A route module that stops being imported vanishes without an error."""
    app = Flask('certbot-package-test')
    certbot.register_certbot_routes(app, logging.getLogger('certbot-package-test'))

    registered = {
        rule.rule for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith('certbot.')
    }
    assert EXPECTED_RULES <= registered, (
        f'missing routes after the split: {sorted(EXPECTED_RULES - registered)}'
    )


@pytest.mark.unit
def test_blueprint_import_name_is_the_package():
    """``blueprint.py`` must pass ``__package__``, not its own ``__name__``."""
    assert certbot.certbot_bp.import_name == 'webapp.admin.certbot'


@pytest.mark.unit
def test_blueprint_keeps_the_admin_url_prefix():
    """Routes are written without '/admin'; the prefix is applied at register.

    Adding '/admin' to a route decorator would produce '/admin/admin/certbot'
    and a 404. The module docstring warns about it; this checks it.
    """
    app = Flask('certbot-prefix-test')
    certbot.register_certbot_routes(app, logging.getLogger('certbot-prefix-test'))

    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith('certbot.'):
            assert rule.rule.startswith('/admin/'), rule.rule
            assert not rule.rule.startswith('/admin/admin/'), rule.rule


@pytest.mark.unit
def test_every_module_is_imported_by_the_package_init():
    """A route module nobody imports is a lost route."""
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
def test_importing_the_package_creates_the_certbot_tree():
    """``paths`` calls ``_ensure_certbot_directories()`` at module scope.

    The single-file module did this at its line 191. Losing the call would not
    raise here — it would fail later, inside certbot, as a permission or
    missing-directory error a long way from the cause.
    """
    importlib.import_module('webapp.admin.certbot')

    for directory in (
        paths_mod.CERTBOT_BASE_DIR,
        paths_mod.CERTBOT_CONFIG_DIR,
        paths_mod.CERTBOT_WORK_DIR,
        paths_mod.CERTBOT_LOGS_DIR,
    ):
        assert directory.is_dir(), f'{directory} was not created on import'


@pytest.mark.unit
def test_domain_and_email_patterns_still_discriminate():
    """These gate every certificate request; a broken regex is a real hole."""
    from webapp.admin.certbot.blueprint import DOMAIN_PATTERN, EMAIL_PATTERN

    for good in ('example.com', 'sub.example.co.uk', 'a-b.example.org', 'localhost'):
        assert DOMAIN_PATTERN.match(good), good
    for bad in ('-example.com', 'example-.com', 'exa mple.com', 'exam#ple.com', ''):
        assert not DOMAIN_PATTERN.match(bad), bad

    for good in ('me@example.com', 'first.last+tag@sub.example.co.uk'):
        assert EMAIL_PATTERN.match(good), good
    for bad in ('me@example', 'me@.com', 'me example.com', '@example.com', ''):
        assert not EMAIL_PATTERN.match(bad), bad


@pytest.mark.unit
def test_package_modules_stay_within_the_size_guidance():
    """AGENTS.md asks for Python modules under ~400 lines.

    ``routes_obtain_execute.py`` is the documented exception: the handler is a
    single 387-line ``try`` block, so module-level splitting cannot shrink it.
    Reducing it means extracting collaborators from the body, which is a
    behavioural refactor and needs characterization tests first — tracked as a
    follow-up in docs/development/LARGE_FILE_REFACTOR_PLAN.md.
    """
    known_exceptions = {'routes_obtain_execute.py'}

    oversized = {
        path.name: len(path.read_text(encoding='utf-8').splitlines())
        for path in _package_modules() + [PACKAGE_DIR / '__init__.py']
        if len(path.read_text(encoding='utf-8').splitlines()) > 400
    }
    unexpected = {k: v for k, v in oversized.items() if k not in known_exceptions}
    assert not unexpected, f'modules over the 400-line guidance: {unexpected}'

    # If the exception ever gets fixed, this test should stop excusing it.
    assert set(oversized) == known_exceptions, (
        f'update known_exceptions — now oversized: {sorted(oversized)}'
    )


@pytest.mark.unit
def test_the_single_file_module_is_gone():
    assert not (REPO_ROOT / 'webapp' / 'admin' / 'certbot.py').exists()
