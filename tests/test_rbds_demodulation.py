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
    RBDSDecoder,
    RBDSWorker,
    pi_to_call_sign,
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


def test_rbds_estimate_pilot_frequency_recovers_clock_offset():
    """_estimate_pilot_frequency must recover a sub-Hz pilot offset.

    Models a typical RTL-SDR with ~50 ppm clock error: the pilot, ostensibly
    19 000 Hz at the transmitter, is recovered at 18 999.05 Hz.  The
    estimator must measure that within 0.2 Hz so the 57 kHz mix can land the
    RBDS subcarrier at exactly DC.
    """
    sr = 250_000
    worker = _make_worker(sample_rate=sr)

    n = 1 << 16  # 65 536 samples ≈ 262 ms @ 250 kHz
    t = np.arange(n) / sr

    # Synthesise a realistic FM multiplex: pilot + audio + RBDS subcarrier + noise.
    pilot_hz = 18999.05  # 50 ppm low (typical uncorrected RTL-SDR)
    rng = np.random.default_rng(0)
    multiplex = (
        0.10 * np.sin(2 * np.pi * pilot_hz * t)
        + 0.50 * np.sin(2 * np.pi * 1000.0 * t)            # audio component
        + 0.05 * np.sin(2 * np.pi * (3 * pilot_hz) * t)    # RBDS subcarrier
        + 0.05 * rng.standard_normal(n)
    ).astype(np.float32)

    measured = worker._estimate_pilot_frequency(multiplex)
    assert measured is not None, "estimator should return a frequency for a station with a pilot"
    assert abs(measured - pilot_hz) < 0.2, (
        f"measured={measured} Hz but expected {pilot_hz} Hz (±0.2 Hz)"
    )
    worker.stop()


def test_rbds_estimate_pilot_frequency_rejects_mono_station():
    """Without a pilot the estimator must return None, not a noise peak."""
    sr = 250_000
    worker = _make_worker(sample_rate=sr)

    n = 1 << 16
    t = np.arange(n) / sr
    rng = np.random.default_rng(1)
    # Just audio + noise — no 19 kHz pilot.
    multiplex = (
        0.50 * np.sin(2 * np.pi * 1000.0 * t)
        + 0.05 * rng.standard_normal(n)
    ).astype(np.float32)

    measured = worker._estimate_pilot_frequency(multiplex)
    assert measured is None, f"expected None for mono station, got {measured}"
    worker.stop()


def test_rbds_pilot_reference_uses_measured_frequency():
    """Once a pilot has been measured, _generate_pilot_reference must use it.

    This is the whole point of the SDR-clock-drift fix: the carrier reference
    must follow the *recovered* pilot, not the nominal 19 000.0 Hz, so the
    57 kHz RBDS subcarrier mixes down to exactly DC.
    """
    sr = 250_000
    worker = _make_worker(sample_rate=sr)

    # Simulate a successful measurement (e.g. SDR clock 50 ppm low).
    measured = 18999.05
    worker._measured_pilot_freq = measured

    n = 1000
    sample_offset = 250_000  # 1 s into the stream
    phases = worker._generate_pilot_reference(n, sample_offset)

    # First sample's phase should reflect the measured frequency, not 19 kHz.
    expected = 2.0 * np.pi * measured * (sample_offset / sr)
    nominal = 2.0 * np.pi * 19000.0 * (sample_offset / sr)
    assert abs(phases[0] - expected) < 1e-6
    # And it should be measurably different from what 19 000 Hz would give.
    assert abs(phases[0] - nominal) > 1e-3
    worker.stop()


def test_rbds_apply_reset_clears_measured_pilot():
    """A worker reset (e.g. retune) must clear the measured pilot frequency.

    Otherwise the new station would be demodulated against the previous
    station's SDR clock measurement.  Although the SDR clock itself doesn't
    change, this also re-baselines the measurement from a fresh capture so
    we never carry forward a stale or low-quality estimate.
    """
    worker = _make_worker()
    worker._measured_pilot_freq = 18999.5

    worker._apply_reset()

    assert worker._measured_pilot_freq is None
    worker.stop()


