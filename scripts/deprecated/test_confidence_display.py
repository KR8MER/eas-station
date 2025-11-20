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

from __future__ import annotations

"""Test confidence display with visual interpretation."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_utils.eas_decode import decode_same_audio


def get_confidence_level(confidence: float) -> tuple[str, str]:
    """Map confidence value to level and color."""
    if confidence >= 0.8:
        return ("Excellent", "🟢")
    elif confidence >= 0.6:
        return ("Good", "🔵")
    elif confidence >= 0.4:
        return ("Fair", "🟡")
    elif confidence >= 0.2:
        return ("Poor", "🟠")
    else:
        return ("Very Poor", "🔴")


def visualize_confidence(confidence: float, width: int = 50) -> str:
    """Create a text-based visualization of confidence."""
    position = int(confidence * width)
    bar = ""

    for i in range(width):
        # Color zones: Red (0-20%), Yellow (20-40%), Yellow (40-60%), Blue (60-80%), Green (80-100%)
        if i < width * 0.2:
            char = "█" if i < position else "░"
            color = "\033[91m"  # Red
        elif i < width * 0.4:
            char = "█" if i < position else "░"
            color = "\033[93m"  # Yellow
        elif i < width * 0.6:
            char = "█" if i < position else "░"
            color = "\033[93m"  # Yellow
        elif i < width * 0.8:
            char = "█" if i < position else "░"
            color = "\033[94m"  # Blue
        else:
            char = "█" if i < position else "░"
            color = "\033[92m"  # Green

        bar += f"{color}{char}\033[0m"

    return bar


def test_file(path: str, label: str) -> None:
    """Test and visualize confidence for a file."""
    print(f"\n{'='*80}")
    print(f"File: {label}")
    print(f"Path: {path}")
    print(f"{'='*80}")

    try:
        result = decode_same_audio(path)

        confidence = result.bit_confidence
        level, emoji = get_confidence_level(confidence)

        print(f"\n📊 Confidence Analysis:")
        print(f"   Value: {confidence:.3f} ({confidence*100:.1f}%)")
        print(f"   Level: {emoji} {level}")
        print(f"\n   Visual Scale:")
        print(f"   0%  Poor    Fair     Good      Excellent  100%")
        print(f"   |━━━━━━━━━━|━━━━━━━━━━|━━━━━━━━━━|━━━━━━━━━━|")
        print(f"   {visualize_confidence(confidence)}")
        print(f"   {' ' * int(confidence * 50)}▲")
        print(f"   {' ' * int(confidence * 50 - 1)}{confidence*100:.1f}%")

        print(f"\n📋 Decode Summary:")
        print(f"   Headers: {len(result.headers)}")
        print(f"   Frame errors: {result.frame_errors}/{result.frame_count}", end="")
        if result.frame_count > 0:
            error_rate = result.frame_errors / result.frame_count
            print(f" ({error_rate:.1%})")
        else:
            print()

        if result.headers:
            print(f"\n📝 Decoded Headers:")
            for i, header in enumerate(result.headers[:3], 1):
                header_confidence = header.confidence
                header_level, header_emoji = get_confidence_level(header_confidence)
                print(f"   {i}. {header.header}")
                print(f"      Confidence: {header_emoji} {header_confidence*100:.1f}% ({header_level})")

    except Exception as e:
        print(f"\n❌ Error: {e}")


def main() -> None:
    samples_dir = ROOT_DIR / "samples"

    print("\n" + "="*80)
    print("SAME DECODER CONFIDENCE ANALYSIS")
    print("Testing with improved confidence visualization")
    print("="*80)

    # Test newly generated file (8N1 format)
    test_file(
        "/tmp/SAMPLE-ALERT-0001_20251102081819.wav",
        "NEWLY GENERATED (8N1 format)"
    )

    # Test old generated file (7E1 format)
    test_file(
        str(samples_dir / "generatedeas.wav"),
        "OLD INTERNAL (7E1 format - backward compatible)"
    )

    # Test external files (certified 8N1)
    test_file(
        str(samples_dir / "valideas.wav"),
        "EXTERNAL - WJON/TV (certified equipment)"
    )

    test_file(
        str(samples_dir / "easwithnarration.wav"),
        "EXTERNAL - WOLF/IP (certified equipment)"
    )

    print(f"\n{'='*80}")
    print("CONFIDENCE INTERPRETATION GUIDE")
    print("="*80)
    print("🟢 Excellent (80-100%): Signal quality is very strong")
    print("🔵 Good (60-80%):      Signal quality is reliable")
    print("🟡 Fair (40-60%):      Signal quality is acceptable")
    print("🟠 Poor (20-40%):      Signal quality is marginal")
    print("🔴 Very Poor (0-20%):  Signal quality is unreliable")
    print("\nNote: External files may show lower confidence due to timing")
    print("variations from different encoders, but still decode correctly")
    print("via the correlation/DLL decoder.")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
