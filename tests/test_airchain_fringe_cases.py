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

"""Tests covering airchain fringe cases and the specific bugs fixed in this PR.

Bug summary
-----------
1. OTA broadcast silently skipped when the EAS monitor thread had no Flask app
   context.  ``_auto_forward_to_air_chain`` guarded on ``has_app_context()``
   which returned False in the daemon thread, so every OTA alert was dropped.
   Fix: ``initialize_eas_monitor`` now wraps the alert callback with
   ``app.app_context()`` before starting the monitor thread.

2. ``EASBroadcaster.handle_alert()`` set ``same_triggered=True`` inside the
   initial ``result.update()`` block *before* the database commit.  If the
   commit raised an exception the function returned early with
   ``same_triggered=True`` even though no record was saved and no audio played,
   causing callers to log a false-positive success.
   Fix: ``same_triggered`` is now set only after the commit succeeds.

3. ``load_eas_config()`` used ``EASSettings.query.get(1)`` which requires a
   Flask application context.  The standalone CAP poller runs outside any Flask
   context, so ``db_broadcast_enabled`` was always ``None`` and fell back to
   the ``EAS_BROADCAST_ENABLED`` env-var default (``false``), silently disabling
   auto-forwarding even when the operator had enabled it in the web UI.
   Fix: a ``db_session`` fallback path (mirroring the existing TTS settings
   fallback) is now used when the Flask path fails.

4. ``alert_forwarding.py`` used the deprecated ``datetime.utcnow()`` when
   building the Redis payload.  This produces a naive datetime which will not
   round-trip correctly when compared against timezone-aware timestamps.
   Fix: replaced with ``datetime.now(timezone.utc)``.

5. ``auto_forward_ota_alert()`` did not early-exit when ``event_code`` was
   ``'UNKNOWN'``.  The deduplication guard already skipped UNKNOWN codes, but
   the broadcast attempt still proceeded, wasting resources and potentially
   emitting a malformed SAME header.
   Fix: an explicit early-return is added for empty / UNKNOWN event codes.

6. ``EASBroadcaster.handle_alert()`` did not catch non-``ValueError`` exceptions
   from ``build_files()``.  Any unexpected I/O or TTS failure would propagate
   out of ``handle_alert()`` and up to the caller, leaving GPIO activated and
   the DB session in an indeterminate state.
   Fix: ``build_files()`` is now wrapped in a ``try/except``.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_minimal_alert(event: str = 'Required Weekly Test') -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=None,
        identifier='TEST-001',
        event=event,
        headline=event,
        description='This is a test.',
        instruction=None,
        sent=now,
        expires=now + timedelta(hours=1),
        status='Actual',
        message_type='Alert',
        severity='Minor',
        urgency='Expected',
        certainty='Likely',
        raw_json=None,
    )


def _build_payload(fips_codes=None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        'identifier': 'TEST-001',
        'event': 'Required Weekly Test',
        'status': 'Actual',
        'message_type': 'Alert',
        'sent': now,
        'expires': now + timedelta(hours=1),
        'raw_json': {
            'properties': {
                'geocode': {
                    'SAME': fips_codes or ['039137'],
                }
            }
        },
        'forwarding_decision': 'forwarded',
        'forwarded': True,
    }


def _minimal_eas_config(output_dir: str) -> Dict[str, Any]:
    from app_utils.eas import load_eas_config
    cfg = load_eas_config()
    cfg.update({
        'enabled': True,
        'output_dir': output_dir,
        'sample_rate': 16000,
        'attention_tone_seconds': 1,
        'tts_provider': '',
    })
    return cfg


def _make_broadcaster(output_dir: str, db_session=None):
    """Return an EASBroadcaster with a real config wired to *db_session*."""
    from app_utils.eas import EASBroadcaster

    cfg = _minimal_eas_config(output_dir)
    session = db_session or MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()

    mock_record = MagicMock()
    mock_record.id = 42

    return EASBroadcaster(
        db_session=session,
        model_cls=MagicMock(return_value=mock_record),
        config=cfg,
        logger=MagicMock(),
    ), session


# ===========================================================================
# Bug 2 — handle_alert() same_triggered must be False on DB commit failure
# ===========================================================================

class TestHandleAlertDbFailure:
    """handle_alert() must not report success when the DB commit fails."""

    def test_db_commit_failure_returns_same_triggered_false(self):
        """If db commit raises, same_triggered must NOT be True."""
        from app_utils.eas import EASBroadcaster

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _minimal_eas_config(tmpdir)

            db_session = MagicMock()
            db_session.add = MagicMock()
            db_session.commit.side_effect = Exception("DB connection lost")
            db_session.rollback = MagicMock()

            broadcaster = EASBroadcaster(
                db_session=db_session,
                model_cls=MagicMock(return_value=MagicMock(id=None)),
                config=cfg,
                logger=MagicMock(),
            )

            result = broadcaster.handle_alert(_build_minimal_alert(), _build_payload())

            assert result.get('same_triggered') is not True, (
                "same_triggered must NOT be True when the DB commit fails — "
                "no record was saved and no audio was played."
            )
            assert 'error' in result, (
                "result must contain an 'error' key when the DB commit raises."
            )
            # Rollback must have been attempted
            db_session.rollback.assert_called()

    def test_db_commit_success_sets_same_triggered_true(self):
        """Normal path: same_triggered must be True after a successful commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            broadcaster, db_session = _make_broadcaster(tmpdir)
            result = broadcaster.handle_alert(_build_minimal_alert(), _build_payload())

            assert result.get('same_triggered') is True, (
                "same_triggered must be True after a successful broadcast."
            )
            assert result.get('record_id') == 42
            assert 'error' not in result

    def test_build_files_exception_returns_gracefully(self):
        """If build_files() raises an unexpected exception handle_alert() must
        return a clean error dict, not propagate the exception."""
        from app_utils.eas import EASBroadcaster

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _minimal_eas_config(tmpdir)
            db_session = MagicMock()

            broadcaster = EASBroadcaster(
                db_session=db_session,
                model_cls=MagicMock(return_value=MagicMock(id=None)),
                config=cfg,
                logger=MagicMock(),
            )

            with patch.object(
                broadcaster.audio_generator,
                'build_files',
                side_effect=RuntimeError("TTS service unavailable"),
            ):
                result = broadcaster.handle_alert(_build_minimal_alert(), _build_payload())

            assert result.get('same_triggered') is not True
            assert 'reason' in result
            assert 'TTS service unavailable' in result['reason']


