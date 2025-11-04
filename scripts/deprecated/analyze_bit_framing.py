#!/usr/bin/env python3
"""Analyze bit-level framing differences between generated and external SAME files."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_utils.eas_decode import decode_same_audio


def analyze_file(path: str, label: str) -> None:
    """Decode and analyze a SAME audio file."""
    print(f"\n{'='*80}")
    print(f"Analyzing: {label}")
    print(f"File: {path}")
    print(f"{'='*80}")

    result = decode_same_audio(path)

    print(f"\nDecoded text: {result.raw_text[:100]}...")
    print(f"Headers found: {len(result.headers)}")
    print(f"Bit count: {result.bit_count}")
    print(f"Frame count: {result.frame_count}")
    print(f"Frame errors: {result.frame_errors}")
    print(f"Bit confidence: {result.bit_confidence:.3f}")

    if result.frame_count > 0:
        error_rate = result.frame_errors / result.frame_count
        print(f"Frame error rate: {error_rate:.1%}")

    print(f"\nHeaders:")
    for i, header in enumerate(result.headers[:3], 1):
        # SAMEHeaderDetails is a dataclass, print the whole header
        print(f"  {i}. {header}")


def main() -> None:
    samples_dir = ROOT_DIR / "samples"

    # Analyze internally generated file
    analyze_file(
        str(samples_dir / "generatedeas.wav"),
        "INTERNALLY GENERATED (our encoder)"
    )

    # Analyze externally generated files
    analyze_file(
        str(samples_dir / "valideas.wav"),
        "EXTERNAL FILE 1 (certified equipment)"
    )

    analyze_file(
        str(samples_dir / "easwithnarration.wav"),
        "EXTERNAL FILE 2 (certified equipment)"
    )

    print(f"\n{'='*80}")
    print("ANALYSIS SUMMARY")
    print(f"{'='*80}")
    print("\nIf internally generated files have significantly better metrics than")
    print("certified external files, it suggests our encoder is NOT following the")
    print("proper protocol and our decoder is tuned to our incorrect format.")


if __name__ == "__main__":
    main()
