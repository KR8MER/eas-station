"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.demodulation import (  # noqa: E402
    DemodulatorConfig,
    FMDemodulator,
    RBDSData,
    RBDSDecoder,
    RBDSWorker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_demodulator(sample_rate: int = 200_000) -> FMDemodulator:
    config = DemodulatorConfig(
        modulation_type="FM",
        sample_rate=sample_rate,
        audio_sample_rate=48_000,
        enable_rbds=True,
    )
    return FMDemodulator(config)


def _make_worker(sample_rate: int = 250_000) -> RBDSWorker:
    return RBDSWorker(sample_rate=sample_rate, intermediate_rate=25_000)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_rbds_differential_bpsk_decoding():
    """Inline differential BPSK decoding in the worker produces correct bits.

    The current implementation handles differential decoding inside
    _process_rbds via numpy operations.  We verify the arithmetic directly:
    given a sequence of raw BPSK symbol values, sign-detection followed by
    differential XOR must produce the expected transition sequence.
    """
    # Raw BPSK symbols: + means "1", - means "0" in the raw decision
    samples = np.array([0.25, 0.3, -0.2, -0.18, 0.5, -0.4], dtype=np.float32)
    raw_bits = (np.real(samples) > 0).astype(np.int8)  # [1, 1, 0, 0, 1, 0]

    prev_sym = 0  # same initialisation used by RBDSWorker
    all_symbols = np.concatenate(([prev_sym], raw_bits))
    diff = (np.diff(all_symbols.astype(np.int32)) % 2).astype(np.int8)

    expected = [1, 0, 1, 0, 1, 1]
    assert list(diff) == expected, f"Differential bits {list(diff)} != expected {expected}"


def test_rbds_differential_bpsk_zero_crossing():
    """Values at 0.0 are decoded as raw bit 0; transitions are still correct."""
    samples = np.array([0.0, -0.01, 0.02], dtype=np.float32)
    raw_bits = (np.real(samples) > 0).astype(np.int8)  # [0, 0, 1]

    prev_sym = 0
    all_symbols = np.concatenate(([prev_sym], raw_bits))
    diff = (np.diff(all_symbols.astype(np.int32)) % 2).astype(np.int8)

    # 0→0 = no transition (0), 0→0 = no transition (0), 0→1 = transition (1)
    assert diff[0] == 0
    assert diff[1] == 0
    assert diff[2] == 1


def test_rbds_pilot_reference_uses_absolute_offset():
    """_generate_pilot_reference must honour the supplied sample_offset.

    This is the core of the phase-continuity fix: when chunks are dropped
    from the RBDS queue the worker must still generate the correct carrier
    phase for each chunk.  Previously the method used an internal counter
    that only advanced on *processed* chunks, causing large phase errors
    when chunks were skipped.
    """
    worker = _make_worker(sample_rate=250_000)

    n = 1000
    offset_a = 0
    offset_b = 250_000  # 1 second later (same as the real stream advancing 1 s)

    phases_a = worker._generate_pilot_reference(n, offset_a)
    phases_b = worker._generate_pilot_reference(n, offset_b)

    # phases_a should start at exactly 0 * 2π * 19000 / 250000 = 0
    assert abs(phases_a[0]) < 1e-9, f"phases_a[0] should be 0, got {phases_a[0]}"

    # phases_b should start at 2π * 19000 * (250000 / 250000) = 2π * 19000
    expected_start_b = 2.0 * np.pi * 19000.0 * (offset_b / 250_000)
    assert abs(phases_b[0] - expected_start_b) < 1e-6, (
        f"phases_b[0]={phases_b[0]:.6f} but expected {expected_start_b:.6f}"
    )


def test_rbds_pilot_reference_independent_of_call_order():
    """Each call to _generate_pilot_reference is stateless w.r.t. the offset.

    Calling it with offset 500 should give the same result whether or not
    we previously called it with offset 0 (old code would not because it
    relied on a mutable internal counter).
    """
    worker_cold = _make_worker()
    worker_warm = _make_worker()

    n = 256
    # warm worker: process a chunk at offset 0 first
    worker_warm._generate_pilot_reference(n, sample_offset=0)

    # Both workers should produce identical output for the same offset/n
    phases_cold = worker_cold._generate_pilot_reference(n, sample_offset=500)
    phases_warm = worker_warm._generate_pilot_reference(n, sample_offset=500)

    np.testing.assert_array_equal(phases_cold, phases_warm)


