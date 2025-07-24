#!/usr/bin/env python3
"""
Duplicate Alert Cleanup Utility
Finds and removes duplicate alerts based on identifier
"""

import os
import sys
from datetime import datetime
from collections import defaultdict

# Add project root to path
sys.path.insert(0, '/home/pi/noaa_alerts_system')
os.chdir('/home/pi/noaa_alerts_system')

from app import app, db, CAPAlert, Intersection
from sqlalchemy import func


def check_duplicates():
    """Check for duplicate alerts in the database"""
    print("🔍 Checking for duplicate alert identifiers...")

    with app.app_context():
        # Query for duplicate identifiers
        duplicates = db.session.query(
            CAPAlert.identifier,
            func.count(CAPAlert.id).label('count'),
            func.min(CAPAlert.created_at).label('first_created'),
            func.max(CAPAlert.created_at).label('last_created')
        ).group_by(CAPAlert.identifier).having(
            func.count(CAPAlert.id) > 1
        ).all()

        if not duplicates:
            print("✅ No duplicate identifiers found!")
            return []

        print(f"❌ Found {len(duplicates)} identifiers with duplicates:")
        print()

        duplicate_details = []

        for dup in duplicates:
            # Get all alerts with this identifier
            alerts = CAPAlert.query.filter_by(
                identifier=dup.identifier
            ).order_by(CAPAlert.created_at.desc()).all()

            duplicate_details.append({
                'identifier': dup.identifier,
                'count': dup.count,
                'alerts': alerts
            })

            print(f"🔴 Identifier: {dup.identifier[:50]}...")
            print(f"   Count: {dup.count} duplicates")
            print(f"   Event: {alerts[0].event}")
            print(f"   First created: {dup.first_created}")
            print(f"   Last created: {dup.last_created}")

            # Show details of each duplicate
            for i, alert in enumerate(alerts):
                sent_str = alert.sent.strftime('%Y-%m-%d %H:%M UTC') if alert.sent else 'Unknown'
                created_str = alert.created_at.strftime('%Y-%m-%d %H:%M UTC') if alert.created_at else 'Unknown'
                print(f"     #{i + 1} ID:{alert.id} Sent:{sent_str} Created:{created_str}")
            print()

        return duplicate_details


def clean_duplicates(dry_run=True):
    """Remove duplicate alerts, keeping the most recent version"""
    print(f"🧹 {'DRY RUN: ' if dry_run else ''}Cleaning duplicate alerts...")

    with app.app_context():
        duplicates = check_duplicates()

        if not duplicates:
            return

        total_removed = 0
        total_kept = 0

        for dup_info in duplicates:
            identifier = dup_info['identifier']
            alerts = dup_info['alerts']  # Already ordered by created_at desc

            # Keep the first one (most recent), remove the rest
            keep_alert = alerts[0]
            remove_alerts = alerts[1:]

            print(f"📝 Processing {identifier[:50]}...:")
            print(f"   ✅ KEEPING: ID {keep_alert.id} (created: {keep_alert.created_at})")

            for alert in remove_alerts:
                print(f"   ❌ {'WOULD REMOVE' if dry_run else 'REMOVING'}: ID {alert.id} (created: {alert.created_at})")

                if not dry_run:
                    # Check for intersections that would be lost
                    intersection_count = Intersection.query.filter_by(cap_alert_id=alert.id).count()
                    if intersection_count > 0:
                        print(
                            f"      ⚠️  This alert has {intersection_count} boundary intersections that will be deleted")

                    db.session.delete(alert)
                    total_removed += 1

            total_kept += 1
            print()

        if not dry_run:
            try:
                db.session.commit()
                print(f"✅ Successfully removed {total_removed} duplicate alerts")
                print(f"✅ Kept {total_kept} unique alerts")
            except Exception as e:
                db.session.rollback()
                print(f"❌ Error committing changes: {e}")
        else:
            print(f"📊 DRY RUN SUMMARY:")
            print(f"   Would remove: {len([a for d in duplicates for a in d['alerts'][1:]])} alerts")
            print(f"   Would keep: {len(duplicates)} alerts")


