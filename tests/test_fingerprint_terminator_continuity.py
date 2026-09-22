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

"""Regression test for the station-fingerprint trill (3 x 0xA9 terminator)
being audibly weakened right after the tone-edge-shaping fix that added
apply_edge_ramp()/apply_low_pass_filter() to every synthesized burst.

The header FSK bits and the terminator FSK bits are always concatenated
with zero gap -- one continuous burst on the wire (see every caller in
EASAudioGenerator: header + terminator + silence, repeated). An earlier
version of EASAudioGenerator._build_header_burst() generated and shaped
the header and the terminator as two INDEPENDENT segments, so each got its
own 5 ms raised-cosine edge-ramp. That introduced a spurious amplitude dip
exactly at the header/terminator junction (the header faded toward zero at
its tail, then the terminator faded from zero at its head, even though
there is no silence there) and burned ~22% of the terminator's very short
(~46 ms) duration on its own redundant fade-in -- weakening the audible
"trill" watermark even though the encoded bytes still decoded correctly.

This guards the fix: header + terminator must be generated and shaped as
ONE continuous signal, with full-strength amplitude straight through the
junction.
"""

import math

from app_utils.eas_fsk import SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ, encode_same_bits
from app_utils.eas.generator import EASAudioGenerator


def _rms(samples):
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


def _build_generator(sample_rate: int) -> EASAudioGenerator:
    import tempfile
    from unittest.mock import MagicMock

    cfg = {
        'output_dir': tempfile.mkdtemp(),
        'sample_rate': sample_rate,
        'endec_fingerprint': True,
    }
    return EASAudioGenerator(cfg, MagicMock())


def test_header_terminator_junction_has_no_amplitude_dip():
    sample_rate = 16000
    gen = _build_generator(sample_rate)
    amplitude = 0.7 * 32767

    header = 'ZCZC-WXR-TOR-039049+0015-2652315-KR8MER  -'
    header_bits = encode_same_bits(header, include_preamble=True)

    burst = gen._build_header_burst(header_bits, amplitude)

    samples_per_bit = sample_rate / float(SAME_BAUD)
    junction_sample = int(len(header_bits) * samples_per_bit)

    # A ~6 ms window straddling the exact header/terminator boundary.
    half_win = int(0.003 * sample_rate)
    junction_window = burst[max(0, junction_sample - half_win): junction_sample + half_win]

    # A window safely inside the terminator's own middle, away from the
    # true tail-edge ramp at the very end of the whole burst.
    terminator_len_samples = int(24 * samples_per_bit)  # 3 x 0xA9 = 24 bits
    inner_start = junction_sample + int(terminator_len_samples * 0.35)
    inner_end = inner_start + int(terminator_len_samples * 0.3)
    interior_window = burst[inner_start:inner_end]

    junction_rms = _rms(junction_window)
    interior_rms = _rms(interior_window)

    assert interior_rms > 0.5 * amplitude, "sanity check: terminator interior should be near full scale"
    assert junction_rms > 0.7 * interior_rms, (
        f"amplitude dips at the header/terminator junction (junction RMS={junction_rms:.0f}, "
        f"terminator interior RMS={interior_rms:.0f}) -- header and terminator are being "
        f"shaped as two independent segments again instead of one continuous burst"
    )


def test_fingerprint_terminator_still_present_when_enabled():
    sample_rate = 16000
    gen = _build_generator(sample_rate)
    amplitude = 0.7 * 32767
    header_bits = encode_same_bits('ZCZC-WXR-TOR-039049+0015-2652315-KR8MER  -', include_preamble=True)

    with_fingerprint = gen._build_header_burst(header_bits, amplitude)
    gen._fingerprint_enabled = False
    without_fingerprint = gen._build_header_burst(header_bits, amplitude)

    samples_per_bit = sample_rate / float(SAME_BAUD)
    expected_terminator_samples = int(24 * samples_per_bit)
    assert len(with_fingerprint) - len(without_fingerprint) == expected_terminator_samples or \
        abs((len(with_fingerprint) - len(without_fingerprint)) - expected_terminator_samples) <= 2
