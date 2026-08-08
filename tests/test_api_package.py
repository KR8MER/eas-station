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

"""Structural guards for the webapp.admin.api package split.

``webapp/admin/api.py`` (2,105 lines) became a package. The split was pure
motion — all 21 top-level definitions are ``ast.dump()``-identical — so what
needs pinning is not the code but the wiring around it, where a mistake is
silent:

* a route module that stops being imported in ``__init__`` disappears from the
  URL map without raising anything,
* the blueprint's ``import_name`` shifts if ``blueprint.py`` passes its own
  ``__name__``, and
* the CPU sample cache stops updating if any module imports it by value.
"""

import ast
import importlib
import logging
from pathlib import Path

import pytest
from flask import Flask

from webapp.admin import api
from webapp.admin.api import county as county_mod
from webapp.admin.api import hostinfo as hostinfo_mod

PACKAGE_DIR = Path(api.__file__).parent
REPO_ROOT = Path(__file__).resolve().parents[1]

# Every rule the single-file module registered, read off its @api_bp.route
# decorators before the split.
EXPECTED_RULES = {
    '/api/alerts/<int:alert_id>/geometry',
    '/alerts/<int:alert_id>',
    '/alerts/<int:alert_id>/export.pdf',
    '/alerts/<int:alert_id>/export-image.png',
    '/alerts/<int:alert_id>/ipaws_audio',
    '/api/alerts',
    '/api/alerts/historical',
    '/api/boundaries',
    '/api/system_status',
    '/api/system_health',
    '/api/system_health/history',
    '/api/smart_diag',
}

# Names mutated under ``global``. Importing one of these by value snapshots it
# at import time, so the importer never sees an update.
MUTABLE_GLOBALS = {'_last_cpu_sample_timestamp', '_last_cpu_sample_value'}


def _package_modules() -> list[Path]:
    return sorted(p for p in PACKAGE_DIR.glob('*.py') if p.name != '__init__.py')


@pytest.mark.unit
def test_every_route_survives_registration():
    """A route module that stops being imported vanishes without an error.

    The side-effect imports in ``__init__`` *are* the registration. Dropping
    one produces a 404 in production and no failure anywhere else.
    """
    app = Flask('api-package-test')
    api.register_api_routes(app, logging.getLogger('api-package-test'))

    registered = {
        rule.rule for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith('api.')
    }
    assert EXPECTED_RULES <= registered, (
        f'missing routes after the split: {sorted(EXPECTED_RULES - registered)}'
    )


@pytest.mark.unit
def test_blueprint_import_name_is_the_package():
    """``blueprint.py`` must pass ``__package__``, not its own ``__name__``.

    Flask resolves a blueprint's root path — and therefore any template or
    static folder it later gains — from ``import_name``. ``__name__`` here
    would silently make it ``webapp.admin.api.blueprint``.
    """
    assert api.api_bp.import_name == 'webapp.admin.api'


@pytest.mark.unit
def test_blueprint_has_no_folder_that_root_path_would_resolve():
    """Documents the one thing the split *did* change, and why it is inert.

    ``import_name`` is unchanged, but it now names a package rather than a
    module, so Flask derives ``root_path`` as ``webapp/admin/api`` where it
    used to be ``webapp/admin``. Nothing reads it: the blueprint sets neither
    a template folder nor a static folder, and never calls ``open_resource``.

    If someone adds one of those later they will get the package directory,
    which is almost certainly what they want — but it is a different directory
    from the pre-split one, so this test exists to make that a deliberate
    decision rather than a surprise.
    """
    assert api.api_bp.template_folder is None
    assert api.api_bp.static_folder is None
    assert Path(api.api_bp.root_path) == PACKAGE_DIR


@pytest.mark.unit
def test_registration_attaches_the_logger_the_handlers_use():
    """Handlers log through ``api_bp.logger``; registration is what sets it."""
    sentinel = logging.getLogger('api-logger-test')
    app = Flask('api-logger-app')
    api.register_api_routes(app, sentinel)

    assert api.api_bp.logger is sentinel


@pytest.mark.unit
def test_no_module_imports_a_mutable_global_by_value():
    """``_last_cpu_sample_*`` must stay reachable only through ``hostinfo``.

    ``_get_cpu_usage_percent`` rebinds these under ``global``. A
    ``from .hostinfo import _last_cpu_sample_value`` elsewhere would bind the
    initial value forever and never see a refresh — and would read as working
    code.
    """
    offenders = []
    for path in _package_modules() + [PACKAGE_DIR / '__init__.py']:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if alias.name in MUTABLE_GLOBALS:
                    offenders.append(f'{path.name} imports {alias.name}')
    assert not offenders, (
        'mutable globals must be reached through their module, not imported: '
        + ', '.join(offenders)
    )


@pytest.mark.unit
def test_the_cpu_sample_cache_lives_with_the_function_that_mutates_it():
    """The ``global`` statement only binds names in the module it appears in."""
    for name in MUTABLE_GLOBALS:
        assert hasattr(hostinfo_mod, name), (
            f'{name} must live in hostinfo alongside _get_cpu_usage_percent'
        )


