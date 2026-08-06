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

"""Structural guards for the webapp.admin.audio_ingest package split.

``webapp/admin/audio_ingest.py`` (3,180 lines) became a package. The split was
pure motion for 69 of its 73 top-level definitions; the four that changed are
each pinned here, along with the two invariants a future edit is most likely to
break silently:

* a route module that stops being imported disappears from the URL map without
  raising anything, and
* importing a mutable module global by value (``from .controller import
  _audio_controller``) snapshots ``None`` forever.
"""

import ast
import logging
from pathlib import Path

import pytest
from flask import Flask

from webapp.admin import audio_ingest
from webapp.admin.audio_ingest import controller as controller_mod

PACKAGE_DIR = Path(audio_ingest.__file__).parent

# Every rule the single-file module registered, as read off its
# @audio_ingest_bp.route decorators before the split.
EXPECTED_RULES = {
    '/api/audio/sources',
    '/api/audio/sources/test-stream',
    '/api/audio/sources/<path:source_name>',
    '/api/audio/sources/<path:source_name>/rbds/history',
    '/api/audio/sources/<path:source_name>/start',
    '/api/audio/sources/<path:source_name>/stop',
    '/api/audio/metrics',
    '/api/audio/metrics/latest',
    '/api/audio/health',
    '/api/audio/alerts',
    '/api/audio/alerts/<int:alert_id>/acknowledge',
    '/api/audio/alerts/<int:alert_id>/resolve',
    '/api/audio/alerts/resolve-all',
    '/api/audio/devices',
    '/api/audio/waveform/<path:source_name>',
    '/api/audio/spectrogram/<path:source_name>',
    '/api/audio/stream/<path:source_name>',
    '/api/audio/health/dashboard',
    '/api/audio/health/metrics',
    '/api/audio/icecast/config',
    '/api/audio/icecast/start',
    '/api/audio/icecast/stop',
    '/audio/health/dashboard',
}

# The names other packages and the test suite import from this one. If a split
# drops one of these the importer fails at import time, which is loud — but it
# fails in *their* test file, so it is cheaper to assert it here.
PUBLIC_IMPORTS = (
    # webapp/routes_settings_radio.py
    'ensure_sdr_audio_monitor_source',
    'list_radio_managed_audio_sources',
    'remove_radio_managed_audio_source',
    '_get_audio_controller',
    '_get_icecast_stream_url',
    # app_core/websocket_push.py
    '_read_audio_metrics_from_redis',
    # webapp/admin/__init__.py
    'register_audio_ingest_routes',
    # tests/test_stream_auth.py
    '_describe_stream_status',
    '_redact_device_params',
)


def _package_modules() -> list[Path]:
    return sorted(p for p in PACKAGE_DIR.glob('*.py') if p.name != '__init__.py')


@pytest.mark.unit
@pytest.mark.parametrize('name', PUBLIC_IMPORTS)
def test_shim_reexports_the_names_other_modules_import(name):
    assert hasattr(audio_ingest, name), (
        f'{name} is imported from webapp.admin.audio_ingest elsewhere in the tree; '
        'the package __init__ must keep re-exporting it.'
    )


@pytest.mark.unit
def test_blueprint_import_name_is_the_package():
    """The Blueprint moved into blueprint.py but must keep its import_name.

    Flask resolves a blueprint's root path (and therefore any template or
    static folder it later gains) from import_name. Using the module's own
    ``__name__`` there would have quietly changed it to
    ``webapp.admin.audio_ingest.blueprint``.
    """
    assert audio_ingest.audio_ingest_bp.import_name == 'webapp.admin.audio_ingest'


@pytest.mark.unit
def test_every_route_survives_registration():
    """A route module that stops being imported vanishes without an error."""
    app = Flask('audio-ingest-package-test')
    audio_ingest.register_audio_ingest_routes(app, logging.getLogger('audio-ingest-package-test'))

    registered = {
        rule.rule for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith('audio_ingest.')
    }
    assert EXPECTED_RULES <= registered, (
        f'missing routes after the split: {sorted(EXPECTED_RULES - registered)}'
    )


@pytest.mark.unit
def test_register_fans_the_logger_out_to_every_submodule():
    """Pre-split there was one ``logger`` global and registration rebound it.

    The package has one per module, so registration has to set all of them —
    otherwise the caller's logger silently applies to none of the code that
    actually logs.
    """
    sentinel = logging.getLogger('audio-ingest-logger-fanout')
    app = Flask('audio-ingest-logger-test')
    audio_ingest.register_audio_ingest_routes(app, sentinel)

    for module in audio_ingest._LOGGING_MODULES:
        assert module.logger is sentinel, f'{module.__name__} kept its own logger'

    assert audio_ingest._LOGGING_MODULES, 'the fan-out list must not be empty'


@pytest.mark.unit
def test_logger_fanout_covers_every_module_that_logs():
    """The fan-out list is hand-written; this keeps it honest."""
    fanned_out = {m.__name__.rsplit('.', 1)[-1] for m in audio_ingest._LOGGING_MODULES}

    for path in _package_modules():
        tree = ast.parse(path.read_text())
        defines_logger = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'logger' for t in node.targets)
            for node in tree.body
        )
        if defines_logger:
            assert path.stem in fanned_out, (
                f'{path.stem} defines a module logger but is missing from '
                '_LOGGING_MODULES, so register_audio_ingest_routes will not rebind it'
            )


@pytest.mark.unit
def test_peek_audio_controller_sees_the_current_singleton():
    """``_audio_controller`` must never be imported by value across modules.

    ``from .controller import _audio_controller`` binds ``None`` at import time
    and never updates, so the fallback path in
    ``remove_radio_managed_audio_source`` would silently stop removing the
    source from the local controller. The accessor is what makes it correct.
    """
    sentinel = object()
    previous = controller_mod._audio_controller
    try:
        controller_mod._audio_controller = sentinel
        assert controller_mod._peek_audio_controller() is sentinel
    finally:
        controller_mod._audio_controller = previous


@pytest.mark.unit
def test_no_module_imports_a_mutable_global_by_value():
    """Guard the whole class of bug, not just the one instance of it."""
    mutable_globals = {
        '_audio_controller',
        '_auto_streaming_service',
        '_streaming_lock_file',
        '_audio_initialization_lock_file',
        '_initialization_started',
        '_initialization_lock',
    }

    offenders = []
    for path in _package_modules():
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            for alias in node.names:
                if alias.name in mutable_globals:
                    offenders.append(f'{path.name}: from .{node.module} import {alias.name}')

    assert not offenders, (
        'these imports snapshot a mutable module global at import time and will '
        f'never see a later rebinding: {offenders}'
    )


@pytest.mark.unit
def test_package_modules_stay_within_the_size_guidance():
    """AGENTS.md asks for Python modules under ~400 lines.

    The whole package clears it. ``routes_sources.py`` was the last holdout at
    749 lines — ``api_get_audio_sources`` alone was 327 of them — until the
    listing reconciliation moved to ``listing``/``source_payload`` and the write
    endpoints to ``routes_sources_write``. There are no exemptions left, so this
    is an exact check.
    """
    over = {
        path.name: len(path.read_text().splitlines())
        for path in _package_modules()
        if len(path.read_text().splitlines()) > 400
    }
    assert not over, f'oversized module(s) in the package: {over}'