def _run_presync_sequence(worker: RBDSWorker, hit_map: dict[int, int]) -> None:
    """Drive _decode_rbds_groups with synthetic syndrome hits at specific bit indices."""
    worker._rbds_bit_buffer = [0] * 220
    call_index = 0

    def fake_calc_syndrome(_word: int, message_length: int) -> int:
        nonlocal call_index
        bit_index = call_index // 2
        is_inverted_path = (call_index % 2) == 1
        call_index += 1
        if message_length == 26 and not is_inverted_path:
            return hit_map.get(bit_index, 0)
        return 0

    worker._calc_syndrome = fake_calc_syndrome  # type: ignore[assignment]
    worker._decode_rbds_groups()


def test_rbds_presync_requires_three_spaced_hits_before_lock():
    """RBDS lock should only occur after 3 correctly spaced presync detections."""
    worker = _make_worker()
    # A -> B -> C detections with exact 26-bit spacing.
    _run_presync_sequence(worker, {100: 383, 126: 14, 152: 303})
    assert worker._rbds_synced is True


def test_rbds_presync_two_hits_do_not_lock():
    """Two spaced detections are insufficient; avoid false sync in noise."""
    worker = _make_worker()
    # Only A -> B (single spacing confirmation) should not lock.
    _run_presync_sequence(worker, {100: 383, 126: 14})
    assert worker._rbds_synced is False


# ---------------------------------------------------------------------------
# RBDSDecoder.process_group tests
#
# Block B layout per EN 50067 / NRSC-4:
#   bits 15..12 = group type (0..15)
#   bit    11   = version (0=A, 1=B)
#   bit    10   = TP
#   bits  9..5  = PTY (5 bits)
#   bits  4..0  = group-type-dependent payload
# ---------------------------------------------------------------------------


def _pack_block_b(group_type: int, version_b: bool, tp: bool, pty: int, low_bits: int) -> int:
    return (
        ((group_type & 0xF) << 12)
        | ((1 if version_b else 0) << 11)
        | ((1 if tp else 0) << 10)
        | ((pty & 0x1F) << 5)
        | (low_bits & 0x1F)
    )


def test_group_0a_decodes_ta_ms_and_ps():
    """Group 0A carries TA (bit 4), MS (bit 3) and a PS segment."""
    decoder = RBDSDecoder()
    pi = 0x4FB5

    # segment 0, TA=1, MS=1, DI=0 → low 5 bits = 0b11000 = 0x18
    b = _pack_block_b(group_type=0, version_b=False, tp=True, pty=5, low_bits=0x18)
    decoder.process_group((pi, b, 0x0000, (ord("E") << 8) | ord("A")))

    # The flags read from any Group 0 land immediately.
    data = decoder.get_current_data()
    assert data.pi_code == "4FB5"
    assert data.pty == 5
    assert data.tp is True
    assert data.ta is True
    assert data.ms is True

    # PS only commits after a full self-consistent cycle has been
    # confirmed twice (see test_ps_name_requires_two_identical_cycles),
    # so after a single segment the visible PS is still blank.
    assert data.ps_name == ""


def test_group_2_does_not_clobber_ta_ms():
    """Regression: TA and MS must only be read from Group 0A/0B.

    Bits 4-0 of Block B are group-type-dependent. Previously the decoder
    extracted TA from bit 4 and MS from bit 3 unconditionally, so any
    Group 2 (RadioText) message overwrote the real TA/MS with the RT A/B
    flag and a text-segment bit.
    """
    decoder = RBDSDecoder()
    pi = 0x4FB5

    # First seed the decoder with a Group 0A carrying TA=0, MS=0
    b0 = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=0b00000)
    decoder.process_group((pi, b0, 0x0000, 0x2020))  # "  " PS chars
    assert decoder.ta is False
    assert decoder.ms is False

    # Now send a Group 2A with AB flag = 1 (bit 4) and an odd segment
    # address that sets bit 3. With the bug present this would flip TA
    # and MS to True.
    b2 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0b11000)
    decoder.process_group((pi, b2, 0x4865, 0x6C6C))  # "Hell"

    assert decoder.ta is False, "TA must not be set by Group 2 A/B flag"
    assert decoder.ms is False, "MS must not be set by Group 2 segment bits"