@pytest.mark.unit
def test_every_module_is_imported_by_the_package_init():
    """A module nobody imports is dead weight; a route module is a lost route."""
    init_tree = ast.parse((PACKAGE_DIR / '__init__.py').read_text(encoding='utf-8'))
    imported: set[str] = set()
    for node in ast.walk(init_tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module is None:
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            imported.add(node.module.split('.')[0])

    missing = {p.stem for p in _package_modules()} - imported
    assert not missing, f'modules never imported by webapp/admin/api/__init__.py: {sorted(missing)}'


@pytest.mark.unit
def test_package_modules_stay_within_the_size_guidance():
    """AGENTS.md asks for Python modules under ~400 lines."""
    oversized = {
        path.name: len(path.read_text(encoding='utf-8').splitlines())
        for path in _package_modules() + [PACKAGE_DIR / '__init__.py']
        if len(path.read_text(encoding='utf-8').splitlines()) > 400
    }
    assert not oversized, f'modules over the 400-line guidance: {oversized}'


@pytest.mark.unit
def test_the_single_file_module_is_gone():
    """The package replaced it; a leftover .py would shadow nothing but confuse."""
    assert not (REPO_ROOT / 'webapp' / 'admin' / 'api.py').exists()


# ---------------------------------------------------------------------------
# _detect_county_wide, exercised directly rather than by grepping the source
# ---------------------------------------------------------------------------


class _StubAlert:
    """The two attributes ``_detect_county_wide`` reads."""

    def __init__(self, area_desc=None, raw_json=None):
        self.area_desc = area_desc
        self.raw_json = raw_json


@pytest.fixture
def putnam_ohio(monkeypatch):
    """Configure the station as Putnam County, Ohio (FIPS 039137).

    ``state_code`` is the two-letter postal code — ``DEFAULT_STATE_CODE`` is
    ``"OH"``. That matters: the ``_multi_county_list`` guard counts occurrences
    of ``", <state_code>"``, and NWS writes multi-county area descriptions as
    ``"Allen, OH; Putnam, OH; Van Wert, OH"``. With a spelled-out ``"ohio"``
    here the guard would count zero and the false positive would come back.
    """
    # ``importlib.import_module`` returns sys.modules[name] directly. Writing
    # ``import app_core.location`` and then reaching through ``app_core.location``
    # fails under a full-suite run with "module 'app_core' has no attribute
    # 'location'": the submodule attribute is only set on the parent by the
    # import that first executes it, and by collection time something else has
    # already put it in sys.modules. conftest.py documents the same trap for
    # ``app_core.auth``.
    location_mod = importlib.import_module('app_core.location')

    monkeypatch.setattr(
        location_mod,
        'get_location_settings',
        lambda: {
            'county_name': 'Putnam County',
            'state_code': 'OH',
            'fips_codes': ['039137'],
        },
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    'area_desc, expected',
    [
        # The bug this heuristic was fixed for: a different county in the
        # same state must not match on the generic word "county" plus the
        # state code alone.
        ('Henry County, OH', False),
        ('Henry County; Fulton County; Williams County; OH', False),
        # The exact area_desc from the SVR alert that triggered the
        # 99.4%/Allen County false positive. The polygon covers only SE
        # Putnam County, so this is a multi-county alert, not county-wide.
        ('Allen, OH; Putnam, OH; Van Wert, OH', False),
        ('Putnam, OH; Allen, OH', False),
        # Genuine county-wide coverage.
        ('Putnam County, OH', True),
        ('Ottawa; Blanchard Township; Putnam; OH', True),
        ('The entire county is affected', True),
        ('state of oh', True),
    ],
)
def test_detect_county_wide_from_area_desc(putnam_ohio, area_desc, expected):
    """Call the real function instead of mirroring its logic in the test.

    The previous regression tests reimplemented the two heuristics locally and
    then grepped ``webapp/admin/api.py`` to check the source still matched. A
    copy of the logic cannot catch a change to the original, and the grep
    broke the moment the file moved. Exercising the function directly does
    both jobs.
    """
    assert county_mod._detect_county_wide(_StubAlert(area_desc=area_desc)) is expected


@pytest.mark.unit
def test_detect_county_wide_matches_statewide_same_code(putnam_ohio):
    """A statewide SAME code (039000) covers the configured county."""
    alert = _StubAlert(
        area_desc='',
        raw_json={'properties': {'geocode': {'SAME': ['039000']}}},
    )
    assert county_mod._detect_county_wide(alert) is True


@pytest.mark.unit
def test_detect_county_wide_ignores_an_exact_county_same_code(putnam_ohio):
    """039137 means the alert *affects* Putnam, not that it covers all of it."""
    alert = _StubAlert(
        area_desc='',
        raw_json={'properties': {'geocode': {'SAME': ['039137']}}},
    )
    assert county_mod._detect_county_wide(alert) is False


@pytest.mark.unit
def test_detect_county_wide_ignores_another_states_statewide_code(putnam_ohio):
    """018000 is statewide Indiana — not our state."""
    alert = _StubAlert(
        area_desc='',
        raw_json={'properties': {'geocode': {'SAME': ['018000']}}},
    )
    assert county_mod._detect_county_wide(alert) is False
