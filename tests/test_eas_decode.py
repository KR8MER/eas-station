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

import struct
import math
import sys
import wave
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app_utils.eas_decode import build_plain_language_summary, decode_same_audio
from app_utils.eas_demod import SAMEDemodulatorCore
from app_utils.eas_fsk import (
    SAME_BAUD,
    SAME_MARK_FREQ,
    SAME_SPACE_FREQ,
    encode_same_bits,
    generate_fsk_samples,
    same_preamble_bits,
)


def _write_same_audio(path: str, header: str, *, sample_rate: int = 44100, scale: float = 1.0) -> None:
    bits = encode_same_bits(header, include_preamble=True)
    base_rate = float(SAME_BAUD)
    bit_rate = base_rate * scale
    mark_freq = SAME_MARK_FREQ * scale
    space_freq = SAME_SPACE_FREQ * scale
    samples = generate_fsk_samples(
        bits,
        sample_rate=sample_rate,
        bit_rate=bit_rate,
        mark_freq=mark_freq,
        space_freq=space_freq,
        amplitude=20000,
    )

    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


def test_encode_same_bits_fcc_format() -> None:
    """Test that encode_same_bits produces FCC 47 CFR §11.31 compliant output.

    Per FCC 47 CFR §11.31: "Characters are ASCII seven bit characters as defined in
    ANSI X3.4-1977 ending with an eighth null bit (either 0 or 1) to constitute a
    full eight-bit byte."

    There are NO start or stop framing bits — each character is exactly 8 bits:
    7 ASCII data bits (LSB first) followed by one null bit.
    """
    header = "CZ"
    bits = encode_same_bits(header, include_preamble=False)

    chars = len(header) + 1  # Include terminating carriage return
    assert len(bits) == chars * 8, (
        f"Expected {chars * 8} bits (8 per char per FCC §11.31), got {len(bits)}"
    )

    for index, char in enumerate(header + "\r"):
        chunk = bits[index * 8 : (index + 1) * 8]
        # Bits 0-6 are the 7-bit ASCII character (LSB first)
        data_bits = chunk[:7]
        null_bit = chunk[7]

        assert null_bit == 0, f"Eighth bit (null bit) must be 0 per FCC §11.31 (char {repr(char)})"

        # Reconstruct character value from LSB-first data bits
        value = sum((b & 1) << i for i, b in enumerate(data_bits))
        assert value == (ord(char) & 0x7F), (
            f"Data bits decode to {value} but expected {ord(char) & 0x7F} for {repr(char)}"
        )


def test_decode_same_audio_handles_slightly_slow_baud(tmp_path) -> None:
    header = "ZCZC-ABC-DEF-123456-000001-"
    path = tmp_path / "slow.wav"
    _write_same_audio(str(path), header, scale=0.96)

    result = decode_same_audio(str(path))

    assert any(item.header == header for item in result.headers)


def test_decode_same_audio_handles_slightly_fast_baud(tmp_path) -> None:
    header = "ZCZC-ABC-DEF-123456-000001-"
    path = tmp_path / "fast.wav"
    _write_same_audio(str(path), header, scale=1.04)

    result = decode_same_audio(str(path))

    assert any(item.header == header for item in result.headers)


