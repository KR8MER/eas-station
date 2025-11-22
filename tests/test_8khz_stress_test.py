"""
Stress test for 8000 Hz sample rate to determine if it's truly production-ready.

This test suite puts 8kHz through aggressive real-world scenarios to see
if the 3.8× margin (vs 7.7× for 16kHz) causes any reliability issues.
"""

import struct
import tempfile
import wave
from pathlib import Path

import pytest

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
    sample_rate: int = 8000,
    scale: float = 1.0,
    noise_level: float = 0.0,
    frequency_drift: float = 0.0
) -> None:
    """Write a synthetic SAME audio file with optional noise and frequency drift."""
    bits = encode_same_bits(header, include_preamble=True)
    base_rate = float(SAME_BAUD)
    bit_rate = base_rate * scale
    mark_freq = SAME_MARK_FREQ * scale * (1.0 + frequency_drift)
    space_freq = SAME_SPACE_FREQ * scale * (1.0 + frequency_drift)
    samples = generate_fsk_samples(
        bits,
        sample_rate=sample_rate,
        bit_rate=bit_rate,
        mark_freq=mark_freq,
        space_freq=space_freq,
        amplitude=20000,
    )

    # Add noise if requested
    if noise_level > 0:
        import random
        samples = [
            int(s + random.randint(-int(noise_level), int(noise_level)))
            for s in samples
        ]

    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


# Real-world headers that must decode reliably
CRITICAL_HEADERS = [
    # Tornado Warning - MUST work perfectly
    "ZCZC-WXR-TOR-039137+0030-3662322-WTHI/TV-",
    # Child Abduction Emergency - MUST work perfectly
    "ZCZC-CIV-CAE-012345+0030-1231200-NOCALL00-",
    # Earthquake Warning - MUST work perfectly
    "ZCZC-WXR-EQW-012345+0030-1231200-NOCALL00-",
]


@pytest.mark.parametrize("noise_pct", [0.0, 0.05, 0.10, 0.15, 0.20])
def test_8khz_with_increasing_noise(noise_pct: float, tmp_path: Path) -> None:
    """Test 8kHz reliability with increasing noise levels."""
    header = "ZCZC-WXR-TOR-039137+0030-3662322-WTHI/TV-"
    audio_file = tmp_path / f"noise_{int(noise_pct*100)}.wav"
    
    # Add noise as percentage of signal amplitude (20000)
    noise_level = 20000 * noise_pct
    _write_same_audio(str(audio_file), header, sample_rate=8000, noise_level=noise_level)
    
    result = decode_same_audio(str(audio_file), sample_rate=8000)
    
    assert len(result.headers) > 0, f"Failed with {noise_pct*100}% noise"
    # Allow some confidence degradation with noise, but not too much
    min_confidence = max(0.2, 0.8 - noise_pct * 2)
    assert result.bit_confidence > min_confidence, \
        f"Confidence too low ({result.bit_confidence:.1%}) with {noise_pct*100}% noise"


@pytest.mark.parametrize("baud_error_pct", [-0.08, -0.06, -0.04, -0.02, 0.0, 0.02, 0.04, 0.06, 0.08])
def test_8khz_with_baud_rate_variations(baud_error_pct: float, tmp_path: Path) -> None:
    """Test 8kHz with various baud rate errors (simulating clock drift)."""
    header = "ZCZC-WXR-RWT-012345+0015-1231200-NOCALL00-"
    audio_file = tmp_path / f"baud_{int(baud_error_pct*100):+03d}.wav"
    
    scale = 1.0 + baud_error_pct
    _write_same_audio(str(audio_file), header, sample_rate=8000, scale=scale)
    
    result = decode_same_audio(str(audio_file), sample_rate=8000)
    
    assert len(result.headers) > 0, f"Failed with {baud_error_pct*100:+.0f}% baud error"
    assert any(h.header == header for h in result.headers), \
        f"Header mismatch with {baud_error_pct*100:+.0f}% baud error"