# ===========================================================================
# Program-level relay lead-in/lead-out (replaces audio-embedded silence)
# ===========================================================================

class TestHandleAlertBroadcastLeadTimes:
    """handle_alert() must key the relay BROADCAST_LEAD_IN_SECONDS before
    real audio playout starts, and hold it BROADCAST_LEAD_OUT_SECONDS after
    playout ends, entirely at the program level -- no silence embedded in
    the generated audio (see TestBuildFilesHasNoEmbeddedLeadInSilence in
    tests/test_forwarded_alert_audio_flow.py for the audio-side guard).

    User-reported bug this replaces: the lead-in/lead-out used to be baked
    into the WAV as literal silence samples. That broke resend (which
    replays stored bytes rather than regenerating audio, so old messages
    could never show the padding) and mixed artificial dead air into every
    consumer of the stored audio (Icecast, FCC exports, archives).
    """

    def test_sleeps_bracket_playout_in_the_right_order(self):
        from app_utils.eas import BROADCAST_LEAD_IN_SECONDS, BROADCAST_LEAD_OUT_SECONDS

        with tempfile.TemporaryDirectory() as tmpdir:
            broadcaster, _ = _make_broadcaster(tmpdir)

            calls = []
            with patch('app_utils.eas.time.sleep', side_effect=lambda s: calls.append(('sleep', s))), \
                 patch('app_utils.eas.set_broadcast_active',
                       side_effect=lambda **kw: calls.append(('set_broadcast_active', kw)) or True), \
                 patch('app_utils.eas.clear_broadcast_active',
                       side_effect=lambda **kw: calls.append(('clear_broadcast_active', kw))), \
                 patch.object(broadcaster, '_play_audio_or_bytes',
                              side_effect=lambda *a, **kw: calls.append(('play', None))):
                result = broadcaster.handle_alert(_build_minimal_alert(), _build_payload())

            assert result.get('same_triggered') is True

            kinds = [c[0] for c in calls]
            # Between 'play' and 'clear_broadcast_active' there may also be a
            # pre-existing reconciliation sleep (holding the marker for the
            # full playback duration when the mocked player returns
            # instantly) -- that's unrelated, expected behavior, not part of
            # what this test guards. What matters: set_broadcast_active is
            # immediately followed by the lead-in sleep and then playout; and
            # clear_broadcast_active is immediately preceded by the lead-out
            # sleep.
            assert kinds[0] == 'set_broadcast_active'
            assert kinds[1] == 'sleep'
            assert kinds[2] == 'play'
            assert kinds[-1] == 'clear_broadcast_active'
            assert kinds[-2] == 'sleep'

            assert calls[1] == ('sleep', BROADCAST_LEAD_IN_SECONDS)
            assert calls[-2] == ('sleep', BROADCAST_LEAD_OUT_SECONDS)

    def test_set_broadcast_active_duration_and_phases_are_padded_by_lead_in(self):
        from app_utils.eas import BROADCAST_LEAD_IN_SECONDS, BROADCAST_LEAD_OUT_SECONDS

        with tempfile.TemporaryDirectory() as tmpdir:
            broadcaster, _ = _make_broadcaster(tmpdir)

            captured = {}
            with patch('app_utils.eas.time.sleep'), \
                 patch('app_utils.eas.set_broadcast_active',
                       side_effect=lambda **kw: captured.update(kw) or True), \
                 patch('app_utils.eas.clear_broadcast_active'), \
                 patch.object(broadcaster, '_play_audio_or_bytes'):
                broadcaster.handle_alert(_build_minimal_alert(), _build_payload())

            # duration_seconds must include both the lead-in and lead-out padding
            # on top of the real playback length; header/eom phase boundaries
            # only shift by the lead-in (they anchor to when real audio starts).
            assert captured['duration_seconds'] >= BROADCAST_LEAD_IN_SECONDS + BROADCAST_LEAD_OUT_SECONDS
            assert captured['header_seconds'] >= BROADCAST_LEAD_IN_SECONDS


