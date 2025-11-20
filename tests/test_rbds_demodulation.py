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

import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.demodulation import DemodulatorConfig, FMDemodulator  # noqa: E402


def _make_demodulator():
    config = DemodulatorConfig(
        modulation_type="FM",
        sample_rate=200_000,
        audio_sample_rate=48_000,
        enable_rbds=True,
    )
    return FMDemodulator(config)


def test_rbds_symbol_to_bit_handles_differential_bpsk():
    demod = _make_demodulator()

    samples = np.array([0.25, 0.3, -0.2, -0.18, 0.5, -0.4], dtype=np.float32)
    bits = [demod._rbds_symbol_to_bit(float(sample)) for sample in samples]

    assert bits == [0, 0, 1, 0, 1, 1]


def test_rbds_symbol_to_bit_handles_zero_crossings():
    demod = _make_demodulator()

    zero_crossing = np.array([0.0, -0.01, 0.02], dtype=np.float32)
    bits = [demod._rbds_symbol_to_bit(float(sample)) for sample in zero_crossing]

    assert bits[0] == 0
    assert bits[1] == 1
    assert bits[2] == 1
