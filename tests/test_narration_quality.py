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

Tests for off-air narration quality assessment (gate-chop detection).

Covers the fix for stuttering relayed narration: upstream ENDECs/processors
that gate their record input produce audio with near-silence gaps and instant
full-level onsets.  assess_narration_quality() must flag that signature as
degraded so the OTA relay path can substitute local TTS, while never flagging
clean speech that merely contains natural pauses.
"""

import io
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_utils.audio_quality import assess_narration_quality, assess_wav_bytes

SAMPLE_RATE = 16000


def _speech_like(seed: int = 1, segments: int = 12) -> np.ndarray:
    """Synthesize speech-like audio: voiced bursts with smooth 50 ms attack and
    release ramps, separated by natural pauses — the clean-narration baseline."""
    rng = np.random.default_rng(seed)
    parts = []
    for _ in range(segments):
        duration = rng.uniform(0.8, 2.5)
        pause = rng.uniform(0.15, 0.6)
        t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
        seg = np.sin(2 * np.pi * 180 * t) * (0.5 + 0.3 * np.sin(2 * np.pi * 4 * t))
        ramp = int(0.05 * SAMPLE_RATE)
        seg[:ramp] *= np.linspace(0.0, 1.0, ramp)
        seg[-ramp:] *= np.linspace(1.0, 0.0, ramp)
        parts.append(seg)
        parts.append(np.zeros(int(pause * SAMPLE_RATE)))
    return np.concatenate(parts)


def _gate_chop(audio: np.ndarray) -> np.ndarray:
    """Apply the upstream-gate artifact: hard-mute quiet stretches and keep the
    gate closed 200 ms into each following word so it slams open mid-word."""
    chopped = audio.copy()
    env = np.abs(np.convolve(chopped ** 2, np.ones(160) / 160, 'same')) ** 0.5
    closed = env < 0.05
    reopen_points = np.where(np.diff(closed.astype(int)) == -1)[0]
    for i in reopen_points:
        chopped[i:i + int(0.2 * SAMPLE_RATE)] = 0.0
    chopped[closed] = 0.0
    return chopped


def _to_wav_bytes(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes((np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def test_clean_speech_with_natural_pauses_is_not_degraded():
    result = assess_narration_quality(_speech_like(), SAMPLE_RATE)
    assert result is not None
    assert result['degraded'] is False
    assert result['gate_events'] == 0


def test_gate_chopped_speech_is_degraded():
    result = assess_narration_quality(_gate_chop(_speech_like()), SAMPLE_RATE)
    assert result is not None
    assert result['degraded'] is True
    assert result['gate_events'] >= 3
    assert result['gate_events_per_minute'] >= 4.0


def test_continuous_tone_is_not_degraded():
    t = np.arange(20 * SAMPLE_RATE) / SAMPLE_RATE
    tone = 0.4 * np.sin(2 * np.pi * 853 * t) + 0.4 * np.sin(2 * np.pi * 960 * t)
    result = assess_narration_quality(tone, SAMPLE_RATE)
    assert result is not None
    assert result['degraded'] is False


def test_result_values_are_jsonb_safe_plain_types():
    result = assess_narration_quality(_gate_chop(_speech_like()), SAMPLE_RATE)
    assert isinstance(result['degraded'], bool)
    assert isinstance(result['gate_events'], int)
    assert isinstance(result['gate_events_per_minute'], float)
    assert isinstance(result['silence_fraction'], float)
    assert isinstance(result['speech_level_dbfs'], float)
    assert isinstance(result['duration_seconds'], float)


def test_int16_input_matches_float_input():
    audio = _gate_chop(_speech_like())
    as_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    float_result = assess_narration_quality(audio, SAMPLE_RATE)
    int_result = assess_narration_quality(as_int16, SAMPLE_RATE)
    assert int_result is not None
    assert int_result['degraded'] == float_result['degraded']
    assert int_result['gate_events'] == float_result['gate_events']


def test_too_short_or_silent_audio_returns_none():
    assert assess_narration_quality(np.zeros(SAMPLE_RATE // 2), SAMPLE_RATE) is None
    assert assess_narration_quality(np.zeros(5 * SAMPLE_RATE), SAMPLE_RATE) is None
    assert assess_narration_quality(None, SAMPLE_RATE) is None
    assert assess_narration_quality(np.zeros(0), SAMPLE_RATE) is None


def test_assess_wav_bytes_roundtrip():
    degraded = assess_wav_bytes(_to_wav_bytes(_gate_chop(_speech_like())))
    assert degraded is not None
    assert degraded['degraded'] is True

    clean = assess_wav_bytes(_to_wav_bytes(_speech_like()))
    assert clean is not None
    assert clean['degraded'] is False


def test_assess_wav_bytes_rejects_garbage():
    assert assess_wav_bytes(b'') is None
    assert assess_wav_bytes(b'not a wav file at all') is None
