#!/usr/bin/env python3
"""
Fix location_settings FIPS codes in database

This script ensures the location_settings table has proper FIPS codes configured.
Run this if diagnostic logs show: 🔢 SAME/FIPS codes: []
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import db
from app_core.models import LocationSettings
from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS

def fix_location_settings():
    """Fix location settings in database."""
    print("=" * 70)
    print("LOCATION SETTINGS FIX")
    print("=" * 70)

    # Get current settings
    settings = db.session.query(LocationSettings).order_by(LocationSettings.id).first()

    if not settings:
        print("\n❌ No location settings found in database!")
        print("Creating new location settings record...")

        settings = LocationSettings()
        settings.county_name = DEFAULT_LOCATION_SETTINGS['county_name']
        settings.state_code = DEFAULT_LOCATION_SETTINGS['state_code']
        settings.timezone = DEFAULT_LOCATION_SETTINGS['timezone']
        settings.zone_codes = DEFAULT_LOCATION_SETTINGS['zone_codes']
        settings.fips_codes = DEFAULT_LOCATION_SETTINGS['fips_codes']
        settings.storage_zone_codes = DEFAULT_LOCATION_SETTINGS.get('storage_zone_codes', [])
        settings.map_center_lat = DEFAULT_LOCATION_SETTINGS['map_center_lat']
        settings.map_center_lng = DEFAULT_LOCATION_SETTINGS['map_center_lng']
        settings.map_default_zoom = DEFAULT_LOCATION_SETTINGS['map_default_zoom']

        db.session.add(settings)
        db.session.commit()

        print("✅ Created new location settings record")
        print(f"   County: {settings.county_name}, {settings.state_code}")
        print(f"   FIPS codes: {settings.fips_codes}")
        print(f"   Zone codes: {settings.zone_codes}")
        return

    print(f"\n📍 Current Settings:")
    print(f"   County: {settings.county_name}, {settings.state_code}")
    print(f"   FIPS codes: {settings.fips_codes}")
    print(f"   Zone codes: {settings.zone_codes}")

    # Check if FIPS codes need fixing
    fips_codes = settings.fips_codes if settings.fips_codes else []

    if not fips_codes or len(fips_codes) == 0:
        print("\n⚠️  FIPS codes are empty!")
        print(f"   Setting to default: {DEFAULT_LOCATION_SETTINGS['fips_codes']}")

        settings.fips_codes = DEFAULT_LOCATION_SETTINGS['fips_codes']
        db.session.commit()

        print("✅ Fixed FIPS codes")
    else:
        print("\n✅ FIPS codes are already configured")

    # Verify zone codes
    zone_codes = settings.zone_codes if settings.zone_codes else []
    if not zone_codes or len(zone_codes) == 0:
        print("\n⚠️  Zone codes are empty!")
        print(f"   Setting to default: {DEFAULT_LOCATION_SETTINGS['zone_codes']}")

        settings.zone_codes = DEFAULT_LOCATION_SETTINGS['zone_codes']
        db.session.commit()

        print("✅ Fixed zone codes")

    # Verify storage zone codes
    storage_zones = getattr(settings, 'storage_zone_codes', None) if hasattr(settings, 'storage_zone_codes') else None
    if not storage_zones:
        print("\n⚠️  Storage zone codes are empty!")
        print(f"   Setting to default: {DEFAULT_LOCATION_SETTINGS.get('storage_zone_codes', [])}")

        if hasattr(settings, 'storage_zone_codes'):
            settings.storage_zone_codes = DEFAULT_LOCATION_SETTINGS.get('storage_zone_codes', [])
            db.session.commit()
            print("✅ Fixed storage zone codes")
        else:
            print("⚠️  Column storage_zone_codes doesn't exist yet (migration needed)")

    print("\n" + "=" * 70)
    print("FINAL CONFIGURATION")
    print("=" * 70)

    # Reload to get fresh data
    db.session.refresh(settings)

    print(f"\n📍 Location: {settings.county_name}, {settings.state_code}")
    print(f"📋 Zone codes ({len(settings.zone_codes or [])}): {settings.zone_codes}")
    print(f"🔢 FIPS codes ({len(settings.fips_codes or [])}): {settings.fips_codes}")

    if hasattr(settings, 'storage_zone_codes'):
        print(f"💾 Storage zone codes ({len(settings.storage_zone_codes or [])}): {settings.storage_zone_codes}")

    print("\n✅ Location settings are now configured correctly")
    print("   Restart pollers to apply changes:")
    print("   docker-compose restart noaa-poller ipaws-poller")

if __name__ == '__main__':
    try:
        fix_location_settings()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
