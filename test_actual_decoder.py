#!/usr/bin/env python3
"""
Test the actual decoder functions to see exactly what's happening.
"""

import sys
sys.path.insert(0, '.')

from app_utils.eas_decode import decode_same_audio, _extract_bits, _find_same_bursts, _bits_to_text
import wave

print("=" * 70)
print("Testing Actual Decoder Functions")
print("=" * 70)
print()

# Read the file
with wave.open('samples/malformed.wav', 'rb') as w:
    sample_rate = w.getframerate()
    pcm = w.readframes(w.getnframes())

from array import array
pcm_array = array('h')
pcm_array.frombytes(pcm)
samples = [s / 32768.0 for s in pcm_array]

print(f"Sample rate: {sample_rate} Hz")
print()

# Extract bits using the actual decoder function
print("Step 1: Extracting bits...")
from fractions import Fraction
SAME_BAUD = Fraction(3125, 6)
bits, avg_conf, min_conf = _extract_bits(samples, sample_rate, float(SAME_BAUD))
print(f"  Total bits: {len(bits)}")
print(f"  Avg confidence: {avg_conf:.2%}")
print()

# Find bursts using the actual decoder function
print("Step 2: Finding SAME bursts...")
burst_positions = _find_same_bursts(bits)
print(f"  Found {len(burst_positions)} burst(s)")
for i, pos in enumerate(burst_positions[:5], 1):
    print(f"    Burst {i}: position {pos}")
print()

# Convert bits to text using actual decoder function
print("Step 3: Converting bits to text...")
metadata = _bits_to_text(bits)
print(f"  Raw text: {repr(metadata.get('text', ''))}")
print(f"  Headers: {metadata.get('headers', [])}")
print()

# Run full decoder
print("Step 4: Running full decoder...")
result = decode_same_audio('samples/malformed.wav')
print(f"  Found {len(result.headers)} header(s)")
if result.headers:
    for i, hdr in enumerate(result.headers, 1):
        print(f"    Header {i}: {hdr.header}")
        print(f"    Confidence: {hdr.confidence:.2%}")

    if "03913715" in result.headers[0].header:
        print()
        print("  ❌ STILL CORRUPTED!")
    else:
        print()
        print("  ✅ FIXED!")

print()
print("=" * 70)
