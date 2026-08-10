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

"""Extracting and caching PCM windows from a decoded file."""

import os
from typing import Optional

import io
import wave
import numpy as np
from app_utils.eas_decode import AudioDecodeError, SAMEAudioSegment


def _extract_audio_segment_wav(audio_path: str, start_sample: int, end_sample: int, sample_rate: int) -> bytes:
    """Extract a segment of audio and return as WAV bytes.

    Supports both WAV and MP3 files.
    """
    file_ext = os.path.splitext(audio_path)[1].lower()

    if file_ext == '.mp3':
        # Handle MP3 files using pydub
        try:
            from pydub import AudioSegment

            # Load MP3 file
            audio = AudioSegment.from_mp3(audio_path)

            # Convert to mono if needed
            if audio.channels > 1:
                audio = audio.set_channels(1)

            # Ensure correct sample rate
            if audio.frame_rate != sample_rate:
                audio = audio.set_frame_rate(sample_rate)

            # Calculate time positions in milliseconds
            start_ms = int((start_sample / sample_rate) * 1000)
            end_ms = int((end_sample / sample_rate) * 1000)

            # Extract segment
            segment = audio[start_ms:end_ms]

            # Export as WAV bytes
            buffer = io.BytesIO()
            segment.export(buffer, format="wav")
            return buffer.getvalue()

        except ImportError:
            raise AudioDecodeError(
                "pydub is required for MP3 file support. Install with: pip install pydub"
            )
    else:
        # Handle WAV files directly
        with wave.open(audio_path, 'rb') as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()

            # Read the specific segment
            wf.setpos(start_sample)
            frames = wf.readframes(end_sample - start_sample)

            # Create WAV file in memory
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wav_out:
                wav_out.setnchannels(n_channels)
                wav_out.setsampwidth(sampwidth)
                wav_out.setframerate(sample_rate)
                wav_out.writeframes(frames)

            return buffer.getvalue()

class _PCMBuffer:
    """Helper for quickly rendering WAV segments from cached PCM samples."""

    def __init__(self, *, sample_rate: int, samples: np.ndarray, origin_start: int = 0):
        self.sample_rate = int(sample_rate)
        # Avoid an unconditional copy: ``astype(copy=False)`` returns the
        # same buffer when the dtype already matches, which is the common
        # case (16-bit PCM extracted via ``np.frombuffer``). For non-int16
        # sources the conversion still allocates a fresh array.
        self.samples = np.ascontiguousarray(samples, dtype=np.int16)
        self.origin_start = max(0, int(origin_start))

    @property
    def sample_count(self) -> int:
        return int(self.samples.size)

    @classmethod
    def from_segment(cls, segment: Optional[SAMEAudioSegment]) -> Optional["_PCMBuffer"]:
        if not segment or not getattr(segment, "wav_bytes", None):
            return None

        try:
            with wave.open(io.BytesIO(segment.wav_bytes), "rb") as handle:
                sample_rate = handle.getframerate()
                sample_width = handle.getsampwidth()
                frames = handle.readframes(handle.getnframes())
        except Exception:
            return None

        if not frames:
            return None

        if sample_width == 2:
            samples = np.frombuffer(frames, dtype=np.int16)
        else:
            dtype_map = {1: np.int8, 4: np.int32}
            dtype = dtype_map.get(sample_width)
            if dtype is None:
                return None
            raw = np.frombuffer(frames, dtype=dtype).astype(np.float32)
            scale = float(2 ** (sample_width * 8 - 1))
            if not scale:
                return None
            samples = np.clip(raw / scale, -1.0, 1.0)
            samples = (samples * 32767.0).astype(np.int16)

        if samples.size == 0:
            return None

        return cls(sample_rate=sample_rate, samples=samples, origin_start=segment.start_sample)

    def build_segment(self, label: str, start_sample: int, end_sample: int) -> Optional[SAMEAudioSegment]:
        if end_sample <= start_sample:
            return None

        relative_start = max(0, start_sample - self.origin_start)
        relative_end = max(relative_start, end_sample - self.origin_start)
        relative_end = min(relative_end, self.sample_count)
        relative_start = min(relative_start, relative_end)

        if relative_end <= relative_start:
            return None

        actual_start = self.origin_start + relative_start
        actual_end = actual_start + (relative_end - relative_start)
        pcm_slice = self.samples[relative_start:relative_end]
        if pcm_slice.size == 0:
            return None

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(self.sample_rate)
            wav_out.writeframes(pcm_slice.tobytes())

        return SAMEAudioSegment(
            label=label,
            start_sample=actual_start,
            end_sample=actual_end,
            sample_rate=self.sample_rate,
            wav_bytes=buffer.getvalue(),
        )