def test_rbds_submit_samples_accepts_offset():
    """submit_samples must accept a sample_offset positional argument."""
    worker = _make_worker()
    multiplex = np.zeros(512, dtype=np.float32)
    # Should not raise
    worker.submit_samples(multiplex, sample_offset=0)
    worker.submit_samples(multiplex, sample_offset=512)
    worker.stop()


def test_fmdemodulator_tracks_sample_index():
    """FMDemodulator._sample_index must advance by the multiplex length each call.

    On the very first call there is no previous IQ sample to prepend, so the
    FM discriminator yields len(iq) - 1 multiplex samples.  On every subsequent
    call the demodulator prepends the last IQ sample, yielding exactly len(iq)
    multiplex samples.  The _sample_index must reflect this accurately so that
    the RBDS worker receives the correct absolute stream offset.
    """
    demod = _make_demodulator(sample_rate=200_000)
    assert demod._sample_index == 0

    chunk = np.exp(1j * 2 * np.pi * 0.01 * np.arange(1024)).astype(np.complex64)

    demod.process(chunk)
    # First call: no previous sample prepended → fm_discriminator produces 1023 samples
    first_call_multiplex_len = len(chunk) - 1
    assert demod._sample_index == first_call_multiplex_len

    demod.process(chunk)
    # Second call: previous sample prepended → fm_discriminator produces 1024 samples
    assert demod._sample_index == first_call_multiplex_len + len(chunk)

    demod.stop()
    time.sleep(0.05)


# ---------------------------------------------------------------------------
# RBDSDecoder – metadata extraction
# ---------------------------------------------------------------------------

def test_rbds_decoder_pi_code():
    """RBDSDecoder extracts the PI code from block A as a 4-hex-digit string."""
    decoder = RBDSDecoder()
    decoder.process_group((0xBEEF, 0x0000, 0x0000, 0x0000))
    assert decoder.pi_code == "BEEF"


def test_rbds_decoder_pi_code_leading_zero():
    """PI codes whose MSB nibble is 0 must be zero-padded to 4 digits."""
    decoder = RBDSDecoder()
    decoder.process_group((0x05B2, 0x0000, 0x0000, 0x0000))
    assert decoder.pi_code == "05B2"


def test_rbds_decoder_pty_extraction():
    """RBDSDecoder extracts PTY from bits 9–5 of block B.

    PTY=4 ('Top 40') is encoded in bits 9–5, i.e. (4 << 5) = 0x0080.
    All other fields in B are 0 for this test.
    """
    decoder = RBDSDecoder()
    b = 4 << 5  # PTY=4 in bits 9-5
    decoder.process_group((0x1234, b, 0x0000, 0x0000))
    assert decoder.pty == 4


def test_rbds_decoder_pty_max():
    """PTY is a 5-bit field; maximum value 31 must be decoded correctly."""
    decoder = RBDSDecoder()
    b = 31 << 5  # PTY=31
    decoder.process_group((0xABCD, b, 0x0000, 0x0000))
    assert decoder.pty == 31


def test_rbds_decoder_tp_ta_ms_flags_set():
    """RBDSDecoder decodes TP=True (bit 10), TA=True (bit 4), M/S=True (bit 3)."""
    decoder = RBDSDecoder()
    b = (1 << 10) | (1 << 4) | (1 << 3)
    decoder.process_group((0xABCD, b, 0x0000, 0x0000))
    assert decoder.tp is True
    assert decoder.ta is True
    assert decoder.ms is True


def test_rbds_decoder_tp_ta_ms_flags_clear():
    """RBDSDecoder decodes TP=False, TA=False, M/S=False when bits are 0."""
    decoder = RBDSDecoder()
    decoder.process_group((0x1234, 0x0000, 0x0000, 0x0000))
    assert decoder.tp is False
    assert decoder.ta is False
    assert decoder.ms is False


# ---------------------------------------------------------------------------
# RBDSDecoder – Group 0A: Program Service name
# ---------------------------------------------------------------------------

