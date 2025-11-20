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

"""Test the newly generated file with 8N1 encoding."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_utils.eas_decode import decode_same_audio


def test_file(path: str, label: str) -> None:
    """Test decode of a file."""
    print(f"\n{'='*80}")
    print(f"Testing: {label}")
    print(f"{'='*80}")

    result = decode_same_audio(path)

    print(f"Decoded text: {result.raw_text[:80]}...")
    print(f"Headers found: {len(result.headers)}")
    print(f"Frame count: {result.frame_count}")
    print(f"Frame errors: {result.frame_errors}")
    print(f"Bit confidence: {result.bit_confidence:.3f}")

    if result.frame_count > 0:
        error_rate = result.frame_errors / result.frame_count
        print(f"Frame error rate: {error_rate:.1%}")

        if error_rate == 0:
            print("✅ PERFECT DECODE - NO FRAME ERRORS!")
        elif error_rate < 0.1:
            print("✅ EXCELLENT - Very low frame errors")
        elif error_rate < 0.3:
            print("⚠️  GOOD - Some frame errors but acceptable")
        else:
            print("❌ POOR - High frame error rate")


# Test newly generated file (8N1 format)
test_file("/tmp/SAMPLE-ALERT-0001_20251102081819.wav", "NEWLY GENERATED FILE (8N1 format)")

# Test old generated file (7E1 format)
test_file("samples/generatedeas.wav", "OLD GENERATED FILE (7E1 format)")

# Test external files (should be 8N1 from certified equipment)
test_file("samples/valideas.wav", "EXTERNAL FILE (certified equipment - 8N1)")
test_file("samples/easwithnarration.wav", "EXTERNAL FILE 2 (certified equipment - 8N1)")
