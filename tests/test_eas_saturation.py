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

"""Tests for apply_saturation() (app_utils/eas_fsk.py) -- the mild,
calibrated odd-harmonic/intermodulation saturation stage added to match the
tone character of a reference Sage 3644 recreation (github.com/
wagwan-piffting-blud/EAS-Tools), and end-to-end verification that it does
not degrade SAME/EOM decodability or the station fingerprint terminator.

Calibration reference (measured from the eas.tools Sage recreation, relative
to each signal's fundamental):
  Single 1562.5 Hz tone:  3rd harmonic -21.3 dB, 5th -32.4 dB, 9th -42.4 dB.
  Two-tone 853/960 Hz:    3f1 -31.9 dB, 3f2 -30.5 dB,
                          2f1-f2 -27.6 dB, 2f2-f1 -29.0 dB,
                          2f1+f2 -27.6 dB, 2f2+f1 -29.0 dB.
"""

import math
import tempfile
from unittest.mock import MagicMock

import numpy as np
import pytest

from app_utils.eas_fsk import (
    SAME_MARK_FREQ,
    SAME_SPACE_FREQ,
    apply_saturation,
    encode_same_bits,
)
from app_utils.eas.generator import EASAudioGenerator
from app_utils.eas_demod import ENDEC_MODE_EAS_STATION, SAMEDemodulatorCore


def _tone(freq_hz, sample_rate, seconds, amplitude=22937.0):
    n = int(seconds * sample_rate)
    return [int(math.sin(2 * math.pi * freq_hz * i / sample_rate) * amplitude) for i in range(n)]


def _two_tone(f1, f2, sample_rate, seconds, amplitude=22937.0):
    n = int(seconds * sample_rate)
    return [
        int(((math.sin(2 * math.pi * f1 * i / sample_rate) + math.sin(2 * math.pi * f2 * i / sample_rate)) / 2) * amplitude)
        for i in range(n)
    ]


def _harmonic_db(samples, sample_rate, fundamental, multiple):
    arr = np.asarray(samples, dtype=np.float64)
    windowed = arr * np.hanning(len(arr))
    spec = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(arr), 1.0 / sample_rate)
    fund_idx = int(np.argmin(np.abs(freqs - fundamental)))
    harm_idx = int(np.argmin(np.abs(freqs - fundamental * multiple)))
    fund_amp = spec[max(0, fund_idx - 2):fund_idx + 3].max()
    harm_amp = spec[max(0, harm_idx - 2):harm_idx + 3].max()
    return 20 * np.log10(harm_amp / fund_amp)


class TestEdgeCases:
    @pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 10, 50])
    def test_length_preserved_for_short_inputs(self, n):
        samples = [1000 * ((i % 2) * 2 - 1) for i in range(n)]
        out = apply_saturation(samples, 16000)
        assert len(out) == n

    def test_all_zero_input_stays_zero(self):
        out = apply_saturation([0] * 200, 16000)
        assert all(x == 0 for x in out)
        assert len(out) == 200

    def test_terminator_length_signal_no_crash_and_length_matches(self):
        # 3 x 0xA9 at 16 kHz / 520.8 baud is ~46 ms (737 samples) -- the
        # shortest real segment this gets applied to in production.
        sr = 16000
        tone = _tone(SAME_SPACE_FREQ, sr, 737.0 / sr)
        out = apply_saturation(tone, sr)
        assert len(out) == len(tone)
        assert max(abs(x) for x in out) <= 32767

    def test_never_clips_int16_range(self):
        sr = 44100
        tone = _tone(1562.5, sr, 1.0)
        out = apply_saturation(tone, sr)
        assert max(abs(x) for x in out) <= 32767