def test_decode_same_audio_extracts_segments(tmp_path) -> None:
    sample_rate = 22050
    header = "ZCZC-ABC-DEF-123456-000001-"
    header_bits = encode_same_bits(header, include_preamble=True)
    header_samples = generate_fsk_samples(
        header_bits,
        sample_rate=sample_rate,
        bit_rate=float(SAME_BAUD),
        mark_freq=SAME_MARK_FREQ,
        space_freq=SAME_SPACE_FREQ,
        amplitude=20000,
    )
    header_sequence = header_samples * 3

    tone_duration = 1.0
    tone_samples = []
    for index in range(int(sample_rate * tone_duration)):
        t = index / sample_rate
        value = 0.5 * (
            math.sin(2 * math.pi * 853 * t) + math.sin(2 * math.pi * 960 * t)
        )
        tone_samples.append(int(value * 15000))

    message_samples = []
    for index in range(int(sample_rate * 1.5)):
        t = index / sample_rate
        # Simple spoken-style waveform approximation
        carrier = math.sin(2 * math.pi * 440 * t) * math.sin(2 * math.pi * 2 * t)
        message_samples.append(int(carrier * 8000))

    eom_bits = encode_same_bits("NNNN", include_preamble=True, include_cr=False)
    eom_samples = generate_fsk_samples(
        eom_bits,
        sample_rate=sample_rate,
        bit_rate=float(SAME_BAUD),
        mark_freq=SAME_MARK_FREQ,
        space_freq=SAME_SPACE_FREQ,
        amplitude=20000,
    ) * 3

    combined = header_sequence + tone_samples + message_samples + eom_samples

    path = tmp_path / "composite.wav"
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        pcm_array = array("h", combined)
        wav_file.writeframes(pcm_array.tobytes())

    result = decode_same_audio(str(path), sample_rate=sample_rate)

    assert "header" in result.segments
    assert "message" in result.segments
    assert "eom" in result.segments
    assert "buffer" in result.segments
    assert result.segments["header"].duration_seconds > 0.0
    assert result.segments["eom"].duration_seconds > 0.0
    assert result.segments["message"].duration_seconds >= 0.9
    assert result.segments["buffer"].duration_seconds <= 120.0


def test_plain_summary_omits_codes_and_formats_locations() -> None:
    fields = {
        "originator_description": "EAS Participant",
        "event_code": "RWT",
        "locations": [
            {"description": "Essex"},
            {"description": "Gloucester"},
            {"description": "King and Queen"},
            {"description": "Lancaster"},
            {"description": "Mathews"},
            {"description": "Middlesex"},
            {"description": "New Kent"},
            {"description": "Northumberland"},
            {"description": "Richmond (county), VA"},
        ],
        "issue_time_iso": "2025-11-01T18:12:00+00:00",
        "purge_minutes": 60,
        "station_identifier": "WKWI/FM",
    }

    summary = build_plain_language_summary("ZCZC-TEST", fields)

    expected = (
        "An EAS Participant has issued A REQUIRED WEEKLY TEST for the following counties/areas: "
        "Essex; Gloucester; King and Queen; Lancaster; Mathews; Middlesex; New Kent; Northumberland; "
        "Richmond (county), VA; at 6:12 PM on NOV 1, 2025 Effective until 7:12 PM. Message from WKWI/FM."
    )

    assert summary == expected


# ---------------------------------------------------------------------------
# Helper shared by DLL round-trip tests
# ---------------------------------------------------------------------------

def _make_fsk_audio(header: str, *, sample_rate: int = 44100, bursts: int = 3) -> "np.ndarray":
    """Encode a SAME header as FSK audio matching real ENDEC hardware output.

    ``bursts`` identical transmissions are separated by 1-second silence gaps,
    exactly matching the FCC §11.31 three-burst transmission sequence.
    """
    import numpy as np
    bits = encode_same_bits(header, include_preamble=True)
    burst_samples = generate_fsk_samples(
        bits,
        sample_rate=sample_rate,
        bit_rate=float(SAME_BAUD),
        mark_freq=SAME_MARK_FREQ,
        space_freq=SAME_SPACE_FREQ,
        amplitude=20000,
    )
    silence = [0] * sample_rate
    combined: list = []
    for _ in range(bursts):
        combined.extend(burst_samples)
        combined.extend(silence)
    return np.array(combined, dtype=np.float32) / 32768.0


# ---------------------------------------------------------------------------
# Regression tests: FCC §11.31 bit format and DLL streaming decoder
#
# HISTORY: A previous AI agent (Claude, Nov 2 2025) "fixed" the encoder from
# 7E1 parity frames to what it believed was the FCC-mandated 8N1 format.
# It correctly identified that FCC §11.31 specifies 8 bits per character but
# INCORRECTLY implemented UART serial framing:
#
#   Wrong (UART 8N1):  [start=0][d0..d6][null][stop=1]  → 10 bits per char
#   Correct (FCC raw): [d0..d6][null]                   → 8 bits per char
#
# SAME uses raw FSK bit transmission — NOT serial UART framing.  There are
# no start or stop bits.  The DLL streaming decoder (SAMEDemodulatorCore)
# was always FCC-correct (reads 8 bits per byte).  With the encoder emitting
# 10-bit frames the byte boundaries shifted by 2 bits on every character,
# making preamble sync impossible.  Zero alerts were decoded from live OTA
# or stream sources for the entire 6-month operational period of the system.
#
# These tests are the permanent regression guard against that bug returning.
# ---------------------------------------------------------------------------

