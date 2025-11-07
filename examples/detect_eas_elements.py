#!/usr/bin/env python3
"""
Example: Detect All EAS Elements from Audio File

This script demonstrates comprehensive EAS detection including:
- SAME headers
- Alert tones (EBS two-tone and NWS 1050 Hz)
- Narration segments
- End-of-Message markers

Usage:
    python examples/detect_eas_elements.py path/to/eas_audio.wav
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_utils.eas_detection import detect_eas_from_file


def main():
    if len(sys.argv) < 2:
        print("Usage: python detect_eas_elements.py <audio_file>")
        print("\nExample:")
        print("  python detect_eas_elements.py samples/eas_alert.wav")
        sys.exit(1)

    audio_path = sys.argv[1]

    if not os.path.exists(audio_path):
        print(f"Error: File not found: {audio_path}")
        sys.exit(1)

    print(f"Analyzing EAS audio: {audio_path}")
    print("=" * 70)

    try:
        # Perform comprehensive detection
        result = detect_eas_from_file(
            audio_path,
            detect_tones=True,
            detect_narration=True
            # Use default detection parameters (optimized to reduce false positives)
        )

        # Print summary
        print(result.get_summary())
        print("=" * 70)

        # Export results to JSON (optional)
        if '--json' in sys.argv:
            import json
            output_path = audio_path.replace('.wav', '_detection.json')
            with open(output_path, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)
            print(f"\nResults exported to: {output_path}")

        # Detailed analysis
        if '--verbose' in sys.argv:
            print("\n" + "=" * 70)
            print("DETAILED ANALYSIS")
            print("=" * 70)

            if result.same_detected:
                print("\nSAME Header Details:")
                for i, header in enumerate(result.same_headers, 1):
                    print(f"\n  Header {i}:")
                    print(f"    Raw: {header.header}")
                    if header.fields:
                        print(f"    Originator: {header.fields.get('originator', 'N/A')}")
                        print(f"    Event Code: {header.fields.get('event_code', 'N/A')}")
                        print(f"    Event Name: {header.fields.get('event_name', 'N/A')}")
                        locations = header.fields.get('locations', [])
                        if locations:
                            print(f"    Locations: {len(locations)}")
                            for loc in locations[:5]:  # Show first 5
                                desc = loc.get('description', loc.get('code', 'Unknown'))
                                print(f"      - {desc}")

            if result.alert_tones:
                print("\nAlert Tone Details:")
                for i, tone in enumerate(result.alert_tones, 1):
                    tone_name = "EBS Two-Tone (853+960 Hz)" if tone.tone_type == 'ebs' else "NWS Single Tone (1050 Hz)"
                    print(f"\n  Tone {i}: {tone_name}")
                    print(f"    Start: {tone.start_sample / result.sample_rate:.3f}s")
                    print(f"    End: {tone.end_sample / result.sample_rate:.3f}s")
                    print(f"    Duration: {tone.duration_seconds:.3f}s")
                    print(f"    SNR: {tone.snr_db:.1f} dB")
                    print(f"    Confidence: {tone.confidence:.1%}")

            if result.narration_segments:
                print("\nNarration Segment Details:")
                for i, seg in enumerate(result.narration_segments, 1):
                    print(f"\n  Segment {i}:")
                    print(f"    Start: {seg.start_sample / result.sample_rate:.3f}s")
                    print(f"    End: {seg.end_sample / result.sample_rate:.3f}s")
                    print(f"    Duration: {seg.duration_seconds:.3f}s")
                    print(f"    RMS Level: {seg.rms_level:.4f}")
                    print(f"    Contains Speech: {seg.contains_speech}")
                    print(f"    Confidence: {seg.confidence:.1%}")

    except Exception as e:
        print(f"Error analyzing audio: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
