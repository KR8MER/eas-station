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

Tails /var/log/nginx/eas-station-access.log for perimeter-defense events
(scanner-bait blocks, bad-actor-blocklist blocks, rate limiting) and writes
new ones to the security_perimeter_events table, powering the Security
Center "Edge Defense" tab. Run every 2 minutes by
security-perimeter-ingest.timer (see systemd/); safe to run by hand.

SKIP_DB_INIT is set before importing app.py so this doesn't also spin up
every background worker (schedulers, pollers, etc.) just to do one tail-
and-insert pass -- see app.py's own comment on that flag.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SKIP_DB_INIT"] = "1"

from app import create_app  # noqa: E402
from app_core.analytics.security_blocks import ingest_new_events  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        count = ingest_new_events()
        print(f"ingest_security_perimeter_log: {count} new event(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