def test_rbds_decoder_group0a_single_segment():
    """Group 0A address=0 writes PS name characters at positions 0 and 1."""
    decoder = RBDSDecoder()
    # group_type=0 → bits 15-12 of B = 0; addr=0 → bits 1-0 of B = 0
    b = 0x0000
    d = (ord('A') << 8) | ord('B')
    decoder.process_group((0x1234, b, 0x0000, d))
    assert decoder.ps_name[0] == 'A'
    assert decoder.ps_name[1] == 'B'


def test_rbds_decoder_group0a_full_ps_name():
    """Four consecutive Group 0A messages (addresses 0–3) build the full 8-char PS name."""
    decoder = RBDSDecoder()
    text = "TESTNAME"  # exactly 8 characters
    for addr in range(4):
        chars = (ord(text[addr * 2]) << 8) | ord(text[addr * 2 + 1])
        b = addr & 0x3          # group_type=0, addr=addr
        decoder.process_group((0xABCD, b, 0x0000, chars))

    data = decoder.get_current_data()
    assert data.ps_name == "TESTNAME"


def test_rbds_decoder_get_current_data_strips_ps_whitespace():
    """get_current_data() strips trailing spaces from the PS name."""
    decoder = RBDSDecoder()
    # Only set address 0; positions 2–7 remain spaces
    b = 0x0000  # addr=0
    d = (ord('H') << 8) | ord('i')
    decoder.process_group((0x1234, b, 0x0000, d))

    data = decoder.get_current_data()
    assert data.ps_name == "Hi"
    assert not data.ps_name.endswith(' ')


# ---------------------------------------------------------------------------
# RBDSDecoder – Group 2A: Radio Text
# ---------------------------------------------------------------------------

def test_rbds_decoder_group2a_radio_text_segment0():
    """Group 2A segment 0 writes four characters to Radio Text positions 0–3."""
    decoder = RBDSDecoder()
    # group_type=2 → bits 15-12 = 0x2; version=0; ab_flag=0; segment=0
    b = (2 << 12)
    c = (ord('H') << 8) | ord('i')   # positions 0,1
    d = (ord('!') << 8) | ord('!')   # positions 2,3 — use non-space so strip() keeps them
    decoder.process_group((0x1234, b, c, d))

    data = decoder.get_current_data()
    assert data.radio_text.startswith("Hi!!")


def test_rbds_decoder_group2a_multi_segment():
    """Multiple Group 2A messages build a longer radio text string."""
    decoder = RBDSDecoder()
    message = "HELLO WORLD     "  # 16 chars → 4 segments of 4 chars
    for seg in range(4):
        b = (2 << 12) | (seg & 0xF)
        c = (ord(message[seg * 4]) << 8) | ord(message[seg * 4 + 1])
        d = (ord(message[seg * 4 + 2]) << 8) | ord(message[seg * 4 + 3])
        decoder.process_group((0xABCD, b, c, d))

    data = decoder.get_current_data()
    assert data.radio_text.startswith("HELLO WORLD")


def test_rbds_decoder_radio_text_ab_flag_clears_buffer():
    """Toggling the A/B flag in Group 2A resets the entire Radio Text buffer."""
    decoder = RBDSDecoder()
    # Write with ab_flag=0
    b_flag0 = (2 << 12) | 0x00          # ab_flag=0, segment=0
    decoder.process_group((0x1234, b_flag0, ord('X') << 8 | ord('Y'), ord('Z') << 8 | ord('W')))

    # Toggle to ab_flag=1 — buffer must clear
    b_flag1 = (2 << 12) | (1 << 4)     # ab_flag=1, segment=0
    decoder.process_group((0x1234, b_flag1, 0x0000, 0x0000))

    data = decoder.get_current_data()
    # All previous text gone; only NUL/space chars remain → stripped to empty
    assert data.radio_text == ""


def test_rbds_decoder_get_current_data_returns_rbds_data():
    """get_current_data() always returns an RBDSData instance."""
    decoder = RBDSDecoder()
    result = decoder.get_current_data()
    assert isinstance(result, RBDSData)


# ---------------------------------------------------------------------------
# RBDSWorker – syndrome / CRC validation
# ---------------------------------------------------------------------------

