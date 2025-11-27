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

"""Unit tests for EAS BLOCKCHANNEL parameter handling.

The BLOCKCHANNEL parameter in CAP/IPAWS alerts specifies which distribution
channels should NOT be used. When "EAS" is in BLOCKCHANNEL, the alert should
not trigger an EAS broadcast.
"""
import logging
from unittest.mock import MagicMock, Mock

import pytest

from app_utils.eas import EASBroadcaster, load_eas_config


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    return logging.getLogger("test_eas_blockchannel")


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    return session


@pytest.fixture
def mock_model_cls():
    """Create a mock EASMessage model class."""
    return MagicMock()


@pytest.fixture
def enabled_config():
    """Return EAS config with broadcasting enabled."""
    config = load_eas_config()
    config['enabled'] = True
    return config


@pytest.fixture
def broadcaster(mock_db_session, mock_model_cls, enabled_config, mock_logger):
    """Create an EASBroadcaster instance for testing."""
    return EASBroadcaster(
        db_session=mock_db_session,
        model_cls=mock_model_cls,
        config=enabled_config,
        logger=mock_logger,
        location_settings={'fips_codes': ['039137']},
    )


class TestBlockchannelExtraction:
    """Tests for _get_blockchannel helper method."""

    def test_extract_blockchannel_from_raw_json_properties_parameters(self, broadcaster):
        """BLOCKCHANNEL in raw_json.properties.parameters should be extracted."""
        alert = Mock()
        alert.raw_json = None
        
        payload = {
            'raw_json': {
                'properties': {
                    'parameters': {
                        'BLOCKCHANNEL': ['EAS', 'NWEM', 'CMAS']
                    }
                }
            }
        }
        
        result = broadcaster._get_blockchannel(alert, payload)
        
        assert 'EAS' in result
        assert 'NWEM' in result
        assert 'CMAS' in result

    def test_extract_blockchannel_from_payload_parameters(self, broadcaster):
        """BLOCKCHANNEL in payload.parameters should be extracted."""
        alert = Mock()
        alert.raw_json = None
        
        payload = {
            'parameters': {
                'BLOCKCHANNEL': ['EAS']
            }
        }
        
        result = broadcaster._get_blockchannel(alert, payload)
        
        assert 'EAS' in result

    def test_extract_blockchannel_from_alert_raw_json(self, broadcaster):
        """BLOCKCHANNEL in alert.raw_json.properties.parameters should be extracted."""
        alert = Mock()
        alert.raw_json = {
            'properties': {
                'parameters': {
                    'BLOCKCHANNEL': ['CMAS']
                }
            }
        }
        
        payload = {}
        
        result = broadcaster._get_blockchannel(alert, payload)
        
        assert 'CMAS' in result

    def test_blockchannel_string_value_handled(self, broadcaster):
        """BLOCKCHANNEL as a single string value should be handled."""
        alert = Mock()
        alert.raw_json = None
        
        payload = {
            'raw_json': {
                'properties': {
                    'parameters': {
                        'BLOCKCHANNEL': 'EAS'  # String instead of list
                    }
                }
            }
        }
        
        result = broadcaster._get_blockchannel(alert, payload)
        
        assert 'EAS' in result

    def test_blockchannel_lowercase_key_handled(self, broadcaster):
        """Lowercase 'blockchannel' key should be handled."""
        alert = Mock()
        alert.raw_json = None
        
        payload = {
            'raw_json': {
                'properties': {
                    'parameters': {
                        'blockchannel': ['EAS']
                    }
                }
            }
        }
        
        result = broadcaster._get_blockchannel(alert, payload)
        
        assert 'EAS' in result

    def test_blockchannel_values_normalized_to_uppercase(self, broadcaster):
        """BLOCKCHANNEL values should be normalized to uppercase."""
        alert = Mock()
        alert.raw_json = None
        
        payload = {
            'raw_json': {
                'properties': {
                    'parameters': {
                        'BLOCKCHANNEL': ['eas', 'Nwem', 'CMAS']
                    }
                }
            }
        }
        
        result = broadcaster._get_blockchannel(alert, payload)
        
        assert 'EAS' in result
        assert 'NWEM' in result
        assert 'CMAS' in result

    def test_empty_blockchannel_returns_empty_set(self, broadcaster):
        """Empty or missing BLOCKCHANNEL should return empty set."""
        alert = Mock()
        alert.raw_json = None
        
        payload = {}
        
        result = broadcaster._get_blockchannel(alert, payload)
        
        assert result == set()

    def test_no_parameters_returns_empty_set(self, broadcaster):
        """Missing parameters section should return empty set."""
        alert = Mock()
        alert.raw_json = {}
        
        payload = {
            'raw_json': {
                'properties': {}
            }
        }
        
        result = broadcaster._get_blockchannel(alert, payload)
        
        assert result == set()


