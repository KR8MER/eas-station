#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Discover a marine UGC prefix → SAME ``SS`` digit mapping.

Given a 6-digit numeric SAME code (the kind that appears in EAS audio
SAME headers, e.g. ``077650`` from a Gulf-of-Mexico Special Marine
Warning), scan ``nws_zones`` for zones whose ``zone_number`` matches
the ``CCC`` portion of the SAME code and print each candidate with its
UGC prefix and area name. The operator then picks the row whose area
name matches the alert's described location, and adds
``PREFIX → SS`` to ``MARINE_PREFIX_TO_SAME_STATE`` in
``app_utils/fips_codes.py``.

Workflow:

1. Receive a marine alert that ignores because of no FIPS match.
2. Look at the alert's SAME header (e.g. ``ZCZC-WXR-SMW-077650-…``).
3. Run ``python tools/match_same_to_zone.py 077650``.
4. Cross-reference the printed candidates against the alert's described
   area (e.g. "Pensacola FL to Pascagoula MS"). Confirm which UGC
   prefix matches.
5. Add the verified mapping to ``MARINE_PREFIX_TO_SAME_STATE`` so the
   admin FIPS picker can surface those zones from then on.

Usage::

    python tools/match_same_to_zone.py 077650
    python tools/match_same_to_zone.py 077650 077633 077632 077631
    python tools/match_same_to_zone.py --prefix PS 156  # search by CCC only
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


def _normalise_same(code: str) -> Optional[str]:
    """Return the digit-only form of ``code`` if it's 6 digits, else None."""

    digits = "".join(ch for ch in code if ch.isdigit())
    return digits if len(digits) == 6 else None


def _format_candidate(zone) -> str:
    name = (zone.name or "").strip()
    return f"  prefix={zone.state_code:<3}  zone={zone.zone_code:<6}  {name}"


def _find_candidates_for_ccc(ccc: str, prefix_filter: Optional[str]):
    from app_core.models import NWSZone

    query = NWSZone.query.filter(NWSZone.zone_number == ccc)
    if prefix_filter:
        query = query.filter(NWSZone.state_code == prefix_filter.upper())
    return query.order_by(NWSZone.state_code, NWSZone.zone_code).all()


def _report_for_same(same: str) -> None:
    """Print candidate zone matches for a single 6-digit SAME code."""

    p_digit = same[0]
    ss = same[1:3]
    ccc = same[3:]

    print(f"SAME {same}: P={p_digit}  SS={ss}  CCC={ccc}")

    candidates = _find_candidates_for_ccc(ccc, prefix_filter=None)
    if not candidates:
        print(
            f"  No zones in nws_zones with zone_number={ccc}. "
            "Either no marine catalog is loaded for this region yet, or "
            "the alert may have been mis-decoded."
        )
        return

    print(f"  {len(candidates)} zone(s) match CCC={ccc}:")
    for zone in candidates:
        print(_format_candidate(zone))

    distinct_prefixes = sorted({c.state_code for c in candidates if c.state_code})
    if len(distinct_prefixes) == 1:
        prefix = distinct_prefixes[0]
        print()
        print(
            f"  → Single prefix match: '{prefix}'. If the alert's described "
            f"area matches one of the above, add to "
            f"MARINE_PREFIX_TO_SAME_STATE: '{prefix}': '{ss}'"
        )
    else:
        print()
        print(
            f"  → Multiple prefixes match ({', '.join(distinct_prefixes)}). "
            "Cross-reference the alert's described area against the names "
            f"above; the right prefix maps to SS='{ss}'."
        )


def _report_for_prefix_ccc(prefix: str, ccc_digits: str) -> None:
    """Print zones for a specific prefix + CCC, with no SAME inference."""

    ccc = "".join(ch for ch in ccc_digits if ch.isdigit()).zfill(3)
    candidates = _find_candidates_for_ccc(ccc, prefix_filter=prefix)
    if not candidates:
        print(f"No {prefix.upper()} zones with zone_number={ccc} in nws_zones.")
        return
    print(f"{prefix.upper()} zones with zone_number={ccc}:")
    for zone in candidates:
        print(_format_candidate(zone))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Suggest marine UGC prefix candidates for one or more 6-digit "
            "SAME codes by matching the CCC portion against loaded zones."
        ),
    )
    parser.add_argument(
        "codes",
        nargs="+",
        help="One or more 6-digit SAME codes (e.g. 077650) or, with --prefix, "
        "the CCC portion alone (e.g. 650).",
    )
    parser.add_argument(
        "--prefix",
        help="Restrict the search to one UGC prefix (e.g. GM, PH, PZ) and "
        "treat each positional argument as a bare CCC value.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.environ.setdefault("SKIP_DB_INIT", "1")
    app = create_app()
    with app.app_context():
        if args.prefix:
            for ccc in args.codes:
                _report_for_prefix_ccc(args.prefix, ccc)
                print()
            return

        for raw in args.codes:
            same = _normalise_same(raw)
            if same is None:
                print(
                    f"Skipping {raw!r}: not a 6-digit SAME code. Use --prefix "
                    "if you mean a bare CCC value."
                )
                continue
            _report_for_same(same)
            print()


if __name__ == "__main__":
    main()
