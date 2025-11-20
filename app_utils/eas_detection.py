"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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
Comprehensive EAS Detection Module

Integrates all EAS detection capabilities:
- SAME header detection (uses existing eas_decode module)
- Alert tone detection (EBS two-tone and NWS 1050 Hz)
- Narration segment extraction
- End-of-Message (EOM) detection

This module provides a unified interface for analyzing EAS audio streams.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np

from .eas_decode import decode_same_audio, SAMEHeaderDetails, SAMEAudioDecodeResult
from .eas_tone_detection import (
    detect_alert_tones,
    extract_narration_segments,
    ToneDetectionResult,
    NarrationSegment,
)

logger = logging.getLogger(__name__)


@dataclass
class EASDetectionResult:
    """Complete EAS detection result with all detected elements."""

    # SAME header information
    same_headers: List[SAMEHeaderDetails] = field(default_factory=list)
    same_confidence: float = 0.0
    same_detected: bool = False

    # Alert tone information
    alert_tones: List[ToneDetectionResult] = field(default_factory=list)
    has_ebs_tone: bool = False
    has_nws_tone: bool = False

    # Narration segments
    narration_segments: List[NarrationSegment] = field(default_factory=list)
    has_narration: bool = False

    # EOM detection
    eom_detected: bool = False
    eom_position: Optional[int] = None

    # Audio metadata
    sample_rate: int = 0
    duration_seconds: float = 0.0

    # Raw detection details
    raw_same_result: Optional[SAMEAudioDecodeResult] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert detection result to dictionary format."""
        return {
            'same_headers': [h.to_dict() for h in self.same_headers],
            'same_confidence': self.same_confidence,
            'same_detected': self.same_detected,
            'alert_tones': [
                {
                    'type': t.tone_type,
                    'confidence': t.confidence,
                    'start_sample': t.start_sample,
                    'end_sample': t.end_sample,
                    'duration_seconds': t.duration_seconds,
                    'frequencies': t.frequencies_detected,
                    'snr_db': t.snr_db,
                }
                for t in self.alert_tones
            ],
            'has_ebs_tone': self.has_ebs_tone,
            'has_nws_tone': self.has_nws_tone,
            'narration_segments': [
                {
                    'start_sample': n.start_sample,
                    'end_sample': n.end_sample,
                    'duration_seconds': n.duration_seconds,
                    'rms_level': n.rms_level,
                    'contains_speech': n.contains_speech,
                    'confidence': n.confidence,
                }
                for n in self.narration_segments
            ],
            'has_narration': self.has_narration,
            'eom_detected': self.eom_detected,
            'eom_position': self.eom_position,
            'sample_rate': self.sample_rate,
            'duration_seconds': self.duration_seconds,
        }

    def get_summary(self) -> str:
        """Get a human-readable summary of the detection."""
        lines = []
        lines.append("EAS Detection Summary")
        lines.append("=" * 50)

        # SAME headers
        if self.same_detected:
            lines.append(f"\nSAME Headers Detected: {len(self.same_headers)}")
            lines.append(f"Confidence: {self.same_confidence:.1%}")
            for i, header in enumerate(self.same_headers, 1):
                lines.append(f"  Header {i}: {header.header}")
                if header.summary:
                    lines.append(f"    {header.summary}")
        else:
            lines.append("\nSAME Headers: Not detected")

        # Alert tones
        lines.append(f"\nAlert Tones: {len(self.alert_tones)} detected")
        if self.has_ebs_tone:
            ebs_tones = [t for t in self.alert_tones if t.tone_type == 'ebs']
            lines.append(f"  EBS Two-Tone: {len(ebs_tones)} segment(s)")
            for tone in ebs_tones:
                lines.append(f"    Duration: {tone.duration_seconds:.2f}s, SNR: {tone.snr_db:.1f} dB")
        if self.has_nws_tone:
            nws_tones = [t for t in self.alert_tones if t.tone_type == 'nws']
            lines.append(f"  NWS 1050 Hz: {len(nws_tones)} segment(s)")
            for tone in nws_tones:
                lines.append(f"    Duration: {tone.duration_seconds:.2f}s, SNR: {tone.snr_db:.1f} dB")

        # Narration
        if self.has_narration:
            lines.append(f"\nNarration Segments: {len(self.narration_segments)}")
            for i, seg in enumerate(self.narration_segments, 1):
                lines.append(
                    f"  Segment {i}: {seg.duration_seconds:.2f}s, "
                    f"Speech: {seg.contains_speech}, "
                    f"Confidence: {seg.confidence:.1%}"
                )
        else:
            lines.append("\nNarration: Not detected")

        # EOM
        if self.eom_detected:
            lines.append(f"\nEOM Detected at sample: {self.eom_position}")
        else:
            lines.append("\nEOM: Not detected")

        lines.append(f"\nTotal Duration: {self.duration_seconds:.2f} seconds")

        return "\n".join(lines)


def detect_eas_from_file(
    audio_path: str,
    sample_rate: Optional[int] = None,
    detect_tones: bool = True,
    detect_narration: bool = True,
    **kwargs
) -> EASDetectionResult:
    """
    Comprehensive EAS detection from an audio file.

    Args:
        audio_path: Path to audio file (WAV, MP3, etc.)
        sample_rate: Sample rate (auto-detected if None)
        detect_tones: Whether to detect alert tones
        detect_narration: Whether to extract narration segments
        **kwargs: Additional parameters for tone detection

    Returns:
        Complete EAS detection result

    Example:
        >>> result = detect_eas_from_file('eas_alert.wav')
        >>> print(result.get_summary())
        >>> if result.same_detected:
        >>>     print(f"Event: {result.same_headers[0].fields.get('event_name')}")
    """
    result = EASDetectionResult()

    try:
        # Step 1: Decode SAME headers using existing decoder
        logger.info(f"Decoding SAME headers from {audio_path}")
        same_result = decode_same_audio(audio_path, sample_rate=sample_rate)
        result.raw_same_result = same_result
        result.same_headers = same_result.headers
        result.same_confidence = same_result.bit_confidence
        result.same_detected = len(same_result.headers) > 0
        result.sample_rate = same_result.sample_rate
        result.duration_seconds = same_result.duration_seconds

        # Check for EOM in SAME result
        if 'eom' in same_result.segments:
            eom_segment = same_result.segments['eom']
            result.eom_detected = True
            result.eom_position = eom_segment.start_sample

        logger.info(f"SAME detection: {len(same_result.headers)} headers, confidence: {same_result.bit_confidence:.2%}")

    except Exception as e:
        logger.error(f"Error decoding SAME headers: {e}")
        # Continue with tone detection even if SAME decode fails

    # Step 2: Detect alert tones if requested
    if detect_tones:
        try:
            # Load audio samples for tone detection (handle both WAV and MP3)
            import wave
            import struct
            import os
            from pydub import AudioSegment

            file_ext = os.path.splitext(audio_path)[1].lower()

            if file_ext == '.wav':
                # Direct WAV file loading
                with wave.open(audio_path, 'rb') as wf:
                    sample_rate = wf.getframerate()
                    n_channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    n_frames = wf.getnframes()

                    # Read audio data
                    frames = wf.readframes(n_frames)

                    # Convert to numpy array
                    if sampwidth == 2:
                        samples = np.frombuffer(frames, dtype=np.int16)
                    elif sampwidth == 4:
                        samples = np.frombuffer(frames, dtype=np.int32)
                    else:
                        raise ValueError(f"Unsupported sample width: {sampwidth}")

                    # Convert to float32 normalized to [-1, 1]
                    samples = samples.astype(np.float32) / (2 ** (sampwidth * 8 - 1))

                    # Convert to mono if stereo
                    if n_channels == 2:
                        samples = samples.reshape((-1, 2))
                        samples = np.mean(samples, axis=1)
            else:
                # Use pydub for MP3 and other formats
                logger.info(f"Loading {file_ext} file with pydub")
                audio = AudioSegment.from_file(audio_path)

                # Convert to mono and get parameters
                if audio.channels > 1:
                    audio = audio.set_channels(1)

                sample_rate = audio.frame_rate

                # Get raw audio data as numpy array
                samples = np.array(audio.get_array_of_samples(), dtype=np.float32)

                # Normalize to [-1, 1] based on sample width
                if audio.sample_width == 2:
                    samples = samples / 32768.0
                elif audio.sample_width == 4:
                    samples = samples / 2147483648.0
                else:
                    samples = samples / (2 ** (audio.sample_width * 8 - 1))

            logger.info(f"Detecting alert tones in {len(samples)} samples")
            tone_results = detect_alert_tones(samples, sample_rate, **kwargs)
            result.alert_tones = tone_results
            result.has_ebs_tone = any(t.tone_type == 'ebs' for t in tone_results)
            result.has_nws_tone = any(t.tone_type == 'nws' for t in tone_results)

            logger.info(f"Tone detection: EBS={result.has_ebs_tone}, NWS={result.has_nws_tone}")

            # Step 3: Extract narration if requested
            if detect_narration and tone_results:
                logger.info("Extracting narration segments")
                narration_results = extract_narration_segments(
                    samples,
                    sample_rate,
                    tone_results,
                    eom_position=result.eom_position
                )
                result.narration_segments = narration_results
                result.has_narration = any(seg.contains_speech for seg in narration_results)

                logger.info(f"Narration: {len(narration_results)} segments, has_speech={result.has_narration}")

        except Exception as e:
            logger.error(f"Error in tone/narration detection: {e}")

    return result


def detect_eas_from_samples(
    samples: np.ndarray,
    sample_rate: int,
    detect_tones: bool = True,
    detect_narration: bool = True,
    **kwargs
) -> EASDetectionResult:
    """
    Comprehensive EAS detection from audio samples array.

    Args:
        samples: Audio samples (mono, float32, normalized to [-1, 1])
        sample_rate: Sample rate in Hz
        detect_tones: Whether to detect alert tones
        detect_narration: Whether to extract narration segments
        **kwargs: Additional parameters for tone detection

    Returns:
        Complete EAS detection result
    """
    result = EASDetectionResult()
    result.sample_rate = sample_rate
    result.duration_seconds = len(samples) / sample_rate

    # Note: SAME decoding requires a file path, so we can only do tones/narration
    # from samples directly

    if detect_tones:
        try:
            logger.info(f"Detecting alert tones in {len(samples)} samples")
            tone_results = detect_alert_tones(samples, sample_rate, **kwargs)
            result.alert_tones = tone_results
            result.has_ebs_tone = any(t.tone_type == 'ebs' for t in tone_results)
            result.has_nws_tone = any(t.tone_type == 'nws' for t in tone_results)

            if detect_narration and tone_results:
                logger.info("Extracting narration segments")
                narration_results = extract_narration_segments(
                    samples,
                    sample_rate,
                    tone_results,
                    eom_position=result.eom_position
                )
                result.narration_segments = narration_results
                result.has_narration = any(seg.contains_speech for seg in narration_results)

        except Exception as e:
            logger.error(f"Error in tone/narration detection: {e}")

    return result


__all__ = [
    'EASDetectionResult',
    'detect_eas_from_file',
    'detect_eas_from_samples',
]
