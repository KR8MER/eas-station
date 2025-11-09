#!/usr/bin/env python3
"""Diagnostic script to check SDR receiver status and audio pipeline."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """Check SDR receiver and RadioManager status."""
    print("=" * 70)
    print("SDR Audio Pipeline Diagnostic Tool")
    print("=" * 70)
    print()

    # Import after path is set
    from app import app, db
    from app_core.models import RadioReceiver
    from app_core.extensions import get_radio_manager

    with app.app_context():
        print("1. Checking database for configured receivers...")
        print("-" * 70)
        receivers = RadioReceiver.query.all()
        print(f"   Total receivers in database: {len(receivers)}")

        if not receivers:
            print("   ⚠️  WARNING: No receivers configured in database!")
            print("   → Add a receiver at /settings/radio to get started")
            print()
            return

        for r in receivers:
            print(f"\n   Receiver: {r.display_name} ({r.identifier})")
            print(f"     - ID: {r.id}")
            print(f"     - Driver: {r.driver}")
            print(f"     - Frequency: {r.frequency_hz / 1e6:.3f} MHz")
            print(f"     - Enabled: {r.enabled}")
            print(f"     - Auto-start: {r.auto_start}")
            print(f"     - Modulation: {r.modulation_type}")

        print()
        print("2. Checking RadioManager...")
        print("-" * 70)

        radio_manager = get_radio_manager()
        print(f"   RadioManager instance: {radio_manager}")
        print(f"   Registered drivers: {list(radio_manager.available_drivers().keys())}")

        # Check internal receivers dict
        if hasattr(radio_manager, '_receivers'):
            print(f"   Loaded receiver instances: {len(radio_manager._receivers)}")
            if radio_manager._receivers:
                for identifier, receiver_instance in radio_manager._receivers.items():
                    status = receiver_instance.get_status()
                    print(f"\n     {identifier}:")
                    print(f"       - Running: {receiver_instance._running.is_set() if hasattr(receiver_instance, '_running') else 'unknown'}")
                    print(f"       - Locked: {status.locked}")
                    print(f"       - Signal strength: {status.signal_strength}")
                    print(f"       - Last error: {status.last_error or 'None'}")

                    # Check if samples are available
                    if hasattr(receiver_instance, 'get_samples'):
                        samples = receiver_instance.get_samples(num_samples=100)
                        if samples is not None:
                            print(f"       - Sample buffer: ✓ Working ({len(samples)} samples)")
                        else:
                            print(f"       - Sample buffer: ✗ No samples available")
                    else:
                        print(f"       - Sample buffer: ✗ get_samples() not available")
            else:
                print("   ⚠️  WARNING: RadioManager has no loaded receivers!")
                print("   → This means receivers in database haven't been initialized")
                print("   → Try restarting the application")

        print()
        print("3. Summary")
        print("-" * 70)

        enabled_receivers = [r for r in receivers if r.enabled]
        auto_start_receivers = [r for r in enabled_receivers if r.auto_start]

        print(f"   Database receivers: {len(receivers)}")
        print(f"   Enabled receivers: {len(enabled_receivers)}")
        print(f"   Auto-start enabled: {len(auto_start_receivers)}")

        if hasattr(radio_manager, '_receivers'):
            running_receivers = sum(1 for r in radio_manager._receivers.values()
                                   if hasattr(r, '_running') and r._running.is_set())
            locked_receivers = sum(1 for r in radio_manager._receivers.values()
                                  if r.get_status().locked)

            print(f"   RadioManager instances: {len(radio_manager._receivers)}")
            print(f"   Running receivers: {running_receivers}")
            print(f"   Locked receivers: {locked_receivers}")

            print()
            if locked_receivers > 0 and len(radio_manager._receivers) > 0:
                print("   ✓ Status: Audio pipeline appears healthy")
                print("   → Receivers are locked and should be producing data")
                print("   → Check /settings/radio for waterfall display")
            elif len(radio_manager._receivers) == 0:
                print("   ✗ Status: RadioManager not initialized")
                print("   → Restart the web application to load receivers")
            elif running_receivers == 0:
                print("   ✗ Status: Receivers configured but not running")
                print("   → Check receiver configuration and auto_start setting")
            else:
                print("   ⚠️  Status: Receivers running but not locked to signal")
                print("   → Check antenna connection and frequency settings")

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
