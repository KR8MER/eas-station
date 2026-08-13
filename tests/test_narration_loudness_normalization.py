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

"""Regression tests for the alert-tone / narration loudness mismatch.

Bug: EASAudioGenerator.build_files() (the automatic path used for real
NOAA/IPAWS alerts) appended TTS/embedded/relay narration straight into the
composite audio with no leveling, while the SAME header, attention tone and
EOM are all generated at a fixed, controlled amplitude. Measured against
production audio (Azure OpenAI TTS): tones sat at -9.1 dB mean/RMS, TTS
narration at -24.7 dB -- a ~15.6 dB gap, easily described as "wildly
different" volume between the tone and the voice message.

build_manual_components() (the manual/uploaded-narration broadcast path)
already normalizes narration via _normalize_audio_amplitude() to match the
tone's RMS; build_files() never called it. This file guards:

  1. _normalize_audio_amplitude() brings quiet audio close to the tone's RMS
     level without hard-clipping high-crest-factor (speech-like) content.
  2. EASAudioGenerator.build_files() applies that normalization to narration
     regardless of source (TTS, IPAWS-embedded, OTA relay all funnel through
     the same `voice_samples` variable), so the tone/narration gap stays
     small instead of silently regressing to raw provider output.
"""

import math
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock

from app_utils.eas import EASAudioGenerator, _normalize_audio_amplitude, load_eas_config

SAMPLE_RATE = 8000


def _rms_dbfs(samples) -> float:
    if not samples:
        return float('-inf')
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return 20 * math.log10(rms / 32768) if rms else float('-inf')


# ---------------------------------------------------------------------------
# _normalize_audio_amplitude
# ---------------------------------------------------------------------------

class TestNormalizeAudioAmplitude:
    def test_quiet_sine_reaches_target_rms(self):
        """Low-crest-factor input (pure tone) should land close to target RMS."""
        n = SAMPLE_RATE  # 1 second
        quiet = [int(3000 * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE)) for i in range(n)]
        target_amplitude = 0.7 * 32767 * 0.7  # matches build_files()'s call

        normalized = _normalize_audio_amplitude(quiet, target_amplitude)

        target_rms_dbfs = 20 * math.log10((target_amplitude / math.sqrt(2)) / 32768)
        assert abs(_rms_dbfs(normalized) - target_rms_dbfs) < 0.5

    def test_peaky_speech_like_signal_does_not_clip(self):
        """High-crest-factor input must not hard-clip even when RMS-matching
        would otherwise demand a gain that pushes peaks past full scale."""
        n = SAMPLE_RATE
        samples = []
        for i in range(n):
            base = 800 * math.sin(2 * math.pi * 200 * i / SAMPLE_RATE)
            # Sparse sharp transients (~1% of samples), like sibilants/plosives,
            # sitting far above the signal's average level.
            spike = 12000 if i % 97 == 0 else 0
            samples.append(int(base + spike))
        target_amplitude = 0.7 * 32767 * 0.7

        normalized = _normalize_audio_amplitude(samples, target_amplitude)

        assert max(abs(s) for s in normalized) <= 32767
        clipped = sum(1 for s in normalized if abs(s) >= 32767)
        assert clipped / len(normalized) < 0.01, f"{clipped} samples pinned at full scale"

    def test_empty_input_returns_empty(self):
        assert _normalize_audio_amplitude([], 20000) == []

    def test_silence_returns_unchanged(self):
        silence = [0] * 100
        assert _normalize_audio_amplitude(silence, 20000) == silence


# ---------------------------------------------------------------------------
# EASAudioGenerator.build_files(): tone/narration loudness gap
# ---------------------------------------------------------------------------

class TestBuildFilesNarrationLoudness:
    def _build_generator(self, provider: str = 'pyttsx3') -> EASAudioGenerator:
        base = load_eas_config()
        cfg: Dict[str, Any] = dict(base)
        cfg['enabled'] = True
        cfg['output_dir'] = tempfile.mkdtemp()
        cfg['sample_rate'] = SAMPLE_RATE
        cfg['attention_tone_seconds'] = 0.5
        cfg['tts_provider'] = provider
        logger = MagicMock()
        return EASAudioGenerator(cfg, logger)

    def _build_alert(self) -> SimpleNamespace:
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id=None,
            identifier='CAPNET-1-1949-20260318094500',
            event='REQUIRED MONTHLY TEST',
            headline='Emergency Alert System Test',
            description='This is only a test.',
            instruction='No action is needed.',
            sent=now,
            expires=now + timedelta(hours=1),
            status='Actual',
            message_type='Alert',
            severity='Minor',
            urgency='Expected',
            certainty='Observed',
            raw_json=None,
        )

    def _build_payload(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            'identifier': 'CAPNET-NARR-001',
            'event': 'REQUIRED MONTHLY TEST',
            'status': 'Actual',
            'message_type': 'Alert',
            'sent': now,
            'expires': now + timedelta(hours=1),
            'raw_json': {'properties': {'geocode': {'SAME': ['039000']}, 'resources': []}},
            'forwarding_decision': 'forwarded',
            'forwarded': True,
        }

    def test_quiet_tts_output_is_leveled_to_match_tone(self):
        """A TTS engine returning audio far quieter than the tone must be
        brought close to the tone's loudness in the composite, not passed
        through raw (the exact regression this test guards)."""
        gen = self._build_generator()
        alert = self._build_alert()
        payload = self._build_payload()

        # Simulate a TTS provider whose native output sits ~-25 dBFS RMS,
        # matching what was measured from Azure OpenAI TTS in production --
        # far below the tones' fixed ~-9 dBFS RMS.
        n = SAMPLE_RATE * 2
        quiet_speech = [
            int(1500 * math.sin(2 * math.pi * 200 * i / SAMPLE_RATE)) for i in range(n)
        ]
        gen.tts_engine.generate = MagicMock(return_value=quiet_speech)

        (
            _audio_filename, _text_filename, _message_text, _audio_bytes,
            text_payload, segment_payload,
        ) = gen.build_files(alert, payload, 'ZCZC-CIV-RMT-039000+0100-0790000-OHIOSTEM-', ['039000'])

        assert text_payload.get('voiceover_provider') == 'pyttsx3'
        assert segment_payload.get('tts') is not None
        assert segment_payload.get('attention') is not None

        import struct
        import wave
        import io

        def _wav_bytes_to_samples(wav_bytes: bytes):
            with wave.open(io.BytesIO(wav_bytes), 'rb') as w:
                n_frames = w.getnframes()
                raw = w.readframes(n_frames)
                return list(struct.unpack('<' + 'h' * n_frames, raw))

        tone_samples = _wav_bytes_to_samples(segment_payload['attention']['wav_bytes'])
        tts_samples = _wav_bytes_to_samples(segment_payload['tts']['wav_bytes'])

        tone_dbfs = _rms_dbfs(tone_samples)
        tts_dbfs = _rms_dbfs(tts_samples)
        gap = abs(tone_dbfs - tts_dbfs)

        # Before the fix this gap was ~15-16 dB (raw provider output, no
        # leveling at all). After normalization it should be a small,
        # unremarkable difference.
        assert gap < 6.0, (
            f"Tone/narration RMS gap is {gap:.1f} dB (tone={tone_dbfs:.1f}, "
            f"tts={tts_dbfs:.1f}) -- narration is not being leveled to the tone."
        )

        # And the narration segment itself must not be louder than raw input
        # would suggest by hard-clipping.
        assert max(abs(s) for s in tts_samples) <= 32767
