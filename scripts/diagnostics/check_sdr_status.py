#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""Diagnostic script to check SDR receiver status and audio pipeline."""

import os
import sys

# Add project root to path (navigate up from scripts/diagnostics/ to repository root)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

_STATUS_SYMBOLS = {
    "pass": "✓",   # check mark
    "warn": "⚠",   # warning triangle
    "fail": "✗",   # cross mark
    "info": "ℹ",   # info
}


def main():
    """Run the shared SDR diagnostics checklist and print it.

    This is a thin wrapper around ``app_core.radio.diagnostics_report`` --
    the same function the web UI's "Run Full Diagnostics" button calls
    (``POST /api/radio/diagnostics/run-check``). Keeping the checks in one
    place means the CLI and the web page can never silently drift apart.
    """
    print("=" * 70)
    print("SDR Audio Pipeline Diagnostic Tool")
    print("=" * 70)
    print()

    # Import after path is set
    from app import app
    from app_core.models import RadioReceiver
    from app_core.extensions import get_redis_client
    from app_core.radio.diagnostics_report import overall_status, run_sdr_diagnostics_checks

    with app.app_context():
        receivers = RadioReceiver.query.all()
        try:
            redis_client = get_redis_client()
        except Exception:
            redis_client = None

        checks = run_sdr_diagnostics_checks(receivers, redis_client)

        for check in checks:
            symbol = _STATUS_SYMBOLS.get(check["status"], "?")
            print(f"[{symbol}] {check['label']}: {check['message']}")

        print()
        print("-" * 70)
        print(f"Overall status: {overall_status(checks).upper()}")
        print("-" * 70)
        print()
        print("=" * 70)
        print("Diagnostic complete")
        print("=" * 70)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n✗ Error running diagnostic: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
