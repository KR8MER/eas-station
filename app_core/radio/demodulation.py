"""
Audio demodulation for SDR receivers.

Supports FM (wideband and narrowband), AM, and includes stereo decoding and RBDS extraction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

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

        # Previous complex sample for phase continuity
        self._prev_sample: Optional[np.complex64] = None
        self._sample_index: int = 0

        # De-emphasis filter state
        self._deemph_alpha = 0.0
        if config.deemphasis_us > 0:
            tau = config.deemphasis_us * 1e-6
            self._deemph_alpha = 1.0 - np.exp(-1.0 / (config.audio_sample_rate * tau))
        self._deemph_state = np.zeros(1, dtype=np.float32)

        # Stereo decoder state
        self._stereo_enabled = (
            config.stereo_enabled
            and config.modulation_type in {"FM", "WFM"}
            and config.sample_rate >= 76000  # Minimum for 38kHz subcarrier
        )
        self._lpr_filter = self._design_fir_lowpass(16000.0, config.sample_rate)
        self._dsb_filter = self._design_fir_lowpass(16000.0, config.sample_rate)
        self._pilot_filter = self._design_fir_bandpass(18000.0, 20000.0, config.sample_rate)

        # RBDS decoder state
        self._rbds_decoder = RBDSDecoder()
        self._rbds_enabled = config.enable_rbds and config.sample_rate >= 50000
        self._rbds_bandpass = self._design_fir_bandpass(54000.0, 60000.0, config.sample_rate)
        self._rbds_lowpass = self._design_fir_lowpass(2400.0, config.sample_rate)
        self._rbds_symbol_rate = 1187.5
        self._rbds_target_rate = self._rbds_symbol_rate * 4.0
        self._rbds_symbol_phase = 0.0
        self._rbds_loop_gain = 0.02
        self._rbds_bit_buffer: List[int] = []
        self._rbds_expected_block: Optional[int] = None
        self._rbds_partial_group: List[int] = []

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

        iq_array = np.asarray(iq_samples, dtype=np.complex64)
        if self._prev_sample is not None:
            iq_array = np.concatenate(([self._prev_sample], iq_array))
        self._prev_sample = iq_array[-1]

        discriminator = np.angle(iq_array[1:] * np.conj(iq_array[:-1]))
        multiplex = discriminator / np.pi

        sample_indices = self._sample_index + np.arange(len(multiplex))
        self._sample_index += len(multiplex)

        audio_signal = self._lpr_filter_signal(multiplex)
        stereo_audio: Optional[np.ndarray] = None

        if self._stereo_enabled:
            stereo_audio = self._decode_stereo(multiplex, sample_indices)

        rbds_data = None
        if self._rbds_enabled:
            rbds_data = self._extract_rbds(multiplex, sample_indices)

        if stereo_audio is not None:
            audio = stereo_audio
        else:
            audio = audio_signal

        if self.config.sample_rate != self.config.audio_sample_rate:
            audio = self._resample(audio, self.config.sample_rate, self.config.audio_sample_rate)

        if self.config.deemphasis_us > 0:
            audio = self._apply_deemphasis(audio)

        return audio.astype(np.float32), rbds_data

    def _resample(self, signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Simple resampling using linear interpolation."""
        if from_rate == to_rate:
            return signal

        ratio = to_rate / from_rate
        if signal.ndim == 1:
            new_length = max(int(len(signal) * ratio), 1)
            old_indices = np.arange(len(signal))
            new_indices = np.linspace(0, len(signal) - 1, new_length)
            return np.interp(new_indices, old_indices, signal)

        channels = []
        for ch in range(signal.shape[1]):
            channel_data = signal[:, ch]
            new_length = max(int(len(channel_data) * ratio), 1)
            old_indices = np.arange(len(channel_data))
            new_indices = np.linspace(0, len(channel_data) - 1, new_length)
            channels.append(np.interp(new_indices, old_indices, channel_data))
        return np.column_stack(channels)

    def _apply_deemphasis(self, audio: np.ndarray) -> np.ndarray:
        """Apply de-emphasis filter (single-pole IIR lowpass)."""
        if audio.ndim == 1:
            output = np.zeros_like(audio)
            if self._deemph_state.shape[0] != 1:
                self._deemph_state = np.zeros(1, dtype=np.float32)
            for i in range(len(audio)):
                self._deemph_state[0] = (
                    self._deemph_state[0]
                    + self._deemph_alpha * (audio[i] - self._deemph_state[0])
                )
                output[i] = self._deemph_state[0]
            return output

        channels = audio.shape[1]
        if self._deemph_state.shape[0] != channels:
            self._deemph_state = np.zeros(channels, dtype=np.float32)

        output = np.zeros_like(audio)
        for ch in range(channels):
            state = self._deemph_state[ch]
            for i in range(audio.shape[0]):
                state = state + self._deemph_alpha * (audio[i, ch] - state)
                output[i, ch] = state
            self._deemph_state[ch] = state
        return output

    def _design_fir_lowpass(self, cutoff: float, fs: int, taps: int = 129) -> np.ndarray:
        nyquist = fs / 2.0
        norm_cutoff = min(cutoff / nyquist, 0.99)
        indices = np.arange(taps) - (taps - 1) / 2.0
        sinc = np.sinc(norm_cutoff * indices)
        window = np.hamming(taps)
        kernel = norm_cutoff * sinc * window
        kernel /= np.sum(kernel) if np.sum(kernel) else 1.0
        return kernel.astype(np.float32)

    def _design_fir_bandpass(self, low_cut: float, high_cut: float, fs: int, taps: int = 129) -> np.ndarray:
        low = self._design_fir_lowpass(high_cut, fs, taps)
        high = self._design_fir_lowpass(low_cut, fs, taps)
        kernel = low - high
        return kernel.astype(np.float32)

    def _lpr_filter_signal(self, signal: np.ndarray) -> np.ndarray:
        filtered = np.convolve(signal, self._lpr_filter, mode="same")
        return filtered

    def _decode_stereo(self, multiplex: np.ndarray, sample_indices: np.ndarray) -> Optional[np.ndarray]:
        if not self._stereo_enabled or len(multiplex) == 0:
            return None

        lpr = np.convolve(multiplex, self._lpr_filter, mode="same")

        time = sample_indices / float(self.config.sample_rate)
        carrier = 2.0 * np.cos(2.0 * np.pi * 38000.0 * time)
        suppressed = multiplex * carrier
        lmr = np.convolve(suppressed, self._dsb_filter, mode="same")

        left = 0.5 * (lpr + lmr)
        right = 0.5 * (lpr - lmr)
        stereo = np.column_stack((left, right))
        return stereo

    def _extract_rbds(self, multiplex: np.ndarray, sample_indices: np.ndarray) -> Optional[RBDSData]:
        if not self._rbds_enabled or len(multiplex) == 0:
            return None

        rbds_band = np.convolve(multiplex, self._rbds_bandpass, mode="same")
        time = sample_indices / float(self.config.sample_rate)
        baseband = rbds_band * np.exp(-1j * 2.0 * np.pi * 57000.0 * time)
        baseband_real = np.convolve(baseband.real, self._rbds_lowpass, mode="same")

        resampled = self._resample(
            baseband_real,
            self.config.sample_rate,
            int(self._rbds_target_rate),
        )

        if len(resampled) == 0:
            return None

        samples_per_symbol = max(self._rbds_target_rate / self._rbds_symbol_rate, 1.0)
        phase = self._rbds_symbol_phase
        bits: List[int] = []

        while phase + samples_per_symbol < len(resampled):
            center = phase + samples_per_symbol / 2.0
            idx = int(min(max(int(center), 0), len(resampled) - 1))
            sample = resampled[idx]
            bits.append(1 if sample >= 0 else 0)

            early_idx = int(min(max(int(center - samples_per_symbol / 4.0), 0), len(resampled) - 1))
            late_idx = int(min(max(int(center + samples_per_symbol / 4.0), 0), len(resampled) - 1))
            early = resampled[early_idx]
            late = resampled[late_idx]
            error = (late - early) * sample
            phase += samples_per_symbol - (self._rbds_loop_gain * error)

        self._rbds_symbol_phase = phase - len(resampled)

        if bits:
            self._rbds_bit_buffer.extend(bits)

        return self._decode_rbds_groups()

    def _decode_rbds_groups(self) -> Optional[RBDSData]:
        changed = False
        while len(self._rbds_bit_buffer) >= 26:
            block_bits = self._rbds_bit_buffer[:26]
            block_type, data_word = self._decode_rbds_block(block_bits)

            if block_type is None:
                del self._rbds_bit_buffer[0]
                self._rbds_expected_block = None
                self._rbds_partial_group.clear()
                continue

            if self._rbds_expected_block is None:
                if block_type != "A":
                    del self._rbds_bit_buffer[0]
                    continue
                self._rbds_partial_group = [data_word]
                self._rbds_expected_block = 1
                del self._rbds_bit_buffer[:26]
                continue

            sequence = ["A", "B", "C", "D"]
            expected = sequence[self._rbds_expected_block]
            if expected == "C" and block_type == "C":
                pass
            elif expected != block_type:
                self._rbds_expected_block = None
                self._rbds_partial_group.clear()
                del self._rbds_bit_buffer[0]
                continue

            self._rbds_partial_group.append(data_word)
            self._rbds_expected_block += 1
            del self._rbds_bit_buffer[:26]

            if self._rbds_expected_block >= 4:
                group_changed = self._rbds_decoder.process_group(tuple(self._rbds_partial_group))
                changed = group_changed or changed
                self._rbds_partial_group = []
                self._rbds_expected_block = None

        if changed:
            return self._rbds_decoder.get_current_data()
        return None

    def _decode_rbds_block(self, bits: List[int]) -> Tuple[Optional[str], Optional[int]]:
        value = 0
        for bit in bits:
            value = (value << 1) | int(bit)

        data_word = value >> 10
        check_word = value & 0x3FF

        remainder = self._rbds_crc(data_word << 10)
        syndrome = remainder ^ check_word

        offset_map = {
            0x0FC: "A",
            0x198: "B",
            0x168: "C",
            0x350: "C",
            0x1B4: "D",
        }
        block_type = offset_map.get(syndrome)
        if block_type is None:
            return None, None
        return block_type, data_word

    def _rbds_crc(self, value: int) -> int:
        polynomial = 0b11101101001
        for bit in range(value.bit_length() - 1, 9, -1):
            if value & (1 << bit):
                value ^= polynomial << (bit - 10)
        return value & 0x3FF


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
        self.ps_name = [' '] * 8  # 8 characters
        self.radio_text = [' '] * 64  # 64 characters
        self.pty = None
        self.tp = None
        self.ta = None
        self.ms = None
        self._radio_text_ab = 0

    def process_group(self, group_data: Tuple[int, int, int, int]) -> Optional[bool]:
        """
        Process a decoded RBDS group.

        Args:
            group_data: Tuple of four 16-bit RBDS blocks (A, B, C, D)

        Returns:
            True if metadata changed, otherwise False/None
        """
        a, b, c, d = group_data
        changed = False

        pi_code = f"{a:04X}"
        if self.pi_code != pi_code:
            self.pi_code = pi_code
            changed = True

        pty = (b >> 5) & 0x1F
        if self.pty != pty:
            self.pty = pty
            changed = True

        tp = bool((b >> 10) & 0x1)
        if self.tp != tp:
            self.tp = tp
            changed = True

        ta = bool((b >> 4) & 0x1)
        if self.ta != ta:
            self.ta = ta
            changed = True

        ms = bool((b >> 3) & 0x1)
        if self.ms != ms:
            self.ms = ms
            changed = True

        group_type = (b >> 12) & 0xF
        version_b = bool((b >> 11) & 0x1)

        if group_type == 0:
            address = b & 0x3
            chars = d
            changed = self._update_ps_name(address, chars) or changed
        elif group_type == 2:
            text_segment = b & 0xF
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._radio_text_ab:
                self._radio_text_ab = ab_flag
                self.radio_text = [' '] * 64
                changed = True

            if not version_b:
                blocks = (c, d)
                for offset, block in enumerate(blocks):
                    chars = [
                        (block >> 8) & 0x7F,
                        block & 0x7F,
                    ]
                    for i, code in enumerate(chars):
                        idx = text_segment * 4 + offset * 2 + i
                        if idx < len(self.radio_text):
                            if self._update_radio_text(idx, code):
                                changed = True
            else:
                chars = [(d >> 8) & 0x7F, d & 0x7F]
                for i, code in enumerate(chars):
                    idx = text_segment * 2 + i
                    if idx < len(self.radio_text):
                        if self._update_radio_text(idx, code):
                            changed = True

        return changed

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

    def _update_ps_name(self, address: int, chars: int) -> bool:
        idx = address * 2
        updated = False
        for offset in range(2):
            char_code = (chars >> (8 * (1 - offset))) & 0xFF
            if 32 <= char_code < 127:
                char = chr(char_code)
            else:
                char = ' '
            pos = idx + offset
            if pos < len(self.ps_name) and self.ps_name[pos] != char:
                self.ps_name[pos] = char
                updated = True
        return updated

    def _update_radio_text(self, index: int, code: int) -> bool:
        if index >= len(self.radio_text):
            return False
        char = chr(code) if 32 <= code < 127 else ' '
        if self.radio_text[index] != char:
            self.radio_text[index] = char
            return True
        return False


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