@pytest.mark.parametrize("freq_drift_pct", [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03])
def test_8khz_with_frequency_drift(freq_drift_pct: float, tmp_path: Path) -> None:
    """Test 8kHz with frequency drift (simulating analog demodulation errors)."""
    header = "ZCZC-WXR-TOR-039137+0030-3662322-WTHI/TV-"
    audio_file = tmp_path / f"drift_{int(freq_drift_pct*100):+03d}.wav"
    
    _write_same_audio(
        str(audio_file),
        header,
        sample_rate=8000,
        frequency_drift=freq_drift_pct
    )
    
    result = decode_same_audio(str(audio_file), sample_rate=8000)
    
    assert len(result.headers) > 0, f"Failed with {freq_drift_pct*100:+.0f}% frequency drift"


@pytest.mark.parametrize("header", CRITICAL_HEADERS)
def test_8khz_critical_alerts_must_decode(header: str, tmp_path: Path) -> None:
    """Test that life-safety critical alerts decode at 8kHz."""
    audio_file = tmp_path / "critical.wav"
    _write_same_audio(str(audio_file), header, sample_rate=8000)
    
    result = decode_same_audio(str(audio_file), sample_rate=8000)
    
    assert len(result.headers) > 0, "CRITICAL: Failed to decode life-safety alert"
    assert any(h.header == header for h in result.headers), \
        f"CRITICAL: Header mismatch for life-safety alert"
    assert result.bit_confidence > 0.5, \
        f"CRITICAL: Low confidence ({result.bit_confidence:.1%}) for life-safety alert"


def test_8khz_vs_16khz_comparison(tmp_path: Path) -> None:
    """Direct comparison of 8kHz vs 16kHz decoding quality."""
    header = "ZCZC-WXR-RWT-012345+0015-1231200-NOCALL00-"
    
    results = {}
    for rate in [8000, 16000]:
        audio_file = tmp_path / f"compare_{rate}.wav"
        _write_same_audio(str(audio_file), header, sample_rate=rate, noise_level=1000)
        results[rate] = decode_same_audio(str(audio_file), sample_rate=rate)
    
    # Both should decode successfully
    assert len(results[8000].headers) > 0, "8kHz failed to decode"
    assert len(results[16000].headers) > 0, "16kHz failed to decode"
    
    # Print comparison for analysis
    print(f"\n=== 8kHz vs 16kHz Comparison ===")
    print(f"8kHz  confidence: {results[8000].bit_confidence:.1%}")
    print(f"16kHz confidence: {results[16000].bit_confidence:.1%}")
    print(f"8kHz  frame errors: {results[8000].frame_errors}/{results[8000].frame_count}")
    print(f"16kHz frame errors: {results[16000].frame_errors}/{results[16000].frame_count}")
    
    # 8kHz should be within 10% confidence of 16kHz
    confidence_ratio = results[8000].bit_confidence / results[16000].bit_confidence
    print(f"Confidence ratio (8k/16k): {confidence_ratio:.2f}")
    
    # If 8kHz is significantly worse, it's not production-ready
    assert confidence_ratio > 0.85, \
        f"8kHz confidence too low vs 16kHz ({confidence_ratio:.1%})"


def test_8khz_worst_case_scenario(tmp_path: Path) -> None:
    """Combine multiple degradations to simulate worst-case real-world conditions."""
    header = "ZCZC-WXR-TOR-039137+0030-3662322-WTHI/TV-"
    audio_file = tmp_path / "worst_case.wav"
    
    # Worst case: noise + baud error + frequency drift
    _write_same_audio(
        str(audio_file),
        header,
        sample_rate=8000,
        noise_level=2000,  # 10% noise
        scale=0.96,  # 4% slow baud
        frequency_drift=0.02  # 2% frequency drift
    )
    
    result = decode_same_audio(str(audio_file), sample_rate=8000)
    
    # Should still decode even in worst case
    assert len(result.headers) > 0, "Failed in worst-case scenario"
    # But we can accept lower confidence
    assert result.bit_confidence > 0.3, \
        f"Confidence too low in worst case ({result.bit_confidence:.1%})"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
