#!/usr/bin/env python3
"""
Backfill missing generated_message_id on ReceivedEASAlert rows.

Background
==========
Until v2.76 the FIPS-filtering callback marked any incoming alert as
``forwarding_decision='forwarded'`` whenever the forward callback returned
without raising — even when the broadcaster suppressed the event, the
broadcaster was disabled, or the broadcast record id was returned in a
shape that ``_extract_message_id`` did not recognise.  The result is a
population of historical rows in ``received_eas_alerts`` with
``forwarding_decision='forwarded'`` and ``generated_message_id IS NULL``
that the detail page renders as "Forwarded but no broadcast record
linked."  Most of those rows DID generate a real broadcast — the link
was just lost.

This script walks the orphaned rows and tries to find the matching
``EASMessage`` by header equivalence: a relayed SAME header is identical
to the incoming raw header except for the trailing callsign field (the
incoming header carries the originating station's callsign, e.g.
``WBKS FM`` or ``DON/JKZ``; the outgoing header carries this station's
callsign).  Stripping the callsign produces a key that is unique per
alert within any reasonable time window.

Usage
=====
    python -m scripts.maintenance.backfill_received_alert_broadcast_links \\
        [--dry-run] [--window-seconds 600]

    --dry-run         Report what would change without writing.
    --window-seconds  Tolerance for matching the broadcast to the receive
                      timestamp.  Defaults to 600s (10 minutes), which
                      comfortably covers TTS generation + audio render +
                      GPIO activation.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from typing import Optional, Tuple

# Make ``app`` importable when running from the repo root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _header_match_key(header: Optional[str]) -> Optional[str]:
    """Return a header stripped of its callsign field for cross-matching.

    A SAME header looks like:
        ZCZC-ORG-EVT-PSSCCC-...+TTTT-JJJHHMM-CCCCCCCC-

    The callsign is the second-to-last ``-`` delimited segment.  Dropping
    that segment yields a key that is identical between the incoming
    (raw) header and the outgoing (relayed) header.
    """
    if not header:
        return None
    header = header.strip()
    if not header.startswith("ZCZC"):
        return None
    parts = header.split("-")
    # A valid SAME header has at least: ZCZC, ORG, EVT, one location/duration
    # group, time, callsign, "" (trailing).  Drop the last two so the key
    # excludes the callsign and the trailing empty segment.
    if len(parts) < 5:
        return None
    return "-".join(parts[:-2])


def _find_candidate(message_cls, received_alert, window: timedelta):
    """Find the EASMessage whose header matches and timestamp is closest."""
    key = _header_match_key(received_alert.raw_same_header)
    if key is None:
        return None, "no usable raw_same_header"

    # Bound the search window around received_at.  Broadcast creation
    # happens after receive, but allow a symmetric window because clock
    # drift between services / DB has been observed in the field.
    received_at = received_alert.received_at
    if received_at is None:
        return None, "received_at is NULL"
    lo = received_at - window
    hi = received_at + window

    candidates = (
        message_cls.query
        .filter(message_cls.created_at >= lo)
        .filter(message_cls.created_at <= hi)
        .all()
    )

    best = None
    best_delta = None
    for msg in candidates:
        if _header_match_key(msg.same_header) != key:
            continue
        delta = abs((msg.created_at - received_at).total_seconds())
        if best_delta is None or delta < best_delta:
            best, best_delta = msg, delta

    if best is None:
        return None, f"no EASMessage with matching header in ±{int(window.total_seconds())}s"
    return best, f"matched (Δ={best_delta:.1f}s)"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show changes without committing.")
    parser.add_argument("--window-seconds", type=int, default=600,
                        help="Match window (default: 600s).")
    args = parser.parse_args(argv)

    # Importing app.py initialises the Flask app and DB engine.  Set the
    # skip flag so the background workers (RWT scheduler, health monitor,
    # auto-backup) don't start for a short-lived maintenance script.
    os.environ.setdefault("SKIP_DB_INIT", "1")

    from app import app
    from app_core.extensions import db
    from app_core.models import EASMessage, ReceivedEASAlert

    window = timedelta(seconds=args.window_seconds)

    with app.app_context():
        orphans = (
            ReceivedEASAlert.query
            .filter(ReceivedEASAlert.forwarding_decision == 'forwarded')
            .filter(ReceivedEASAlert.generated_message_id.is_(None))
            .order_by(ReceivedEASAlert.received_at)
            .all()
        )

        print(f"Found {len(orphans)} 'forwarded' rows missing generated_message_id.")
        if not orphans:
            return 0

        linked = 0
        unmatched = 0
        for alert in orphans:
            msg, reason = _find_candidate(EASMessage, alert, window)
            ts = alert.received_at.isoformat() if alert.received_at else 'n/a'
            if msg is None:
                unmatched += 1
                print(f"  [skip] alert#{alert.id} {ts}: {reason}")
                continue
            linked += 1
            print(
                f"  [link] alert#{alert.id} {ts} → eas_message#{msg.id} "
                f"({reason})"
            )
            if not args.dry_run:
                alert.generated_message_id = msg.id
                db.session.add(alert)

        if args.dry_run:
            print(f"\nDry run: would link {linked}, leave {unmatched} unmatched.")
            db.session.rollback()
        else:
            db.session.commit()
            print(f"\nCommitted: linked {linked}, left {unmatched} unmatched.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