# ===========================================================================
# Bug 3 — load_eas_config() must use db_session for EASSettings outside Flask
# ===========================================================================

class TestLoadEasConfigDbSessionFallback:
    """load_eas_config(db_session=...) must read EASSettings via the raw session
    when the Flask context is unavailable (CAP poller scenario).

    We do NOT patch EASSettings.query because Flask-SQLAlchemy 3.x triggers the
    scoped session when the descriptor is accessed, which raises RuntimeError
    before the patch context even enters — exactly the production bug we are
    fixing.  Instead we rely on the real failure (outside Flask context) to
    exercise the fallback path.
    """

    def test_broadcast_enabled_comes_from_db_session(self):
        """broadcast_enabled=True from db_session propagates to cfg['enabled']."""
        from app_utils.eas import load_eas_config

        mock_eas_settings = MagicMock()
        mock_eas_settings.broadcast_enabled = True
        mock_eas_settings.originator = 'WXR'
        mock_eas_settings.station_id = 'TESTNODE'
        mock_eas_settings.sample_rate = 16000
        mock_eas_settings.attention_tone_seconds = 8
        mock_eas_settings.audio_player = ''

        mock_session = MagicMock()
        mock_session.get.return_value = mock_eas_settings

        # No patching needed — EASSettings.query.get(1) will fail naturally
        # (no Flask context) and the db_session fallback will be used.
        cfg = load_eas_config(db_session=mock_session)

        assert cfg['enabled'] is True, (
            "broadcast_enabled=True from db_session must propagate to "
            "cfg['enabled'] when EASSettings.query is unavailable."
        )

    def test_originator_and_station_id_come_from_db_session(self):
        """originator and station_id from db_session must appear in config."""
        from app_utils.eas import load_eas_config

        mock_eas_settings = MagicMock()
        mock_eas_settings.broadcast_enabled = True
        mock_eas_settings.originator = 'CIV'
        mock_eas_settings.station_id = 'MYSTATION'
        mock_eas_settings.sample_rate = 16000
        mock_eas_settings.attention_tone_seconds = 8
        mock_eas_settings.audio_player = ''

        mock_session = MagicMock()
        mock_session.get.return_value = mock_eas_settings

        # Override env vars to make sure DB wins
        with patch.dict('os.environ', {'EAS_ORIGINATOR': '', 'EAS_STATION_ID': ''}):
            cfg = load_eas_config(db_session=mock_session)

        assert cfg['originator'] == 'CIV'
        assert cfg['station_id'] == 'MYSTATION'.ljust(8)[:8]

    def test_row_not_found_falls_back_to_env_default(self):
        """When the EASSettings row is absent, the env-var default is used."""
        from app_utils.eas import load_eas_config

        mock_session = MagicMock()
        mock_session.get.return_value = None  # row not found

        with patch.dict('os.environ', {'EAS_BROADCAST_ENABLED': 'false'}):
            cfg = load_eas_config(db_session=mock_session)

        assert cfg['enabled'] is False, (
            "When no EASSettings row is found, enabled must default to False."
        )


