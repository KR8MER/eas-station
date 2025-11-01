#!/usr/bin/env python3
"""
Clean up EAS audio files generated before the parity bit fix (Oct 31, 2025).

This script removes audio files that were generated with the buggy encoder
that used hardcoded parity=0 instead of computed even parity. These files
cannot be decoded correctly by the fixed decoder.

Run this script to clean up:
1. Database records with stored audio data
2. Audio files on disk

After running this script, regenerate your EAS messages using the web interface.
"""

import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Parity fix date
PARITY_FIX_DATE = datetime(2025, 10, 31, 12, 0, 0, tzinfo=timezone.utc)


def cleanup_database():
    """Remove audio data from database for records created before the parity fix."""
    try:
        from app_core.database import get_session
        from app_core.models import ManualEASActivation, EASMessage

        print("Cleaning up database records...")

        with get_session() as session:
            # Clean ManualEASActivation records
            manual_count = session.query(ManualEASActivation).filter(
                ManualEASActivation.created_at < PARITY_FIX_DATE
            ).count()

            if manual_count > 0:
                print(f"Found {manual_count} manual activation(s) created before Oct 31, 2025")
                confirm = input(f"Delete these {manual_count} record(s)? (yes/no): ").strip().lower()

                if confirm == 'yes':
                    deleted = session.query(ManualEASActivation).filter(
                        ManualEASActivation.created_at < PARITY_FIX_DATE
                    ).delete()
                    session.commit()
                    print(f"✓ Deleted {deleted} manual activation record(s)")
                else:
                    print("Skipped manual activations")
            else:
                print("✓ No old manual activation records found")

            # Clean EASMessage records
            msg_count = session.query(EASMessage).filter(
                EASMessage.created_at < PARITY_FIX_DATE
            ).count()

            if msg_count > 0:
                print(f"Found {msg_count} EAS message(s) created before Oct 31, 2025")
                confirm = input(f"Delete these {msg_count} record(s)? (yes/no): ").strip().lower()

                if confirm == 'yes':
                    deleted = session.query(EASMessage).filter(
                        EASMessage.created_at < PARITY_FIX_DATE
                    ).delete()
                    session.commit()
                    print(f"✓ Deleted {deleted} EAS message record(s)")
                else:
                    print("Skipped EAS messages")
            else:
                print("✓ No old EAS message records found")

    except Exception as e:
        print(f"✗ Database cleanup error: {e}")
        print("  (This is expected if the database is not configured)")


def cleanup_disk_files():
    """Remove audio files from disk that were created before the parity fix."""
    from app_utils.eas import load_eas_config

    print("\nCleaning up disk files...")

    config = load_eas_config()
    output_dir = config.get('output_dir', './static/eas_messages')

    if not os.path.exists(output_dir):
        print(f"✓ Output directory does not exist: {output_dir}")
        return

    deleted_count = 0
    kept_count = 0

    for filename in os.listdir(output_dir):
        if filename.startswith('.'):
            continue

        filepath = os.path.join(output_dir, filename)

        if os.path.isfile(filepath):
            file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath), tz=timezone.utc)

            if file_mtime < PARITY_FIX_DATE:
                try:
                    os.remove(filepath)
                    deleted_count += 1
                    print(f"  Deleted: {filename}")
                except Exception as e:
                    print(f"  ✗ Failed to delete {filename}: {e}")
            else:
                kept_count += 1
        elif os.path.isdir(filepath):
            # Check manual directory
            dir_mtime = datetime.fromtimestamp(os.path.getmtime(filepath), tz=timezone.utc)

            if dir_mtime < PARITY_FIX_DATE:
                import shutil
                try:
                    shutil.rmtree(filepath)
                    deleted_count += 1
                    print(f"  Deleted directory: {filename}/")
                except Exception as e:
                    print(f"  ✗ Failed to delete directory {filename}/: {e}")
            else:
                kept_count += 1

    print(f"\n✓ Deleted {deleted_count} file(s)/directory(ies)")
    print(f"✓ Kept {kept_count} file(s)/directory(ies) (created after Oct 31)")


def main():
    print("=" * 70)
    print("EAS Audio Cleanup Script")
    print("=" * 70)
    print()
    print("This script will remove EAS audio files generated before Oct 31, 2025")
    print("due to a parity bit encoding bug that was fixed on that date.")
    print()
    print("Old audio files cannot be decoded correctly and will show malformed")
    print("SAME headers like: ZCZC-EAS-RWT-03913715-3051127-KR8MER@ -")
    print()
    print("After cleanup, regenerate your EAS messages using the web interface.")
    print()

    confirm = input("Continue with cleanup? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("Cleanup cancelled")
        return

    print()
    cleanup_database()
    cleanup_disk_files()

    print()
    print("=" * 70)
    print("Cleanup complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("1. Regenerate any needed EAS messages using the web interface")
    print("2. Test audio generation and decoding")
    print("3. Verify SAME headers are properly formatted")


if __name__ == '__main__':
    main()
