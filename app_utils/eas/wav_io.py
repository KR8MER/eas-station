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

"""Raw PCM samples <-> WAV file bytes."""

import io
import struct
import wave
from typing import Optional, Sequence



def _write_wave_file(path: str, samples: Sequence[int], sample_rate: int) -> None:
    with wave.open(path, 'w') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = struct.pack('<' + 'h' * len(samples), *samples)
        wav.writeframes(frames)




def samples_to_wav_bytes(samples: Sequence[int], sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, 'w') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = struct.pack('<' + 'h' * len(samples), *samples)
        wav.writeframes(frames)
    buffer.seek(0)
    return buffer.getvalue()




def _wav_duration_seconds(wav_bytes: bytes) -> float:
    """Return the duration of a WAV file in seconds, or 0.0 on error."""
    try:
        with io.BytesIO(wav_bytes) as bio:
            with wave.open(bio, 'rb') as w:
                return w.getnframes() / w.getframerate()
    except Exception:
        return 0.0




def truncate_wav_to_max_seconds(
    composite_wav: bytes,
    eom_wav: Optional[bytes],
    max_seconds: float,
) -> bytes:
    """Enforce the hard activation time limit on composite EAS audio.

    If *composite_wav* is within *max_seconds* it is returned unchanged.
    Otherwise the audio is trimmed so that the total duration equals
    *max_seconds*, with the EOM segment (*eom_wav*) preserved at the end.
    This mirrors DASDEC behaviour: the narration is cut short when it would
    exceed the configured hard limit, and the EOM plays immediately after.
    """
    composite_duration = _wav_duration_seconds(composite_wav)
    if composite_duration <= max_seconds:
        return composite_wav

    # Read composite WAV parameters
    with io.BytesIO(composite_wav) as bio:
        with wave.open(bio, 'rb') as w:
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            framerate = w.getframerate()

    # Determine how many frames to keep from the composite (before EOM)
    eom_duration = _wav_duration_seconds(eom_wav) if eom_wav else 0.0
    pre_eom_limit = max(0.0, max_seconds - eom_duration)
    max_pre_eom_frames = int(pre_eom_limit * framerate)

    with io.BytesIO(composite_wav) as bio:
        with wave.open(bio, 'rb') as w:
            truncated_frames = w.readframes(max_pre_eom_frames)

    # Append the EOM frames from the isolated EOM WAV
    eom_raw_frames = b''
    if eom_wav:
        try:
            with io.BytesIO(eom_wav) as bio:
                with wave.open(bio, 'rb') as w:
                    eom_raw_frames = w.readframes(w.getnframes())
        except Exception:
            pass

    output = io.BytesIO()
    with wave.open(output, 'w') as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(truncated_frames)
        if eom_raw_frames:
            w.writeframes(eom_raw_frames)
    output.seek(0)
    return output.getvalue()