def test_encoder_produces_fcc_8bit_frames() -> None:
    """encode_same_bits must emit 8 bits per character with no start/stop bits.

    REGRESSION GUARD: If this reverts to 10-bit UART framing the DLL
    streaming decoder will be completely deaf to live OTA/stream alerts.

    FCC 47 CFR §11.31: each character = 7 ASCII data bits (LSB first) + 1
    null bit.  No start bit.  No stop bit.  Total = 8 bits per character.
    """
    bits = encode_same_bits("ZCZC", include_preamble=False)
    chars_with_cr = 5  # "ZCZC" + CR
    assert len(bits) == chars_with_cr * 8, (
        f"encode_same_bits returned {len(bits)} bits for {chars_with_cr} chars. "
        f"Expected {chars_with_cr * 8} (8-bit FCC format). "
        f"10-bit UART framing ({chars_with_cr * 10} bits) breaks the DLL streaming decoder."
    )


def test_preamble_produces_fcc_8bit_bytes() -> None:
    """same_preamble_bits must emit 16 bytes × 8 bits = 128 bits with no framing.

    REGRESSION GUARD: 10-bit framing (160 bits) misaligns all byte boundaries
    in the DLL, preventing preamble sync and silencing all live alert decoding.
    """
    preamble = same_preamble_bits()
    assert len(preamble) == 128, (
        f"same_preamble_bits returned {len(preamble)} bits. "
        f"Expected 128 (16 × 8-bit FCC). "
        f"10-bit framing (160 bits) breaks preamble sync in the DLL decoder."
    )
    for i in range(16):
        byte_val = sum((preamble[i * 8 + b] & 1) << b for b in range(8))
        assert byte_val == 0xAB, (
            f"Preamble byte {i} = 0x{byte_val:02X}, expected 0xAB. "
            f"Wrong preamble value prevents DLL sync."
        )


def test_dll_decoder_round_trip_nominal() -> None:
    """SAMEDemodulatorCore (DLL) must decode audio produced by the encoder.

    REGRESSION GUARD: This is the exact code path used for live OTA and
    stream monitoring (UnifiedEASMonitorService feeds audio to
    SAMEDemodulatorCore).  A failure here means zero live alerts received.

    With 10-bit UART framing the DLL returns 0 messages.
    With correct 8-bit FCC framing the DLL returns 3 messages (one per burst).
    """
    header = "ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"
    samples = _make_fsk_audio(header, sample_rate=44100)

    core = SAMEDemodulatorCore(44100, apply_bandpass=True)
    core.process_samples(samples)

    assert len(core.messages) >= 1, (
        f"SAMEDemodulatorCore decoded 0 messages. "
        f"The encoder may have reverted to 10-bit UART framing. "
        f"Check encode_same_bits() and same_preamble_bits(). "
        f"bytes_decoded={core.bytes_decoded}"
    )
    assert any(header in m for m in core.messages), (
        f"Header not found in decoded messages: {core.messages!r}"
    )


def test_dll_decoder_round_trip_all_three_bursts() -> None:
    """DLL must decode all 3 EAS transmission bursts (required for reliable operation)."""
    header = "ZCZC-WXR-SVR-029177+0100-0181500-KOAX/NWS-"
    samples = _make_fsk_audio(header, sample_rate=44100, bursts=3)

    core = SAMEDemodulatorCore(44100, apply_bandpass=True)
    core.process_samples(samples)

    assert len(core.messages) == 3, (
        f"Expected 3 decoded bursts (one per EAS transmission), got {len(core.messages)}. "
        f"Messages: {core.messages!r}"
    )