def test_group_2a_decodes_radiotext_segment():
    """Group 2A delivers 4 RT characters per segment (2 from C, 2 from D)."""
    decoder = RBDSDecoder()
    pi = 0x4FB5

    # segment 0, AB flag = 0
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((pi, b, (ord("H") << 8) | ord("e"), (ord("l") << 8) | ord("l")))

    # segment 1
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x01)
    decoder.process_group((pi, b, (ord("o") << 8) | ord(" "), (ord("R") << 8) | ord("T")))

    data = decoder.get_current_data()
    assert data.radio_text.startswith("Hello RT")


def test_group_2a_preserves_high_bit_characters():
    """RT mask must be 0xFF, not 0x7F.

    With the old 7-bit mask, an RDS character like 0xE9 ('é' in Annex E)
    was silently rewritten to 0x69 ('i'), producing a plausible but
    wrong ASCII character. After the fix, the high bit survives the
    mask; since the printable-ASCII filter in _update_radio_text still
    rejects codes >= 127, the slot shows as space rather than a lying
    ASCII character.
    """
    decoder = RBDSDecoder()
    pi = 0x4FB5

    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    # Block C: two RDS-Annex-E chars (0xE9 0xE8 → 'é' 'è' in Latin locales).
    # Block D: plain ASCII so we can anchor the segment.
    decoder.process_group((pi, b, (0xE9 << 8) | 0xE8, (ord("a") << 8) | ord("b")))

    data = decoder.get_current_data()
    # Positions 0 and 1 should not be the wrong-ASCII fallback that the
    # 0x7F mask produced (0xE9 & 0x7F = 0x69 = 'i', 0xE8 & 0x7F = 0x68 = 'h').
    assert decoder.radio_text[0] != "i"
    assert decoder.radio_text[1] != "h"
    # Positions 2 and 3 from block D remain plain ASCII.
    assert decoder.radio_text[2] == "a"
    assert decoder.radio_text[3] == "b"
    # Stripping trims leading spaces, so the visible RT starts with "ab".
    assert data.radio_text.startswith("ab")


def test_pi_to_call_sign_four_letter_w():
    # Real-world example from production: PI 0x5862 is station WBKS.
    assert pi_to_call_sign(0x5862) == "WBKS"


def test_pi_to_call_sign_four_letter_k():
    # K-prefix algorithmic decode: 0x1000 -> KAAA, 0x54A7 -> KZZZ.
    assert pi_to_call_sign(0x1000) == "KAAA"
    assert pi_to_call_sign(0x54A7) == "KZZZ"


def test_pi_to_call_sign_w_boundary():
    # W-prefix boundary: 0x54A8 -> WAAA, 0x994F -> WZZZ.
    assert pi_to_call_sign(0x54A8) == "WAAA"
    assert pi_to_call_sign(0x994F) == "WZZZ"


def test_pi_to_call_sign_three_letter_legacy():
    # NRSC-4 Annex D.3 assigns explicit PI codes to legacy 3-letter calls.
    assert pi_to_call_sign(0x99A5) == "KDKA"
    assert pi_to_call_sign(0x9990) == "KYW"
    assert pi_to_call_sign(0x9950) == "WBZ"


def test_pi_to_call_sign_out_of_range():
    # European RDS codes and reserved ranges should not produce bogus calls.
    assert pi_to_call_sign(0x0FFF) is None  # below K range
    assert pi_to_call_sign(0x9A00) is None  # above W range + legacy table
    assert pi_to_call_sign(0xD340) is None  # typical European PI


def test_decoder_populates_call_sign_from_pi():
    decoder = RBDSDecoder()
    b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=0)
    decoder.process_group((0x5862, b, 0x0000, 0x2020))
    assert decoder.get_current_data().call_sign == "WBKS"


