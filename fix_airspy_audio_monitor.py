#!/usr/bin/env python3
"""
Fix Airspy R2 Audio Monitor Configuration

This script fixes all issues preventing Airspy R2 audio monitors from working:
1. Sets valid sample rates (2.5MHz or 10MHz - only rates Airspy supports)
2. Enables audio_output and sets proper modulation
3. Ensures audio_sample_rate is set correctly
4. Recreates audio monitor sources with correct redis_sdr configuration
"""

import os
import sys

# Setup path to import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    print("=" * 70)
    print("AIRSPY R2 AUDIO MONITOR FIX SCRIPT")
    print("=" * 70)
    print()

    # Import Flask app and database
    from app import create_app
    from app_core.extensions import db
    from app_core.models import RadioReceiver, AudioSourceConfigDB

    app = create_app()

    with app.app_context():
        # Find all Airspy receivers
        airspy_receivers = RadioReceiver.query.filter_by(driver='airspy').all()

        if not airspy_receivers:
            print("❌ No Airspy receivers found in database!")
            print("   Please add an Airspy receiver in the web UI first.")
            return 1

        print(f"Found {len(airspy_receivers)} Airspy receiver(s):\n")

        for receiver in airspy_receivers:
            print(f"📻 Receiver: {receiver.display_name} ({receiver.identifier})")
            print(f"   Frequency: {receiver.frequency_hz / 1e6:.3f} MHz")
            print(f"   Current IQ sample rate: {receiver.sample_rate}")
            print(f"   Current audio sample rate: {receiver.audio_sample_rate}")
            print(f"   Modulation: {receiver.modulation_type}")
            print(f"   Audio output: {receiver.audio_output}")
            print(f"   Enabled: {receiver.enabled}")
            print()

            changes_made = False

            # Fix 1: Ensure valid IQ sample rate (2.5MHz or 10MHz)
            VALID_RATES = {2500000, 10000000}
            if receiver.sample_rate not in VALID_RATES:
                old_rate = receiver.sample_rate
                # Default to 2.5MHz for better resolution
                receiver.sample_rate = 2500000
                print(f"   ✅ Fixed IQ sample rate: {old_rate} → {receiver.sample_rate} (2.5 MHz)")
                changes_made = True
            else:
                print(f"   ✓ IQ sample rate is valid: {receiver.sample_rate / 1e6:.1f} MHz")

            # Fix 2: Set audio sample rate (for demodulated audio output)
            # Use 32kHz for NFM (NOAA weather), 48kHz for WFM (FM broadcast)
            if receiver.audio_sample_rate is None:
                # Default to 32kHz for narrow FM
                receiver.audio_sample_rate = 32000
                print(f"   ✅ Set audio sample rate: {receiver.audio_sample_rate}")
                changes_made = True
            else:
                print(f"   ✓ Audio sample rate is set: {receiver.audio_sample_rate}")

            # Fix 3: Set modulation type
            # NFM for NOAA weather radio, WFM for FM broadcast
            if not receiver.modulation_type or receiver.modulation_type == 'IQ':
                # Default to NFM (narrow FM) - good for NOAA weather radio
                receiver.modulation_type = 'NFM'
                print(f"   ✅ Set modulation type: {receiver.modulation_type}")
                changes_made = True
            else:
                print(f"   ✓ Modulation type is set: {receiver.modulation_type}")

            # Fix 4: Enable audio output
            if not receiver.audio_output:
                receiver.audio_output = True
                print(f"   ✅ Enabled audio output")
                changes_made = True
            else:
                print(f"   ✓ Audio output is enabled")

            # Fix 5: Enable receiver and auto-start
            if not receiver.enabled:
                receiver.enabled = True
                print(f"   ✅ Enabled receiver")
                changes_made = True
            else:
                print(f"   ✓ Receiver is enabled")

            if not receiver.auto_start:
                receiver.auto_start = True
                print(f"   ✅ Enabled auto-start")
                changes_made = True
            else:
                print(f"   ✓ Auto-start is enabled")

            if changes_made:
                db.session.commit()
                print(f"\n   💾 Saved receiver configuration changes")
            else:
                print(f"\n   ℹ️  No receiver configuration changes needed")

            # Fix 6: Recreate audio monitor source
            print(f"\n   🔧 Recreating audio monitor source...")
            from webapp.admin.audio_ingest import ensure_sdr_audio_monitor_source

            try:
                result = ensure_sdr_audio_monitor_source(
                    receiver,
                    start_immediately=True,
                    commit=True
                )

                print(f"      Source name: {result['source_name']}")
                print(f"      Created: {result['created']}")
                print(f"      Updated: {result['updated']}")
                print(f"      Started: {result['started']}")

                if result['started']:
                    print(f"   ✅ Audio monitor should now be starting!")
                else:
                    print(f"   ⚠️  Audio monitor was configured but may not have started.")
                    print(f"      Check that audio-service is running:")
                    print(f"      docker ps | grep audio-service")
                    print(f"      docker logs audio-service --tail 50")

            except Exception as e:
                print(f"   ❌ Error creating audio monitor: {e}")
                import traceback
                traceback.print_exc()

            print()
            print("-" * 70)
            print()

        # Summary
        print("\n" + "=" * 70)
        print("NEXT STEPS:")
        print("=" * 70)
        print()
        print("1. Check that sdr-service is running and has started the Airspy:")
        print("   docker logs sdr-service --tail 50 | grep -i airspy")
        print()
        print("2. Check that IQ samples are being published to Redis:")
        print("   docker exec -it redis redis-cli")
        print("   PSUBSCRIBE sdr:samples:*")
        print("   (You should see messages being published)")
        print()
        print("3. Check that audio-service received the source_add command:")
        print("   docker logs audio-service --tail 50 | grep -i redis_sdr")
        print()
        print("4. Check the audio monitor status in the web UI:")
        print("   Navigate to Settings → Radio")
        print("   Look for 'Audio monitor is running' under your Airspy receiver")
        print()
        print("5. If still not working, restart the audio service:")
        print("   docker restart audio-service")
        print()

        return 0

if __name__ == '__main__':
    sys.exit(main())