def test_dll_decoder_round_trip_at_16khz() -> None:
    """DLL must decode at 16 kHz — the sample rate used by UnifiedEASMonitorService.

    The live OTA/stream monitoring pipeline resamples all audio to 16 kHz
    before feeding it to the decoder.  If decoding fails at 16 kHz, live
    monitoring is silently deaf regardless of signal quality.
    """
    header = "ZCZC-EAS-RWT-000000+0100-0010000-KKKK/FM  -"
    samples = _make_fsk_audio(header, sample_rate=16000)

    core = SAMEDemodulatorCore(16000, apply_bandpass=True)
    core.process_samples(samples)

    assert len(core.messages) >= 1, (
        f"DLL decoded 0 messages at 16 kHz. "
        f"Live OTA/stream monitoring (UnifiedEASMonitorService) uses 16 kHz and "
        f"would be completely silent. bytes_decoded={core.bytes_decoded}"
    )


def test_dll_decoder_round_trip_chunked_100ms() -> None:
    """DLL must handle audio delivered as 100 ms chunks (real OTA/stream scenario).

    UnifiedEASMonitorService feeds the decoder in 1600-sample (100 ms at
    16 kHz) chunks.  The decoder must assemble a complete SAME header across
    many separate process_samples() calls, just as it does in production.
    """
    header = "ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"
    full_audio = _make_fsk_audio(header, sample_rate=16000)
    chunk_size = 1600  # 100 ms at 16 kHz

    core = SAMEDemodulatorCore(16000, apply_bandpass=True)
    for offset in range(0, len(full_audio), chunk_size):
        core.process_samples(full_audio[offset : offset + chunk_size])

    assert len(core.messages) >= 1, (
        f"DLL decoded 0 messages when audio was delivered in 100 ms chunks. "
        f"This is exactly how UnifiedEASMonitorService feeds the decoder in production."
    )


def test_dll_decoder_round_trip_varied_headers() -> None:
    """DLL must successfully decode a variety of real-world SAME header formats."""
    headers = [
        "ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-",
        "ZCZC-EAS-RWT-000000+0100-0010000-KKKK/FM  -",
        "ZCZC-CIV-EVI-037001-037063+0015-0121615-WXYZ/FM -",
        "ZCZC-PEP-EAN-000000+0600-0010000-WHITEHSE -",
        "ZCZC-WXR-SVR-029015-029177+0100-0181500-KOAX/NWS-",
    ]
    for header in headers:
        samples = _make_fsk_audio(header, sample_rate=44100)
        core = SAMEDemodulatorCore(44100, apply_bandpass=True)
        core.process_samples(samples)
        assert len(core.messages) >= 1, (
            f"DLL failed to decode: {header!r}"
        )
        assert any(header in m for m in core.messages), (
            f"Header {header!r} not in decoded messages {core.messages!r}"
        )


# ---------------------------------------------------------------------------
# ENDEC detection tests — EAS-Tools-compatible voting logic
#
# EAS-Tools (wagwan-piffting-blud/EAS-Tools) determines the originating ENDEC
# by analysing null/FF bytes appended after each burst and inter-burst gap
# timing.  The tests below validate that detect_endec_mode() produces the
# correct result for each supported profile.
# ---------------------------------------------------------------------------

from app_utils.eas_demod import (
    detect_endec_mode,
    ENDEC_MODE_UNKNOWN,
    ENDEC_MODE_DEFAULT,
    ENDEC_MODE_NWS,
    ENDEC_MODE_NWS_BMH,
    ENDEC_MODE_SAGE_3644,
    ENDEC_MODE_SAGE_1822,
    ENDEC_MODE_TRILITHIC,
    ENDEC_MODE_EAS_STATION,
)


def test_detect_endec_no_evidence_returns_unknown() -> None:
    """With no timing or terminator-byte evidence the mode is UNKNOWN."""
    assert detect_endec_mode([], []) == ENDEC_MODE_UNKNOWN
    assert detect_endec_mode([], [], terminator_runs=[]) == ENDEC_MODE_UNKNOWN