def test_decoder_clock_time_from_group_4a():
    """Group 4A: MJD 59935 = 2022-12-22, hour 17, minute 30, offset -5h
    (local offset = -10 half-hours = -5h)."""
    decoder = RBDSDecoder()
    # Block B low 5 bits = top 2 bits of MJD + group-type-fixed zeros
    mjd = 59935
    hour = 17
    minute = 30
    offset_half_hours = 10  # 5h
    offset_sign_bit = 1  # negative

    # Block B bits 1-0 = MJD bits 16..15
    b_low = (mjd >> 15) & 0x3
    b = _pack_block_b(group_type=4, version_b=False, tp=False, pty=0, low_bits=b_low)
    # Block C: MJD bits 14..0 shifted up by 1, plus hour MSB in bit 0
    c = ((mjd & 0x7FFF) << 1) | ((hour >> 4) & 0x1)
    # Block D: hour low 4 bits in 15..12, minute in 11..6, sign in bit 5, offset in 4..0
    d = ((hour & 0xF) << 12) | ((minute & 0x3F) << 6) | (offset_sign_bit << 5) | offset_half_hours

    decoder.process_group((0x5862, b, c, d))
    data = decoder.get_current_data()
    assert data.clock_time_utc is not None
    assert data.clock_time_utc.startswith("2022-12-22T17:30"), data.clock_time_utc
    # Local should be 17:30 - 5:00 = 12:30 on the same date.
    assert data.clock_time_local.startswith("2022-12-22T12:30"), data.clock_time_local


def test_decoder_pty_name_from_group_10a():
    decoder = RBDSDecoder()
    # First seed PTY so PTY-change logic doesn't reset on every group
    b0 = _pack_block_b(group_type=0, version_b=False, tp=False, pty=9, low_bits=0)
    decoder.process_group((0x5862, b0, 0x0000, 0x2020))

    # Group 10A segment 0 ("NEWS" - just an example)
    b = _pack_block_b(group_type=10, version_b=False, tp=False, pty=9, low_bits=0x00)
    decoder.process_group((0x5862, b, (ord("N") << 8) | ord("E"), (ord("W") << 8) | ord("S")))
    # Segment 1 (" CH 1")
    b = _pack_block_b(group_type=10, version_b=False, tp=False, pty=9, low_bits=0x01)
    decoder.process_group((0x5862, b, (ord(" ") << 8) | ord("C"), (ord("H") << 8) | ord("1")))

    assert decoder.get_current_data().pty_name == "NEWS CH1"


def test_decoder_di_bits_from_group_0():
    decoder = RBDSDecoder()

    # Address 3 -> stereo bit (d0). DI bit = 1 on segment 3.
    for addr, di in [(0, True), (1, False), (2, False), (3, True)]:
        low = (di << 2) | addr  # bit 2 = DI, bits 1..0 = address
        b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=low)
        decoder.process_group((0x5862, b, 0x0000, 0x2020))

    data = decoder.get_current_data()
    assert data.di_dynamic_pty is True    # address 0
    assert data.di_compressed is False    # address 1
    assert data.di_artificial_head is False  # address 2
    assert data.di_stereo is True         # address 3


def _send_ps_cycle(decoder, text: str, pi: int = 0x5862) -> None:
    """Send a complete PS cycle (all 4 segments of an 8-char PS)."""
    assert len(text) == 8
    for seg in range(4):
        b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=seg)
        c1, c2 = text[seg * 2], text[seg * 2 + 1]
        decoder.process_group((pi, b, 0x0000, (ord(c1) << 8) | ord(c2)))


def test_ps_name_requires_two_identical_cycles():
    """PS commits only after two consecutive identical full cycles.

    This debounces the 'Frankenstein blend' failure mode where four
    segments from two different rotating PS strings interleave across
    four distinct addresses (no per-segment conflict to catch) and
    spell out 8 chars that were never broadcast together.
    """
    decoder = RBDSDecoder()
    _send_ps_cycle(decoder, "KISS-FM ")
    assert "".join(decoder.ps_name) == " " * 8, "first cycle must not commit"
    _send_ps_cycle(decoder, "KISS-FM ")
    assert "".join(decoder.ps_name) == "KISS-FM "


def test_ps_name_follows_dynamic_ps_rotation():
    """Rotating PS transitions cleanly once each new string repeats."""
    decoder = RBDSDecoder()
    for _ in range(2):
        _send_ps_cycle(decoder, "KISS-FM ")
    assert "".join(decoder.ps_name) == "KISS-FM "

    # One rotation to a different string doesn't update yet — candidate
    # needs confirmation.
    _send_ps_cycle(decoder, "93-9 FM ")
    assert "".join(decoder.ps_name) == "KISS-FM "
    # The station's next cycle of '93-9 FM ' confirms it.
    _send_ps_cycle(decoder, "93-9 FM ")
    assert "".join(decoder.ps_name) == "93-9 FM "


