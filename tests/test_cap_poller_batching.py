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

"""Unit tests for CAP poller NOAA API batching."""
import logging

from poller.cap_poller import CAPPoller


def _make_test_poller() -> CAPPoller:
    """Create a minimal CAPPoller instance for testing batching logic."""
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_cap_poller_batching")
    return poller


def test_batching_combines_zone_codes():
    """Test that multiple zone codes are combined into a single API request."""
    poller = _make_test_poller()
    zone_codes = ["OHZ004", "OHZ005", "OHZ006", "OHC137"]
    
    endpoints = poller._build_batched_noaa_endpoints(zone_codes)
    
    # Should produce a single endpoint with all zones
    assert len(endpoints) == 1
    assert endpoints[0] == "https://api.weather.gov/alerts/active?zone=OHZ004,OHZ005,OHZ006,OHC137"


def test_batching_handles_empty_list():
    """Test that empty zone code list returns empty endpoints."""
    poller = _make_test_poller()
    
    endpoints = poller._build_batched_noaa_endpoints([])
    
    assert endpoints == []


def test_batching_handles_single_zone():
    """Test that single zone code produces single endpoint."""
    poller = _make_test_poller()
    
    endpoints = poller._build_batched_noaa_endpoints(["OHZ016"])
    
    assert len(endpoints) == 1
    assert endpoints[0] == "https://api.weather.gov/alerts/active?zone=OHZ016"


def test_batching_respects_url_length_limit():
    """Test that batching splits zones when URL would exceed limit."""
    poller = _make_test_poller()
    # Create enough zone codes to exceed a small URL limit
    zone_codes = [f"OHZ{i:03d}" for i in range(50)]
    
    # Use a small max_url_length to force batching
    endpoints = poller._build_batched_noaa_endpoints(zone_codes, max_url_length=200)
    
    # Should produce multiple endpoints
    assert len(endpoints) > 1
    # Each endpoint should be under the limit
    for endpoint in endpoints:
        assert len(endpoint) <= 200
    # All zones should be included across all endpoints
    all_zones = []
    for endpoint in endpoints:
        # Extract zones from URL
        zones_part = endpoint.split("?zone=")[1]
        all_zones.extend(zones_part.split(","))
    assert set(all_zones) == set(zone_codes)


def test_batching_with_typical_zone_count():
    """Test batching with a typical configuration (16 zones)."""
    poller = _make_test_poller()
    # Simulate the 16 zones from the issue
    zone_codes = [
        'OHC003', 'OHC039', 'OHC063', 'OHC069', 'OHC125', 'OHC137', 'OHC161', 'OHC173',
        'OHZ004', 'OHZ005', 'OHZ006', 'OHZ015', 'OHZ016', 'OHZ017', 'OHZ024', 'OHZ025'
    ]
    
    endpoints = poller._build_batched_noaa_endpoints(zone_codes)
    
    # With default 2000 char limit, 16 zones should fit in 1 request
    # Base URL is ~45 chars, each zone is 6 chars + 1 comma = ~7 chars each
    # 45 + 16*7 = ~157 chars, well under 2000
    assert len(endpoints) == 1
    # Verify all zones are in the URL
    for code in zone_codes:
        assert code in endpoints[0]


def test_parse_cap_alert_extracts_noaa_id():
    """Test that parse_cap_alert correctly extracts 'id' field from NOAA API responses."""
    poller = _make_test_poller()
    # Simulate NOAA API response structure where identifier is in 'id' not 'identifier'
    alert_data = {
        "properties": {
            "id": "urn:oid:2.49.0.1.840.0.012993182ce4df4373b29b81453102e4bf2023b3.001.1",
            "event": "Wind Advisory",
            "sent": "2025-11-25T13:24:00-05:00",
            "status": "Actual",
            "messageType": "Alert",
            "scope": "Public",
            "category": "Met",
            "urgency": "Expected",
            "severity": "Moderate",
            "certainty": "Likely",
            "areaDesc": "Lucas; Wood",
            "headline": "Wind Advisory",
            "description": "Test description",
            "instruction": "Test instruction",
        },
        "geometry": None,
    }
    
    parsed = poller.parse_cap_alert(alert_data)
    
    assert parsed is not None
    assert parsed['identifier'] == "urn:oid:2.49.0.1.840.0.012993182ce4df4373b29b81453102e4bf2023b3.001.1"
    assert parsed['event'] == "Wind Advisory"


def test_parse_cap_alert_prefers_identifier_over_id():
    """Test that 'identifier' field takes precedence over 'id' if both present."""
    poller = _make_test_poller()
    alert_data = {
        "properties": {
            "identifier": "preferred-identifier",
            "id": "fallback-id",
            "event": "Test Alert",
            "sent": "2025-11-25T13:24:00-05:00",
        },
        "geometry": None,
    }
    
    parsed = poller.parse_cap_alert(alert_data)
    
    assert parsed is not None
    assert parsed['identifier'] == "preferred-identifier"
