#!/usr/bin/env python3
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
Simple analyzer for malformed.wav that doesn't require full imports.
"""

import wave
import math
from array import array
from collections import Counter

# SAME constants
SAME_MARK_FREQ = 2083.333  # Binary 1
SAME_SPACE_FREQ = 1562.5   # Binary 0
SAME_BAUD = 520.833333     # Baud rate

def read_wav_samples(filename):
    """Read WAV file and return samples as floats."""
    with wave.open(filename, 'rb') as wav:
        params = wav.getparams()
        print(f"WAV Properties:")
        print(f"  Channels: {params.nchannels}")
        print(f"  Sample width: {params.sampwidth} bytes")
        print(f"  Frame rate: {params.framerate} Hz")
        print(f"  Frames: {params.nframes}")
        print(f"  Duration: {params.nframes / params.framerate:.2f} seconds")
        print()

        sample_rate = params.framerate
        pcm = wav.readframes(params.nframes)

    # Convert to signed 16-bit
    pcm_array = array('h')
    pcm_array.frombytes(pcm)

    # Normalize to float [-1, 1]
    samples = [s / 32768.0 for s in pcm_array]

    return samples, sample_rate

def goertzel(samples, sample_rate, target_freq):
    """Compute Goertzel power for target frequency."""
    coeff = 2.0 * math.cos(2.0 * math.pi * target_freq / sample_rate)
    s_prev = 0.0
    s_prev2 = 0.0
    for sample in samples:
        s = sample + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    power = s_prev2 ** 2 + s_prev ** 2 - coeff * s_prev * s_prev2
    return power if power > 0.0 else 0.0

def extract_bits(samples, sample_rate):
    """Extract bits from FSK samples."""
    bits = []
    samples_per_bit = sample_rate / SAME_BAUD
    carry = 0.0
    index = 0

    while index < len(samples):
        total = samples_per_bit + carry
        chunk_length = int(total)
        if chunk_length <= 0:
            chunk_length = 1
        carry = total - chunk_length
        end = index + chunk_length
        if end > len(samples):
            break

        chunk = samples[index:end]
        mark_power = goertzel(chunk, sample_rate, SAME_MARK_FREQ)
        space_power = goertzel(chunk, sample_rate, SAME_SPACE_FREQ)
        bit = 1 if mark_power >= space_power else 0
        bits.append(bit)

        index = end

    return bits

def find_preamble(bits):
    """Find 0xAB preamble patterns."""
    # 0xAB = 10101011 in binary (but we use LSB first with start/stop bits)
    # Frame: [start=0][bit0-6][parity][stop=1]
    # For 0xAB (0x55 in LSB = 10101010 + parity):
    # Let's just search for sequences that look like repeating patterns

    positions = []
    # Look for sequences of 10 bits that repeat
    for i in range(len(bits) - 160):  # 16 preamble bytes * 10 bits each
        # Check if we have a repeating 10-bit pattern
        pattern = bits[i:i+10]
        matches = 0
        for j in range(16):
            offset = i + j * 10
            if offset + 10 > len(bits):
                break
            if bits[offset:offset+10] == pattern:
                matches += 1

        if matches >= 10:  # Found significant repetition
            positions.append(i)
            break  # Just find the first one

    return positions

def bits_to_bytes(bits, start_pos, max_bytes=100):
    """Extract bytes from bits starting at position."""
    bytes_list = []
    i = start_pos

    while i + 10 <= len(bits) and len(bytes_list) < max_bytes:
        # Check for valid frame: start bit (0) and stop bit (1)
        if bits[i] != 0 or bits[i + 9] != 1:
            i += 1
            continue

        # Extract 7 data bits and parity
        data_bits = bits[i + 1:i + 8]
        parity_bit = bits[i + 8]

        # Check even parity
        ones_total = sum(data_bits) + parity_bit
        if ones_total % 2 != 0:
            i += 1
            continue

        # Convert to byte value (LSB first)
        value = 0
        for pos, bit in enumerate(data_bits):
            value |= (bit & 1) << pos

        bytes_list.append(value)
        i += 10

    return bytes_list

def bytes_to_string(byte_values):
    """Convert byte values to string."""
    chars = []
    for val in byte_values:
        if 32 <= val <= 126 or val in (10, 13):
            chars.append(chr(val))
        else:
            chars.append(f'[0x{val:02X}]')
    return ''.join(chars)

# Main analysis
print("="*70)
print("Analyzing samples/malformed.wav")
print("="*70)
print()

samples, sample_rate = read_wav_samples('samples/malformed.wav')

print("Extracting FSK bits...")
bits = extract_bits(samples, sample_rate)
print(f"  Total bits extracted: {len(bits)}")
print(f"  Bit 0/1 distribution: 0={bits.count(0)}, 1={bits.count(1)}")
print()

print("Searching for preamble...")
preamble_positions = find_preamble(bits)
if preamble_positions:
    print(f"  Found preamble at bit positions: {preamble_positions}")

    for pos in preamble_positions[:3]:  # Check first 3
        print(f"\n  Decoding from position {pos}:")
        # Skip preamble (16 bytes * 10 bits = 160 bits)
        message_start = pos + 160
        byte_values = bits_to_bytes(bits, message_start, max_bytes=100)

        if byte_values:
            message = bytes_to_string(byte_values)
            print(f"    Decoded {len(byte_values)} bytes:")
            print(f"    {repr(message)}")

            # Also show without special chars
            clean = ''.join(chr(b) if 32 <= b <= 126 else '?' for b in byte_values)
            print(f"    Clean: {clean}")
else:
    print("  No preamble found!")
    print("\n  Trying raw decoding from beginning...")
    byte_values = bits_to_bytes(bits, 0, max_bytes=100)
    if byte_values:
        message = bytes_to_string(byte_values)
        print(f"    Decoded {len(byte_values)} bytes:")
        print(f"    {repr(message)}")

print()
print("="*70)