def test_detect_endec_nws_legacy_two_null_bytes() -> None:
    """NWS Legacy / EAS.js appends 2 × 0x00 after each burst → NWS mode."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [],
        terminator_runs=[(0x00, 2)],
    )
    assert mode == ENDEC_MODE_NWS, f"Expected NWS, got {mode}"


def test_detect_endec_nws_bmh_three_null_bytes() -> None:
    """NWS BMH (2016+) appends 3 × 0x00 after each burst → NWS_BMH mode."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [],
        terminator_runs=[(0x00, 3)],
    )
    assert mode == ENDEC_MODE_NWS_BMH, f"Expected NWS_BMH, got {mode}"


def test_detect_endec_sage_analog_1822_single_ff() -> None:
    """SAGE ANALOG 1822 appends 1 × 0xFF after each burst → SAGE_ANALOG_1822."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [],
        terminator_runs=[(0xFF, 1)],
    )
    assert mode == ENDEC_MODE_SAGE_1822, f"Expected SAGE_ANALOG_1822, got {mode}"


def test_detect_endec_sage_digital_3644_three_ff_bytes() -> None:
    """SAGE DIGITAL 3644 appends 3 × 0xFF after each burst → SAGE_DIGITAL_3644."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [],
        terminator_runs=[(0xFF, 3)],
    )
    assert mode == ENDEC_MODE_SAGE_3644, f"Expected SAGE_DIGITAL_3644, got {mode}"


def test_detect_endec_sage_digital_3644_leading_null() -> None:
    """SAGE DIGITAL 3644 leading-null signature alone is enough to identify it."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [],
        leading_null_detected=True,
    )
    assert mode == ENDEC_MODE_SAGE_3644, f"Expected SAGE_DIGITAL_3644, got {mode}"


def test_detect_endec_trilithic_gap_timing() -> None:
    """Trilithic EASyPLUS uses ~868 ms inter-burst gaps → TRILITHIC mode."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [868.0, 868.0],
    )
    assert mode == ENDEC_MODE_TRILITHIC, f"Expected TRILITHIC, got {mode}"


def test_detect_endec_default_standard_gap_timing() -> None:
    """Standard ~1000 ms gaps with no terminator bytes → DEFAULT (DASDEC) mode."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [1000.0, 1000.0],
    )
    assert mode == ENDEC_MODE_DEFAULT, f"Expected DEFAULT, got {mode}"


def test_detect_endec_sage_digital_beats_timing_alone() -> None:
    """3 × 0xFF terminator evidence overrides standard-gap timing for SAGE DIGITAL."""
    # Even at a 1000 ms gap (which would vote DEFAULT), three FF bytes should
    # produce a higher-confidence vote for SAGE_DIGITAL_3644.
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [1000.0],
        terminator_runs=[(0xFF, 3)],
    )
    assert mode == ENDEC_MODE_SAGE_3644, f"Expected SAGE_DIGITAL_3644, got {mode}"


def test_detect_endec_trilithic_beats_no_terminator_bytes() -> None:
    """Trilithic gap timing wins when no terminator bytes are present."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [868.0],
        terminator_runs=[],
    )
    assert mode == ENDEC_MODE_TRILITHIC, f"Expected TRILITHIC, got {mode}"


