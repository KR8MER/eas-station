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

"""ECIG CAP-to-EAS Implementation Guide V1.0 compliance tests.

Covers the five gaps closed in the audit pass:
  - §3.4.1.7  EAS-Must-Carry parameter overrides event-code filter
  - §3.8      msgType filtering (Cancel/Ack/Error suppressed)
  - §3.5.1    Embedded-audio fetch timeouts (120 s download, 30 s streaming)
  - §3.5.2/4  '***' text-deletion marker becomes an audible pause
  - §3.10     Default originator is CIV (not WXR) for non-NOAA sources
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stub heavy dependencies so only the gating logic is exercised.  Note:
# `app_core` is NOT stubbed because TestMustCarryDetection imports the real
# `app_core.audio.auto_forward` module; only the `app_core.models` and
# `app_core.tts_settings` submodules used by `app_utils.eas` are replaced.
_STUBS = [
    'flask', 'flask_sqlalchemy',
    'sqlalchemy', 'sqlalchemy.orm',
    'pytz',
    'azure', 'azure.cognitiveservices', 'azure.cognitiveservices.speech',
    'pyttsx3', 'pydub',
    'RPi', 'RPi.GPIO', 'gpiozero',
    'psutil',
    'app_core.models', 'app_core.tts_settings',
]
for _mod in _STUBS:
    sys.modules.setdefault(_mod, MagicMock())


# ---------------------------------------------------------------------------
# §3.5.2 / §3.5.4 — '***' deletion marker becomes an audible pause
# ---------------------------------------------------------------------------

def _get_normalize():
    with patch('app_utils.eas._load_pronunciation_rules', return_value=[]):
        from app_utils.eas import _normalize_text_for_tts
    return _normalize_text_for_tts


class TestAsteriskDeletionPause(unittest.TestCase):
    """Three or more asterisks ('***') mark a deletion and SHALL be followed
    by a one-second pause (ECIG §3.5.2, §3.5.4).  In this codebase that
    pause is rendered as a sentence break ('. ') because every TTS backend
    we ship treats a sentence break as roughly a one-second silence."""

    def setUp(self):
        self.n = _get_normalize()

    def test_triple_asterisk_becomes_sentence_break(self):
        result = self.n('WARNING ISSUED *** DETAILS WITHHELD')
        self.assertNotIn('***', result)
        self.assertNotIn('*', result)
        # A sentence break ". " (post-lowercasing) must appear where the
        # deletion marker was.
        self.assertIn('. ', result)

    def test_quadruple_asterisk_also_becomes_pause(self):
        result = self.n('LINE ONE **** LINE TWO')
        self.assertNotIn('*', result)
        self.assertIn('. ', result)

    def test_single_asterisk_still_stripped(self):
        # NWS bullet markers ("* WHAT...") remain stripped, not turned into
        # a pause — that behavior predates the ECIG fix.
        result = self.n('* WHAT...TORNADO WARNING')
        self.assertNotIn('*', result)

    def test_double_asterisk_stripped(self):
        result = self.n('A ** B')
        self.assertNotIn('*', result)


# ---------------------------------------------------------------------------
# §3.4.1.7 — Governor's Must-Carry detection
# ---------------------------------------------------------------------------

def _load_auto_forward_module():
    """Load app_core/audio/auto_forward.py directly from disk.

    Importing it through the `app_core.audio` package would pull in the
    full audio-ingest pipeline (SDR, ALSA, redis_client, etc.), which is
    far more than this test needs.  spec_from_file_location bypasses the
    package machinery while still letting auto_forward import its own
    function-scoped dependencies.  The function-scoped imports pull in
    `app_core.logging_context` which transitively imports redis; stub
    those before exec'ing the module.
    """
    import importlib.util
    import contextlib

    # Satisfy the module-level `from app_utils.vtec import ...`.
    sys.modules.setdefault('app_utils.vtec', MagicMock(
        VTEC_BROADCAST_ACTIONS=set(),
        VTEC_SKIP_ACTIONS=set(),
        VTEC_TERMINAL_ACTIONS=set(),
    ))

    # Stub the function-scoped imports that auto_forward_cap_alert pulls
    # in at call time — these would otherwise drag in redis, gevent, etc.
    @contextlib.contextmanager
    def _noop_ctx(*args, **kwargs):
        yield None

    logging_ctx_stub = MagicMock()
    logging_ctx_stub.push_alert = MagicMock(return_value=object())
    logging_ctx_stub.pop_alert = MagicMock()
    sys.modules.setdefault('app_core.logging_context', logging_ctx_stub)
    sys.modules.setdefault('app_core.extensions', MagicMock())
    sys.modules.setdefault('app_core.redis_client', MagicMock())
    sys.modules.setdefault('app_utils.event_codes', MagicMock(
        EVENT_CODE_REGISTRY={
            'CEM': {'name': 'Civil Emergency Message'},
            'RWT': {'name': 'Required Weekly Test'},
            'TOR': {'name': 'Tornado Warning'},
        },
    ))

    path = ROOT / 'app_core' / 'audio' / 'auto_forward.py'
    spec = importlib.util.spec_from_file_location(
        'auto_forward_under_test', str(path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMustCarryDetection(unittest.TestCase):
    """`_is_must_carry` reads
    `<parameter><valueName>EAS-Must-Carry</valueName><value>True</value></parameter>`
    from the parsed raw_json dict."""

    @classmethod
    def setUpClass(cls):
        cls._mod = _load_auto_forward_module()

    def setUp(self):
        self.is_must_carry = self._mod._is_must_carry

    def test_true_string_detected(self):
        raw = {'properties': {'parameters': {'EAS-Must-Carry': 'True'}}}
        self.assertTrue(self.is_must_carry(raw))

    def test_lowercase_true_detected(self):
        raw = {'properties': {'parameters': {'EAS-Must-Carry': 'true'}}}
        self.assertTrue(self.is_must_carry(raw))

    def test_list_value_first_occurrence(self):
        # §3.3.1: when a parameter appears multiple times, only the first
        # occurrence is honored.
        raw = {'properties': {'parameters': {
            'EAS-Must-Carry': ['True', 'False'],
        }}}
        self.assertTrue(self.is_must_carry(raw))

    def test_false_value_returns_false(self):
        raw = {'properties': {'parameters': {'EAS-Must-Carry': 'False'}}}
        self.assertFalse(self.is_must_carry(raw))

    def test_missing_parameter_returns_false(self):
        raw = {'properties': {'parameters': {}}}
        self.assertFalse(self.is_must_carry(raw))

    def test_missing_raw_json_returns_false(self):
        self.assertFalse(self.is_must_carry(None))
        self.assertFalse(self.is_must_carry({}))


# ---------------------------------------------------------------------------
# §3.5.1 — embedded-audio fetch timeouts
# ---------------------------------------------------------------------------

class TestEmbeddedAudioTimeouts(unittest.TestCase):
    """Per ECIG §3.5.1, downloads get up to 120 s and streaming sources up
    to 30 s.  _fetch_embedded_audio selects per-resource based on MIME or
    resourceDesc.  On timeout the loop falls through and the caller
    eventually renders TTS instead."""

    def setUp(self):
        from app_utils import eas as eas_mod
        self.eas_mod = eas_mod

    def _run_with_resource(self, resource):
        import requests
        captured = {}

        class _FakeResponse:
            def __init__(self):
                self.content = b''
            def raise_for_status(self):
                pass

        def fake_get(url, **kwargs):
            captured['timeout'] = kwargs.get('timeout')
            return _FakeResponse()

        log = MagicMock()
        with patch.object(self.eas_mod, '_convert_audio_to_samples', return_value=None), \
             patch.object(requests, 'get', side_effect=fake_get):
            self.eas_mod._fetch_embedded_audio([resource], 24000, log)
        return captured

    def test_download_uses_120s_timeout(self):
        # Plain MP3 download: spec cap is 2 minutes.
        captured = self._run_with_resource({
            'uri': 'https://example.com/eas.mp3',
            'mimeType': 'audio/mpeg',
            'resourceDesc': 'EAS Broadcast Content',
        })
        self.assertEqual(captured.get('timeout'),
                         self.eas_mod.EMBEDDED_AUDIO_DOWNLOAD_TIMEOUT)
        self.assertEqual(captured.get('timeout'), 120)

    def test_streaming_mime_uses_30s_timeout(self):
        captured = self._run_with_resource({
            'uri': 'https://example.com/eas.m3u',
            'mimeType': 'audio/x-ipaws-streaming-audio-mp3',
            'resourceDesc': 'EAS Broadcast Content',
        })
        self.assertEqual(captured.get('timeout'),
                         self.eas_mod.EMBEDDED_AUDIO_STREAMING_TIMEOUT)
        self.assertEqual(captured.get('timeout'), 30)

    def test_streaming_in_desc_uses_30s_timeout(self):
        # Some originators only signal "streaming" in the resourceDesc.
        captured = self._run_with_resource({
            'uri': 'https://example.com/eas',
            'mimeType': 'audio/mpeg',
            'resourceDesc': 'EAS Streaming Audio',
        })
        self.assertEqual(captured.get('timeout'), 30)

    def test_explicit_override_wins(self):
        import requests
        captured = {}

        class _FakeResponse:
            content = b''
            def raise_for_status(self):
                pass

        def fake_get(url, **kwargs):
            captured['timeout'] = kwargs.get('timeout')
            return _FakeResponse()

        log = MagicMock()
        resource = {
            'uri': 'https://example.com/eas.mp3',
            'mimeType': 'audio/mpeg',
            'resourceDesc': 'EAS Broadcast Content',
        }
        with patch.object(self.eas_mod, '_convert_audio_to_samples', return_value=None), \
             patch.object(requests, 'get', side_effect=fake_get):
            self.eas_mod._fetch_embedded_audio([resource], 24000, log, timeout=5)
        self.assertEqual(captured.get('timeout'), 5)


# ---------------------------------------------------------------------------
# §3.10 — Default originator: CIV for non-NOAA, WXR for NOAA
# ---------------------------------------------------------------------------

class TestDefaultOriginator(unittest.TestCase):
    """When the CAP message omits an EAS-ORG parameter, §3.10 says assume
    CIV.  NOAA/NWS feeds are the practical exception: they consistently
    omit EAS-ORG and are by definition WXR."""

    def setUp(self):
        from app_utils import eas as eas_mod
        self.eas_mod = eas_mod
        # Stub the heavy machinery that _construct_alert_text doesn't need
        # for the originator-selection branch.

    def _construct(self, alert_source):
        alert = SimpleNamespace(
            event='Civil Emergency Message',
            description='',
            instruction='',
            sent=None,
            expires=None,
            source=alert_source,
        )
        payload = {'raw_json': {'properties': {}}, 'source': alert_source}
        with patch.object(self.eas_mod, '_load_pronunciation_rules', return_value=[]):
            return self.eas_mod._compose_message_text(alert, payload)

    def test_noaa_source_defaults_to_wxr(self):
        text = self._construct('NOAA')
        # ORIGINATOR_DESCRIPTIONS['WXR'] = 'National Weather Service'
        # (text gets lowercased by the TTS normalizer).
        self.assertIn('national weather service', text.lower())

    def test_ipaws_source_defaults_to_civ(self):
        text = self._construct('IPAWS')
        # ORIGINATOR_DESCRIPTIONS['CIV'] = 'Civil authorities'.
        self.assertIn('civil authorit', text.lower())
        self.assertNotIn('national weather service', text.lower())

    def test_unknown_source_defaults_to_civ(self):
        text = self._construct('UNKNOWN')
        self.assertIn('civil authorit', text.lower())
        self.assertNotIn('national weather service', text.lower())


# ---------------------------------------------------------------------------
# AWIPS identifier stripped from narration body
# ---------------------------------------------------------------------------

class TestAwipsIdentifierStripped(unittest.TestCase):
    """NWS warning descriptions begin with the internal AWIPS product
    identifier (e.g. "SVRCLE") on its own line.  It is a routing code, not
    narratable content, and must not be spoken in the TTS voiceover."""

    def setUp(self):
        from app_utils import eas as eas_mod
        self.eas_mod = eas_mod

    def _construct(self, description, parameters=None):
        alert = SimpleNamespace(
            event='Severe Thunderstorm Warning',
            description=description,
            instruction='',
            sent=None,
            expires=None,
            source='NOAA',
        )
        props = {'senderName': 'NWS Cleveland OH'}
        if parameters is not None:
            props['parameters'] = parameters
        payload = {'raw_json': {'properties': props}, 'source': 'NOAA'}
        with patch.object(self.eas_mod, '_load_pronunciation_rules', return_value=[]):
            return self.eas_mod._compose_message_text(alert, payload)

    def test_strip_helper_uses_parameter(self):
        desc = 'SVRCLE\n\nThe National Weather Service in Cleveland has issued a'
        out = self.eas_mod._strip_awips_identifier(
            desc, {'AWIPSidentifier': ['SVRCLE']}
        )
        self.assertFalse(out.startswith('SVRCLE'))
        self.assertTrue(out.startswith('The National Weather Service'))

    def test_no_parameter_leaves_text_untouched(self):
        # Without the AWIPSidentifier parameter we must NOT guess: even an
        # AWIPS-shaped first line is preserved, because many messages have no
        # identifier and stripping would delete real content.
        desc = 'SVRCLE\n\nThe National Weather Service in Cleveland has issued a'
        out = self.eas_mod._strip_awips_identifier(desc, {})
        self.assertEqual(out, desc)

    def test_parameter_present_but_no_match_left_untouched(self):
        # Parameter exists but the description does not begin with it — leave
        # the body intact rather than stripping the wrong line.
        desc = 'The National Weather Service in Cleveland has issued a warning.'
        out = self.eas_mod._strip_awips_identifier(
            desc, {'AWIPSidentifier': ['SVRCLE']}
        )
        self.assertEqual(out, desc)

    def test_narration_omits_awips_identifier(self):
        text = self._construct(
            'SVRCLE\n\nThe National Weather Service in Cleveland has issued a\n\n'
            '* Severe Thunderstorm Warning for...',
            parameters={'AWIPSidentifier': ['SVRCLE']},
        )
        # Lowercased by the normalizer; the identifier must not appear.
        self.assertNotIn('svrcle', text.lower())
        self.assertIn('national weather service', text.lower())

    def test_narration_keeps_text_without_parameter(self):
        # No AWIPSidentifier parameter — the body is narrated as-is.  We do not
        # guess, because not every message carries an identifier.
        text = self._construct(
            'SVRCLE\n\nThe National Weather Service in Cleveland has issued a',
        )
        self.assertIn('svrcle', text.lower())

    def test_legitimate_text_not_stripped(self):
        # A description that does not start with an AWIPS-shaped line must be
        # left intact (no blank-line-delimited 4-6 letter code at the top).
        out = self.eas_mod._strip_awips_identifier(
            'The National Weather Service has issued a warning.', {}
        )
        self.assertTrue(out.startswith('The National Weather Service'))

    def test_short_caps_word_without_blank_line_preserved(self):
        # "TAKE cover now" — a single newline (not a blank line) after a caps
        # word is normal prose, not an AWIPS header, so it is preserved.
        desc = 'TAKE\ncover now and stay away from windows.'
        out = self.eas_mod._strip_awips_identifier(desc, {})
        self.assertEqual(out, desc)


# ---------------------------------------------------------------------------
# §3.8 — msgType filtering (Cancel/Ack/Error not aired; Alert/Update aired)
# ---------------------------------------------------------------------------

class TestMsgTypeFiltering(unittest.TestCase):
    """auto_forward_cap_alert must respect CAP msgType (ECIG §3.8):
      - Alert     → process
      - Update    → process (supersede handled by cap_poller upstream)
      - Cancel    → MUST NOT air the cancelled message
      - Ack/Error → not required to process
    """

    @classmethod
    def setUpClass(cls):
        cls._mod = _load_auto_forward_module()

    def _call(self, msg_type):
        """Invoke auto_forward_cap_alert with just enough scaffolding to
        reach the msgType gate (status=Actual, scope=Public).

        For msgTypes that pass §3.8 (Alert, Update), we short-circuit the
        downstream broadcaster path by forcing the cross-source dedupe
        check to claim duplicate — that way the function returns with a
        non-§3.8 reason and never tries to import the real audio
        machinery.
        """
        from datetime import datetime, timezone, timedelta
        sent = datetime.now(timezone.utc) - timedelta(minutes=1)
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        cap_alert = SimpleNamespace(
            identifier='TEST-001',
            status='Actual',
            scope='Public',
            message_type=msg_type,
            sent=sent,
            expires=expires,
            source='IPAWS',
            event='Civil Emergency Message',
            vtec_action=None,
        )
        with patch.object(self._mod, '_update_cap_forwarding_status'), \
             patch.object(self._mod, '_acquire_dedupe_lock'), \
             patch.object(self._mod, 'is_duplicate_broadcast', return_value=True):
            return self._mod.auto_forward_cap_alert(
                cap_alert,
                {'raw_json': {'properties': {'geocode': {'SAME': ['039001']}}}},
                db_session=MagicMock(),
                eas_message_cls=MagicMock(),
                eas_config={'enabled': True, 'forwarded_event_codes': []},
            )

    def test_cancel_is_not_aired(self):
        result = self._call('Cancel')
        self.assertFalse(result['forwarded'])
        self.assertIn('Cancel', result.get('reason', ''))
        self.assertIn('§3.8', result.get('reason', ''))

    def test_ack_is_not_aired(self):
        result = self._call('Ack')
        self.assertFalse(result['forwarded'])
        self.assertIn('§3.8', result.get('reason', ''))

    def test_error_is_not_aired(self):
        result = self._call('Error')
        self.assertFalse(result['forwarded'])
        self.assertIn('§3.8', result.get('reason', ''))

    def test_unknown_msgtype_is_not_aired(self):
        result = self._call('Bogus')
        self.assertFalse(result['forwarded'])
        self.assertIn('§3.8', result.get('reason', ''))

    def test_alert_passes_msgtype_gate(self):
        # Alert msgType should clear the §3.8 gate; downstream gates
        # (event-code filter, dedupe, etc.) may still reject it but the
        # reason MUST NOT cite §3.8.
        result = self._call('Alert')
        self.assertNotIn('§3.8', result.get('reason', '') or '')

    def test_update_passes_msgtype_gate(self):
        result = self._call('Update')
        self.assertNotIn('§3.8', result.get('reason', '') or '')


# ---------------------------------------------------------------------------
# §3.4.1.7 — Must-Carry bypasses event-code filter in auto_forward
# ---------------------------------------------------------------------------

class TestMustCarryBypassesEventFilter(unittest.TestCase):
    """When EAS-Must-Carry=True, auto_forward must NOT reject the alert on
    the event-code allowlist (§3.4.1.7).  We can verify this by setting a
    restrictive allowlist that would otherwise reject the alert."""

    @classmethod
    def setUpClass(cls):
        cls._mod = _load_auto_forward_module()

    def _call(self, must_carry, event_name='Civil Emergency Message',
              allowlist=('TOR',)):
        from datetime import datetime, timezone, timedelta
        sent = datetime.now(timezone.utc) - timedelta(minutes=1)
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        cap_alert = SimpleNamespace(
            identifier='TEST-002',
            status='Actual',
            scope='Public',
            message_type='Alert',
            sent=sent,
            expires=expires,
            source='IPAWS',
            event=event_name,
            vtec_action=None,
        )
        parameters = {'EAS-Must-Carry': 'True'} if must_carry else {}
        # Force the cross-source dedupe to claim duplicate so the function
        # bails out before hitting the real broadcaster (which would pull
        # in scipy / alert_metadata).  We're only verifying the upstream
        # event-code gate here.
        with patch.object(self._mod, '_update_cap_forwarding_status'), \
             patch.object(self._mod, '_acquire_dedupe_lock'), \
             patch.object(self._mod, 'is_duplicate_broadcast', return_value=True):
            return self._mod.auto_forward_cap_alert(
                cap_alert,
                {'raw_json': {'properties': {
                    'parameters': parameters,
                    'geocode': {'SAME': ['039001']},
                }}},
                db_session=MagicMock(),
                eas_message_cls=MagicMock(),
                eas_config={
                    'enabled': True,
                    'forwarded_event_codes': list(allowlist),
                },
            )

    def test_without_must_carry_event_outside_allowlist_is_rejected(self):
        result = self._call(must_carry=False)
        self.assertFalse(result['forwarded'])
        self.assertIn('not in the configured forwarding allowlist',
                      result.get('reason', ''))

    def test_must_carry_bypasses_event_allowlist(self):
        result = self._call(must_carry=True)
        # Reason (if any) MUST NOT be the event-code allowlist; the alert
        # may still fail later gates (no dedupe table, no real DB), but the
        # event-code gate must let it through.
        reason = result.get('reason') or ''
        self.assertNotIn('not in the configured forwarding allowlist', reason)
        self.assertTrue(result.get('must_carry'))

    def test_must_carry_bypasses_rwt_suppression(self):
        # RWT is normally suppressed unless explicitly listed; must-carry
        # overrides this too.
        result = self._call(must_carry=True, event_name='Required Weekly Test',
                            allowlist=())
        reason = result.get('reason') or ''
        self.assertNotIn('RWT not forwarded', reason)


if __name__ == '__main__':
    unittest.main()
