#!/usr/bin/env python3
"""
Debug script to see exactly what alerts are being retrieved and why they're filtered out
"""

import requests
import json
import sys
import os

# Add project path
sys.path.insert(0, '/home/pi/noaa_alerts_system')
os.chdir('/home/pi/noaa_alerts_system')

def debug_alert_filtering():
    """Debug what alerts are being filtered and why"""
    
    endpoints = [
        ("OHZ016", "https://api.weather.gov/alerts/active?zone=OHZ016"),
        ("OHC137", "https://api.weather.gov/alerts/active?zone=OHC137"),
        ("Ohio State", "https://api.weather.gov/alerts/active?area=OH")
    ]
    
    print("?? DEBUG: Checking Alert Filtering Logic")
    print("=" * 60)
    
    def is_relevant_alert_debug(alert_data, source):
        """Debug version of relevance check"""
        properties = alert_data.get('properties', {})
        
        print(f"\n?? ALERT from {source}:")
        print(f"  Event: {properties.get('event', 'Unknown')}")
        print(f"  Identifier: {properties.get('identifier', 'None')[:50]}...")
        
        # Check area description
        area_desc = properties.get('areaDesc', '').upper()
        print(f"  Area Description: {area_desc}")
        
        # Check geocode
        geocode = properties.get('geocode', {})
        ugc_codes = geocode.get('UGC', [])
        print(f"  UGC Codes: {ugc_codes}")
        
        # Test our filtering logic
        area_match = any(code in area_desc for code in ['OHZ016', 'OHC137', 'PUTNAM'])
        ugc_match = any(code in str(ugc_code) for ugc_code in ugc_codes for code in ['OHZ016', 'OHC137'])
        
        print(f"  Area Description Match: {area_match}")
        print(f"  UGC Code Match: {ugc_match}")
        
        event = properties.get('event', '').lower()
        is_special_weather = 'special weather statement' in event
        print(f"  Is Special Weather Statement: {is_special_weather}")
        
        if is_special_weather:
            # Additional checks for Special Weather Statements
            description = properties.get('description', '').upper()
            instruction = properties.get('instruction', '').upper()
            
            print(f"  Description contains PUTNAM: {'PUTNAM' in description}")
            print(f"  Description contains OHZ016: {'OHZ016' in description}")
            print(f"  Description contains OHC137: {'OHC137' in description}")
            
            # Check for Ohio-related content
            ohio_in_area = 'OHIO' in area_desc or any('OH' in str(code) for code in ugc_codes)
            print(f"  Ohio-related: {ohio_in_area}")
            
            # Check if it's a broad multi-zone alert
            is_broad_alert = len(ugc_codes) > 10
            print(f"  Broad alert (>10 zones): {is_broad_alert} ({len(ugc_codes)} zones)")
        
        # Final relevance decision
        relevant = area_match or ugc_match
        
        if is_special_weather and not relevant:
            # Special logic for Special Weather Statements
            ohio_related = 'OHIO' in area_desc or any('OH' in str(code) for code in ugc_codes)
            if ohio_related:
                description = (properties.get('description') or '').upper()
                instruction = (properties.get('instruction') or '').upper()
                
                # Look for our area in description
                area_mentioned = any(term in description + instruction for term in ['PUTNAM', 'OHZ016', 'OHC137'])
                broad_alert = len(ugc_codes) > 10
                
                relevant = area_mentioned or broad_alert
                print(f"  Special Weather Statement additional check: {relevant}")
        
        print(f"  ?? FINAL DECISION: {'RELEVANT' if relevant else 'FILTERED OUT'}")
        
        return relevant
    
    total_alerts = 0
    relevant_alerts = 0
    
    for name, url in endpoints:
        print(f"\n{'='*20} {name} {'='*20}")
        
        try:
            response = requests.get(url, timeout=30, headers={
                'User-Agent': 'NOAA-CAP-Alert-Debug/1.0'
            })
            response.raise_for_status()
            
            data = response.json()
            features = data.get('features', [])
            
            print(f"?? Retrieved {len(features)} alerts from {name}")
            total_alerts += len(features)
            
            for i, feature in enumerate(features, 1):
                print(f"\n--- Alert {i} of {len(features)} ---")
                if is_relevant_alert_debug(feature, name):
                    relevant_alerts += 1
                    
        except Exception as e:
            print(f"? Error fetching from {name}: {e}")
    
    print(f"\n{'='*60}")
    print(f"?? SUMMARY")
    print(f"Total alerts found: {total_alerts}")
    print(f"Relevant alerts: {relevant_alerts}")
    print(f"Filtered out: {total_alerts - relevant_alerts}")
    
    if total_alerts > 0 and relevant_alerts == 0:
        print("\n??  ALL ALERTS WERE FILTERED OUT!")
        print("This suggests the filtering logic is too restrictive.")
        print("\nPossible fixes:")
        print("1. The alert area descriptions don't contain expected keywords")
        print("2. UGC codes don't match our expected patterns")
        print("3. Special Weather Statement logic needs adjustment")
    
    return relevant_alerts > 0

def check_current_special_weather_statement():
    """Check the specific Special Weather Statement we know exists"""
    
    print(f"\n???  SPECIFIC CHECK: Special Weather Statement")
    print("=" * 50)
    
    # We know from your paste.txt that there's a Special Weather Statement for OHZ016
    url = "https://api.weather.gov/alerts/active?zone=OHZ016"
    
    try:
        response = requests.get(url, timeout=30, headers={
            'User-Agent': 'NOAA-CAP-Alert-Debug/1.0'
        })
        response.raise_for_status()
        
        data = response.json()
        features = data.get('features', [])
        
        print(f"Found {len(features)} alerts for OHZ016")
        
        for feature in features:
            props = feature.get('properties', {})
            event = props.get('event', '')
            
            if 'special weather statement' in event.lower():
                print(f"\n? Found Special Weather Statement!")
                print(f"   Event: {event}")
                print(f"   ID: {props.get('identifier', 'None')}")
                print(f"   Area: {props.get('areaDesc', 'None')}")
                print(f"   UGC: {props.get('geocode', {}).get('UGC', [])}")
                print(f"   Description: {props.get('description', 'None')[:200]}...")
                
                # Test our filtering on this specific alert
                print(f"\n?? Testing our filter logic on this alert:")
                is_relevant_alert_debug(feature, "OHZ016")
                
                return True
        
        print("? No Special Weather Statement found in current OHZ016 alerts")
        
    except Exception as e:
        print(f"? Error: {e}")
    
    return False

def main():
    """Run comprehensive debug"""
    
    print("?? NOAA CAP Alert Filtering Debug")
    from datetime import datetime
    print(f"?? Debug Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Check general filtering
    found_relevant = debug_alert_filtering()
    
    # Check specific Special Weather Statement
    found_sws = check_current_special_weather_statement()
    
    print(f"\n?? DEBUG RESULTS")
    print("=" * 20)
    if found_relevant:
        print("? Found relevant alerts - poller should be working")
    else:
        print("? No relevant alerts found - filtering is too restrictive")
    
    if found_sws:
        print("? Special Weather Statement detected")
    else:
        print("? Special Weather Statement not detected or expired")
    
    print(f"\n?? NEXT STEPS")
    print("=" * 15)
    if not found_relevant:
        print("1. Review and adjust the is_relevant_alert() function")
        print("2. Consider broader area matching criteria")
        print("3. Add more debug logging to the actual poller")
    else:
        print("1. Filtering logic appears correct")
        print("2. Check database connection and saving logic")
        print("3. Verify alert expiration times")

if __name__ == '__main__':
    main()