def _make_fsk_audio_with_terminator(
    header: str,
    terminator_bytes: bytes,
    *,
    sample_rate: int = 44100,
    bursts: int = 3,
    gap_ms: float = 1000.0,
) -> "np.ndarray":
    """Encode a SAME header with ENDEC-style terminator bytes appended to each burst.

    This mirrors how real ENDEC hardware transmits:  each of the three FCC-required
    bursts is followed immediately by ``terminator_bytes`` (e.g. b'\\xff\\xff\\xff'
    for SAGE DIGITAL 3644) before the inter-burst gap.

    A low-level white-noise floor is used for the inter-burst gap to match real audio
    conditions.  Pure silence (all-zero samples) causes the DLL to produce a constant
    stream of 0x00 bytes indistinguishable from intentional NWS terminators; noise
    produces varied byte values, terminating the post-message capture window quickly.

    Args:
        header:           SAME header string (e.g. "ZCZC-WXR-TOR-...").
        terminator_bytes: Raw bytes appended after the header FSK data.
        sample_rate:      Audio sample rate in Hz.
        bursts:           Number of identical transmission bursts.
        gap_ms:           Inter-burst gap duration in milliseconds.
    """
    import numpy as np

    header_bits = encode_same_bits(header, include_preamble=True)
    header_samples = generate_fsk_samples(
        header_bits,
        sample_rate=sample_rate,
        bit_rate=float(SAME_BAUD),
        mark_freq=SAME_MARK_FREQ,
        space_freq=SAME_SPACE_FREQ,
        amplitude=20000,
    )

    # Build FSK bits for the raw terminator bytes (8 bits each, LSB first)
    term_bits: list = []
    for b in terminator_bytes:
        for bit_pos in range(8):
            term_bits.append((b >> bit_pos) & 1)

    term_samples: list = []
    if term_bits:
        term_samples = generate_fsk_samples(
            term_bits,
            sample_rate=sample_rate,
            bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=20000,
        )

    # Use low-level noise for the inter-burst gap.  This faithfully simulates
    # real audio where background noise is always present during silence periods.
    # Pure zeros produce a constant 0x00 byte stream in the DLL, which is
    # indistinguishable from intentional NWS null-byte terminators.
    rng = np.random.default_rng(seed=42)
    gap_len = int(sample_rate * gap_ms / 1000.0)
    gap_samples = list(
        (rng.uniform(-1, 1, size=gap_len) * 200).astype(np.int16)
    )

    combined: list = []
    for _ in range(bursts):
        combined.extend(header_samples)
        combined.extend(term_samples)
        combined.extend(gap_samples)

    return np.array(combined, dtype=np.float32) / 32768.0


def test_dll_endec_detection_sage_digital_3644_integration() -> None:
    """SAMEDemodulatorCore must detect SAGE DIGITAL 3644 from 3 × 0xFF terminator bytes.

    SAGE DIGITAL 3644 appends three 0xFF bytes after each SAME burst.  The DLL
    streaming decoder must capture these bytes in post-message mode and report
    SAGE_DIGITAL_3644 as the detected ENDEC.
    """
    header = "ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"
    samples = _make_fsk_audio_with_terminator(
        header, b"\xff\xff\xff", sample_rate=44100
    )

    core = SAMEDemodulatorCore(44100, apply_bandpass=True)
    core.process_samples(samples)

    assert len(core.messages) >= 1, "DLL must decode at least one burst"
    assert core.endec_mode == ENDEC_MODE_SAGE_3644, (
        f"Expected SAGE_DIGITAL_3644 from 3×0xFF terminator bytes, got {core.endec_mode!r}. "
        f"terminator_runs={core._all_terminator_runs!r}"
    )


def test_dll_endec_detection_sage_analog_1822_integration() -> None:
    """SAMEDemodulatorCore must detect SAGE ANALOG 1822 from 1 × 0xFF terminator byte."""
    header = "ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"
    samples = _make_fsk_audio_with_terminator(
        header, b"\xff", sample_rate=44100
    )

    core = SAMEDemodulatorCore(44100, apply_bandpass=True)
    core.process_samples(samples)

    assert len(core.messages) >= 1, "DLL must decode at least one burst"
    assert core.endec_mode == ENDEC_MODE_SAGE_1822, (
        f"Expected SAGE_ANALOG_1822 from 1×0xFF terminator byte, got {core.endec_mode!r}. "
        f"terminator_runs={core._all_terminator_runs!r}"
    )


def test_dll_endec_detection_nws_null_bytes_integration() -> None:
    """SAMEDemodulatorCore must detect NWS from 2 × 0x00 null byte terminators."""
    header = "ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"
    samples = _make_fsk_audio_with_terminator(
        header, b"\x00\x00", sample_rate=44100
    )

    core = SAMEDemodulatorCore(44100, apply_bandpass=True)
    core.process_samples(samples)

    assert len(core.messages) >= 1, "DLL must decode at least one burst"
    assert core.endec_mode == ENDEC_MODE_NWS, (
        f"Expected NWS from 2×0x00 terminator bytes, got {core.endec_mode!r}. "
        f"terminator_runs={core._all_terminator_runs!r}"
    )


