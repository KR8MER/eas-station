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

"""Regression tests for AudioCommandSubscriber.reconcile_orphaned_radio_sources().

Deleting a RadioReceiver sends a single, best-effort 'source_delete' Redis
command (webapp/admin/audio_ingest/radio_sources.py) to tear its audio
source down in the running eas-station-audio.service process. Found live:
an orphaned 'sdr-wxmon' RedisSDRSourceAdapter that outlived its deleted
receiver -- its AudioSourceConfigDB row was gone, but the adapter stayed
registered in AudioIngestController, so app_core/audio/ingest.py's stall
supervisor just quarantine-retried it forever (every retry stalls
immediately, since the demod service has nothing to publish for a receiver
id nothing references any more), respawning FFmpeg/Icecast connections
every ~30s-4min.

These tests pin down the periodic self-heal: any RedisSDRSourceAdapter with
no matching AudioSourceConfigDB(source_type='sdr', managed_by='radio') row
gets torn down (EAS monitor watcher, Icecast stream, and the controller
registration itself) the next time reconcile runs, and non-radio sources
(plain stream monitors like WNCI/ERN-LUC) are never touched.
"""

import sys
import types
from types import SimpleNamespace

import pytest

import app_core.audio.redis_commands as redis_commands


class _AppContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeApp:
    def app_context(self):
        return _AppContext()


class _FakeRedisSDRSourceAdapter:
    """Stand-in for RedisSDRSourceAdapter. Reconcile identifies radio-managed
    sources purely by isinstance check against the real class, so tests
    monkeypatch that class to this one and construct instances of it."""


class _FakeStreamAdapter:
    """A non-SDR adapter (e.g. an internet stream monitor like WNCI/ERN-LUC)
    that must never be touched by the reconciliation."""


def _stub_config_db_module(monkeypatch, *, rows):
    """Install a fake app_core.models with just enough of AudioSourceConfigDB
    to answer the query the reconciler issues."""

    fake_models = types.ModuleType('app_core.models')

    class _FakeQuery:
        def filter_by(self, **kwargs):
            assert kwargs == {'source_type': 'sdr'}
            return self

        def all(self):
            return rows

    class _FakeAudioSourceConfigDB:
        query = _FakeQuery()

    fake_models.AudioSourceConfigDB = _FakeAudioSourceConfigDB
    monkeypatch.setitem(sys.modules, 'app_core.models', fake_models)


def _db_row(name, managed_by='radio', source_type='sdr'):
    return SimpleNamespace(
        name=name,
        source_type=source_type,
        config_params={'managed_by': managed_by},
    )


def _make_subscriber(monkeypatch, *, sources, app=None):
    stub_redis = SimpleNamespace(ping=lambda: True)
    monkeypatch.setattr(redis_commands, 'get_redis_client', lambda *a, **k: stub_redis)
    monkeypatch.setattr(
        redis_commands.AudioCommandSubscriber, '_check_connection', lambda self: None
    )

    import app_core.audio.redis_sdr_adapter as redis_sdr_adapter
    monkeypatch.setattr(redis_sdr_adapter, 'RedisSDRSourceAdapter', _FakeRedisSDRSourceAdapter)

    sub = redis_commands.AudioCommandSubscriber.__new__(redis_commands.AudioCommandSubscriber)
    sub.audio_controller = SimpleNamespace(
        get_all_sources=lambda: dict(sources),
        remove_source=lambda name: sources.pop(name, None),
    )
    sub.auto_streaming_service = SimpleNamespace(remove_source=lambda name: removed_from_icecast.append(name))
    sub.eas_monitor = SimpleNamespace(remove_monitor_for_source=lambda name: removed_watchers.append(name))
    sub.app = app
    sub.archiver_registry = {}
    sub.redis_client = stub_redis
    return sub


removed_from_icecast = []
removed_watchers = []


@pytest.fixture(autouse=True)
def _reset_removal_logs():
    removed_from_icecast.clear()
    removed_watchers.clear()
    yield
    removed_from_icecast.clear()
    removed_watchers.clear()


