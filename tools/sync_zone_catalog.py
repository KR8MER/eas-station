#!/usr/bin/env python3
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