class TestHarmonicCalibration:
    """Verify the saturation stage reproduces the measured eas.tools Sage
    reference's harmonic/intermodulation levels within a reasonable tolerance."""

    def test_single_tone_harmonics_match_reference(self):
        sr = 44100  # high enough that even the 9th harmonic clears Nyquist
        tone = _tone(SAME_SPACE_FREQ, sr, 0.2)
        out = apply_saturation(tone, sr)

        h3 = _harmonic_db(out, sr, SAME_SPACE_FREQ, 3)
        h5 = _harmonic_db(out, sr, SAME_SPACE_FREQ, 5)
        h9 = _harmonic_db(out, sr, SAME_SPACE_FREQ, 9)

        assert -25.0 < h3 < -18.0, f"3rd harmonic {h3:.1f}dB outside tolerance of -21.3dB reference"
        assert -37.0 < h5 < -25.0, f"5th harmonic {h5:.1f}dB outside tolerance of -32.4dB reference"
        assert -50.0 < h9 < -33.0, f"9th harmonic {h9:.1f}dB outside tolerance of -42.4dB reference"

    def test_two_tone_intermodulation_matches_reference(self):
        sr = 44100
        f1, f2 = 853.0, 960.0
        tone = _two_tone(f1, f2, sr, 0.3)
        out = apply_saturation(tone, sr)

        # 2f1-f2 and 2f2-f1 measured at -27.6/-29.0 dB in the reference.
        arr = np.asarray(out, dtype=np.float64)
        windowed = arr * np.hanning(len(arr))
        spec = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(arr), 1.0 / sr)

        def level_at(freq):
            idx = int(np.argmin(np.abs(freqs - freq)))
            fund_idx = int(np.argmin(np.abs(freqs - f1)))
            fund_amp = spec[max(0, fund_idx - 2):fund_idx + 3].max()
            amp = spec[max(0, idx - 2):idx + 3].max()
            return 20 * np.log10(amp / fund_amp)

        im_2f1_minus_f2 = level_at(2 * f1 - f2)
        im_2f2_minus_f1 = level_at(2 * f2 - f1)
        assert -35.0 < im_2f1_minus_f2 < -20.0
        assert -35.0 < im_2f2_minus_f1 < -20.0

    def test_saturation_disabled_by_low_drive_stays_near_clean(self):
        # Sanity check the calibration is meaningfully different from a no-op:
        # a threshold near 1.0 (barely clipping) should leave far less
        # harmonic energy than the default 0.8.
        sr = 44100
        tone = _tone(SAME_SPACE_FREQ, sr, 0.2)
        default_out = apply_saturation(tone, sr, threshold_fraction=0.8)
        gentle_out = apply_saturation(tone, sr, threshold_fraction=0.99)
        h3_default = _harmonic_db(default_out, sr, SAME_SPACE_FREQ, 3)
        h3_gentle = _harmonic_db(gentle_out, sr, SAME_SPACE_FREQ, 3)
        assert h3_default > h3_gentle + 10, "default drive should add substantially more 3rd-harmonic energy than a near-unity threshold"


class TestNoAliasingAtLowSampleRates:
    def test_8khz_degrades_gracefully_without_alias_garbage(self):
        # At 8 kHz (Nyquist 4 kHz), even the 3rd harmonic of the space tone
        # (4687.5 Hz) exceeds Nyquist -- the oversample+downsample path must
        # drop it cleanly via anti-aliasing filtering rather than fold it
        # back in-band as uncontrolled noise.
        sr = 8000
        tone = _tone(SAME_SPACE_FREQ, sr, 0.2)
        out = apply_saturation(tone, sr)
        arr = np.asarray(out, dtype=np.float64)
        windowed = arr * np.hanning(len(arr))
        spec = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(arr), 1.0 / sr)
        total_power = np.sum(spec ** 2)
        # Everything above 3400 Hz (well below the 4000 Hz Nyquist, clear of
        # the fundamental) should be a small fraction of total energy --
        # aliased garbage would show up as broadband energy filling this band.
        above = np.sum(spec[freqs > 3400] ** 2)
        assert above / total_power < 0.05


class TestEndToEndDecodability:
    """The critical safety property: saturation must not break SAME/EOM
    decoding or the station fingerprint terminator on the real pipeline."""

    def _build_generator(self, sample_rate):
        cfg = {'output_dir': tempfile.mkdtemp(), 'sample_rate': sample_rate, 'attention_tone_seconds': 8}
        return EASAudioGenerator(cfg, MagicMock())

    @pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050, 44100])
    def test_same_header_decodes_correctly_with_saturation(self, sample_rate):
        header = 'ZCZC-WXR-TOR-039049+0015-2652315-KR8MER  -'
        gen = self._build_generator(sample_rate)
        result = gen.build_manual_components(
            type('FakeAlert', (), {'identifier': 'sat-decode-test'})(),
            header, tone_profile='attention', include_tts=False,
        )
        same_samples = result['same_samples']
        arr = np.asarray(same_samples, dtype=np.float32) / 32768.0

        core = SAMEDemodulatorCore(sample_rate, apply_bandpass=True)
        core.process_samples(arr)

        assert len(core.messages) >= 1, f"no SAME burst decoded at {sample_rate} Hz"
        decoded_headers = [getattr(m, 'header', m) for m in core.messages]
        assert header in decoded_headers, (
            f"decoded header mismatch at {sample_rate} Hz: {decoded_headers!r}"
        )
        assert core.endec_mode == ENDEC_MODE_EAS_STATION, (
            f"fingerprint terminator not recognized at {sample_rate} Hz: "
            f"terminator_runs={core._all_terminator_runs!r}"
        )

    def test_composite_never_clips_with_saturation(self):
        header = 'ZCZC-WXR-TOR-039049+0015-2652315-KR8MER  -'
        gen = self._build_generator(16000)
        result = gen.build_manual_components(
            type('FakeAlert', (), {'identifier': 'sat-clip-test'})(),
            header, tone_profile='attention', include_tts=False,
        )
        composite = np.asarray(result['composite_samples'], dtype=np.float64)
        assert np.max(np.abs(composite)) <= 32767
