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

"""
Off-air narration quality assessment.

Detects "gate-chopped" voice audio — the stutter signature produced when an
upstream ENDEC or air-chain processor mutes its record input between words
and re-opens the gate mid-word.  The measurable fingerprint (validated
against real degraded captures from two independent relaying stations) is:

  1. Stretches of near-digital silence between words (the gate closed), and
  2. Instant transitions from that silence straight to full speech level
     within ~10-20 ms (the gate re-opening mid-word).

Natural speech and TTS narration never do (2): even abrupt word onsets ramp
up over 40-100 ms because microphones, codecs, and FM transmission chains
are band-limited.  A calibration sweep showed clean TTS narration with 20 %
natural pause time scores 0 gate events, while the degraded off-air captures
score 8-28 gate events per minute.

Used by the OTA relay path to decide whether the captured off-air narration
is worth re-broadcasting or whether locally synthesised TTS should be used
instead (see ``EASSettings.relay_narration_source``).
"""

import io
import wave
from typing import Any, Dict, Optional

import numpy as np

# Frames shorter than this many seconds cannot be assessed meaningfully.
_MIN_DURATION_SECONDS = 2.0

# 10 ms analysis frames — fine enough to see a gate slam open.
_FRAME_SECONDS = 0.010

# A frame is "silent" when its RMS is below this fraction of the speech
# level (90th-percentile frame RMS).  0.02 ≈ 34 dB below speech — far
# beneath any FM noise floor or room tone, so only a closed gate or true
# digital silence lands here.
_SILENCE_FRACTION_OF_SPEECH = 0.02

# A gate event is counted when a silent frame is followed within 2 frames
# (≤ 20 ms) by a frame at or above this fraction of the speech level.
_ONSET_FRACTION_OF_SPEECH = 0.35

# Degraded verdict threshold: real chopped captures measure 8-28 events/min;
# clean narration measures 0.  4/min leaves generous margin on both sides.
_DEGRADED_EVENTS_PER_MINUTE = 4.0


def assess_narration_quality(
    samples: Any,
    sample_rate: int,
) -> Optional[Dict[str, Any]]:
    """Assess voice narration for gate-chopping (off-air stutter).

    Args:
        samples: 1-D float or int array of mono audio samples.
        sample_rate: Sample rate of ``samples`` in Hz.

    Returns:
        Dict with plain-Python (JSONB-safe) values::

            {
                'degraded': bool,        # True when gate-chopping detected
                'gate_events': int,      # silence→full-level jumps counted
                'gate_events_per_minute': float,
                'silence_fraction': float,   # 0.0-1.0 of frames near-silent
                'speech_level_dbfs': float,  # 90th-percentile frame RMS
                'duration_seconds': float,
            }

        or ``None`` when the audio is too short or too quiet to assess.
    """
    if samples is None or sample_rate <= 0:
        return None

    x = np.asarray(samples, dtype=np.float64).flatten()
    if np.issubdtype(np.asarray(samples).dtype, np.integer):
        x = x / 32768.0

    duration = len(x) / float(sample_rate)
    if duration < _MIN_DURATION_SECONDS:
        return None

    frame_len = max(1, int(sample_rate * _FRAME_SECONDS))
    n_frames = len(x) // frame_len
    if n_frames < 10:
        return None

    frames = x[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt((frames ** 2).mean(axis=1))

    nonzero = rms[rms > 0]
    if nonzero.size == 0:
        return None
    speech_level = float(np.percentile(nonzero, 90))
    if speech_level <= 1e-6:
        # Effectively silent recording — nothing to assess.
        return None

    silence_threshold = speech_level * _SILENCE_FRACTION_OF_SPEECH
    onset_threshold = speech_level * _ONSET_FRACTION_OF_SPEECH

    silent = rms < silence_threshold
    silence_fraction = float(silent.mean())

    # Count silence→full-level jumps.  Require the silent frame to be part
    # of a run of at least 3 silent frames (≥ 30 ms) so a single quiet
    # zero-crossing frame inside normal speech is never counted.
    gate_events = 0
    run = 0
    i = 0
    while i < n_frames - 2:
        if silent[i]:
            run += 1
        else:
            run = 0
        if run >= 3 and (rms[i + 1] >= onset_threshold or rms[i + 2] >= onset_threshold):
            gate_events += 1
            run = 0
            i += 2  # skip past the onset so one event is counted once
        i += 1

    events_per_minute = gate_events / (duration / 60.0)
    degraded = events_per_minute >= _DEGRADED_EVENTS_PER_MINUTE

    return {
        'degraded': bool(degraded),
        'gate_events': int(gate_events),
        'gate_events_per_minute': round(float(events_per_minute), 1),
        'silence_fraction': round(silence_fraction, 3),
        'speech_level_dbfs': round(20.0 * float(np.log10(speech_level)), 1),
        'duration_seconds': round(duration, 2),
    }


def assess_wav_bytes(wav_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Assess narration quality of an in-memory mono WAV byte string.

    Convenience wrapper around :func:`assess_narration_quality` for callers
    that hold encoded WAV bytes (e.g. ``relay_audio_wav``).  Returns ``None``
    when the bytes cannot be decoded as 16-bit PCM WAV.
    """
    if not wav_bytes:
        return None
    try:
        with wave.open(io.BytesIO(wav_bytes)) as wf:
            if wf.getsampwidth() != 2:
                return None
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        return assess_narration_quality(samples, sample_rate)
    except Exception:
        return None