# ===========================================================================
# Bug 3b — load_eas_config() must read TTSSettings from db_session outside Flask
# ===========================================================================

class TestLoadEasConfigTTSDbSession:
    """tts_provider must be read from db_session in the CAP poller scenario.

    get_tts_settings() internally catches every exception (including the
    RuntimeError raised when there is no Flask app context) and returns a
    fake TTSSettings(id=1) with enabled=False.  That fake object is *not*
    None, so the old guard ``if tts_settings is None and db_session is not
    None`` was never True — the db_session path was permanently skipped and
    TTS was always disabled for every CAP/IPAWS alert regardless of what the
    operator configured in the web UI.

    Fix: when db_session is supplied, query it directly before attempting
    get_tts_settings(), exactly mirroring the existing EASSettings fix (Bug 3).
    """

    def _make_mock_session(self, tts_enabled: bool, tts_provider: str):
        """Return a mock db_session whose .get() dispatches by model name."""
        mock_tts = MagicMock()
        mock_tts.enabled = tts_enabled
        mock_tts.provider = tts_provider
        mock_tts.azure_openai_endpoint = ''
        mock_tts.azure_openai_key = ''
        mock_tts.azure_openai_model = 'tts-1'
        mock_tts.azure_openai_voice = 'alloy'
        mock_tts.azure_openai_speed = 1.0

        mock_eas = MagicMock()
        mock_eas.broadcast_enabled = True
        mock_eas.originator = 'WXR'
        mock_eas.station_id = 'TESTNODE'
        mock_eas.sample_rate = 16000
        mock_eas.attention_tone_seconds = 8
        mock_eas.audio_player = ''

        def _get(model_cls, pk):
            name = getattr(model_cls, '__name__', '')
            if 'TTS' in name:
                return mock_tts
            return mock_eas

        mock_session = MagicMock()
        mock_session.get.side_effect = _get
        return mock_session

    def test_tts_provider_from_db_session(self):
        """tts_provider must be read from db_session, not from get_tts_settings().

        This is the core regression test.  Without the fix, get_tts_settings()
        returns a fake disabled default (no Flask context) and tts_provider is
        always ''.  With the fix, db_session.get(TTSSettings, 1) is called
        directly and the real provider is returned.
        """
        from app_utils.eas import load_eas_config

        mock_session = self._make_mock_session(
            tts_enabled=True, tts_provider='azure_openai'
        )
        cfg = load_eas_config(db_session=mock_session)

        assert cfg['tts_provider'] == 'azure_openai', (
            "tts_provider from db_session must propagate to cfg['tts_provider'] "
            "when there is no Flask app context (CAP poller scenario).  "
            "If this fails, get_tts_settings() is still being called first and "
            "its fake disabled default is blocking the real db_session read."
        )

    def test_tts_disabled_row_respected(self):
        """When enabled=False in the DB, tts_provider must remain empty."""
        from app_utils.eas import load_eas_config

        mock_session = self._make_mock_session(
            tts_enabled=False, tts_provider='azure_openai'
        )
        cfg = load_eas_config(db_session=mock_session)

        assert cfg['tts_provider'] == '', (
            "tts_provider must be '' when TTSSettings.enabled is False."
        )

    def test_tts_provider_pyttsx3_from_db_session(self):
        """pyttsx3 provider is also correctly read from db_session."""
        from app_utils.eas import load_eas_config

        mock_session = self._make_mock_session(
            tts_enabled=True, tts_provider='pyttsx3'
        )
        cfg = load_eas_config(db_session=mock_session)

        assert cfg['tts_provider'] == 'pyttsx3', (
            "pyttsx3 tts_provider must be read from db_session."
        )

    def test_tts_row_absent_gives_empty_provider(self):
        """When there is no TTSSettings row, tts_provider must be ''."""
        from app_utils.eas import load_eas_config

        mock_eas = MagicMock()
        mock_eas.broadcast_enabled = True
        mock_eas.originator = 'WXR'
        mock_eas.station_id = 'TESTNODE'
        mock_eas.sample_rate = 16000
        mock_eas.attention_tone_seconds = 8
        mock_eas.audio_player = ''

        def _get(model_cls, pk):
            name = getattr(model_cls, '__name__', '')
            if 'TTS' in name:
                return None  # no TTSSettings row
            return mock_eas

        mock_session = MagicMock()
        mock_session.get.side_effect = _get

        cfg = load_eas_config(db_session=mock_session)

        assert cfg['tts_provider'] == '', (
            "tts_provider must be '' when no TTSSettings row exists."
        )


