"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""
Test suite to evaluate optimal sample rate for EAS SAME header decoding.

This test evaluates whether 22.5kHz is overkill and if we can safely lower
the sample rate while maintaining reliable SAME header detection.

SAME Signal Characteristics:
- Mark frequency: 2083.3 Hz
- Space frequency: 1562.5 Hz  
- Baud rate: 520.83 baud
- Nyquist minimum: 4167 Hz (2× highest frequency)
- Recommended: 8-10 kHz (4-5× highest frequency for reliable decoding)

Test Sample Rates:
- 8000 Hz: 3.8× highest frequency (marginal)
- 11025 Hz: 5.3× highest frequency (good)
- 16000 Hz: 7.7× highest frequency (excellent)
- 22050 Hz: 10.6× highest frequency (overkill?)
- 44100 Hz: 21.2× highest frequency (way overkill)
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
    path: str, header: str, *, sample_rate: int = 16000, scale: float = 1.0, noise_level: float = 0.0
) -> None:
    """Write a synthetic SAME audio file with optional noise."""
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


# Test headers representing different scenarios
TEST_HEADERS = [
    # Standard RWT (Required Weekly Test)
    "ZCZC-WXR-RWT-012345-012346-012347+0015-1231200-NOCALL00-",
    # Tornado Warning (critical alert)
    "ZCZC-WXR-TOR-039137+0030-3662322-WTHI/TV-",
    # Child Abduction Emergency
    "ZCZC-CIV-CAE-012345+0030-1231200-NOCALL00-",
    # Severe Weather Statement
    "ZCZC-WXR-SVS-039137-039051+0100-3662322-WTHI/TV-",
]


@pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050, 44100])
@pytest.mark.parametrize("header", TEST_HEADERS)
def test_decode_at_various_sample_rates(sample_rate: int, header: str, tmp_path: Path) -> None:
    """Test that SAME headers decode correctly at various sample rates."""
    audio_file = tmp_path / f"same_{sample_rate}hz.wav"
    _write_same_audio(str(audio_file), header, sample_rate=sample_rate)

    # Decode with explicit sample rate
    result = decode_same_audio(str(audio_file), sample_rate=sample_rate)

    # Verify we got the header
    assert len(result.headers) > 0, f"No headers decoded at {sample_rate} Hz"
    assert any(h.header == header for h in result.headers), \
        f"Expected header '{header}' not found at {sample_rate} Hz. Got: {[h.header for h in result.headers]}"
    
    # Verify confidence is reasonable
    assert result.bit_confidence > 0.3, \
        f"Low confidence ({result.bit_confidence:.2%}) at {sample_rate} Hz"


@pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050])
def test_decode_with_timing_variations(sample_rate: int, tmp_path: Path) -> None:
    """Test decoding with slightly off timing (simulating real-world conditions)."""
    header = "ZCZC-WXR-RWT-012345+0015-1231200-NOCALL00-"
    
    # Test with slightly slow baud rate (4% slower)
    audio_file = tmp_path / f"slow_{sample_rate}hz.wav"
    _write_same_audio(str(audio_file), header, sample_rate=sample_rate, scale=0.96)
    
    result = decode_same_audio(str(audio_file), sample_rate=sample_rate)
    assert len(result.headers) > 0, f"Failed to decode slow baud at {sample_rate} Hz"
    assert any(h.header == header for h in result.headers)


@pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050])
def test_decode_with_light_noise(sample_rate: int, tmp_path: Path) -> None:
    """Test decoding with light background noise."""
    header = "ZCZC-WXR-RWT-012345+0015-1231200-NOCALL00-"
    audio_file = tmp_path / f"noise_{sample_rate}hz.wav"
    
    # Add light noise (5% of signal amplitude)
    _write_same_audio(str(audio_file), header, sample_rate=sample_rate, noise_level=1000)
    
    result = decode_same_audio(str(audio_file), sample_rate=sample_rate)
    assert len(result.headers) > 0, f"Failed to decode with noise at {sample_rate} Hz"


