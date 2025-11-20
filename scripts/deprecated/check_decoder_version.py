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
Quick script to check if the correlation decoder fix is loaded.
Run this to verify the code version before/after restart.
"""

import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # Import the decoder module
    from app_utils import eas_decode

    # Read the source file to check the flag
    import inspect
    source_file = inspect.getsourcefile(eas_decode.decode_same_audio)

    print("=" * 70)
    print("EAS Decoder Version Check")
    print("=" * 70)
    print()
    print(f"Module loaded from: {source_file}")
    print()

    # Read the source and look for the flag
    with open(source_file, 'r') as f:
        source = f.read()

    if 'USE_CORRELATION_DECODER = False' in source:
        print("✓ CORRECT VERSION LOADED")
        print("  The correlation decoder fix is present.")
        print("  USE_CORRELATION_DECODER = False")
        print()
        print("The decoder should now work correctly.")
    elif 'USE_CORRELATION_DECODER = True' in source:
        print("✗ OLD VERSION (correlation enabled)")
        print("  USE_CORRELATION_DECODER = True")
        print()
        print("This will cause corrupted output.")
    elif 'USE_CORRELATION_DECODER' not in source:
        print("✗ VERY OLD VERSION")
        print("  No USE_CORRELATION_DECODER flag found.")
        print()
        print("This is before the fix was applied.")
    else:
        print("? UNKNOWN VERSION")
        print("  USE_CORRELATION_DECODER flag exists but value unclear.")

    print()
    print("=" * 70)

    # Try to check if it's the in-memory version
    import importlib
    print()
    print("Module info:")
    print(f"  Package: {eas_decode.__package__}")
    if hasattr(eas_decode, '__file__'):
        print(f"  File: {eas_decode.__file__}")
    print()

except ImportError as e:
    print(f"✗ Failed to import module: {e}")
    print()
    print("Make sure you're running from the project directory.")
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()

print()
print("If you see 'OLD VERSION' or 'VERY OLD VERSION', you need to:")
print("  1. Restart your web application server")
print("  2. Run this script again to verify")
print("  3. Then test the upload")
print()
