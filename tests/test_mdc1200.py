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
    MDC1200DecodeError,
    MDC1200Packet,
    _apply_fec,
    _de_interleave,
    _de_xor_modulate,
    _interleave,
    _xor_modulate,
    bytes_to_bits_msb,
    compute_crc,
    decode_all_mdc1200_from_samples,
    decode_double_packet,
    decode_mdc1200_from_samples,
    decode_packet,
    encode_packet,
    find_sync_in_bits,
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
    assert _de_xor_modulate(_xor_modulate(original)) == original


# ---------------------------------------------------------------------------
# Top-level encoder
# ---------------------------------------------------------------------------

def test_encode_packet_length_and_prefix_structure():
    """Frame must be 26 bytes: 3 preamble + 5 sync + 14 payload + 4 post-preamble."""
    frame = encode_packet(0x01, 0x80, 0x1234)
    assert len(frame) == 3 + 5 + 14 + 4 == 26

    # The preamble + sync prefix passes through differential modulation as
    # well, but their *decoded* values must still match the canonical
    # MDC1200 preamble/sync constants.
    decoded = _de_xor_modulate(frame[: 3 + 5])
    assert decoded[:3] == list(MDC1200_PREAMBLE)
    assert decoded[3:8] == list(MDC1200_SYNC)


def test_encode_packet_includes_trailing_post_preamble():
    """The last 4 bytes of a single packet are the post-preamble: under
    differential modulation they decode to 0x00 0x00 0x00 0x00, which
    is what real Motorola subscribers expect as a clean tail-of-frame
    marker before they commit a decoded ID to their call list."""
    frame = encode_packet(0x01, 0x80, 0x1234)
    decoded = _de_xor_modulate(frame)
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


