"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""Tests for /api/gps_status -- the GPS OLED screen's data source.

Calls build_gps_status_payload() directly with a mocked Redis client rather
than going through a Flask test_client(): a full request touches the
before_request DB-health gate, which the shared app/app_client fixtures
can't satisfy against sqlite (see test_support_smoke.py's xfail for the
same underlying JSONB-on-sqlite limitation) -- so route-registration is
checked separately, without a live request.
"""

import json
import logging
from unittest.mock import Mock

from webapp.admin.api import routes_system
from webapp.admin.api.routes_system import build_gps_status_payload

# webapp.admin.api.__init__.register_api_routes() normally attaches this
# logger to the blueprint before any route can fire; outside a full app
# boot (as here) api_bp.logger is unset, so set it the same way.
routes_system.api_bp.logger = logging.getLogger("test.gps_status")


def test_no_redis_client_returns_no_fix_defaults():
    """GPS disabled/Redis entirely unreachable must degrade gracefully."""
    payload = build_gps_status_payload(None)

    assert payload['enabled'] is False
    assert payload['has_fix'] is False
    assert payload['fix_label'] == 'NO FIX'
    assert payload['satellite_snrs'] == []


def test_no_redis_data_returns_no_fix_defaults():
    """gps:status has never been published (GPS disabled/no service)."""
    fake_client = Mock()
    fake_client.get.return_value = None

    payload = build_gps_status_payload(fake_client)

    assert payload['enabled'] is False
    assert payload['fix_label'] == 'NO FIX'


def test_flattens_redis_fix_and_computes_labels():
    """A live 3D fix with satellites in view produces fix_label/fix_summary
    and a descending-sorted, capped satellite_snrs array."""
    gps_payload = {
        'has_fix': True,
        'fix_mode': 3,
        'fix_quality': 1,
        'latitude': 39.9612,
        'longitude': -82.9988,
        'altitude_m': 234.5,
        'speed_knots': 0.2,
        'track_angle': 214.5,
        'satellites': 7,
        'hdop': 0.9,
        'satellites_in_view': [
            {'prn': 1, 'snr': 45},
            {'prn': 2, 'snr': 12},
            {'prn': 3, 'snr': 38.7},
            {'prn': 4, 'snr': None},  # must be dropped, not crash
            {'prn': 5},               # missing snr key entirely
        ],
    }
    fake_client = Mock()
    fake_client.get.return_value = json.dumps(gps_payload)

    payload = build_gps_status_payload(fake_client)

    assert payload['enabled'] is True
    assert payload['has_fix'] is True
    assert payload['fix_label'] == '3D FIX'
    assert payload['satellites'] == 7
    assert payload['satellites_in_view_count'] == 5
    assert payload['fix_summary'] == '3D FIX 7/5'
    # Descending order, non-numeric entries dropped, capped at 8.
    assert payload['satellite_snrs'] == [45, 39, 12]
    assert payload['latitude'] == 39.9612
    assert payload['longitude'] == -82.9988


def test_2d_fix_label():
    fake_client = Mock()
    fake_client.get.return_value = json.dumps({'has_fix': True, 'fix_mode': 2})

    payload = build_gps_status_payload(fake_client)

    assert payload['fix_label'] == '2D FIX'


def test_satellite_snrs_capped_at_eight():
    fake_client = Mock()
    fake_client.get.return_value = json.dumps({
        'satellites_in_view': [{'prn': i, 'snr': 50 - i} for i in range(12)],
    })

    payload = build_gps_status_payload(fake_client)

    assert len(payload['satellite_snrs']) == 8
    assert payload['satellite_snrs'] == sorted(payload['satellite_snrs'], reverse=True)


def test_malformed_redis_json_does_not_raise():
    fake_client = Mock()
    fake_client.get.return_value = "not valid json {{{"

    payload = build_gps_status_payload(fake_client)

    assert payload['enabled'] is False


def test_gps_status_is_registered_as_local_only():
    """Physical location must never be reachable by an anonymous internet caller."""
    import app as appmod

    assert '/api/gps_status' in appmod.LOCAL_API_GET_PATHS
    assert '/api/gps_status' not in appmod.PUBLIC_API_GET_PATHS
