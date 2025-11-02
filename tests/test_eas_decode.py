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
from app_utils.eas_fsk import (
    SAME_BAUD,
    SAME_MARK_FREQ,
    SAME_SPACE_FREQ,
    encode_same_bits,
    generate_fsk_samples,
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


def test_encode_same_bits_uses_8n1_framing() -> None:
    """Test that encode_same_bits uses proper 8N1 framing (8 data bits, no parity, 1 stop).

    Per FCC 47 CFR §11.31: "Characters are ASCII seven bit characters ending with
    an eighth null bit (either 0 or 1) to constitute a full eight-bit byte."

    Frame format: start(0) + 7 data bits + null bit(0) + stop(1)
    """
    header = "CZ"
    bits = encode_same_bits(header, include_preamble=False)

    chars = len(header) + 1  # Include terminating carriage return
    assert len(bits) == chars * 10

    for index in range(chars):
        chunk = bits[index * 10 : (index + 1) * 10]
        assert chunk[0] == 0, "Start bit must be 0"
        assert chunk[9] == 1, "Stop bit must be 1"

        # In 8N1 format:
        # - Bits 1-7 are the 7-bit ASCII character (LSB first)
        # - Bit 8 is the null bit (should be 0 per spec)
        data_bits = chunk[1:8]
        null_bit = chunk[8]

        assert null_bit == 0, "Eighth bit (null bit) must be 0 per FCC regulation"


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

    eom_bits = encode_same_bits("NNNN", include_preamble=True)
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