# ===========================================================================
# Bug 4 — alert_forwarding.py timestamps must be UTC-aware
# ===========================================================================

class TestAlertForwardingTimestamps:
    """forward_alert_to_api must produce timezone-aware ISO timestamps."""

    def _call_forward(self, alert_dict):
        from app_core.audio.alert_forwarding import forward_alert_to_api
        collected = []

        with patch('app_core.audio.alert_forwarding._publish_to_redis',
                   side_effect=collected.append), \
             patch('app_core.audio.alert_forwarding._auto_forward_to_air_chain',
                   return_value=None):
            forward_alert_to_api(alert_dict)

        return collected[0] if collected else None

    def test_forwarded_at_is_utc_aware(self):
        payload = self._call_forward({
            'source_name': 'test',
            'event_code': 'RWT',
            'location_codes': ['039137'],
        })
        assert payload is not None
        dt = datetime.fromisoformat(payload['forwarded_at'])
        assert dt.tzinfo is not None, (
            "forwarded_at must be a timezone-aware ISO string, not naive."
        )

    def test_default_timestamp_is_utc_aware(self):
        """When no 'timestamp' key is supplied the generated value must be UTC-aware."""
        payload = self._call_forward({
            'source_name': 'test',
            'event_code': 'SVR',
            'location_codes': ['039137'],
            # deliberately omit 'timestamp'
        })
        assert payload is not None
        dt = datetime.fromisoformat(payload['timestamp'])
        assert dt.tzinfo is not None, (
            "Default timestamp must be UTC-aware, not naive."
        )

    def test_provided_timestamp_is_preserved(self):
        """A caller-supplied timestamp must pass through unchanged."""
        ts = '2025-01-15T12:00:00+00:00'
        payload = self._call_forward({
            'source_name': 'test',
            'event_code': 'TOR',
            'location_codes': ['039137'],
            'timestamp': ts,
        })
        assert payload is not None
        assert payload['timestamp'] == ts


