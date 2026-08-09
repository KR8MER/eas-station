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

"""Stitching detected segments into one playable file."""

from dataclasses import replace as dataclass_replace
from typing import Dict, Optional

import io
import wave
import numpy as np
from app_utils.eas_decode import SAMEAudioSegment


def _build_composite_audio_segment(segments: Dict[str, SAMEAudioSegment], sample_rate: int, audio_path: Optional[str] = None) -> Optional[SAMEAudioSegment]:
    """
    Build a composite audio segment that represents the complete EAS alert.
    
    Strategy:
    1. If we have individual segments (header, tone, narration, eom), combine them
    2. Otherwise, use the buffer segment which contains the full audio
    
    Args:
        segments: Dictionary of detected segments
        sample_rate: Audio sample rate
        audio_path: Optional path to original audio file for fallback extraction
        
    Returns:
        Composite SAMEAudioSegment or None if no segments available
    """
    # Check if we have buffer segment - it contains the full alert audio.
    # Reuse the existing dataclass instance via ``dataclasses.replace`` so we
    # share the immutable wav_bytes reference instead of allocating a fresh
    # copy of all fields just to relabel the segment.
    if 'buffer' in segments:
        return dataclass_replace(segments['buffer'], label='composite')
    
    # Fallback: combine individual segments
    # Define the order of segments for the composite
    segment_order = ['header', 'attention_tone', 'narration', 'eom']
    
    # Collect PCM buffers for each segment
    pcm_buffers = []
    start_sample = None
    end_sample = None
    
    for segment_name in segment_order:
        segment = segments.get(segment_name)
        if not segment or not segment.wav_bytes:
            continue
            
        # Extract PCM data from WAV bytes
        try:
            with wave.open(io.BytesIO(segment.wav_bytes), 'rb') as wf:
                seg_sample_rate = wf.getframerate()
                sample_width = wf.getsampwidth()
                frames = wf.readframes(wf.getnframes())
                
                # Convert to int16 PCM
                if sample_width == 2:
                    pcm_data = np.frombuffer(frames, dtype=np.int16)
                else:
                    # Convert other formats to int16
                    dtype_map = {1: np.int8, 4: np.int32}
                    dtype = dtype_map.get(sample_width)
                    if dtype is None:
                        continue
                    raw = np.frombuffer(frames, dtype=dtype).astype(np.float32)
                    scale = float(2 ** (sample_width * 8 - 1))
                    if not scale:
                        continue
                    normalized = np.clip(raw / scale, -1.0, 1.0)
                    pcm_data = (normalized * 32767.0).astype(np.int16)
                
                pcm_buffers.append(pcm_data)
                
                # Track overall start and end samples
                if start_sample is None:
                    start_sample = segment.start_sample
                end_sample = segment.end_sample
                
        except Exception as e:
            # Skip this segment if we can't process it
            continue
    
    if not pcm_buffers:
        return None
    
    # Concatenate all PCM buffers
    composite_pcm = np.concatenate(pcm_buffers)
    
    # Create WAV file
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(composite_pcm.tobytes())
    
    return SAMEAudioSegment(
        label='composite',
        start_sample=start_sample or 0,
        end_sample=end_sample or len(composite_pcm),
        sample_rate=sample_rate,
        wav_bytes=buffer.getvalue(),
    )