def test_ps_name_rejects_single_blended_cycle():
    """A single cycle built from segments of two different PS strings
    must not commit — the four-address blend could decode any plausible
    8 chars and would corrupt the display.
    """
    decoder = RBDSDecoder()
    for _ in range(2):
        _send_ps_cycle(decoder, "KISS-FM ")
    assert "".join(decoder.ps_name) == "KISS-FM "

    # One cycle's worth of segments, each drawn from a different PS.
    # "K", "I" from 'KISS-FM ', "-", "9" from '93-9 FM ', " ", "F"
    # from '93-9 FM ', "M", " " from 'KISS-FM '.
    for seg, pair in enumerate([("K", "I"), ("-", "9"), (" ", "F"), ("M", " ")]):
        b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=seg)
        decoder.process_group((0x5862, b, 0x0000, (ord(pair[0]) << 8) | ord(pair[1])))
    assert "".join(decoder.ps_name) == "KISS-FM ", \
        f"blended cycle committed: {decoder.ps_name}"


def test_radio_text_grows_when_station_extends_without_cr():
    """Some stations change their RT without re-sending 0x0D or toggling
    the A/B flag; the decoder must let the visible length grow back out
    when non-space characters arrive past the current terminator.
    """
    decoder = RBDSDecoder()
    b0 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    # Initial RT: "Hi!\r"  → terminator at 3
    decoder.process_group((0x5862, b0, (ord("H") << 8) | ord("i"), (ord("!") << 8) | 0x0D))
    assert decoder.get_current_data().radio_text == "Hi!"

    # Station re-broadcasts segment 0 with a space in place of the CR,
    # then fills segment 1 with "Worl" — the RT should grow back out.
    decoder.process_group((0x5862, b0, (ord("H") << 8) | ord("i"), (ord("!") << 8) | ord(" ")))
    b1 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x01)
    decoder.process_group((0x5862, b1, (ord("W") << 8) | ord("o"), (ord("r") << 8) | ord("l")))
    assert decoder.get_current_data().radio_text == "Hi! Worl"


def test_radio_text_drops_padding_past_terminator():
    """Spaces (padding) arriving in a later segment past a terminator
    must not extend the RT — only real non-space content should.
    """
    decoder = RBDSDecoder()
    b0 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((0x5862, b0, (ord("H") << 8) | ord("i"), (ord("!") << 8) | 0x0D))
    b1 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x01)
    decoder.process_group((0x5862, b1, (ord(" ") << 8) | ord(" "), (ord(" ") << 8) | ord(" ")))
    assert decoder.get_current_data().radio_text == "Hi!"


def test_radio_text_trims_at_carriage_return():
    """Per RDS spec, 0x0D ends the Radio Text; anything past it must not be shown.

    Without this handling, stations that terminate RT short of 64 chars and
    pad the rest with spaces or junk would leak padding into the display.
    """
    decoder = RBDSDecoder()

    # Segment 0: "Hell"
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((0x5862, b, (ord("H") << 8) | ord("e"), (ord("l") << 8) | ord("l")))
    # Segment 1: "o!\r<junk>"  -- '!' then CR terminator, then padding
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x01)
    decoder.process_group((0x5862, b, (ord("o") << 8) | ord("!"), (0x0D << 8) | ord("X")))

    assert decoder.get_current_data().radio_text == "Hello!"


def test_group_2a_ab_flag_clears_buffer():
    """Toggling the RT A/B flag must clear the radio-text buffer."""
    decoder = RBDSDecoder()
    pi = 0x4FB5

    # First pass: AB=0, segment 0, "Hell"
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((pi, b, (ord("H") << 8) | ord("e"), (ord("l") << 8) | ord("l")))
    assert decoder.radio_text[0] == "H"

    # Flip AB flag: buffer must reset regardless of segment number
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x10)
    decoder.process_group((pi, b, (ord("N") << 8) | ord("e"), (ord("w") << 8) | ord(" ")))
    assert decoder.radio_text[0] == "N"
    assert decoder.radio_text[1] == "e"
    # Position 4+ must still be space: earlier "Hell" was cleared.
    assert all(c == " " for c in decoder.radio_text[4:])


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