# ===========================================================================
# Bug 5 — auto_forward_ota_alert() must skip UNKNOWN event codes
# ===========================================================================

class TestOTAAutoForwardUnknownEventCode:
    """auto_forward_ota_alert() must refuse to rebroadcast garbled event codes."""

    def _call_ota_forward(self, alert_dict):
        from app_core.audio.auto_forward import auto_forward_ota_alert
        from app_core.models import EASMessage
        eas_config = {'enabled': True, 'originator': 'WXR', 'station_id': 'EASNODES'}
        db_session = MagicMock()
        db_session.query.return_value.filter.return_value.all.return_value = []
        return auto_forward_ota_alert(
            alert_dict=alert_dict,
            db_session=db_session,
            eas_message_cls=EASMessage,
            eas_config=eas_config,
        )

    def test_unknown_event_code_is_rejected(self):
        result = self._call_ota_forward({
            'event_code': 'UNKNOWN',
            'location_codes': ['039137'],
            'source_name': 'test-source',
        })
        assert result.get('forwarded') is False
        assert 'unresolvable' in result.get('reason', '').lower(), (
            "Result reason must mention that the event code is unresolvable."
        )

    def test_empty_event_code_is_rejected(self):
        result = self._call_ota_forward({
            'event_code': '',
            'location_codes': ['039137'],
            'source_name': 'test-source',
        })
        assert result.get('forwarded') is False
        assert result.get('reason'), "Reason must be set when event code is empty."

    def test_valid_event_code_proceeds_to_broadcast(self):
        """A valid event code must not be rejected by the early-exit guard."""
        from app_core.audio.auto_forward import auto_forward_ota_alert
        from app_core.models import EASMessage
        eas_config = {'enabled': True, 'originator': 'WXR', 'station_id': 'EASNODES'}
        db_session = MagicMock()
        # No recent messages → dedup passes
        db_session.query.return_value.filter.return_value.all.return_value = []

        with patch(
            'app_utils.eas.EASBroadcaster',
        ) as MockBroadcaster:
            mock_instance = MockBroadcaster.return_value
            mock_instance.handle_alert.return_value = {
                'same_triggered': True,
                'same_header': 'ZCZC-WXR-RWT-039137+0015-0011200-EASNODES-',
                'record_id': 1,
            }
            result = auto_forward_ota_alert(
                alert_dict={
                    'event_code': 'RWT',
                    'location_codes': ['039137'],
                    'source_name': 'test-source',
                },
                db_session=db_session,
                eas_message_cls=EASMessage,
                eas_config=eas_config,
            )

        # Must not have been rejected by the early exit
        assert result.get('reason') != "OTA alert has unresolvable event code; skipping rebroadcast"
        # broadcaster must have been called
        mock_instance.handle_alert.assert_called_once()


# ===========================================================================
# Bug 1 — _auto_forward_to_air_chain skips gracefully without Flask context
# ===========================================================================

class TestAutoForwardAirChainContextGuard:
    """_auto_forward_to_air_chain must return None (not raise) when there is
    no Flask application context active."""

    def test_returns_none_without_app_context(self):
        from app_core.audio.alert_forwarding import _auto_forward_to_air_chain

        # The monitoring service thread has no context → function must return None
        with patch('flask.has_app_context', return_value=False):
            result = _auto_forward_to_air_chain({'event_code': 'TOR'})

        assert result is None, (
            "_auto_forward_to_air_chain must return None (not raise) when "
            "there is no Flask application context."
        )
