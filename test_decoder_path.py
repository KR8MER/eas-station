#!/usr/bin/env python3
"""Check which decoder path is being used for each file."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_utils import eas_decode

# Monkey patch to trace which decoder is used
original_decode = eas_decode.decode_same_audio

def traced_decode(path: str, **kwargs):
    print(f"\n>>> Decoding: {Path(path).name}")
    result = original_decode(path, **kwargs)
    print(f">>> Decoder used: {'Correlation/DLL' if hasattr(result, '_correlation_used') else 'Goertzel'}")
    return result

eas_decode.decode_same_audio = traced_decode

from app_utils.eas_decode import decode_same_audio


# Test all files
files = [
    ("/tmp/SAMPLE-ALERT-0001_20251102081819.wav", "NEW (8N1)"),
    ("samples/generatedeas.wav", "OLD (7E1)"),
    ("samples/valideas.wav", "EXTERNAL 1"),
    ("samples/easwithnarration.wav", "EXTERNAL 2"),
]

for path, label in files:
    result = decode_same_audio(path)
    print(f"{label}: {result.frame_errors}/{result.frame_count} errors ({result.frame_errors/result.frame_count*100:.1f}%)")
