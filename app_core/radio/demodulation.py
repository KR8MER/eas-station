"""
Audio demodulation for SDR receivers.

Supports FM (wideband and narrowband), AM, and includes stereo decoding and RBDS extraction.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DemodulatorConfig:
    """Configuration for audio demodulator."""
    modulation_type: str  # 'FM', 'WFM', 'NFM', 'AM', 'IQ'
    sample_rate: int  # Input sample rate (Hz)
    audio_sample_rate: int = 44100  # Output audio sample rate
    stereo_enabled: bool = True  # Enable FM stereo decoding
    deemphasis_us: float = 75.0  # De-emphasis time constant (75μs NA, 50μs EU, 0 to disable)
    enable_rbds: bool = False  # Extract RBDS data from FM multiplex


@dataclass
class RBDSData:
    """Decoded RBDS/RDS data from FM broadcast."""
    pi_code: Optional[str] = None  # Program Identification
    ps_name: Optional[str] = None  # Program Service name (8 chars)
    radio_text: Optional[str] = None  # Radio Text (64 chars)
    pty: Optional[int] = None  # Program Type
    tp: Optional[bool] = None  # Traffic Program flag
    ta: Optional[bool] = None  # Traffic Announcement flag
    ms: Optional[bool] = None  # Music/Speech flag


class FMDemodulator:
    """FM demodulator with stereo decoding and RBDS extraction."""

    def __init__(self, config: DemodulatorConfig):
        self.config = config
        self.prev_phase = 0.0

        # De-emphasis filter state
        self.deemph_alpha = 0.0
        if config.deemphasis_us > 0:
            # Calculate de-emphasis filter coefficient
            # tau = time constant in seconds
            tau = config.deemphasis_us * 1e-6
            self.deemph_alpha = 1.0 - np.exp(-1.0 / (config.audio_sample_rate * tau))
        self.deemph_state = 0.0

        # Stereo decoder state
        self.pilot_locked = False
        self.pilot_phase = 0.0

        # RBDS decoder state
        self.rbds_data = RBDSData()
        self.rbds_buffer = np.array([], dtype=np.complex64)

    def demodulate(self, iq_samples: np.ndarray) -> Tuple[np.ndarray, Optional[RBDSData]]:
        """
        Demodulate FM signal from IQ samples.

        Args:
            iq_samples: Complex IQ samples

        Returns:
            Tuple of (audio samples, RBDS data if available)
        """
        if len(iq_samples) == 0:
            return np.array([], dtype=np.float32), None

        # FM discriminator - compute instantaneous frequency
        # Multiply by conjugate of previous sample
        angle_diff = np.angle(iq_samples[1:] * np.conj(iq_samples[:-1]))

        # Convert to audio (frequency deviation is proportional to signal)
        audio = angle_diff / np.pi  # Normalize to [-1, 1]

        # Resample to audio sample rate if needed
        if self.config.sample_rate != self.config.audio_sample_rate:
            audio = self._resample(audio, self.config.sample_rate, self.config.audio_sample_rate)

        # Apply de-emphasis filter
        if self.config.deemphasis_us > 0:
            audio = self._apply_deemphasis(audio)

        # Stereo decoding (if enabled and this is wideband FM)
        if self.config.stereo_enabled and self.config.modulation_type == 'WFM':
            audio = self._decode_stereo(audio)

        # RBDS extraction (if enabled)
        rbds_data = None
        if self.config.enable_rbds and self.config.modulation_type in ('FM', 'WFM'):
            rbds_data = self._extract_rbds(iq_samples)

        return audio.astype(np.float32), rbds_data

    def _resample(self, signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Simple resampling using linear interpolation."""
        if from_rate == to_rate:
            return signal

        # Calculate resampling ratio
        ratio = to_rate / from_rate
        new_length = int(len(signal) * ratio)

        # Use numpy linear interpolation
        old_indices = np.arange(len(signal))
        new_indices = np.linspace(0, len(signal) - 1, new_length)

        return np.interp(new_indices, old_indices, signal)

    def _apply_deemphasis(self, audio: np.ndarray) -> np.ndarray:
        """Apply de-emphasis filter (single-pole IIR lowpass)."""
        output = np.zeros_like(audio)

        for i in range(len(audio)):
            self.deemph_state = self.deemph_state + self.deemph_alpha * (audio[i] - self.deemph_state)
            output[i] = self.deemph_state

        return output

    def _decode_stereo(self, audio: np.ndarray) -> np.ndarray:
        """
        Decode FM stereo (L+R and L-R channels).

        For now, returns mono. Full stereo decoding requires:
        - 19kHz pilot tone detection
        - 38kHz subcarrier demodulation
        - Matrix decoding to L and R channels
        """
        # TODO: Implement full stereo decoding
        # This would require operating on the multiplex signal before de-emphasis
        return audio

    def _extract_rbds(self, iq_samples: np.ndarray) -> Optional[RBDSData]:
        """
        Extract RBDS data from FM multiplex signal.

        RBDS is on a 57kHz subcarrier (3rd harmonic of 19kHz pilot).
        This is a placeholder for full RBDS decoding.
        """
        # TODO: Implement RBDS extraction
        # Requires:
        # - 57kHz subcarrier extraction
        # - BPSK demodulation (1187.5 baud)
        # - Differential decoding
        # - Block synchronization
        # - Error correction (modified Hamming code)
        # - Group type parsing
        return None


