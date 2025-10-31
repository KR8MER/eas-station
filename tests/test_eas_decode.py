import struct
import math
import sys
import wave
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app_utils.eas_decode import decode_same_audio
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
