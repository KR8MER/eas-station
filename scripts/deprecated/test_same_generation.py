#!/usr/bin/env python3
"""
Diagnostic script to test SAME header generation and decoding.
This will help identify where the corruption is occurring.
"""

import sys
import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_utils.eas import build_same_header
from app_utils.eas_fsk import encode_same_bits, generate_fsk_samples
from app_utils.eas import samples_to_wav_bytes
from app_utils.eas_decode import decode_same_audio

def test_same_generation():
    """Test the complete SAME generation and decoding pipeline."""

    print("=" * 70)
    print("SAME Header Generation & Decoding Test")
    print("=" * 70)
    print()

    # Step 1: Build SAME header
    print("Step 1: Building SAME header...")
    config = {
        'originator': 'EAS',
        'station_id': 'KR8MER'  # Will be padded to 8 chars
    }

    sent_dt = datetime.now(timezone.utc)
    expires_dt = sent_dt + timedelta(minutes=30)

    alert = SimpleNamespace(
        event='Required Weekly Test',
        sent=sent_dt,
        expires=expires_dt
    )

    payload = {
        'sent': sent_dt,
        'expires': expires_dt,
        'raw_json': {
            'properties': {
                'geocode': {
                    'SAME': ['039137', '150000']  # Two location codes
                }
            }
        }
    }

    header, locations, event_code = build_same_header(alert, payload, config)

    print(f"Generated SAME header:")
    print(f"  Header: {header}")
    print(f"  Length: {len(header)} characters")
    print(f"  Locations: {locations}")
    print(f"  Event code: {event_code}")
    print()

    # Step 2: Encode to bits
    print("Step 2: Encoding to FSK bits...")
    bits = encode_same_bits(header, include_preamble=True)
    print(f"  Total bits: {len(bits)}")
    print(f"  First 50 bits: {bits[:50]}")
    print()

    # Step 3: Generate audio samples at 16kHz
    print("Step 3: Generating audio samples at 16kHz...")
    sample_rate = 16000
    from app_utils.eas_fsk import SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ

    samples = generate_fsk_samples(
        bits,
        sample_rate,
        float(SAME_BAUD),
        SAME_MARK_FREQ,
        SAME_SPACE_FREQ,
        0.7 * 32767
    )
    print(f"  Sample rate: {sample_rate} Hz")
    print(f"  Total samples: {len(samples)}")
    print(f"  Duration: {len(samples) / sample_rate:.2f} seconds")
    print()

    # Step 4: Convert to WAV
    print("Step 4: Creating WAV file...")
    wav_bytes = samples_to_wav_bytes(samples, sample_rate)
    print(f"  WAV file size: {len(wav_bytes)} bytes")

    # Save to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        temp_path = f.name
        f.write(wav_bytes)

    print(f"  Saved to: {temp_path}")
    print()

    # Step 5: Read back and verify WAV properties
    print("Step 5: Verifying WAV file properties...")
    import wave
    with wave.open(temp_path, 'rb') as wav:
        params = wav.getparams()
        print(f"  Channels: {params.nchannels}")
        print(f"  Sample width: {params.sampwidth} bytes")
        print(f"  Frame rate: {params.framerate} Hz")
        print(f"  Frames: {params.nframes}")
    print()

    # Step 6: Decode the audio
    print("Step 6: Decoding SAME audio...")
    try:
        result = decode_same_audio(temp_path)
        print(f"  Decoded successfully!")
        print(f"  Raw text: {repr(result.raw_text)}")
        print(f"  Sample rate used: {result.sample_rate} Hz")
        print(f"  Bit confidence: {result.bit_confidence:.2%}")
        print(f"  Min bit confidence: {result.min_bit_confidence:.2%}")
        print()

        if result.headers:
            print(f"  Decoded headers ({len(result.headers)}):")
            for i, hdr in enumerate(result.headers, 1):
                print(f"    {i}. {hdr.header}")
                print(f"       Confidence: {hdr.confidence:.2%}")
        else:
            print(f"  No headers decoded!")
        print()

        # Compare original vs decoded
        print("Step 7: Comparison...")
        print(f"  Original:  {header}")
        if result.headers:
            print(f"  Decoded:   {result.headers[0].header}")
            if header == result.headers[0].header:
                print(f"  ✓ MATCH!")
            else:
                print(f"  ✗ MISMATCH!")
                print()
                print(f"  Character-by-character comparison:")
                max_len = max(len(header), len(result.headers[0].header))
                for i in range(max_len):
                    orig_char = header[i] if i < len(header) else '∅'
                    dec_char = result.headers[0].header[i] if i < len(result.headers[0].header) else '∅'
                    match = '✓' if orig_char == dec_char else '✗'
                    print(f"    {i:3d}: '{orig_char}' vs '{dec_char}' {match}")
        else:
            print(f"  ✗ NO DECODED HEADER TO COMPARE!")

    except Exception as e:
        print(f"  ✗ Decoding failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        try:
            os.unlink(temp_path)
        except:
            pass

    print()
    print("=" * 70)


if __name__ == '__main__':
    test_same_generation()