class AMDemodulator:
    """AM envelope demodulator."""

    def __init__(self, config: DemodulatorConfig):
        self.config = config
        self.dc_offset = 0.0
        self.dc_alpha = 0.001  # DC removal filter coefficient

    def demodulate(self, iq_samples: np.ndarray) -> np.ndarray:
        """
        Demodulate AM signal from IQ samples using envelope detection.

        Args:
            iq_samples: Complex IQ samples

        Returns:
            Audio samples
        """
        if len(iq_samples) == 0:
            return np.array([], dtype=np.float32)

        # Envelope detection - compute magnitude
        audio = np.abs(iq_samples)

        # Remove DC offset (high-pass filter)
        for i in range(len(audio)):
            self.dc_offset = self.dc_offset + self.dc_alpha * (audio[i] - self.dc_offset)
            audio[i] -= self.dc_offset

        # Resample to audio sample rate if needed
        if self.config.sample_rate != self.config.audio_sample_rate:
            audio = self._resample(audio, self.config.sample_rate, self.config.audio_sample_rate)

        # Normalize amplitude
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val

        return audio.astype(np.float32)

    def _resample(self, signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Simple resampling using linear interpolation."""
        if from_rate == to_rate:
            return signal

        ratio = to_rate / from_rate
        new_length = int(len(signal) * ratio)
        old_indices = np.arange(len(signal))
        new_indices = np.linspace(0, len(signal) - 1, new_length)

        return np.interp(new_indices, old_indices, signal)


class RBDSDecoder:
    """
    RBDS/RDS decoder for FM radio.

    Decodes Program Service name, Radio Text, and other metadata from the
    57kHz RBDS subcarrier in FM broadcasts.
    """

    def __init__(self):
        self.pi_code = None
        self.ps_name = [''] * 8  # 8 characters
        self.radio_text = [''] * 64  # 64 characters
        self.pty = None
        self.tp = None
        self.ta = None
        self.ms = None

    def process_group(self, group_data: np.ndarray) -> Optional[RBDSData]:
        """
        Process a decoded RBDS group.

        Args:
            group_data: 104-bit RBDS group (after error correction)

        Returns:
            Updated RBDS data if something changed
        """
        # TODO: Implement RBDS group parsing
        # Group types:
        # 0A/0B: Basic tuning and switching info (PI, PS name)
        # 2A/2B: Radio Text
        # 4A: Clock-time and date
        # Others: Various features
        return None

    def get_current_data(self) -> RBDSData:
        """Get the currently decoded RBDS data."""
        return RBDSData(
            pi_code=self.pi_code,
            ps_name=''.join(self.ps_name).strip(),
            radio_text=''.join(self.radio_text).strip(),
            pty=self.pty,
            tp=self.tp,
            ta=self.ta,
            ms=self.ms
        )


def create_demodulator(config: DemodulatorConfig):
    """Factory function to create the appropriate demodulator."""
    if config.modulation_type in ('FM', 'WFM', 'NFM'):
        return FMDemodulator(config)
    elif config.modulation_type == 'AM':
        return AMDemodulator(config)
    elif config.modulation_type == 'IQ':
        # No demodulation, return raw IQ
        return None
    else:
        raise ValueError(f"Unsupported modulation type: {config.modulation_type}")