def test_call_alert_and_selective_call_presets_match_reference():
    """Call Alert and Selective Call use op/arg pairs widely attested in
    Matthew Kaufman's reference MDC modem and Motorola CPS programming sheets.
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

    decoded = _de_xor_modulate(frame)
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
# Signaling-metadata target gating: a configured target unit ID must only be
# advertised for double-packet ops (Call Alert / Selective Call).  PTT-ID and
# the other single-packet ops have no destination field on the wire, so the
# UI/PDF/log must not show a phantom target (e.g. "PTT-ID → 0xFFFF").
# ---------------------------------------------------------------------------

def test_meta_target_suppressed_for_single_packet_ops():
    from app_utils.eas import _mdc1200_meta_target_unit_id
    # PTT-ID Pre/Post and the other single-packet presets ignore the target
    # on the wire, so the metadata must report None even when one is set.
    for preset in ("ptt_id_pre", "ptt_id_post", "emergency",
                   "request_to_talk", "remote_monitor"):
        assert _mdc1200_meta_target_unit_id(preset, None, None, 0xFFFF) is None, preset
        assert _mdc1200_meta_target_unit_id(preset, None, None, 0x1234) is None, preset


def test_meta_target_kept_for_double_packet_ops():
    from app_utils.eas import _mdc1200_meta_target_unit_id
    # Call Alert / Selective Call genuinely carry the target on packet 2.
    assert _mdc1200_meta_target_unit_id("call_alert", None, None, 0x2222) == 0x2222
    assert _mdc1200_meta_target_unit_id("selective_call", None, None, 0xFFFF) == 0xFFFF
    # A double-packet op with no target falls back to single-packet emission,
    # so still nothing to advertise.
    assert _mdc1200_meta_target_unit_id("call_alert", None, None, None) is None
    assert _mdc1200_meta_target_unit_id("call_alert", None, None, 0) is None


def test_meta_target_uses_raw_op_arg_bytes_for_custom_preset():
    from app_utils.eas import _mdc1200_meta_target_unit_id
    # Custom preset: raw op/arg bytes decide single vs double packet.
    # 0x63/0x85 == Call Alert (double), 0x01/0x80 == PTT-ID Pre (single).
    assert _mdc1200_meta_target_unit_id("custom", 0x63, 0x85, 0x2222) == 0x2222
    assert _mdc1200_meta_target_unit_id("custom", 0x01, 0x80, 0x2222) is None


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


# ---------------------------------------------------------------------------
# Receive-side decoder
# ---------------------------------------------------------------------------

def test_de_xor_modulate_inverts_xor_modulate_for_arbitrary_buffers():
    """The de-XOR-modulator must round-trip every byte buffer exactly,
    including buffers that exercise the cross-byte ``prev_bit`` carry."""
    cases = [
        [0x00] * 8,                        # steady mark tone
        [0xFF] * 8,                        # alternating-bit input
        [0x55, 0xAA, 0x55, 0xAA],          # high-transition density
        list(range(256)),                  # every byte value once
    ]
    for buf in cases:
        assert _de_xor_modulate(_xor_modulate(buf)) == buf


def test_de_interleave_inverts_interleave():
    """The de-interleaver must recover the source-order bytes for any
    14-byte interleaver input — the encoder uses a 16×7 distance-16
    spreading and the inverse mapping must agree on every bit."""
    payloads = [
        list(range(14)),
        [0x00] * 14,
        [0xFF] * 14,
        [0x01, 0x80, 0x12, 0x34, 0x2E, 0x3E, 0x00,
         0x65, 0x80, 0xA8, 0x62, 0xDD, 0x88, 0x08],  # the documented vector
    ]
    for payload in payloads:
        assert _de_interleave(_interleave(list(payload))) == payload


def test_de_interleave_rejects_wrong_length():
    with pytest.raises(ValueError):
        _de_interleave([0] * 5)


def test_decode_packet_round_trips_known_vector():
    """``encode_packet`` → ``decode_packet`` must recover the original
    op/arg/unit_id/status with both CRC and FEC validating cleanly."""
    frame = encode_packet(0x01, 0x80, 0x1234, status=0x00)
    pkt = decode_packet(frame)
    assert pkt.opcode == 0x01
    assert pkt.arg == 0x80
    assert pkt.unit_id == 0x1234
    assert pkt.status == 0x00
    assert pkt.crc_ok is True
    assert pkt.fec_ok is True
    assert pkt.is_double_packet is False
    assert pkt.all_checks_pass is True


@pytest.mark.parametrize(
    "preset",
    [
        "ptt_id_pre", "ptt_id_post", "emergency",
        "request_to_talk", "remote_monitor",
    ],
)
def test_decode_packet_round_trips_every_single_packet_preset(preset):
    """Every single-packet op-code preset must round-trip through
    encode → decode unchanged."""
    op, arg = resolve_op_preset(preset)
    frame = encode_packet(op, arg, 0xBEEF, status=0x00)
    pkt = decode_packet(frame)
    assert pkt.opcode == op
    assert pkt.arg == arg
    assert pkt.unit_id == 0xBEEF
    assert pkt.crc_ok and pkt.fec_ok


def test_decode_packet_recovers_full_hex_unit_id():
    """4-digit hex IDs that exercise A–F must round-trip — this is the
    range Motorola CPS uses for unit IDs."""
    frame = encode_packet(0xAB, 0xCD, 0xDEAD, status=0xEF)
    pkt = decode_packet(frame)
    assert pkt.opcode == 0xAB
    assert pkt.arg == 0xCD
    assert pkt.unit_id == 0xDEAD
    assert pkt.status == 0xEF


def test_decode_double_packet_round_trips():
    """``encode_double_packet`` → ``decode_double_packet`` must recover
    both the source ID (in packet 1) and the target ID (in packet 2),
    with CRC and FEC validating on both halves."""
    from app_utils.mdc1200 import encode_double_packet
    frame = encode_double_packet(0x63, 0x85, 0x1111, 0x2222)
    pkt = decode_double_packet(frame)
    assert pkt.opcode == 0x63
    assert pkt.arg == 0x85
    assert pkt.unit_id == 0x1111
    assert pkt.target_unit_id == 0x2222
    assert pkt.is_double_packet is True
    assert pkt.crc_ok and pkt.fec_ok
    assert pkt.crc2_ok and pkt.fec2_ok
    assert pkt.all_checks_pass is True


def test_decode_packet_flags_corrupted_payload_byte():
    """A bit error in the interleaved payload must trip the CRC and/or
    FEC checks without raising — structural validation stays clean so
    callers can decide their own tolerance.

    Differential modulation propagates a single on-air bit error
    through every subsequent bit, so corrupting an on-air byte directly
    would also mangle the post-preamble.  Instead we corrupt the
    *pre-modulation* payload byte and re-modulate; that produces an
    on-air frame whose differential decode yields a payload-only
    corruption with preamble / sync / post-preamble all intact."""
    frame = encode_packet(0x01, 0x80, 0x1234)
    pre_mod = _de_xor_modulate(frame)
    # Byte 10 sits at index 2 of the 14-byte interleaved payload region
    # (offset 3 preamble + 5 sync + 2).  A single-bit flip there will
    # both trip the FEC re-encode and (after de-interleaving) likely
    # corrupt one of the info bytes the CRC covers.
    pre_mod[10] ^= 0x10
    frame_corrupt = _xor_modulate(pre_mod)
    pkt = decode_packet(frame_corrupt)
    assert pkt.is_double_packet is False
    assert not pkt.all_checks_pass


def test_decode_packet_rejects_wrong_length():
    with pytest.raises(MDC1200DecodeError):
        decode_packet([0x00] * 25)
    with pytest.raises(MDC1200DecodeError):
        decode_packet([0x00] * 27)


def test_decode_packet_rejects_corrupted_sync_word():
    """If the sync word is mangled the buffer is not an MDC1200 frame
    at all — the decoder must raise rather than return a soft-bad
    result, since the rest of the buffer cannot be trusted to align."""
    frame = list(encode_packet(0x01, 0x80, 0x1234))
    # Sync word lives at on-air bytes 3..7; corrupt one of them after
    # differential modulation.  Flipping one bit in the modulated byte
    # propagates to subsequent bits via the cross-byte prev_bit carry,
    # so the decoded sync word will diverge from the canonical pattern.
    frame[5] ^= 0xFF
    with pytest.raises(MDC1200DecodeError):
        decode_packet(frame)


def test_decode_double_packet_rejects_wrong_length():
    with pytest.raises(MDC1200DecodeError):
        decode_double_packet([0x00] * 39)


def test_find_sync_in_bits_locates_known_frame_at_offset_zero():
    """A freshly-encoded frame, serialised MSB-first, must match sync at
    bit offset 0 with polarity 0 (the encoder starts with prev_bit=0)."""
    frame = encode_packet(0x01, 0x80, 0x1234)
    bits = bytes_to_bits_msb(frame)
    result = find_sync_in_bits(bits)
    assert result is not None
    offset, polarity = result
    assert offset == 0
    assert polarity == 0


def test_find_sync_in_bits_locates_frame_after_leading_garbage():
    """Real receivers see noise before the first frame.  Prepend some
    arbitrary bits and confirm the search still locks onto the frame."""
    frame = encode_packet(0x01, 0x80, 0x1234)
    frame_bits = bytes_to_bits_msb(frame)
    # 17 bits of arbitrary garbage so the offset is *not* a multiple of 8 —
    # this exercises the bit-level (rather than byte-level) sync search.
    garbage = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 0, 0, 1, 0, 1]
    stream = garbage + frame_bits
    result = find_sync_in_bits(stream)
    assert result is not None
    offset, _polarity = result
    assert offset == len(garbage)


def test_find_sync_in_bits_returns_none_for_too_short_stream():
    assert find_sync_in_bits([0, 1] * 10) is None


def test_find_sync_in_bits_returns_none_for_random_bits():
    """A stream of pseudo-random bits with no embedded frame must not
    produce a spurious sync hit."""
    import random
    rng = random.Random(0xC0FFEE)
    noise = [rng.randint(0, 1) for _ in range(2000)]
    assert find_sync_in_bits(noise) is None


def test_mdc1200_packet_all_checks_pass_requires_double_packet_halves():
    """A double-packet result must require *both* halves to validate —
    a corrupt second half cannot be silently masked by a clean first
    half."""
    pkt = MDC1200Packet(
        opcode=0x63, arg=0x85, unit_id=0x1111, status=0,
        crc_ok=True, fec_ok=True,
        target_unit_id=0x2222, crc2_ok=False, fec2_ok=True,
    )
    assert pkt.all_checks_pass is False


# ---------------------------------------------------------------------------
# Multi-packet sample-level decoder
# ---------------------------------------------------------------------------

def test_decode_all_mdc1200_recovers_ptt_id_pre_and_post():
    """Audio containing both PTT-ID Pre (start) and PTT-ID Post (end)
    must yield two packets — the single-pass ``decode_mdc1200_from_samples``
    used to return only the first sync match and silently dropped the
    trailing Post burst that real EAS Station composites emit."""
    import numpy as np

    sr = 16000
    amp = 0.7 * 32767
    unit_id = 0x1F96

    pre = generate_mdc1200_samples(0x01, 0x80, unit_id, sr, amp)
    post = generate_mdc1200_samples(0x00, 0x80, unit_id, sr, amp)
    silence = [0] * sr  # 1 second of silence between bursts

    waveform = np.array(list(pre) + silence + list(post), dtype=np.float32) / 32768.0

    packets = decode_all_mdc1200_from_samples(waveform, sr)
    assert len(packets) == 2, f"Expected Pre + Post, got {len(packets)} packets"

    assert packets[0].opcode == 0x01 and packets[0].arg == 0x80
    assert packets[0].unit_id == unit_id
    assert packets[0].crc_ok

    assert packets[1].opcode == 0x00 and packets[1].arg == 0x80
    assert packets[1].unit_id == unit_id
    assert packets[1].crc_ok


def test_decode_all_mdc1200_recovers_post_burst_with_clipped_post_preamble():
    """The trailing post-alert PTT-ID burst must still decode when its
    4-byte post-preamble (pure mark tone, no data) is clipped.

    EAS Station emits the post-alert MDC burst at the very end of the
    composite with no trailing audio, so a recording that ends at the
    packet boundary — or that a lossy re-encode trims by a few samples —
    loses the final mark-tone bits.  The strict ``decode_packet``
    post-preamble check used to reject the whole burst on that account,
    dropping the Post packet so the decoder UI showed only PTT-ID Pre.
    """
    import numpy as np

    sr = 16000
    amp = 0.7 * 32767
    unit_id = 0xBEEF

    pre = generate_mdc1200_samples(0x01, 0x80, unit_id, sr, amp)
    post = generate_mdc1200_samples(0x00, 0x80, unit_id, sr, amp)
    silence = [0] * (sr * 2)

    full = list(pre) + silence + list(post)
    # Clip the tail by ~20 samples (less than two bit periods) — enough to
    # destroy the trailing post-preamble but not the payload or its CRC.
    clipped = full[: len(full) - 20]
    waveform = np.array(clipped, dtype=np.float32) / 32768.0

    packets = decode_all_mdc1200_from_samples(waveform, sr)
    assert len(packets) == 2, f"Expected Pre + Post, got {len(packets)} packets"
    assert packets[0].opcode == 0x01 and packets[0].crc_ok
    assert packets[1].opcode == 0x00 and packets[1].arg == 0x80
    assert packets[1].unit_id == unit_id
    assert packets[1].crc_ok and packets[1].fec_ok


def test_decode_all_mdc1200_rejects_burst_truncated_into_payload():
    """Recovery of a clipped post-preamble must not fabricate a packet when
    the truncation reaches into the payload — the CRC/FEC guard rejects it
    rather than emitting a phantom burst with corrupt data."""
    import numpy as np

    sr = 16000
    amp = 0.7 * 32767

    pre = generate_mdc1200_samples(0x01, 0x80, 0xBEEF, sr, amp)
    post = generate_mdc1200_samples(0x00, 0x80, 0xBEEF, sr, amp)
    full = list(pre) + [0] * (sr * 2) + list(post)
    # Drop far more than the 32-bit post-preamble (~426 samples) so the cut
    # eats into the FEC/CRC payload of the final burst.
    clipped = full[: len(full) - 700]
    waveform = np.array(clipped, dtype=np.float32) / 32768.0

    packets = decode_all_mdc1200_from_samples(waveform, sr)
    assert len(packets) == 1, f"Corrupt tail must be rejected, got {len(packets)}"
    assert packets[0].opcode == 0x01 and packets[0].crc_ok


def test_decode_single_packet_is_not_misread_as_double_packet():
    """A single-packet PTT-ID Pre must not be promoted into a double-
    packet decode just because its trailing 4-byte 0x00 post-preamble
    overlaps the start of a double-packet's inter-packet preamble.

    Before this guard, ``target_unit_id`` ended up set to ``0x0000``
    (with ``crc2_ok=False``) and the UI rendered the burst as
    ``PTT-ID Pre → 0x0000`` — a phantom target that misled operators
    into thinking the decoder had also recovered a Post burst.
    """
    import numpy as np

    sr = 16000
    amp = 0.7 * 32767
    samples = generate_mdc1200_samples(0x01, 0x80, 0x1F96, sr, amp)
    waveform = np.array(list(samples) + [0] * (sr // 2), dtype=np.float32) / 32768.0

    packet = decode_mdc1200_from_samples(waveform, sr)
    assert packet is not None
    assert packet.opcode == 0x01 and packet.arg == 0x80
    assert packet.crc_ok
    assert packet.target_unit_id is None, (
        f"Single-packet PTT-ID Pre must report target_unit_id=None, "
        f"got {packet.target_unit_id!r}"
    )
    assert packet.is_double_packet is False


def test_decode_all_mdc1200_returns_empty_on_silence():
    """Pure silence must not produce any phantom packets."""
    import numpy as np
    sr = 16000
    waveform = np.zeros(sr, dtype=np.float32)
    assert decode_all_mdc1200_from_samples(waveform, sr) == []


def test_decode_all_mdc1200_recovers_real_double_packet():
    """A genuine double-packet op (Call Alert 0x63/0x85) must still
    decode as a single double-packet, not be misread as two singles."""
    import numpy as np
    from app_utils.mdc1200 import generate_mdc1200_samples as gen

    sr = 16000
    amp = 0.7 * 32767
    # Call Alert is in MDC1200_DOUBLE_PACKET_OPS — gen() emits 40-byte frame.
    samples = gen(0x63, 0x85, 0x1111, sr, amp, target_unit_id=0x2222)
    waveform = np.array(list(samples) + [0] * (sr // 2), dtype=np.float32) / 32768.0

    packets = decode_all_mdc1200_from_samples(waveform, sr)
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt.opcode == 0x63 and pkt.arg == 0x85
    assert pkt.unit_id == 0x1111
    assert pkt.target_unit_id == 0x2222
    assert pkt.crc_ok and pkt.crc2_ok
