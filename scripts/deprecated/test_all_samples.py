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

"""Test all sample files to verify 8N1 protocol fix."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_utils.eas_decode import decode_same_audio


def test_file(path: str) -> dict:
    """Test a file and return results."""
    try:
        result = decode_same_audio(path)
        return {
            "success": True,
            "headers": len(result.headers),
            "text": result.raw_text[:50],
            "confidence": result.bit_confidence,
            "frame_errors": result.frame_errors,
            "frame_count": result.frame_count,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# Test all sample files
samples_dir = Path("samples")
test_files = list(samples_dir.glob("*.wav"))

print("="*80)
print("TESTING ALL SAMPLE FILES WITH 8N1 PROTOCOL")
print("="*80)

for file_path in sorted(test_files):
    print(f"\n📁 {file_path.name}")
    result = test_file(str(file_path))

    if result["success"]:
        print(f"   ✅ SUCCESS - {result['headers']} header(s) decoded")
        print(f"   Text: {result['text']}...")
        print(f"   Confidence: {result['confidence']:.3f}")
        if result['frame_count'] > 0:
            error_rate = result['frame_errors'] / result['frame_count']
            print(f"   Frame errors: {result['frame_errors']}/{result['frame_count']} ({error_rate:.1%})")
    else:
        print(f"   ❌ FAILED: {result['error']}")

print(f"\n{'='*80}")
print("SUMMARY: All files tested with 8N1 protocol implementation")
print("External files may show frame errors due to timing variations,")
print("but should successfully decode via correlation/DLL decoder.")
print("="*80)