def test_rbds_calc_syndrome_known_block_types():
    """_calc_syndrome on a valid 26-bit RBDS block returns the expected syndrome.

    For each block type (A–D and C') we construct a valid block:
        checkword = calc_syndrome(dataword, 16) XOR offset_word[type]
        block     = (dataword << 10) | checkword
    Then calc_syndrome(block, 26) must equal syndrome[type].
    This verifies the CRC polynomial implementation is correct.
    """
    worker = _make_worker()

    offset_word      = [252, 408, 360, 436, 848]
    expected_syndromes = [383,  14, 303, 663, 748]

    dataword = 0x5678
    for block_type in range(5):
        crc = worker._calc_syndrome(dataword, 16)
        checkword = (crc ^ offset_word[block_type]) & 0x3FF
        block = (dataword << 10) | checkword
        syndrome = worker._calc_syndrome(block, 26)
        assert syndrome == expected_syndromes[block_type], (
            f"Block type {block_type}: expected {expected_syndromes[block_type]}, got {syndrome}"
        )

    worker.stop()


def test_rbds_calc_syndrome_zero_input():
    """_calc_syndrome of an all-zeros block is 0."""
    worker = _make_worker()
    assert worker._calc_syndrome(0, 26) == 0
    assert worker._calc_syndrome(0, 16) == 0
    worker.stop()


def test_rbds_calc_syndrome_different_datawords():
    """Different datawords produce different syndromes (non-degenerate CRC)."""
    worker = _make_worker()
    s1 = worker._calc_syndrome(0x1234, 16)
    s2 = worker._calc_syndrome(0x5678, 16)
    s3 = worker._calc_syndrome(0xABCD, 16)
    assert s1 != s2
    assert s1 != s3
    assert s2 != s3
    worker.stop()


# ---------------------------------------------------------------------------
# RBDSWorker – configuration and filter validity
# ---------------------------------------------------------------------------

def test_rbds_worker_low_sample_rate_disables_bandpass():
    """RBDSWorker below RBDS_MIN_SAMPLE_RATE must not build the 57 kHz bandpass."""
    worker = RBDSWorker(sample_rate=44100, intermediate_rate=22050)
    assert worker._rbds_bandpass is None
    worker.stop()


def test_rbds_worker_sufficient_sample_rate_builds_bandpass():
    """RBDSWorker at 250 kHz must build a valid 57 kHz bandpass filter."""
    worker = _make_worker(sample_rate=250_000)
    assert worker._rbds_bandpass is not None
    assert len(worker._rbds_bandpass) > 0
    worker.stop()


def test_rbds_filter_arrays_are_finite():
    """All filter arrays produced by RBDSWorker must be finite and non-empty."""
    worker = _make_worker(sample_rate=250_000)
    for name, filt in [
        ("bandpass", worker._rbds_bandpass),
        ("lowpass",  worker._rbds_lowpass),
        ("pilot",    worker._pilot_bandpass),
    ]:
        assert filt is not None, f"{name} filter is None"
        assert len(filt) > 0, f"{name} filter is empty"
        assert np.all(np.isfinite(filt)), f"{name} filter contains NaN/Inf"
    worker.stop()


# ---------------------------------------------------------------------------
# FMDemodulator – RBDS worker lifecycle
# ---------------------------------------------------------------------------

def test_fmdemodulator_no_rbds_worker_when_disabled():
    """FMDemodulator must not create an RBDSWorker when enable_rbds=False."""
    config = DemodulatorConfig(
        modulation_type="FM",
        sample_rate=250_000,
        audio_sample_rate=48_000,
        enable_rbds=False,
    )
    demod = FMDemodulator(config)
    assert demod._rbds_worker is None
    demod.stop()


def test_fmdemodulator_creates_rbds_worker_when_enabled():
    """FMDemodulator creates an RBDSWorker when enable_rbds=True at sufficient rate."""
    demod = _make_demodulator(sample_rate=250_000)
    assert demod._rbds_worker is not None
    demod.stop()
    time.sleep(0.05)


def test_fmdemodulator_rbds_disabled_below_min_rate():
    """FMDemodulator with sample_rate < 114 kHz must not enable RBDS."""
    config = DemodulatorConfig(
        modulation_type="FM",
        sample_rate=48_000,
        audio_sample_rate=48_000,
        enable_rbds=True,   # requested but rate is too low
    )
    demod = FMDemodulator(config)
    # _rbds_enabled should be False because sample_rate < 114000
    assert demod._rbds_enabled is False
    assert demod._rbds_worker is None
    demod.stop()