def test_reconcile_removes_source_with_no_backing_db_row(monkeypatch):
    sources = {
        'sdr-wbks': _FakeRedisSDRSourceAdapter(),
        'sdr-wxmon': _FakeRedisSDRSourceAdapter(),
    }
    sub = _make_subscriber(monkeypatch, sources=sources, app=_FakeApp())
    _stub_config_db_module(monkeypatch, rows=[_db_row('sdr-wbks')])

    removed = sub.reconcile_orphaned_radio_sources()

    assert removed == 1
    assert 'sdr-wxmon' not in sources
    assert 'sdr-wbks' in sources
    assert removed_watchers == ['sdr-wxmon']
    assert removed_from_icecast == ['sdr-wxmon']


def test_reconcile_never_touches_non_radio_sources(monkeypatch):
    sources = {
        'WNCI': _FakeStreamAdapter(),
        'sdr-wxmon': _FakeRedisSDRSourceAdapter(),
    }
    sub = _make_subscriber(monkeypatch, sources=sources, app=_FakeApp())
    # No DB rows at all -- if WNCI were (wrongly) treated as a candidate it
    # would get removed too, since nothing backs it either.
    _stub_config_db_module(monkeypatch, rows=[])

    removed = sub.reconcile_orphaned_radio_sources()

    assert removed == 1
    assert 'WNCI' in sources
    assert 'sdr-wxmon' not in sources
    assert removed_watchers == ['sdr-wxmon']


def test_reconcile_is_noop_when_all_radio_sources_have_db_rows(monkeypatch):
    sources = {'sdr-wbks': _FakeRedisSDRSourceAdapter()}
    sub = _make_subscriber(monkeypatch, sources=sources, app=_FakeApp())
    _stub_config_db_module(monkeypatch, rows=[_db_row('sdr-wbks')])

    removed = sub.reconcile_orphaned_radio_sources()

    assert removed == 0
    assert 'sdr-wbks' in sources
    assert removed_watchers == []


def test_reconcile_skips_db_lookup_when_no_radio_sources_exist(monkeypatch):
    sources = {'WNCI': _FakeStreamAdapter()}
    # app is None: if the reconciler tried to open an app context here it
    # would crash (NoneType has no app_context()) -- proves it never gets
    # that far when there are no RedisSDRSourceAdapter candidates at all.
    sub = _make_subscriber(monkeypatch, sources=sources, app=None)

    removed = sub.reconcile_orphaned_radio_sources()

    assert removed == 0


def test_reconcile_returns_zero_without_an_app_reference(monkeypatch):
    sources = {'sdr-wxmon': _FakeRedisSDRSourceAdapter()}
    sub = _make_subscriber(monkeypatch, sources=sources, app=None)

    removed = sub.reconcile_orphaned_radio_sources()

    assert removed == 0
    assert 'sdr-wxmon' in sources  # left alone rather than guessed at


def test_reconcile_swallows_db_errors_without_removing_anything(monkeypatch):
    sources = {'sdr-wxmon': _FakeRedisSDRSourceAdapter()}
    sub = _make_subscriber(monkeypatch, sources=sources, app=_FakeApp())

    fake_models = types.ModuleType('app_core.models')

    class _ExplodingQuery:
        def filter_by(self, **kwargs):
            raise RuntimeError('database unavailable')

    class _FakeAudioSourceConfigDB:
        query = _ExplodingQuery()

    fake_models.AudioSourceConfigDB = _FakeAudioSourceConfigDB
    monkeypatch.setitem(sys.modules, 'app_core.models', fake_models)

    removed = sub.reconcile_orphaned_radio_sources()

    assert removed == 0
    assert 'sdr-wxmon' in sources


def test_source_delete_command_still_removes_via_the_shared_helper(monkeypatch):
    """Regression test for the _remove_source_everywhere() refactor: the
    'source_delete' Redis command must still tear down the EAS monitor
    watcher, the Icecast stream, and the controller registration."""
    sources = {'sdr-wxmon': _FakeRedisSDRSourceAdapter()}
    sub = _make_subscriber(monkeypatch, sources=sources, app=None)

    result = sub._execute_command('source_delete', {'source_name': 'sdr-wxmon'})

    assert result['success'] is True
    assert 'sdr-wxmon' not in sources
    assert removed_watchers == ['sdr-wxmon']
    assert removed_from_icecast == ['sdr-wxmon']