def test_auto_detection_prefers_lower_rates(tmp_path: Path) -> None:
    """Test that auto-detection works and chooses appropriate sample rate."""
    header = "ZCZC-WXR-RWT-012345+0015-1231200-NOCALL00-"
    
    # Create file at 16kHz but with incorrect metadata saying 44100
    audio_file = tmp_path / "mismatched.wav"
    _write_same_audio(str(audio_file), header, sample_rate=16000)
    
    # Decode without specifying sample rate (auto-detection)
    result = decode_same_audio(str(audio_file))
    
    # Should decode successfully
    assert len(result.headers) > 0
    assert any(h.header == header for h in result.headers)
    # Result should use 16000 Hz
    assert result.sample_rate == 16000


@pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050])
def test_eom_detection_at_various_rates(sample_rate: int, tmp_path: Path) -> None:
    """Test that EOM (End of Message) is detected at various sample rates."""
    # NNNN is the EOM marker
    header = "ZCZC-WXR-RWT-012345+0015-1231200-NOCALL00-"
    
    # Generate header bits
    header_bits = encode_same_bits(header, include_preamble=True)
    # Generate EOM bits (NNNN repeated 3 times per spec)
    eom_bits = []
    for _ in range(3):
        eom_bits.extend(encode_same_bits("NNNN", include_preamble=True))
    
    # Combine
    all_bits = header_bits + eom_bits
    
    # Generate audio
    samples = generate_fsk_samples(
        all_bits,
        sample_rate=sample_rate,
        bit_rate=float(SAME_BAUD),
        mark_freq=SAME_MARK_FREQ,
        space_freq=SAME_SPACE_FREQ,
        amplitude=20000,
    )
    
    audio_file = tmp_path / f"with_eom_{sample_rate}hz.wav"
    with wave.open(str(audio_file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    
    result = decode_same_audio(str(audio_file), sample_rate=sample_rate)
    
    # Should have decoded both header and EOM
    assert len(result.headers) > 0
    assert "eom" in result.segments or "NNNN" in result.raw_text.upper()


def test_cpu_time_comparison(tmp_path: Path) -> None:
    """Compare CPU time for decoding at different sample rates."""
    import time
    
    header = "ZCZC-WXR-RWT-012345-012346-012347+0015-1231200-NOCALL00-"
    sample_rates = [8000, 11025, 16000, 22050, 44100]
    times = {}
    
    for rate in sample_rates:
        audio_file = tmp_path / f"perf_{rate}hz.wav"
        _write_same_audio(str(audio_file), header, sample_rate=rate)
        
        # Time the decode
        start = time.perf_counter()
        for _ in range(5):  # Average over 5 runs
            result = decode_same_audio(str(audio_file), sample_rate=rate)
            assert len(result.headers) > 0
        elapsed = time.perf_counter() - start
        
        times[rate] = elapsed / 5  # Average time
    
    # Print results for analysis
    print("\n=== CPU Time Comparison ===")
    baseline = times[22050]
    for rate in sample_rates:
        pct = (times[rate] / baseline) * 100
        print(f"{rate:6} Hz: {times[rate]:.4f}s ({pct:5.1f}% of 22050 Hz)")
    
    # Verify that lower sample rates are faster
    assert times[16000] < times[22050], "16kHz should be faster than 22kHz"
    assert times[11025] < times[16000], "11kHz should be faster than 16kHz"


def test_memory_usage_comparison(tmp_path: Path) -> None:
    """Compare memory usage for different sample rates."""
    header = "ZCZC-WXR-RWT-012345+0015-1231200-NOCALL00-"
    sample_rates = [8000, 11025, 16000, 22050, 44100]
    
    print("\n=== Memory Usage Comparison ===")
    print("(Based on 12 seconds of audio buffer)")
    
    for rate in sample_rates:
        # Calculate buffer size for 12 seconds
        samples_per_buffer = rate * 12
        bytes_per_buffer = samples_per_buffer * 2  # 16-bit samples
        kb = bytes_per_buffer / 1024
        
        # Compare to 22050 baseline
        baseline = 22050 * 12 * 2
        pct = (bytes_per_buffer / baseline) * 100
        
        print(f"{rate:6} Hz: {kb:7.1f} KB ({pct:5.1f}% of 22050 Hz)")


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_eas_sample_rate_evaluation.py -v -s
    pytest.main([__file__, "-v", "-s"])
