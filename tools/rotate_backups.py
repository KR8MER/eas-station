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

from __future__ import annotations

"""Rotate and clean up old backup snapshots.

This utility manages backup retention by removing old snapshots according to a
configurable retention policy. It keeps a specified number of daily, weekly,
and monthly backups to balance storage usage with recovery options.
"""

import argparse
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List


def parse_backup_timestamp(folder_name: str) -> datetime | None:
    """Extract the timestamp from a backup folder name.

    Args:
        folder_name: Backup folder name like 'backup-20250305-143022' or
                     'backup-20250305-143022-scheduled'

    Returns:
        datetime object if parsing succeeds, None otherwise
    """
    # Strip 'backup-' prefix
    if not folder_name.startswith("backup-"):
        return None

    parts = folder_name[7:].split("-")
    if len(parts) < 2:
        return None

    date_str = parts[0]  # YYYYMMDD
    time_str = parts[1]  # HHMMSS

    try:
        return datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
    except ValueError:
        return None


def get_backup_folders(backup_dir: Path) -> List[tuple[datetime, Path]]:
    """Get all backup folders with their timestamps.

    Args:
        backup_dir: Directory containing backup folders

    Returns:
        List of (timestamp, path) tuples sorted by timestamp (newest first)
    """
    backups = []
    for folder in backup_dir.iterdir():
        if not folder.is_dir():
            continue

        timestamp = parse_backup_timestamp(folder.name)
        if timestamp:
            backups.append((timestamp, folder))

    return sorted(backups, key=lambda x: x[0], reverse=True)


def apply_retention_policy(
    backups: List[tuple[datetime, Path]],
    keep_daily: int,
    keep_weekly: int,
    keep_monthly: int,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Apply retention policy and remove old backups.

    Args:
        backups: List of (timestamp, path) tuples sorted by timestamp
        keep_daily: Number of daily backups to keep
        keep_weekly: Number of weekly backups to keep (Sundays)
        keep_monthly: Number of monthly backups to keep (1st of month)
        dry_run: If True, only print what would be deleted

    Returns:
        Tuple of (kept_count, deleted_count)
    """
    now = datetime.now()
    kept = set()
    deleted = 0

    # Keep the most recent daily backups
    for i, (_, path) in enumerate(backups):
        if i < keep_daily:
            kept.add(path)

    # Keep weekly backups (Sundays)
    weekly_kept = 0
    for timestamp, path in backups:
        if weekly_kept >= keep_weekly:
            break
        if timestamp.weekday() == 6:  # Sunday
            if path not in kept:
                kept.add(path)
                weekly_kept += 1

    # Keep monthly backups (1st of month)
    monthly_kept = 0
    for timestamp, path in backups:
        if monthly_kept >= keep_monthly:
            break
        if timestamp.day == 1:
            if path not in kept:
                kept.add(path)
                monthly_kept += 1

    # Delete backups not in the kept set
    for timestamp, path in backups:
        if path not in kept:
            age_days = (now - timestamp).days
            size_mb = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)

            if dry_run:
                print(f"[DRY RUN] Would delete: {path.name} (age: {age_days} days, size: {size_mb:.1f} MB)")
            else:
                print(f"Deleting: {path.name} (age: {age_days} days, size: {size_mb:.1f} MB)")
                shutil.rmtree(path)
            deleted += 1

    return len(kept), deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate and clean up old EAS Station backup snapshots",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Retention Policy:
  The script keeps backups according to a tiered retention policy:
  - Daily: Most recent N backups (default: 7)
  - Weekly: N most recent Sunday backups (default: 4)
  - Monthly: N most recent backups from the 1st of the month (default: 6)

Examples:
  # Preview what would be deleted (dry run)
  python rotate_backups.py --dry-run

  # Apply default retention policy (7 daily, 4 weekly, 6 monthly)
  python rotate_backups.py

  # Custom retention: keep 14 daily, 8 weekly, 12 monthly
  python rotate_backups.py --keep-daily 14 --keep-weekly 8 --keep-monthly 12

  # Custom backup directory
  python rotate_backups.py --backup-dir /var/backups/eas-station
        """,
    )
    parser.add_argument(
        "--backup-dir",
        default="backups",
        help="Directory containing backup snapshots (default: backups)",
    )
    parser.add_argument(
        "--keep-daily",
        type=int,
        default=7,
        help="Number of daily backups to keep (default: 7)",
    )
    parser.add_argument(
        "--keep-weekly",
        type=int,
        default=4,
        help="Number of weekly backups to keep (default: 4)",
    )
    parser.add_argument(
        "--keep-monthly",
        type=int,
        default=6,
        help="Number of monthly backups to keep (default: 6)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir).resolve()
    if not backup_dir.exists():
        print(f"ERROR: Backup directory does not exist: {backup_dir}")
        sys.exit(1)

    backups = get_backup_folders(backup_dir)
    if not backups:
        print(f"No backup folders found in {backup_dir}")
        return

    print(f"Found {len(backups)} backup(s) in {backup_dir}")
    print(f"Retention policy: {args.keep_daily} daily, {args.keep_weekly} weekly, {args.keep_monthly} monthly")
    if args.dry_run:
        print("[DRY RUN MODE - No files will be deleted]")
    print()

    kept, deleted = apply_retention_policy(
        backups,
        args.keep_daily,
        args.keep_weekly,
        args.keep_monthly,
        args.dry_run,
    )

    print()
    print(f"Summary: Kept {kept} backup(s), {'would delete' if args.dry_run else 'deleted'} {deleted} backup(s)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 - surface meaningful errors to operators
        sys.stderr.write(f"ERROR: {exc}\n")
        sys.exit(1)