def analyze_duplicate_patterns():
    """Analyze patterns in duplicate alerts"""
    print("📊 Analyzing duplicate patterns...")

    with app.app_context():
        duplicates = check_duplicates()

        if not duplicates:
            return

        print(f"\n📈 Duplicate Analysis:")
        print(f"   Total duplicate identifiers: {len(duplicates)}")

        # Count by event type
        event_counts = defaultdict(int)
        time_gaps = []

        for dup_info in duplicates:
            alerts = dup_info['alerts']
            event_counts[alerts[0].event] += 1

            # Calculate time gaps between duplicates
            for i in range(len(alerts) - 1):
                if alerts[i].created_at and alerts[i + 1].created_at:
                    gap = alerts[i].created_at - alerts[i + 1].created_at
                    time_gaps.append(gap.total_seconds())

        print(f"\n🏷️  Most duplicated event types:")
        for event, count in sorted(event_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"   {event}: {count} duplicates")

        if time_gaps:
            avg_gap = sum(time_gaps) / len(time_gaps)
            print(f"\n⏱️  Average time between duplicates: {avg_gap / 60:.1f} minutes")
            print(f"   Shortest gap: {min(time_gaps):.0f} seconds")
            print(f"   Longest gap: {max(time_gaps) / 3600:.1f} hours")


def test_enhanced_poller():
    """Test the enhanced poller's duplicate detection"""
    print("\n🧪 Testing Enhanced Poller Duplicate Detection...")

    try:
        from poller.cap_poller import CAPPoller

        with app.app_context():
            poller = CAPPoller()

            # Check for duplicates using the enhanced method
            duplicates = poller.check_for_duplicate_identifiers()

            if duplicates.get('error'):
                print(f"❌ Error: {duplicates['error']}")
                return

            print(f"📊 Enhanced poller found:")
            print(f"   - Duplicate identifiers: {duplicates['total_duplicates']}")

            if duplicates['total_duplicates'] > 0:
                print(f"   📋 Sample duplicates:")
                for dup in duplicates['duplicates'][:3]:
                    print(f"     - {dup['identifier'][:40]}... ({dup['count']} copies)")

            # Test the cleanup function
            if duplicates['total_duplicates'] > 0:
                print(f"\n🧹 Testing enhanced cleanup (dry run)...")
                cleanup_result = poller.remove_duplicate_alerts(dry_run=True)
                print(f"   📊 Result: {cleanup_result.get('message', 'Unknown')}")

            poller.close()

    except ImportError as e:
        print(f"❌ Could not import enhanced poller: {e}")
    except Exception as e:
        print(f"❌ Error testing enhanced poller: {e}")


def main():
    """Main cleanup function"""
    print("🚨 NOAA CAP Alert Duplicate Cleanup Utility")
    print("=" * 50)

    # Test the enhanced poller first
    test_enhanced_poller()

    # Check current duplicates
    duplicates = check_duplicates()

    if not duplicates:
        print("\n🎉 No duplicates found! Your database is clean.")
        return

    # Analyze patterns
    analyze_duplicate_patterns()

    # Ask user what to do
    print("\n" + "=" * 50)
    print("🤔 What would you like to do?")
    print("1. Run dry run cleanup (show what would be removed)")
    print("2. Actually clean up duplicates (DESTRUCTIVE)")
    print("3. Exit without changes")

    choice = input("\nEnter your choice (1-3): ").strip()

    if choice == "1":
        clean_duplicates(dry_run=True)
    elif choice == "2":
        print("\n⚠️  WARNING: This will permanently delete duplicate alerts!")
        confirm = input("Type 'DELETE DUPLICATES' to confirm: ").strip()

        if confirm == "DELETE DUPLICATES":
            clean_duplicates(dry_run=False)
        else:
            print("❌ Cleanup cancelled - confirmation text didn't match")
    elif choice == "3":
        print("👋 Exiting without changes")
    else:
        print("❌ Invalid choice")


if __name__ == '__main__':
    main()