class TestBlockchannelHandling:
    """Tests for BLOCKCHANNEL handling in handle_alert."""

    def test_eas_blocked_when_blockchannel_contains_eas(self, broadcaster):
        """Alert with BLOCKCHANNEL containing EAS should not trigger broadcast."""
        alert = Mock()
        alert.event = "Winter Storm Watch"
        alert.status = "Actual"
        alert.raw_json = {
            'properties': {
                'parameters': {
                    'BLOCKCHANNEL': ['EAS', 'NWEM', 'CMAS']
                }
            }
        }
        
        payload = {
            'message_type': 'Alert',
            'raw_json': alert.raw_json,
        }
        
        result = broadcaster.handle_alert(alert, payload)
        
        assert result['same_triggered'] is False
        assert 'BLOCKCHANNEL' in result['reason'] or 'blocked' in result['reason'].lower()
        assert 'blockchannel' in result
        assert 'EAS' in result['blockchannel']

    def test_eas_allowed_when_blockchannel_does_not_contain_eas(self, broadcaster):
        """Alert with BLOCKCHANNEL not containing EAS should proceed to next check."""
        alert = Mock()
        alert.event = "Tornado Warning"
        # Use Draft status to trigger early exit after BLOCKCHANNEL check passes
        alert.status = "Draft"
        alert.raw_json = {
            'properties': {
                'parameters': {
                    'BLOCKCHANNEL': ['NWEM']  # No EAS in block list
                },
                'geocode': {
                    'SAME': ['039137']
                }
            }
        }
        
        payload = {
            'message_type': 'Alert',
            'raw_json': alert.raw_json,
            'event': 'Tornado Warning',
        }
        
        # Note: This test verifies the BLOCKCHANNEL check passes, not full broadcast
        # The method will proceed past BLOCKCHANNEL check but fail on status check
        result = broadcaster.handle_alert(alert, payload)
        
        # Should be blocked by status (Draft is not valid), NOT by BLOCKCHANNEL
        assert result['same_triggered'] is False
        assert 'BLOCKCHANNEL' not in result.get('reason', '')
        assert 'status' in result.get('reason', '').lower()

    def test_eas_allowed_when_no_blockchannel(self, broadcaster):
        """Alert without BLOCKCHANNEL should proceed to other checks (not BLOCKCHANNEL blocking)."""
        alert = Mock()
        alert.event = "Tornado Warning"
        # Set status to invalid value to trigger early exit after BLOCKCHANNEL check passes
        alert.status = "Draft"  # Invalid status will cause early return
        alert.raw_json = {}
        
        payload = {
            'message_type': 'Alert',
            'raw_json': {
                'properties': {
                    'geocode': {
                        'SAME': ['039137']
                    }
                }
            },
            'event': 'Tornado Warning',
        }
        
        result = broadcaster.handle_alert(alert, payload)
        
        # Should not be blocked by BLOCKCHANNEL (blocked by invalid status instead)
        assert 'BLOCKCHANNEL' not in result.get('reason', '')
        assert 'blockchannel' not in result


class TestRealWorldAlert:
    """Test with real-world alert data from the issue."""

    def test_winter_storm_watch_with_eas_blocked(self, broadcaster):
        """Winter Storm Watch from the issue should be blocked due to BLOCKCHANNEL."""
        # This is the actual alert data from the issue
        alert = Mock()
        alert.event = "Winter Storm Watch"
        alert.status = "Actual"
        alert.identifier = "urn:oid:2.49.0.1.840.0.e1b515bef44e7b2e4cff69cf3c6066df2204282e.002.1"
        alert.raw_json = {
            "properties": {
                "event": "Winter Storm Watch",
                "status": "Actual",
                "messageType": "Update",
                "severity": "Severe",
                "certainty": "Possible",
                "urgency": "Future",
                "parameters": {
                    "AWIPSidentifier": ["WSWIWX"],
                    "BLOCKCHANNEL": ["EAS", "NWEM", "CMAS"],
                    "EAS-ORG": ["WXR"],
                    "NWSheadline": [
                        "WINTER STORM WATCH REMAINS IN EFFECT FROM LATE FRIDAY NIGHT THROUGH SUNDAY AFTERNOON"
                    ],
                    "VTEC": ["/O.CON.KIWX.WS.A.0004.251129T0900Z-251130T1800Z/"],
                    "WMOidentifier": ["WWUS43 KIWX 272002"],
                    "eventEndingTime": ["2025-11-30T13:00:00-05:00"]
                },
                "geocode": {
                    "SAME": [
                        "018039", "018087", "018151", "018113", "018033", "018149",
                        "018131", "018099", "018049", "018183", "018003", "018181",
                        "018017", "018103", "018169", "018069", "018179", "018001",
                        "018053", "018009", "018075", "018091", "018141", "018085",
                        "026023", "026059", "039171", "039051", "039039", "039069",
                        "039125", "039137", "039161"
                    ],
                    "UGC": [
                        "INZ005", "INZ006", "INZ007", "INZ008", "INZ009", "INZ012",
                        "INZ013", "INZ014", "INZ015", "INZ017", "INZ018", "INZ020",
                        "INZ022", "INZ023", "INZ024", "INZ025", "INZ026", "INZ027",
                        "INZ032", "INZ033", "INZ034", "INZ103", "INZ104", "INZ116",
                        "INZ203", "INZ204", "INZ216", "MIZ080", "MIZ081", "OHZ001",
                        "OHZ002", "OHZ004", "OHZ005", "OHZ015", "OHZ016", "OHZ024"
                    ]
                }
            }
        }
        
        payload = {
            'message_type': 'Update',
            'raw_json': alert.raw_json,
            'event': 'Winter Storm Watch',
        }
        
        result = broadcaster.handle_alert(alert, payload)
        
        # Should be blocked due to BLOCKCHANNEL containing EAS
        assert result['same_triggered'] is False
        assert 'BLOCKCHANNEL' in result['reason'] or 'blocked' in result['reason'].lower()
        assert 'blockchannel' in result
        assert set(result['blockchannel']) == {'EAS', 'NWEM', 'CMAS'}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
