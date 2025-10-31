import struct
import sys
import wave
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


def _write_same_audio(
    path: str,
    header: str,
    *,
    sample_rate: int = 44100,
    scale: float = 1.0,
    leading_pad: int = 0,
) -> None:
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
        if leading_pad > 0:
            wav.writeframes(b"\x00\x00" * leading_pad)
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


def test_decode_same_audio_handles_leading_offset(tmp_path) -> None:
    header = "ZCZC-ABC-DEF-123456-000001-"
    path = tmp_path / "offset.wav"
    # Pad the start of the audio by half a bit to simulate imperfect capture alignment.
    leading_pad = 15
    _write_same_audio(str(path), header, leading_pad=leading_pad)

    result = decode_same_audio(str(path))

    assert any(item.header == header for item in result.headers)
