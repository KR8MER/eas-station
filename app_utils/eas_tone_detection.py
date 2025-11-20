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

from __future__ import annotations

"""
Enhanced EAS Tone Detection Module

Provides robust detection for:
- EBS two-tone attention signal (853 Hz + 960 Hz simultaneously)
- NWS 1050 Hz single tone
- End-of-Message (EOM) detection
- Narration extraction and segmentation
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np


# EAS tone frequencies
EBS_TONE_FREQ_1 = 853.0  # Hz - First tone of EBS two-tone signal
EBS_TONE_FREQ_2 = 960.0  # Hz - Second tone of EBS two-tone signal
NWS_TONE_FREQ = 1050.0   # Hz - National Weather Service alert tone


@dataclass
class ToneDetectionResult:
    """Result of tone detection analysis."""
    tone_type: str  # 'ebs', 'nws', 'eom', or 'none'
    confidence: float  # 0.0 to 1.0
    start_sample: int
    end_sample: int
    duration_seconds: float
    frequencies_detected: List[float]
    snr_db: float  # Signal-to-noise ratio in dB


@dataclass
class NarrationSegment:
    """Detected narration segment in EAS audio."""
    start_sample: int
    end_sample: int
    duration_seconds: float
    rms_level: float
    contains_speech: bool
    confidence: float


def _goertzel_power(samples: np.ndarray, sample_rate: int, target_freq: float) -> float:
    """
    Compute Goertzel algorithm for efficient single-frequency power detection.

    More efficient than FFT for detecting specific frequencies.
    """
    if len(samples) == 0:
        return 0.0

    # Normalize target frequency
    k = int(0.5 + (len(samples) * target_freq / sample_rate))
    omega = (2.0 * math.pi * k) / len(samples)
    coeff = 2.0 * math.cos(omega)

    # Goertzel algorithm
    q0 = 0.0
    q1 = 0.0
    q2 = 0.0

    for sample in samples:
        q0 = coeff * q1 - q2 + float(sample)
        q2 = q1
        q1 = q0

    # Calculate power
    real = q1 - q2 * math.cos(omega)
    imag = q2 * math.sin(omega)
    power = real * real + imag * imag

    return power


def _estimate_noise_floor(samples: np.ndarray, sample_rate: int, signal_freqs: List[float]) -> float:
    """
    Estimate the noise floor by measuring power in frequency bands away from signal.

    Args:
        samples: Audio samples
        sample_rate: Sample rate in Hz
        signal_freqs: Frequencies to avoid when measuring noise

    Returns:
        Estimated noise power
    """
    # Measure power at frequencies offset from the signal
    noise_freqs = []
    for freq in signal_freqs:
        noise_freqs.append(freq - 150.0)  # 150 Hz below
        noise_freqs.append(freq + 150.0)  # 150 Hz above

    # Remove any negative or invalid frequencies
    noise_freqs = [f for f in noise_freqs if 100.0 < f < sample_rate / 2 - 100.0]

    if not noise_freqs:
        # Fallback to general noise estimation
        noise_freqs = [300.0, 500.0, 1500.0, 2000.0]

    noise_powers = []
    for freq in noise_freqs:
        power = _goertzel_power(samples, sample_rate, freq)
        noise_powers.append(power)

    # Return median noise power (robust against outliers)
    return float(np.median(noise_powers)) if noise_powers else 0.0


def detect_ebs_two_tone(
    samples: np.ndarray,
    sample_rate: int,
    window_size: float = 0.1,
    threshold_db: float = 10.0,
    min_duration: float = 0.5
) -> List[ToneDetectionResult]:
    """
    Detect EBS two-tone attention signal (853 Hz + 960 Hz simultaneously).

    Args:
        samples: Audio samples (mono, float32, normalized to [-1, 1])
        sample_rate: Sample rate in Hz
        window_size: Analysis window size in seconds (default 0.1s / 100ms)
        threshold_db: SNR threshold in dB for detection (default 10 dB)
        min_duration: Minimum tone duration in seconds (default 0.5s)

    Returns:
        List of detected two-tone segments
    """
    if len(samples) == 0:
        return []

    window_samples = int(window_size * sample_rate)
    hop_samples = window_samples // 2  # 50% overlap

    detections: List[Tuple[int, float, float, float]] = []  # (sample_idx, conf1, conf2, snr)

    # Slide window across audio
    for i in range(0, len(samples) - window_samples, hop_samples):
        window = samples[i:i + window_samples]

        # Measure power at both EBS frequencies
        power_853 = _goertzel_power(window, sample_rate, EBS_TONE_FREQ_1)
        power_960 = _goertzel_power(window, sample_rate, EBS_TONE_FREQ_2)

        # Estimate noise floor
        noise_power = _estimate_noise_floor(window, sample_rate, [EBS_TONE_FREQ_1, EBS_TONE_FREQ_2])

        # Calculate SNR for each frequency (protect against zero power)
        snr_853 = 10 * math.log10(max(power_853, 1e-10) / max(noise_power, 1e-10))
        snr_960 = 10 * math.log10(max(power_960, 1e-10) / max(noise_power, 1e-10))

        # Both tones must be present simultaneously
        if snr_853 > threshold_db and snr_960 > threshold_db:
            # Calculate confidence based on how balanced the two tones are
            balance = min(power_853, power_960) / max(power_853, power_960, 1e-10)
            avg_snr = (snr_853 + snr_960) / 2.0
            confidence = min(balance, 1.0) * min(avg_snr / 20.0, 1.0)

            detections.append((i, snr_853, snr_960, confidence))

    # Merge consecutive detections into continuous segments
    results = []
    if detections:
        segment_start = detections[0][0]
        segment_end = detections[0][0] + window_samples
        segment_snrs = [(detections[0][1], detections[0][2])]
        segment_confidences = [detections[0][3]]

        for i in range(1, len(detections)):
            sample_idx, snr1, snr2, conf = detections[i]

            # Check if this detection is continuous with the previous segment
            if sample_idx - segment_end < hop_samples * 2:
                # Extend current segment
                segment_end = sample_idx + window_samples
                segment_snrs.append((snr1, snr2))
                segment_confidences.append(conf)
            else:
                # Finish previous segment and start new one
                duration = (segment_end - segment_start) / sample_rate
                if duration >= min_duration:
                    avg_snr = np.mean([sum(snr) / 2 for snr in segment_snrs])
                    avg_confidence = np.mean(segment_confidences)

                    results.append(ToneDetectionResult(
                        tone_type='ebs',
                        confidence=float(avg_confidence),
                        start_sample=segment_start,
                        end_sample=segment_end,
                        duration_seconds=duration,
                        frequencies_detected=[EBS_TONE_FREQ_1, EBS_TONE_FREQ_2],
                        snr_db=float(avg_snr)
                    ))

                # Start new segment
                segment_start = sample_idx
                segment_end = sample_idx + window_samples
                segment_snrs = [(snr1, snr2)]
                segment_confidences = [conf]

        # Don't forget the last segment
        duration = (segment_end - segment_start) / sample_rate
        if duration >= min_duration:
            avg_snr = np.mean([sum(snr) / 2 for snr in segment_snrs])
            avg_confidence = np.mean(segment_confidences)

            results.append(ToneDetectionResult(
                tone_type='ebs',
                confidence=float(avg_confidence),
                start_sample=segment_start,
                end_sample=segment_end,
                duration_seconds=duration,
                frequencies_detected=[EBS_TONE_FREQ_1, EBS_TONE_FREQ_2],
                snr_db=float(avg_snr)
            ))

    return results


def detect_nws_single_tone(
    samples: np.ndarray,
    sample_rate: int,
    window_size: float = 0.1,
    threshold_db: float = 18.0,
    min_duration: float = 2.0
) -> List[ToneDetectionResult]:
    """
    Detect NWS 1050 Hz single tone.

    Args:
        samples: Audio samples (mono, float32, normalized to [-1, 1])
        sample_rate: Sample rate in Hz
        window_size: Analysis window size in seconds (default 0.1s / 100ms)
        threshold_db: SNR threshold in dB for detection (default 18 dB, higher to reduce false positives)
        min_duration: Minimum tone duration in seconds (default 2.0s, NWS tones are typically 3-10 seconds)

    Returns:
        List of detected 1050 Hz tone segments
    """
    if len(samples) == 0:
        return []

    window_samples = int(window_size * sample_rate)
    hop_samples = window_samples // 2  # 50% overlap

    detections: List[Tuple[int, float, float]] = []  # (sample_idx, snr, confidence)

    # Slide window across audio
    for i in range(0, len(samples) - window_samples, hop_samples):
        window = samples[i:i + window_samples]

        # Measure power at 1050 Hz
        power_1050 = _goertzel_power(window, sample_rate, NWS_TONE_FREQ)

        # Estimate noise floor
        noise_power = _estimate_noise_floor(window, sample_rate, [NWS_TONE_FREQ])

        # Calculate SNR (protect against zero power)
        snr = 10 * math.log10(max(power_1050, 1e-10) / max(noise_power, 1e-10))

        if snr > threshold_db:
            # Check for harmonic purity (reduce false positives)
            # Measure power at harmonics
            power_harmonic2 = _goertzel_power(window, sample_rate, NWS_TONE_FREQ * 2)
            power_harmonic3 = _goertzel_power(window, sample_rate, NWS_TONE_FREQ * 3)

            # Pure tones have lower harmonic content
            fundamental_ratio = power_1050 / (power_1050 + power_harmonic2 + power_harmonic3 + 1e-10)
            confidence = min(fundamental_ratio * (snr / 20.0), 1.0)

            # Stricter confidence threshold to reduce false positives
            if confidence > 0.5 and fundamental_ratio > 0.7:
                detections.append((i, snr, confidence))

    # Merge consecutive detections into continuous segments
    results = []
    if detections:
        segment_start = detections[0][0]
        segment_end = detections[0][0] + window_samples
        segment_snrs = [detections[0][1]]
        segment_confidences = [detections[0][2]]

        for i in range(1, len(detections)):
            sample_idx, snr, conf = detections[i]

            # Check if this detection is continuous with the previous segment
            if sample_idx - segment_end < hop_samples * 2:
                # Extend current segment
                segment_end = sample_idx + window_samples
                segment_snrs.append(snr)
                segment_confidences.append(conf)
            else:
                # Finish previous segment and start new one
                duration = (segment_end - segment_start) / sample_rate
                if duration >= min_duration:
                    avg_snr = np.mean(segment_snrs)
                    avg_confidence = np.mean(segment_confidences)

                    results.append(ToneDetectionResult(
                        tone_type='nws',
                        confidence=float(avg_confidence),
                        start_sample=segment_start,
                        end_sample=segment_end,
                        duration_seconds=duration,
                        frequencies_detected=[NWS_TONE_FREQ],
                        snr_db=float(avg_snr)
                    ))

                # Start new segment
                segment_start = sample_idx
                segment_end = sample_idx + window_samples
                segment_snrs = [snr]
                segment_confidences = [conf]

        # Don't forget the last segment
        duration = (segment_end - segment_start) / sample_rate
        if duration >= min_duration:
            avg_snr = np.mean(segment_snrs)
            avg_confidence = np.mean(segment_confidences)

            results.append(ToneDetectionResult(
                tone_type='nws',
                confidence=float(avg_confidence),
                start_sample=segment_start,
                end_sample=segment_end,
                duration_seconds=duration,
                frequencies_detected=[NWS_TONE_FREQ],
                snr_db=float(avg_snr)
            ))

    return results


def detect_alert_tones(
    samples: np.ndarray,
    sample_rate: int,
    **kwargs
) -> List[ToneDetectionResult]:
    """
    Detect all alert tones (EBS two-tone and NWS 1050 Hz).

    Args:
        samples: Audio samples (mono, float32, normalized to [-1, 1])
        sample_rate: Sample rate in Hz
        **kwargs: Additional parameters passed to individual detectors

    Returns:
        List of all detected tone segments, sorted by start time
    """
    ebs_detections = detect_ebs_two_tone(samples, sample_rate, **kwargs)
    nws_detections = detect_nws_single_tone(samples, sample_rate, **kwargs)

    # Combine and sort by start time
    all_detections = ebs_detections + nws_detections
    all_detections.sort(key=lambda d: d.start_sample)

    return all_detections


def extract_narration_segments(
    samples: np.ndarray,
    sample_rate: int,
    tone_segments: List[ToneDetectionResult],
    eom_position: Optional[int] = None,
    min_duration: float = 0.5,
    speech_threshold_db: float = -40.0
) -> List[NarrationSegment]:
    """
    Extract narration segments from EAS audio between tones and before EOM.

    Args:
        samples: Audio samples (mono, float32, normalized to [-1, 1])
        sample_rate: Sample rate in Hz
        tone_segments: List of detected tone segments
        eom_position: Sample position of End-of-Message marker (if detected)
        min_duration: Minimum narration segment duration in seconds
        speech_threshold_db: RMS threshold in dB for speech detection

    Returns:
        List of detected narration segments
    """
    if len(samples) == 0:
        return []

    narration_segments = []

    # Find gaps between tones where narration would occur
    if tone_segments:
        # After last tone to EOM (or end of audio)
        last_tone_end = tone_segments[-1].end_sample
        narration_end = eom_position if eom_position else len(samples)

        # Look for audio activity in this region
        if narration_end > last_tone_end:
            segment_samples = samples[last_tone_end:narration_end]

            # Calculate RMS level
            rms = np.sqrt(np.mean(segment_samples ** 2))
            rms_db = 20 * math.log10(max(rms, 1e-10))

            # Detect speech-like activity
            contains_speech = rms_db > speech_threshold_db

            # Calculate confidence based on signal characteristics
            # Speech has varying amplitude (not constant like tones)
            if contains_speech:
                # Measure amplitude variation (speech varies more than constant tones)
                windowed_rms = []
                window_size = int(0.05 * sample_rate)  # 50ms windows
                for i in range(0, len(segment_samples) - window_size, window_size):
                    window = segment_samples[i:i + window_size]
                    windowed_rms.append(np.sqrt(np.mean(window ** 2)))

                if windowed_rms:
                    # Speech has high variation (std dev / mean)
                    variation_coefficient = np.std(windowed_rms) / max(np.mean(windowed_rms), 1e-10)
                    confidence = min(variation_coefficient * 2.0, 1.0)  # Scale to 0-1
                else:
                    confidence = 0.5
            else:
                confidence = 0.0

            duration = (narration_end - last_tone_end) / sample_rate

            if duration >= min_duration:
                narration_segments.append(NarrationSegment(
                    start_sample=last_tone_end,
                    end_sample=narration_end,
                    duration_seconds=duration,
                    rms_level=float(rms),
                    contains_speech=contains_speech,
                    confidence=float(confidence)
                ))

    return narration_segments


__all__ = [
    'ToneDetectionResult',
    'NarrationSegment',
    'detect_ebs_two_tone',
    'detect_nws_single_tone',
    'detect_alert_tones',
    'extract_narration_segments',
    'EBS_TONE_FREQ_1',
    'EBS_TONE_FREQ_2',
    'NWS_TONE_FREQ',
]
