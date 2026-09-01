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

"""Tests verifying that forwarded EAS alert audio includes TTS narration
   and EOM in a single uninterrupted audio file.

   The core requirement (FCC 47 CFR §11.31) is that the broadcast sequence is:
     SAME header (3×) → attention tone → voice message → End Of Message (NNNN ×3)

   Prior to this fix build_files() omitted the EOM from the composite audio,
   and handle_alert() played it as a separate subprocess call.  This meant any
   startup latency for the second subprocess introduced a gap between narration
   and EOM – and there was no guarantee the second call was actually made if an
   exception occurred between the two _play_audio_or_bytes() calls.

   After the fix, build_files() appends EOM samples to the audio buffer so that
   every forwarded alert audio file is complete from header to EOM.
"""

import io
import struct
import tempfile
import wave
from types import SimpleNamespace
from typing import Dict, Any
from unittest.mock import MagicMock

import pytest

from app_utils.eas import EASAudioGenerator, load_eas_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_wav_duration(wav_bytes: bytes) -> float:
    """Return the duration of a raw WAV payload in seconds."""
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        return wf.getnframes() / wf.getframerate()


def _build_generator() -> EASAudioGenerator:
    """Return an EASAudioGenerator with a real (but minimal) config."""
    base = load_eas_config()
    cfg: Dict[str, Any] = dict(base)
    cfg['enabled'] = True
    cfg['output_dir'] = tempfile.mkdtemp()
    cfg['sample_rate'] = 16000
    cfg['attention_tone_seconds'] = 1  # keep tests fast
    cfg['tts_provider'] = ''           # no TTS – we only test structure here
    logger = MagicMock()
    return EASAudioGenerator(cfg, logger)


