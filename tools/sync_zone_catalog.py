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

"""Synchronise the NOAA zone catalog from the bundled DBF file."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app import create_app
from app_core.zones import synchronise_zone_catalog


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load the NOAA public forecast zone catalog into the database.",
    )
    parser.add_argument(
        "--dbf-path",
        type=Path,
        help="Optional path to a DBF file to ingest instead of the bundled asset.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many records would be loaded without modifying the database.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.environ.setdefault("SKIP_DB_INIT", "1")
    app = create_app()
    with app.app_context():
        result = synchronise_zone_catalog(
            source_path=args.dbf_path,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            print(
                f"Discovered {result.total} zone records in {result.source_path.resolve()}"
            )
        else:
            print(
                "Zone catalog synchronised from {path}: {inserted} inserted, {updated} updated, {removed} removed (total {total}).".format(
                    path=result.source_path.resolve(),
                    inserted=result.inserted,
                    updated=result.updated,
                    removed=result.removed,
                    total=result.total,
                )
            )


if __name__ == "__main__":
    main()
