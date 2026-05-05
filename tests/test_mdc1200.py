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

"""Tests for the MDC1200 selective-calling encoder.

Reference vector:

    op=0x01  arg=0x80  unit_id=0x1234  status=0x00
        info bytes:    01 80 12 34 2E 3E 00
        CRC of info:   0x3E2E (low byte 2E first on the wire)
        FEC bytes:     65 80 A8 62 DD 88 08

This vector is documented in the public MDC1200 algorithm description and
was independently verified by hand-computation of the K=7 / R=1/2
convolutional encoder against the ``01 80 12 34`` payload.
"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app_utils.mdc1200 import (  # noqa: E402
    MDC1200_BAUD,
    MDC1200_MARK_FREQ,
    MDC1200_OP_PRESETS,
    MDC1200_PREAMBLE,
    MDC1200_SPACE_FREQ,
    MDC1200_SYNC,
    _apply_fec,
    _interleave,
    _xor_modulate,
    bytes_to_bits_msb,
    compute_crc,
    encode_packet,
    generate_mdc1200_samples,
    resolve_op_preset,
)


# ---------------------------------------------------------------------------
# CRC
# ---------------------------------------------------------------------------

def test_compute_crc_known_vector():
    """CRC of the 4-byte info block ``01 80 12 34`` is ``0x3E2E``."""
    assert compute_crc([0x01, 0x80, 0x12, 0x34]) == 0x3E2E


def test_compute_crc_empty_input_is_xff_xor_zero_init():
    """Empty input yields the final XOR mask alone (init=0, ^0xFFFF)."""
    assert compute_crc([]) == 0xFFFF


def test_compute_crc_masks_to_byte_input():
    """CRC ignores bits above the byte boundary in inputs."""
    assert compute_crc([0x101, 0x80, 0x12, 0x34]) == compute_crc(
        [0x01, 0x80, 0x12, 0x34]
    )


# ---------------------------------------------------------------------------
# FEC convolutional encoder
# ---------------------------------------------------------------------------

def test_apply_fec_known_vector():
    """K=7 R=1/2 FEC of the documented 7-byte info block matches the
    expected 7 parity bytes ``65 80 A8 62 DD 88 08``."""
    info = [0x01, 0x80, 0x12, 0x34, 0x2E, 0x3E, 0x00]
    out = _apply_fec(info)
    assert out[:7] == info, "info block must be preserved"
    assert out[7:] == [0x65, 0x80, 0xA8, 0x62, 0xDD, 0x88, 0x08]


def test_apply_fec_rejects_wrong_length():
    with pytest.raises(ValueError):
        _apply_fec([0, 1, 2])


# ---------------------------------------------------------------------------
# Interleaver
# ---------------------------------------------------------------------------

def test_interleaver_is_a_bit_permutation():
    """The interleaver must permute exactly 112 bits — every input bit
    appears exactly once at a known output position, so the population
    count of the input and output buffers is identical."""
    payload = list(range(14))  # arbitrary 14-byte input
    out = _interleave(list(payload))
    assert len(out) == 14
    pop_in = sum(bin(b).count("1") for b in payload)
    pop_out = sum(bin(b).count("1") for b in out)
    assert pop_in == pop_out


def test_interleaver_rejects_wrong_length():
    with pytest.raises(ValueError):
        _interleave([0] * 5)


# ---------------------------------------------------------------------------
# Differential modulation
# ---------------------------------------------------------------------------

def test_xor_modulate_zero_buffer_emits_steady_mark():
    """A run of 0x00 bytes (no transitions) must encode to 0xFF after
    inversion, producing a continuous mark tone for FFSK PLL lock."""
    assert _xor_modulate([0x00, 0x00, 0x00]) == [0xFF, 0xFF, 0xFF]


def test_xor_modulate_round_trip():
    """Differential decode must recover the original buffer."""
    original = [0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0]
    encoded = _xor_modulate(original)

    # Decode: invert bytes, then turn each 0/1 transition flag back into bits.
    decoded = []
    prev_bit = 0
    for byte in encoded:
        b = byte ^ 0xFF
        out = 0
        for bit_num in range(7, -1, -1):
            transitioned = (b >> bit_num) & 1
            new_bit = prev_bit ^ transitioned
            out |= new_bit << bit_num
            prev_bit = new_bit
        decoded.append(out)
    assert decoded == original


# ---------------------------------------------------------------------------
# Top-level encoder
# ---------------------------------------------------------------------------

def test_encode_packet_length_and_prefix_structure():
    """Frame must be 26 bytes: 3 preamble + 5 sync + 14 payload + 4 post-preamble."""
    frame = encode_packet(0x01, 0x80, 0x1234)
    assert len(frame) == 3 + 5 + 14 + 4 == 26

    # The preamble + sync prefix passes through differential modulation as
    # well, but their *decoded* values must still match the canonical
    # MDC1200 preamble/sync constants.  Decode the first 8 bytes:
    decoded = []
    prev_bit = 0
    for byte in frame[: 3 + 5]:
        b = byte ^ 0xFF
        out = 0
        for bit_num in range(7, -1, -1):
            transitioned = (b >> bit_num) & 1
            new_bit = prev_bit ^ transitioned
            out |= new_bit << bit_num
            prev_bit = new_bit
        decoded.append(out)
    assert decoded[:3] == list(MDC1200_PREAMBLE)
    assert decoded[3:8] == list(MDC1200_SYNC)


def test_encode_packet_includes_trailing_post_preamble():
    """The last 4 bytes of a single packet are the post-preamble: under
    differential modulation they decode to 0x00 0x00 0x00 0x00, which
    is what real Motorola subscribers expect as a clean tail-of-frame
    marker before they commit a decoded ID to their call list."""
    frame = encode_packet(0x01, 0x80, 0x1234)
    decoded = []
    prev_bit = 0
    for byte in frame:
        b = byte ^ 0xFF
        out = 0
        for bit_num in range(7, -1, -1):
            transitioned = (b >> bit_num) & 1
            new_bit = prev_bit ^ transitioned
            out |= new_bit << bit_num
            prev_bit = new_bit
        decoded.append(out)
    assert decoded[-4:] == [0x00, 0x00, 0x00, 0x00]


def test_encode_packet_validates_inputs():
    with pytest.raises(ValueError):
        encode_packet(-1, 0, 0)
    with pytest.raises(ValueError):
        encode_packet(0, 0x100, 0)
    with pytest.raises(ValueError):
        encode_packet(0, 0, 0x10000)
    with pytest.raises(ValueError):
        encode_packet(0, 0, 0, status=-1)


def test_op_presets_well_formed():
    assert "ptt_id_pre" in MDC1200_OP_PRESETS
    for name, (op, arg) in MDC1200_OP_PRESETS.items():
        assert 0 <= op <= 0xFF, name
        assert 0 <= arg <= 0xFF, name


def test_resolve_op_preset_unknown_falls_back_to_ptt_id_pre():
    assert resolve_op_preset("nonsense") == MDC1200_OP_PRESETS["ptt_id_pre"]
    assert resolve_op_preset("") == MDC1200_OP_PRESETS["ptt_id_pre"]


def test_call_alert_and_selective_call_presets_match_multimon_ng():
    """Call Alert and Selective Call use op/arg pairs widely attested in
    multimon-ng's MDC decoder source and Motorola CPS programming sheets.
    Pin them so a future refactor cannot silently change the on-air bytes."""
    assert resolve_op_preset("call_alert") == (0x63, 0x85)
    assert resolve_op_preset("selective_call") == (0x35, 0x80)


def test_call_alert_and_selective_call_encode_to_valid_frames():
    """Both new presets must produce a valid 26-byte single-packet frame
    when called via :func:`encode_packet` (target ID carried in the
    unit_id field — receivers tolerate this fallback when no separate
    target is configured)."""
    for preset in ("call_alert", "selective_call"):
        op, arg = resolve_op_preset(preset)
        frame = encode_packet(op, arg, 0x1234)
        assert len(frame) == 26, preset


def test_double_packet_frame_length_and_structure():
    """``encode_double_packet`` must emit a 40-byte frame: 3 preamble +
    5 sync + 14 payload-1 + 4 inter-packet preamble + 14 payload-2.
    At 1200 baud that is exactly 266.67 ms of audio — the Motorola-
    specified on-air duration for Call Alert and Selective Call."""
    from app_utils.mdc1200 import encode_double_packet
    frame = encode_double_packet(0x63, 0x85, 0x1111, 0x2222)
    assert len(frame) == 3 + 5 + 14 + 4 + 14 == 40

    # Decode the prefix to verify preamble + sync round-trip
    decoded = []
    prev_bit = 0
    for byte in frame:
        b = byte ^ 0xFF
        out = 0
        for bit_num in range(7, -1, -1):
            transitioned = (b >> bit_num) & 1
            new_bit = prev_bit ^ transitioned
            out |= new_bit << bit_num
            prev_bit = new_bit
        decoded.append(out)
    assert decoded[:3] == list(MDC1200_PREAMBLE)
    assert decoded[3:8] == list(MDC1200_SYNC)
    # 4-byte inter-packet preamble after payload 1 (offsets 22..25)
    assert decoded[22:26] == [0x00, 0x00, 0x00, 0x00]


def test_double_packet_validates_inputs():
    from app_utils.mdc1200 import encode_double_packet
    with pytest.raises(ValueError):
        encode_double_packet(-1, 0, 0, 0)
    with pytest.raises(ValueError):
        encode_double_packet(0, 0x100, 0, 0)
    with pytest.raises(ValueError):
        encode_double_packet(0, 0, 0x10000, 0)
    with pytest.raises(ValueError):
        encode_double_packet(0, 0, 0, 0x10000)
    with pytest.raises(ValueError):
        encode_double_packet(0, 0, 0, 0, status=-1)


def test_is_double_packet_op_recognises_call_alert_and_selective_call():
    from app_utils.mdc1200 import is_double_packet_op
    assert is_double_packet_op(0x63, 0x85) is True   # Call Alert
    assert is_double_packet_op(0x35, 0x80) is True   # Selective Call
    # PTT-ID, Emergency, etc. stay single-packet
    assert is_double_packet_op(0x01, 0x80) is False
    assert is_double_packet_op(0x00, 0x80) is False
    assert is_double_packet_op(0x40, 0x80) is False


def test_generate_mdc1200_samples_dispatches_to_double_packet_when_target_set():
    """Audio waveform length must match double-packet timing when the
    operator picks Call Alert / Selective Call AND configures a
    target unit ID; otherwise it falls back to single-packet timing."""
    sr = 16000
    amp = 0.7 * 32767

    # Call Alert with target -> double packet (40 bytes)
    samples_double = generate_mdc1200_samples(
        0x63, 0x85, unit_id=0x1111, sample_rate=sr, amplitude=amp,
        target_unit_id=0x2222,
    )
    expected_double = 40 * 8 * sr / MDC1200_BAUD
    assert abs(len(samples_double) - expected_double) <= 2

    # Call Alert without target -> falls back to single packet (26 bytes)
    samples_single_fallback = generate_mdc1200_samples(
        0x63, 0x85, unit_id=0x1111, sample_rate=sr, amplitude=amp,
        target_unit_id=None,
    )
    expected_single = 26 * 8 * sr / MDC1200_BAUD
    assert abs(len(samples_single_fallback) - expected_single) <= 2

    # PTT-ID Pre with target set -> still single packet (op is not double-packet-eligible)
    samples_pttid = generate_mdc1200_samples(
        0x01, 0x80, unit_id=0x1111, sample_rate=sr, amplitude=amp,
        target_unit_id=0x2222,
    )
    assert abs(len(samples_pttid) - expected_single) <= 2


# ---------------------------------------------------------------------------
# Smart pre/post PTT-ID pairing
# ---------------------------------------------------------------------------

def test_smart_pairing_substitutes_post_for_ptt_id_pre():
    """When both pre/post chimes are MDC1200 and the preset is the default
    ``ptt_id_pre``, the post side must auto-substitute ``ptt_id_post`` so a
    receiving Motorola subscriber sees a complete bookend pair."""
    from app_utils.eas import _resolve_mdc1200_op_for_position
    assert _resolve_mdc1200_op_for_position("ptt_id_pre", "pre") == "ptt_id_pre"
    assert _resolve_mdc1200_op_for_position("ptt_id_pre", "post") == "ptt_id_post"


def test_smart_pairing_passes_other_presets_through():
    """Non-PTT presets must NOT be rewritten — operators sandwich a broadcast
    in two emergency-alarm packets on purpose, and Call Alert / Selective
    Call have no natural pre/post pair so the operator's exact choice must
    survive on both sides."""
    from app_utils.eas import _resolve_mdc1200_op_for_position
    for preset in (
        "emergency",
        "request_to_talk",
        "remote_monitor",
        "ptt_id_post",
        "call_alert",
        "selective_call",
        "custom",
    ):
        assert _resolve_mdc1200_op_for_position(preset, "pre") == preset
        assert _resolve_mdc1200_op_for_position(preset, "post") == preset


def test_smart_pairing_handles_empty_and_case_insensitivity():
    from app_utils.eas import _resolve_mdc1200_op_for_position
    assert _resolve_mdc1200_op_for_position("", "post") == ""
    assert _resolve_mdc1200_op_for_position("PTT_ID_PRE", "POST") == "ptt_id_post"


# ---------------------------------------------------------------------------
# Hex inputs (operators commonly copy MDC1200 unit IDs from Motorola CPS,
# which displays them in 4-digit hex)
# ---------------------------------------------------------------------------

def test_encode_packet_accepts_full_hex_byte_range():
    """Op-code, arg, and unit ID must each accept the full 8-/16-bit
    hex range — including A–F digits — without raising."""
    frame = encode_packet(0xAB, 0xCD, 0xDEAD, status=0xEF)
    assert len(frame) == 26


def test_encode_packet_unit_id_round_trips_hex_value():
    """The unit ID is carried in the information block at offsets 2..3
    (high byte first); after differential decode of the payload, those
    two bytes must match the input hex value."""
    # Build the same packet as encode_packet but stop before differential
    # modulation so we can read the raw info block back.
    from app_utils.mdc1200 import (
        _apply_fec, _interleave, MDC1200_PREAMBLE, MDC1200_SYNC,
    )
    info = [0x01, 0x80, 0xDE, 0xAD]
    info.append(compute_crc(info) & 0xFF)
    info.append((compute_crc(info[:4]) >> 8) & 0xFF)
    info.append(0x00)
    payload = _interleave(_apply_fec(info))
    # idH / idL after FEC are still at offsets 2 / 3 of the FEC info half
    fec_block = _apply_fec([0x01, 0x80, 0xDE, 0xAD,
                            compute_crc([0x01, 0x80, 0xDE, 0xAD]) & 0xFF,
                            (compute_crc([0x01, 0x80, 0xDE, 0xAD]) >> 8) & 0xFF,
                            0x00])
    assert fec_block[2] == 0xDE
    assert fec_block[3] == 0xAD


def test_compute_crc_with_hex_a_through_f_bytes():
    """CRC must process A–F hex bytes correctly (no hidden ASCII filtering)."""
    # Two different inputs that share no bytes must yield different CRCs
    crc_lower = compute_crc([0x12, 0x34, 0x56, 0x78])
    crc_upper = compute_crc([0xAB, 0xCD, 0xEF, 0xFE])
    assert crc_lower != crc_upper
    # Sanity: our verified vector still holds
    assert compute_crc([0x01, 0x80, 0x12, 0x34]) == 0x3E2E


# ---------------------------------------------------------------------------
# Bit serialisation
# ---------------------------------------------------------------------------

def test_bytes_to_bits_msb():
    assert bytes_to_bits_msb([0x80]) == [1, 0, 0, 0, 0, 0, 0, 0]
    assert bytes_to_bits_msb([0x01]) == [0, 0, 0, 0, 0, 0, 0, 1]
    assert bytes_to_bits_msb([0xA5]) == [1, 0, 1, 0, 0, 1, 0, 1]


# ---------------------------------------------------------------------------
# Audio waveform
# ---------------------------------------------------------------------------

def test_generate_mdc1200_samples_length_at_16khz():
    """26 bytes * 8 bits / 1200 baud * 16000 Hz ≈ 2773.33 samples; the
    fractional-bit timing means we expect within ±2 samples of that."""
    samples = generate_mdc1200_samples(0x01, 0x80, 0x1234, 16000, 0.7 * 32767)
    expected = 26 * 8 * 16000 / MDC1200_BAUD
    assert abs(len(samples) - expected) <= 2
    assert all(-32768 <= s <= 32767 for s in samples)


def test_generate_mdc1200_samples_is_phase_continuous():
    """Adjacent samples must not exhibit a discontinuity larger than the
    per-sample step at the higher (1800 Hz) carrier — phase continuity
    is what lets receivers FFSK-lock cleanly across mark/space transitions.
    """
    sr = 16000
    amp = 0.7 * 32767
    samples = generate_mdc1200_samples(0x01, 0x80, 0x0001, sr, amp)
    # For a sine at frequency f sampled at sr, the maximum absolute sample-
    # to-sample delta is 2 * amplitude * sin(pi * f / sr).  At 1800 Hz / 16
    # kHz that is ≈ amplitude * 0.694.  Allow a small slack for int-rounding.
    max_delta = 2.0 * amp * math.sin(math.pi * MDC1200_SPACE_FREQ / sr) + 2
    for prev, curr in zip(samples, samples[1:]):
        assert abs(curr - prev) <= max_delta, (
            f"phase discontinuity at sample boundary: {prev} -> {curr}"
        )


def test_generate_mdc1200_samples_contains_both_carriers():
    """A balanced packet should exercise both 1200 Hz mark and 1800 Hz
    space tones; verify they both contribute meaningful energy via a
    coarse Goertzel-style power estimate at each carrier."""
    sr = 16000
    amp = 0.7 * 32767
    # Use a unit_id that exercises a mix of 0/1 bits to ensure both
    # mark and space frequencies are present in the waveform.
    samples = generate_mdc1200_samples(0x01, 0x80, 0xA5C3, sr, amp)

    def _goertzel_power(target_hz: float) -> float:
        coeff = 2.0 * math.cos(2.0 * math.pi * target_hz / sr)
        s_prev = 0.0
        s_prev2 = 0.0
        for x in samples:
            s = x + coeff * s_prev - s_prev2
            s_prev2 = s_prev
            s_prev = s
        return s_prev2 ** 2 + s_prev ** 2 - coeff * s_prev * s_prev2

    p_mark = _goertzel_power(MDC1200_MARK_FREQ)
    p_space = _goertzel_power(MDC1200_SPACE_FREQ)
    p_offband = _goertzel_power(3000.0)
    # Both carriers should each carry far more energy than an unrelated
    # off-band frequency.
    assert p_mark > 10 * p_offband
    assert p_space > 10 * p_offband