def test_dll_endec_no_regression_on_plain_audio() -> None:
    """Standard SAME audio without terminator bytes must still decode correctly.

    REGRESSION GUARD: The post-message terminator capture must not interfere
    with normal decoding of alerts from DEFAULT/DASDEC hardware that appends
    no special bytes.
    """
    header = "ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"
    samples = _make_fsk_audio(header, sample_rate=44100)

    core = SAMEDemodulatorCore(44100, apply_bandpass=True)
    core.process_samples(samples)

    assert len(core.messages) >= 1, "DLL must still decode plain audio after ENDEC refactor"
    assert any(header in m for m in core.messages), (
        f"Header not found in decoded messages: {core.messages!r}"
    )


def test_detect_endec_eas_station_a9_bytes() -> None:
    """KR8MER EAS Station appends 3 × 0xA9 after each burst → EAS_STATION."""
    mode = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [],
        terminator_runs=[(0xA9, 3)],
    )
    assert mode == ENDEC_MODE_EAS_STATION, f"Expected EAS_STATION, got {mode}"


def test_dll_endec_detection_eas_station_integration() -> None:
    """SAMEDemodulatorCore must detect KR8MER EAS Station from 3 × 0xA9 terminator bytes.

    The DLL must capture these bytes in post-message mode and report EAS_STATION —
    and the SAME message must decode correctly.
    """
    header = "ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"
    samples = _make_fsk_audio_with_terminator(
        header, b"\xa9\xa9\xa9", sample_rate=44100
    )

    core = SAMEDemodulatorCore(44100, apply_bandpass=True)
    core.process_samples(samples)

    assert len(core.messages) >= 1, "DLL must decode at least one burst"
    assert core.endec_mode == ENDEC_MODE_EAS_STATION, (
        f"Expected EAS_STATION from 3×0xA9 terminator bytes, got {core.endec_mode!r}. "
        f"terminator_runs={core._all_terminator_runs!r}"
    )


def test_detect_endec_eas_station_a9_beats_silence_floor_ff_noise() -> None:
    """When the DLL captures a real KR8MER 3×0xA9 trill on every burst
    but the FSK demod also picks up post-fingerprint silence as long
    runs of 0xFF (mark tone), the EAS_STATION vote must still win.

    Before this guard, repeated ``(0xFF, large_N)`` runs accumulated
    enough SAGE_DIGITAL_3644 vote to tie or beat the legitimate KR8MER
    fingerprint, and a clean EAS Station composite was misidentified as
    SAGE DIGITAL.
    """
    runs = []
    # Three bursts, each emitting the legitimate trill followed by a
    # long silence-floor 0xFF run.
    for _ in range(3):
        runs.append((0xA9, 3))
        runs.append((0xFF, 8))
    mode = detect_endec_mode(
        ["ZCZC-WXR-DMO-039003+0015-0001234-KR8MER-"],
        [],
        terminator_runs=runs,
    )
    assert mode == ENDEC_MODE_EAS_STATION, (
        f"Expected EAS_STATION (0xA9 trill is unique to KR8MER), got {mode!r}"
    )


def test_detect_endec_deduplicates_repeated_burst_evidence() -> None:
    """Three identical SAME bursts produce three identical terminator
    runs; the vote must not multiply by three (which used to allow
    accumulated 0xFF silence noise to override a single legitimate
    fingerprint observed in a different vote slot)."""
    # SAGE DIGITAL — 3 bursts × (0xFF, 3) should still pick SAGE_3644,
    # but a single (0xFF, 3) entry should yield the same result.
    mode_single = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [],
        terminator_runs=[(0xFF, 3)],
    )
    mode_triple = detect_endec_mode(
        ["ZCZC-WXR-TOR-029015+0030-0181500-KOAX/NWS-"],
        [],
        terminator_runs=[(0xFF, 3), (0xFF, 3), (0xFF, 3)],
    )
    assert mode_single == mode_triple == ENDEC_MODE_SAGE_3644
