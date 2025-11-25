#!/usr/bin/env python3
"""
Diagnostic script to check poller configuration and test alert matching
"""
import os
import sys
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import db, LocationSettings
from app_utils.location_settings import sanitize_fips_codes, normalise_upper

def check_config():
    """Check current location configuration."""
    print("=" * 60)
    print("LOCATION CONFIGURATION CHECK")
    print("=" * 60)

    # Get location settings from database
    settings = db.session.query(LocationSettings).order_by(LocationSettings.id).first()

    if not settings:
        print("❌ No location settings found in database")
        return

    print(f"\n📍 Location: {settings.county_name}, {settings.state_code}")
    print(f"🕐 Timezone: {settings.timezone}")

    # Zone codes
    zone_codes = normalise_upper(settings.zone_codes) if settings.zone_codes else []
    print(f"\n🗺️  Zone Codes ({len(zone_codes)}):")
    for code in zone_codes[:10]:  # Show first 10
        print(f"   - {code}")
    if len(zone_codes) > 10:
        print(f"   ... and {len(zone_codes) - 10} more")

    # Storage zone codes
    storage_zones = normalise_upper(getattr(settings, 'storage_zone_codes', [])) if hasattr(settings, 'storage_zone_codes') and getattr(settings, 'storage_zone_codes') else []
    print(f"\n💾 Storage Zone Codes ({len(storage_zones)}):")
    if storage_zones:
        for code in storage_zones[:10]:
            print(f"   - {code}")
        if len(storage_zones) > 10:
            print(f"   ... and {len(storage_zones) - 10} more")
    else:
        print("   (none configured - will only store SAME code matches)")

    # SAME/FIPS codes
    fips_codes, invalid = sanitize_fips_codes(settings.fips_codes if settings.fips_codes else [])
    print(f"\n🔢 SAME/FIPS Codes ({len(fips_codes)}):")
    for code in fips_codes[:10]:
        print(f"   - {code}")
    if len(fips_codes) > 10:
        print(f"   ... and {len(fips_codes) - 10} more")

    # Check environment variables
    print("\n" + "=" * 60)
    print("POLLER CONFIGURATION CHECK")
    print("=" * 60)

    # Check NOAA configuration
    noaa_user_agent = os.getenv('NOAA_USER_AGENT', '').strip()
    print(f"\n🌐 NOAA Weather API:")
    if noaa_user_agent:
        print(f"   ✅ NOAA_USER_AGENT: {noaa_user_agent[:50]}{'...' if len(noaa_user_agent) > 50 else ''}")
    else:
        print(f"   ⚠️  NOAA_USER_AGENT: Not set (NOAA poller may not work)")

    # Check IPAWS configuration
    ipaws_urls = os.getenv('IPAWS_CAP_FEED_URLS', '').strip()
    print(f"\n📡 IPAWS Feed:")
    if ipaws_urls:
        print(f"   ✅ IPAWS_CAP_FEED_URLS: {ipaws_urls[:80]}{'...' if len(ipaws_urls) > 80 else ''}")
    else:
        print(f"   ⚠️  IPAWS_CAP_FEED_URLS: Not set (using defaults)")

    # Check SSL configuration
    ssl_disable = os.getenv('SSL_VERIFY_DISABLE', '').strip().lower() in ('1', 'true', 'yes')
    print(f"\n🔒 SSL Configuration:")
    if ssl_disable:
        print(f"   ⚠️  SSL_VERIFY_DISABLE: {ssl_disable} (certificate verification disabled - insecure!)")
    else:
        print(f"   ✅ SSL verification: Enabled")

    # Test Wind Advisory matching
    print("\n" + "=" * 60)
    print("WIND ADVISORY ALERT TEST")
    print("=" * 60)

    wind_advisory_ugc = ['OHZ016']
    wind_advisory_same = ['039125']

    print(f"\nWind Advisory for Putnam County, OH:")
    print(f"   UGC Codes: {', '.join(wind_advisory_ugc)}")
    print(f"   SAME Codes: {', '.join(wind_advisory_same)}")

    # Check UGC match
    ugc_match = any(code in zone_codes for code in wind_advisory_ugc)
    storage_ugc_match = any(code in storage_zones for code in wind_advisory_ugc)

    print(f"\n📋 UGC Match:")
    if ugc_match:
        print(f"   ✅ OHZ016 found in zone_codes → Alert will be ACCEPTED")
        if storage_ugc_match:
            print(f"   ✅ OHZ016 found in storage_zone_codes → Alert will be STORED + BROADCAST")
        else:
            print(f"   ⚠️  OHZ016 NOT in storage_zone_codes → Alert will be BROADCAST ONLY (no storage/boundaries)")
    else:
        print(f"   ❌ OHZ016 NOT found in zone_codes → Alert will be REJECTED")

    # Check SAME match
    same_match = any(code in fips_codes for code in wind_advisory_same)
    print(f"\n🔢 SAME Match:")
    if same_match:
        print(f"   ✅ 039125 found in fips_codes → Alert will be STORED + BROADCAST")
    else:
        print(f"   ❌ 039125 NOT found in fips_codes")

    # Overall verdict
    print(f"\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)

    if ugc_match or same_match:
        print("✅ Wind Advisory SHOULD be processed")
        if same_match or storage_ugc_match:
            print("✅ Alert will be STORED in database")
        else:
            print("⚠️  Alert will be BROADCAST ONLY (not stored)")
    else:
        print("❌ Wind Advisory will be REJECTED (no match found)")

    if not noaa_user_agent:
        print("\n⚠️  WARNING: NOAA_USER_AGENT not configured!")
        print("   The NOAA poller requires a User-Agent header for API compliance.")
        print("   Configure it in Settings → Alert Feeds → NOAA Weather Alerts")

if __name__ == '__main__':
    check_config()
