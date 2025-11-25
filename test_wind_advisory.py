#!/usr/bin/env python3
"""
Test script to diagnose why Wind Advisory isn't being accepted by the poller
"""
import json
import sys
import os

# Wind Advisory alert data from NOAA (user provided)
WIND_ADVISORY = {
    "type": "Feature",
    "geometry": None,
    "properties": {
        "id": "urn:oid:2.49.0.1.840.0.c235ba287f1a114190201e903b6189dacad4a7af.001.1",
        "areaDesc": "Elkhart; Lagrange; Steuben; Noble; De Kalb; Starke; Pulaski; Marshall; Fulton; Whitley; Allen; White; Cass; Miami; Wabash; Huntington; Wells; Adams; Grant; Blackford; Jay; Northern La Porte; Eastern St. Joseph; Northern Kosciusko; Southern La Porte; Western St. Joseph; Southern Kosciusko; Cass; St. Joseph; Branch; Hillsdale; Northern Berrien; Southern Berrien; Williams; Fulton; Defiance; Henry; Paulding; Putnam; Van Wert; Allen",
        "geocode": {
            "SAME": [
                "018039", "018087", "018151", "018113", "018033", "018149", "018131", "018099",
                "018049", "018183", "018003", "018181", "018017", "018103", "018169", "018069",
                "018179", "018001", "018053", "018009", "018075", "018091", "018141", "018085",
                "026027", "026149", "026023", "026059", "026021",
                "039171", "039051", "039039", "039069", "039125", "039137", "039161", "039003"
            ],
            "UGC": [
                "INZ005", "INZ006", "INZ007", "INZ008", "INZ009", "INZ012", "INZ013", "INZ014",
                "INZ015", "INZ017", "INZ018", "INZ020", "INZ022", "INZ023", "INZ024", "INZ025",
                "INZ026", "INZ027", "INZ032", "INZ033", "INZ034", "INZ103", "INZ104", "INZ116",
                "INZ203", "INZ204", "INZ216",
                "MIZ078", "MIZ079", "MIZ080", "MIZ081", "MIZ177", "MIZ277",
                "OHZ001", "OHZ002", "OHZ004", "OHZ005", "OHZ015", "OHZ016", "OHZ024", "OHZ025"
            ]
        },
        "event": "Wind Advisory",
        "severity": "Moderate",
        "certainty": "Likely",
        "urgency": "Expected",
    }
}

def test_matching():
    """Test if the Wind Advisory would match Putnam County configuration."""
    print("=" * 70)
    print("WIND ADVISORY MATCHING TEST")
    print("=" * 70)

    # Expected Putnam County, OH configuration
    expected_zone_codes = {"OHZ016", "OHC137"}
    expected_same_codes = {"039137"}
    expected_storage_zones = {"OHZ003", "OHC137"}

    # Extract from Wind Advisory
    alert_ugc = set(WIND_ADVISORY["properties"]["geocode"]["UGC"])
    alert_same = set(WIND_ADVISORY["properties"]["geocode"]["SAME"])

    print(f"\n📍 Expected Putnam County Configuration:")
    print(f"   Zone Codes: {sorted(expected_zone_codes)}")
    print(f"   SAME Codes: {sorted(expected_same_codes)}")
    print(f"   Storage Zones: {sorted(expected_storage_zones)}")

    print(f"\n🌪️  Wind Advisory Contains:")
    print(f"   {len(alert_ugc)} UGC codes: {sorted([c for c in alert_ugc if c.startswith('OHZ')])}")
    print(f"   {len(alert_same)} SAME codes: {sorted([c for c in alert_same if c.startswith('039')])}")

    # Test SAME matching
    same_matches = expected_same_codes & alert_same
    print(f"\n🔢 SAME Code Matching:")
    if same_matches:
        print(f"   ✅ MATCH: {sorted(same_matches)}")
        print(f"   → Alert should be STORED + BROADCAST")
    else:
        print(f"   ❌ NO MATCH")
        print(f"   → Alert will not match on SAME codes")

    # Test UGC matching
    ugc_matches = expected_zone_codes & alert_ugc
    print(f"\n📋 UGC Code Matching:")
    if ugc_matches:
        print(f"   ✅ MATCH: {sorted(ugc_matches)}")
        storage_matches = expected_storage_zones & alert_ugc
        if storage_matches:
            print(f"   ✅ Storage zone match: {sorted(storage_matches)}")
            print(f"   → Alert should be STORED + BROADCAST")
        else:
            print(f"   ⚠️  Not in storage zones")
            print(f"   → Alert should be BROADCAST ONLY")
    else:
        print(f"   ❌ NO MATCH")
        print(f"   → Alert will not match on UGC codes")

    # Overall verdict
    print(f"\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)

    if same_matches or ugc_matches:
        print("✅ Wind Advisory SHOULD BE ACCEPTED")
        if same_matches or (ugc_matches & expected_storage_zones):
            print("✅ Alert will be STORED in database")
        else:
            print("⚠️  Alert will be BROADCAST ONLY (not stored)")
    else:
        print("❌ Wind Advisory WILL BE REJECTED")
        print("\n⚠️  This indicates a configuration problem!")
        print("   Possible causes:")
        print("   1. Database location_settings differ from defaults")
        print("   2. Zone codes or FIPS codes not properly configured")
        print("   3. Location settings table is empty or corrupted")

    print("\n" + "=" * 70)
    print("DIAGNOSTIC RECOMMENDATIONS")
    print("=" * 70)

    if not (same_matches or ugc_matches):
        print("\n1. Check database location_settings:")
        print("   SELECT county_name, state_code, zone_codes, fips_codes")
        print("   FROM location_settings ORDER BY id LIMIT 1;")

        print("\n2. Verify the poller is loading settings correctly:")
        print("   Look for log messages like:")
        print("   'Zone codes: [...]'")
        print("   'SAME codes: [...]'")

        print("\n3. Check if OHZ016 and 039137 are in the configuration")

    print()

if __name__ == '__main__':
    test_matching()