def _build_minimal_alert() -> SimpleNamespace:
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=None,
        identifier='TEST-RWT-001',
        event='Required Weekly Test',
        headline='Required Weekly Test',
        description='This is an automated weekly test of the EAS system.',
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
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    return {
        'identifier': 'TEST-RWT-001',
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildFilesIncludesEOM:
    """build_files() must return audio that contains the EOM burst."""

    def test_segment_payload_contains_eom_key(self):
        """build_files() segment_payload must include an 'eom' entry."""
        gen = _build_generator()
        alert = _build_minimal_alert()
        payload = _build_payload()
        header = 'ZCZC-WXR-RWT-039137+0100-0011200-EASNODES-'

        _, _, _, _, _, segment_payload = gen.build_files(
            alert, payload, header, ['039137']
        )

        assert 'eom' in segment_payload, (
            "segment_payload must contain 'eom' so that EOM audio can be "
            "stored in the EASMessage.eom_audio_data column."
        )

    def test_eom_segment_has_wav_bytes(self):
        """The EOM segment must include non-empty WAV bytes."""
        gen = _build_generator()
        alert = _build_minimal_alert()
        payload = _build_payload()
        header = 'ZCZC-WXR-RWT-039137+0100-0011200-EASNODES-'

        _, _, _, _, _, segment_payload = gen.build_files(
            alert, payload, header, ['039137']
        )

        eom_bytes = (segment_payload.get('eom') or {}).get('wav_bytes')
        assert eom_bytes, "EOM segment must have non-empty WAV bytes."
        # Should be a valid WAV file
        duration = _parse_wav_duration(eom_bytes)
        assert duration > 0, "EOM WAV must have a positive duration."

    def test_main_audio_duration_includes_eom(self):
        """wav_bytes from build_files() must be longer than the audio without EOM.

        We verify this by comparing against a SAME+attention-only duration:
        after the fix the main audio must include EOM samples (≥ ~4 s extra for
        three NNNN bursts + 1-s silences).
        """
        gen = _build_generator()
        alert = _build_minimal_alert()
        payload = _build_payload()
        header = 'ZCZC-WXR-RWT-039137+0100-0011200-EASNODES-'

        _, _, _, wav_bytes, _, segment_payload = gen.build_files(
            alert, payload, header, ['039137']
        )

        main_duration = _parse_wav_duration(wav_bytes)
        eom_duration = _parse_wav_duration(
            (segment_payload['eom'])['wav_bytes']
        )

        # The main WAV must be at least as long as the EOM itself, since EOM is
        # embedded inside it.
        assert main_duration >= eom_duration, (
            f"Main audio duration ({main_duration:.2f}s) should be ≥ EOM "
            f"duration ({eom_duration:.2f}s) because EOM is embedded."
        )

    def test_eom_segment_duration_is_reasonable(self):
        """EOM must be long enough to contain 3 NNNN bursts plus 3 seconds of silence.

        EOM structure: 3 × NNNN FSK burst, separated by 1-second silences,
        followed by a 1-second trailing silence.  The 3 silences account for
        3.0 s; the 3 short NNNN FSK bursts each take ~0.32 s at 16 kHz, for
        a total of ~3.97 s.  We use 3.5 s as the lower bound to guard against
        genuinely broken EOM generation (e.g. all-silence or missing bursts)
        while not being sensitive to floating-point sample-count rounding.
        """
        gen = _build_generator()
        alert = _build_minimal_alert()
        payload = _build_payload()
        header = 'ZCZC-WXR-RWT-039137+0100-0011200-EASNODES-'

        _, _, _, _, _, segment_payload = gen.build_files(
            alert, payload, header, ['039137']
        )

        eom_duration = _parse_wav_duration(segment_payload['eom']['wav_bytes'])
        assert eom_duration >= 3.5, (
            f"EOM must be at least 3.5 s (got {eom_duration:.4f}s). "
            "EOM is 3 NNNN FSK bursts (~0.32 s each) + 3 silences of 1 s each."
        )
        # Also verify it is not absurdly long (> 10 s would indicate duplicated bursts).
        assert eom_duration < 10.0, (
            f"EOM duration ({eom_duration:.2f}s) is unreasonably long."
        )

class TestBuildFilesHasLeadInSilence:
    """build_files() must open with a second of silence before the SAME
    header burst, mirroring the second of silence that already trails the
    EOM.  Confirmed missing in production 2026-09-01: the GPIO subprocess
    keys the relay off the broadcast_active marker, which tracks actual
    audio playback, so a composite that starts right on the first FSK bit
    keys the relay with no time to stabilize -- unlike the tail, which was
    already correct, and unlike build_manual_components() (the manual-send
    path), which already had this same lead-in silence.
    """

    def _same_segment_samples(self, wav_bytes: bytes):
        with wave.open(io.BytesIO(wav_bytes)) as wf:
            frame_count = wf.getnframes()
            raw = wf.readframes(frame_count)
            rate = wf.getframerate()
        sample_count = len(raw) // 2
        samples = struct.unpack(f'<{sample_count}h', raw)
        return samples, rate

    def test_same_segment_opens_with_a_second_of_silence(self):
        gen = _build_generator()
        alert = _build_minimal_alert()
        payload = _build_payload()
        header = 'ZCZC-WXR-RWT-039137+0100-0011200-EASNODES-'

        _, _, _, _, _, segment_payload = gen.build_files(
            alert, payload, header, ['039137']
        )

        same_bytes = segment_payload['same']['wav_bytes']
        samples, rate = self._same_segment_samples(same_bytes)

        one_second = int(rate * 1.0)
        assert len(samples) > one_second, (
            "'same' segment must be longer than 1 s to hold both the "
            "lead-in silence and the header burst."
        )

        lead_in = samples[:one_second]
        after_lead_in = samples[one_second:one_second + int(rate * 0.1)]

        lead_in_peak = max(abs(s) for s in lead_in)
        after_peak = max(abs(s) for s in after_lead_in)

        assert lead_in_peak == 0, (
            f"First second of the 'same' segment must be pure silence "
            f"(peak amplitude {lead_in_peak}) so the relay has a full "
            "second to stabilize before the FSK burst starts."
        )
        assert after_peak > 1000, (
            "Audio immediately after the 1-second mark must be the SAME "
            f"header FSK burst (peak amplitude {after_peak} too low)."
        )

    def test_header_seconds_passed_to_broadcast_state_includes_lead_in(self):
        """header_seconds (read from segment_payload['same']'s own duration
        by the EASBroadcaster caller) must include the lead-in silence, not
        just the header burst -- otherwise the countdown overlay's header
        phase boundary drifts 1 s early relative to true elapsed playback
        time.
        """
        gen = _build_generator()
        alert = _build_minimal_alert()
        payload = _build_payload()
        header = 'ZCZC-WXR-RWT-039137+0100-0011200-EASNODES-'

        _, _, _, _, _, segment_payload = gen.build_files(
            alert, payload, header, ['039137']
        )

        same_duration = _parse_wav_duration(segment_payload['same']['wav_bytes'])
        # 3 header bursts + 2 inter-burst silences (no lead-in) would already
        # be several seconds; the lead-in silence adds exactly 1 more full
        # second on top of that structure.
        assert same_duration >= 1.0, (
            f"'same' segment duration ({same_duration:.2f}s) must include "
            "the 1-second lead-in silence."
        )


class TestHandleAlertEOMInSegmentPayload:
    """handle_alert() must pass EOM audio to the model constructor via segment_payload."""

    def test_handle_alert_passes_eom_to_model(self):
        """The EASMessage model must be created with eom_audio_data set."""
        from app_utils.eas import EASBroadcaster

        cfg = load_eas_config()
        cfg['enabled'] = True
        cfg['output_dir'] = tempfile.mkdtemp()
        cfg['sample_rate'] = 16000
        cfg['attention_tone_seconds'] = 1
        cfg['tts_provider'] = ''

        captured_kwargs: Dict[str, Any] = {}

        def capture_model(**kwargs):
            captured_kwargs.update(kwargs)
            m = MagicMock()
            m.id = 42
            return m

        db_session = MagicMock()
        db_session.add = MagicMock()
        db_session.commit = MagicMock()

        broadcaster = EASBroadcaster(
            db_session=db_session,
            model_cls=capture_model,
            config=cfg,
            logger=MagicMock(),
        )

        alert = _build_minimal_alert()
        payload = _build_payload(['039137'])

        broadcaster.handle_alert(alert, payload)

        assert 'eom_audio_data' in captured_kwargs, (
            "handle_alert() must pass eom_audio_data to the model constructor."
        )
        assert captured_kwargs['eom_audio_data'] is not None, (
            "eom_audio_data must not be None for a normal forwarded alert."
        )

    def test_handle_alert_has_eom_flag_in_metadata(self):
        """metadata_payload must contain has_eom=True for normal forwarded alerts."""
        from app_utils.eas import EASBroadcaster

        cfg = load_eas_config()
        cfg['enabled'] = True
        cfg['output_dir'] = tempfile.mkdtemp()
        cfg['sample_rate'] = 16000
        cfg['attention_tone_seconds'] = 1
        cfg['tts_provider'] = ''

        captured_kwargs: Dict[str, Any] = {}

        def capture_model(**kwargs):
            captured_kwargs.update(kwargs)
            m = MagicMock()
            m.id = 1
            return m

        db_session = MagicMock()
        db_session.add = MagicMock()
        db_session.commit = MagicMock()

        broadcaster = EASBroadcaster(
            db_session=db_session,
            model_cls=capture_model,
            config=cfg,
            logger=MagicMock(),
        )

        alert = _build_minimal_alert()
        payload = _build_payload(['039137'])

        broadcaster.handle_alert(alert, payload)

        meta = captured_kwargs.get('metadata_payload') or {}
        assert meta.get('has_eom') is True, (
            "metadata_payload must have has_eom=True after the EOM fix."
        )
