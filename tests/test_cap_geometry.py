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

from __future__ import annotations

"""Unit tests for poller/cap_geometry.py.

Extracted out of CAPPoller (Large File Refactor Plan Phase 4c continuation)
as a collaborator: these 12 methods (plus the module-level
``_serialize_alert_for_sig`` helper) only ever touched ``self.logger`` --
never ``self.db_session`` or the poller's own zone/SAME-code
configuration -- so they moved as free functions taking ``logger``
explicitly. This file supersedes
``tests/test_cap_geometry_characterization.py``, which pinned the same
behaviors against the pre-extraction bound methods; all 59 cases here are
verified equivalent (2 mutation spot-checks against the original bound
methods also confirmed these are load-bearing, not vacuous).

Covers: _extract_cap_resources, _extract_area_details, _parse_cap_polygon,
_parse_cap_circle, _approximate_circle_polygon, _message_type_priority,
_alert_sort_key, _should_replace_alert, _count_vertices, parse_cap_alert.
(_convert_cap_alert and _parse_ipaws_xml_feed already have coverage in
tests/test_ipaws_event_code_extraction.py and
tests/test_cap_poller_per_item_isolation.py.)
"""

import logging
from datetime import datetime, timezone

import pytest

from poller.cap_geometry import (
    _alert_sort_key,
    _approximate_circle_polygon,
    _count_vertices,
    _extract_area_details,
    _extract_cap_resources,
    _message_type_priority,
    _parse_cap_circle,
    _parse_cap_polygon,
    _should_replace_alert,
    parse_cap_alert,
)
from app_utils.optimized_parsing import parse_xml_string

_LOGGER = logging.getLogger("test_cap_geometry")

_NS = {
    'feed': 'http://gov.fema.ipaws.services/feed',
    'cap': 'urn:oasis:names:tc:emergency:cap:1.2',
}


def _parse_info(xml_body: str):
    wrapped = (
        '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
        '<identifier>test-1</identifier><sender>test@example.gov</sender>'
        '<sent>2026-08-12T17:36:37-00:00</sent><status>Actual</status>'
        '<msgType>Alert</msgType><scope>Public</scope>'
        f'{xml_body}'
        '</alert>'
    )
    root = parse_xml_string(wrapped)
    return root.find('cap:info', _NS)


# ---------------------------------------------------------------------------
# _extract_cap_resources
# ---------------------------------------------------------------------------

class TestExtractCapResources:
    def test_none_info_elem_returns_empty_list(self):
        assert _extract_cap_resources(None, _NS, _LOGGER) == []

    def test_no_resource_elements_returns_empty_list(self):
        info = _parse_info('<info><event>Test</event></info>')
        assert _extract_cap_resources(info, _NS, _LOGGER) == []

    def test_full_resource_extracted(self):
        xml_body = (
            '<info><resource>'
            '<resourceDesc>Audio Message</resourceDesc>'
            '<mimeType>audio/mpeg</mimeType>'
            '<uri>https://example.gov/alert.mp3</uri>'
            '<digest>abc123</digest>'
            '<size>4096</size>'
            '</resource></info>'
        )
        info = _parse_info(xml_body)
        resources = _extract_cap_resources(info, _NS, _LOGGER)
        assert resources == [{
            'resourceDesc': 'Audio Message',
            'mimeType': 'audio/mpeg',
            'uri': 'https://example.gov/alert.mp3',
            'digest': 'abc123',
            'size': '4096',
        }]

    def test_resource_without_desc_or_uri_is_skipped(self):
        xml_body = '<info><resource><mimeType>audio/mpeg</mimeType></resource></info>'
        info = _parse_info(xml_body)
        assert _extract_cap_resources(info, _NS, _LOGGER) == []

    def test_derefuri_alone_is_kept(self):
        xml_body = '<info><resource><derefUri>base64data==</derefUri></resource></info>'
        info = _parse_info(xml_body)
        resources = _extract_cap_resources(info, _NS, _LOGGER)
        assert resources == [{'derefUri': 'base64data=='}]


# ---------------------------------------------------------------------------
# _parse_cap_polygon
# ---------------------------------------------------------------------------

class TestParseCapPolygon:
    def test_none_text_returns_none(self):
        assert _parse_cap_polygon(None, _LOGGER) is None

    def test_too_few_points_returns_none(self):
        assert _parse_cap_polygon("40.0,-80.0 41.0,-81.0", _LOGGER) is None

    def test_valid_triangle_closes_the_ring(self):
        text = "40.0,-80.0 41.0,-81.0 42.0,-82.0"
        coords = _parse_cap_polygon(text, _LOGGER)
        assert coords[0] == coords[-1]
        assert coords[0] == [-80.0, 40.0]
        assert len(coords) == 4

    def test_already_closed_ring_not_duplicated(self):
        text = "40.0,-80.0 41.0,-81.0 42.0,-82.0 40.0,-80.0"
        coords = _parse_cap_polygon(text, _LOGGER)
        assert len(coords) == 4

    def test_invalid_latitude_skipped(self):
        text = "95.0,-80.0 41.0,-81.0 42.0,-82.0"
        coords = _parse_cap_polygon(text, _LOGGER)
        assert coords is None  # only 2 valid points remain after dropping the bad one

    def test_malformed_pair_skipped_silently(self):
        text = "40.0,-80.0 not-a-pair 41.0,-81.0 42.0,-82.0"
        coords = _parse_cap_polygon(text, _LOGGER)
        assert len(coords) == 4  # 3 valid points + closing point


# ---------------------------------------------------------------------------
# _parse_cap_circle / _approximate_circle_polygon
# ---------------------------------------------------------------------------

class TestParseCapCircle:
    def test_none_text_returns_none(self):
        assert _parse_cap_circle(None, _LOGGER) is None

    def test_empty_text_returns_none(self):
        assert _parse_cap_circle("   ", _LOGGER) is None

    def test_missing_comma_returns_none(self):
        assert _parse_cap_circle("40.0 10", _LOGGER) is None

    def test_zero_radius_returns_none(self):
        assert _parse_cap_circle("40.0,-80.0 0", _LOGGER) is None

    def test_negative_radius_returns_none(self):
        assert _parse_cap_circle("40.0,-80.0 -5", _LOGGER) is None

    def test_excessive_radius_returns_none(self):
        assert _parse_cap_circle("40.0,-80.0 20001", _LOGGER) is None

    def test_valid_circle_produces_closed_ring(self):
        coords = _parse_cap_circle("40.0,-80.0 10", _LOGGER, points=8)
        assert coords is not None
        assert coords[0] == coords[-1]
        assert len(coords) == 9  # 8 points + closing point

    def test_default_points_is_36(self):
        coords = _parse_cap_circle("40.0,-80.0 10", _LOGGER)
        assert len(coords) == 37  # 36 + closing point


class TestApproximateCirclePolygon:
    def test_invalid_latitude_raises(self):
        with pytest.raises(ValueError):
            _approximate_circle_polygon(95.0, -80.0, 10.0, 36, _LOGGER)

    def test_invalid_longitude_raises(self):
        with pytest.raises(ValueError):
            _approximate_circle_polygon(40.0, -200.0, 10.0, 36, _LOGGER)

    def test_zero_radius_raises(self):
        with pytest.raises(ValueError):
            _approximate_circle_polygon(40.0, -80.0, 0.0, 36, _LOGGER)

    def test_too_few_points_raises(self):
        with pytest.raises(ValueError):
            _approximate_circle_polygon(40.0, -80.0, 10.0, 2, _LOGGER)

    def test_normal_circle_has_closed_ring(self):
        coords = _approximate_circle_polygon(40.0, -80.0, 10.0, 12, _LOGGER)
        assert coords[0] == coords[-1]
        assert len(coords) == 13

    def test_near_pole_uses_rectangular_fallback(self):
        coords = _approximate_circle_polygon(89.8, 0.0, 50.0, 36, _LOGGER)
        assert len(coords) == 5  # square fallback: 4 corners + closing point

    def test_all_coordinates_within_valid_ranges(self):
        coords = _approximate_circle_polygon(35.0, -90.0, 100.0, 36, _LOGGER)
        for lon, lat in coords:
            assert -180 <= lon <= 180
            assert -90 <= lat <= 90


# ---------------------------------------------------------------------------
# _extract_area_details
# ---------------------------------------------------------------------------

class TestExtractAreaDetails:
    def test_none_info_elem(self):
        geometry, area_desc, geocodes = _extract_area_details(None, _NS, _LOGGER)
        assert geometry is None
        assert area_desc == ''
        assert geocodes == {}

    def test_single_polygon_area(self):
        xml_body = (
            '<info><area><areaDesc>Test County</areaDesc>'
            '<polygon>40.0,-80.0 41.0,-81.0 42.0,-82.0</polygon>'
            '<geocode><valueName>SAME</valueName><value>039137</value></geocode>'
            '</area></info>'
        )
        info = _parse_info(xml_body)
        geometry, area_desc, geocodes = _extract_area_details(info, _NS, _LOGGER)
        assert geometry['type'] == 'Polygon'
        assert area_desc == 'Test County'
        assert geocodes == {'SAME': ['039137']}

    def test_multiple_polygons_produce_multipolygon(self):
        xml_body = (
            '<info>'
            '<area><areaDesc>A</areaDesc><polygon>40.0,-80.0 41.0,-81.0 42.0,-82.0</polygon></area>'
            '<area><areaDesc>B</areaDesc><polygon>50.0,-90.0 51.0,-91.0 52.0,-92.0</polygon></area>'
            '</info>'
        )
        info = _parse_info(xml_body)
        geometry, area_desc, geocodes = _extract_area_details(info, _NS, _LOGGER)
        assert geometry['type'] == 'MultiPolygon'
        assert area_desc == 'A; B'

    def test_duplicate_area_desc_not_repeated(self):
        xml_body = (
            '<info>'
            '<area><areaDesc>Same County</areaDesc></area>'
            '<area><areaDesc>Same County</areaDesc></area>'
            '</info>'
        )
        info = _parse_info(xml_body)
        _, area_desc, _ = _extract_area_details(info, _NS, _LOGGER)
        assert area_desc == 'Same County'

    def test_multiple_geocodes_same_valuename_accumulate(self):
        xml_body = (
            '<info><area>'
            '<geocode><valueName>UGC</valueName><value>OHC001</value></geocode>'
            '<geocode><valueName>UGC</valueName><value>OHC003</value></geocode>'
            '</area></info>'
        )
        info = _parse_info(xml_body)
        _, _, geocodes = _extract_area_details(info, _NS, _LOGGER)
        assert geocodes == {'UGC': ['OHC001', 'OHC003']}


# ---------------------------------------------------------------------------
# _message_type_priority / _alert_sort_key / _should_replace_alert
# ---------------------------------------------------------------------------

class TestMessageTypePriority:
    @pytest.mark.parametrize("message_type,expected", [
        ('CANCEL', 4),
        ('UPDATE', 3),
        ('ALERT', 2),
        ('ACK', 1),
        ('cancel', 4),  # case-insensitive
        (' Update ', 3),  # whitespace-tolerant
        ('UNKNOWN', 0),
        (None, 0),
        ('', 0),
    ])
    def test_priority_mapping(self, message_type, expected):
        assert _message_type_priority(message_type) == expected


class TestAlertSortKey:
    def test_missing_sent_falls_back_to_datetime_min(self):
        sent_dt, priority = _alert_sort_key({'properties': {}})
        assert sent_dt == datetime.min.replace(tzinfo=timezone.utc)
        assert priority == 0

    def test_valid_sent_and_priority(self):
        alert = {'properties': {'sent': '2026-08-12T17:36:37-00:00', 'messageType': 'UPDATE'}}
        sent_dt, priority = _alert_sort_key(alert)
        assert sent_dt.year == 2026
        assert priority == 3


class TestShouldReplaceAlert:
    def _alert(self, message_type, sent, geometry=None):
        return {
            'properties': {'messageType': message_type, 'sent': sent},
            'geometry': geometry,
        }

    def test_cancel_always_beats_non_cancel(self):
        existing = self._alert('ALERT', '2026-08-12T18:00:00-00:00')
        candidate = self._alert('CANCEL', '2026-08-12T10:00:00-00:00')  # earlier but CANCEL
        assert _should_replace_alert(existing, candidate) is True

    def test_non_cancel_never_beats_existing_cancel(self):
        existing = self._alert('CANCEL', '2026-08-12T10:00:00-00:00')
        candidate = self._alert('UPDATE', '2026-08-12T18:00:00-00:00')  # later but not CANCEL
        assert _should_replace_alert(existing, candidate) is False

    def test_later_sent_time_wins(self):
        existing = self._alert('ALERT', '2026-08-12T10:00:00-00:00')
        candidate = self._alert('ALERT', '2026-08-12T18:00:00-00:00')
        assert _should_replace_alert(existing, candidate) is True

    def test_earlier_sent_time_loses(self):
        existing = self._alert('ALERT', '2026-08-12T18:00:00-00:00')
        candidate = self._alert('ALERT', '2026-08-12T10:00:00-00:00')
        assert _should_replace_alert(existing, candidate) is False

    def test_same_time_higher_priority_wins(self):
        existing = self._alert('ALERT', '2026-08-12T10:00:00-00:00')
        candidate = self._alert('UPDATE', '2026-08-12T10:00:00-00:00')
        assert _should_replace_alert(existing, candidate) is True

    def test_same_time_and_priority_prefers_geometry(self):
        existing = self._alert('ALERT', '2026-08-12T10:00:00-00:00', geometry=None)
        candidate = self._alert('ALERT', '2026-08-12T10:00:00-00:00', geometry={'type': 'Polygon'})
        assert _should_replace_alert(existing, candidate) is True

    def test_same_time_priority_and_geometry_keeps_existing(self):
        existing = self._alert('ALERT', '2026-08-12T10:00:00-00:00')
        candidate = self._alert('ALERT', '2026-08-12T10:00:00-00:00')
        assert _should_replace_alert(existing, candidate) is False


# ---------------------------------------------------------------------------
# _count_vertices
# ---------------------------------------------------------------------------

class TestCountVertices:
    def test_not_a_list_returns_zero(self):
        assert _count_vertices("not a list", _LOGGER) == 0

    def test_single_coordinate_pair(self):
        assert _count_vertices([1.0, 2.0], _LOGGER) == 1

    def test_polygon_ring(self):
        ring = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]
        assert _count_vertices(ring, _LOGGER) == 4

    def test_multipolygon_nesting(self):
        multipolygon = [[[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
                         [[[5.0, 5.0], [6.0, 5.0], [6.0, 6.0], [5.0, 5.0]]]]
        assert _count_vertices(multipolygon, _LOGGER) == 8

    def test_excessive_nesting_depth_returns_zero(self):
        nested = [1.0, 2.0]
        for _ in range(15):
            nested = [nested]
        assert _count_vertices(nested, _LOGGER) == 0


# ---------------------------------------------------------------------------
# parse_cap_alert
# ---------------------------------------------------------------------------

class TestParseCapAlert:
    def test_minimal_alert_gets_synthetic_identifier(self):
        parsed = parse_cap_alert({'properties': {'event': 'Test Event'}}, _LOGGER)
        assert parsed is not None
        assert parsed['identifier'].startswith('temp_')
        assert parsed['event'] == 'Test Event'

    def test_ipaws_source_defaults_when_raw_xml_present(self):
        parsed = parse_cap_alert({
            'properties': {'identifier': 'abc-123', 'event': 'Test'},
            'raw_xml': '<alert/>',
        }, _LOGGER)
        assert parsed['source'] == 'IPAWS'

    def test_noaa_source_default_without_raw_xml(self):
        parsed = parse_cap_alert({'properties': {'identifier': 'abc-123', 'event': 'Test'}}, _LOGGER)
        assert parsed['source'] == 'NOAA'

    def test_list_area_desc_joined(self):
        parsed = parse_cap_alert({
            'properties': {'identifier': 'abc-123', 'areaDesc': ['County A', 'County B']},
        }, _LOGGER)
        assert parsed['area_desc'] == 'County A; County B'

    def test_malformed_input_returns_none(self):
        # alert_data.get() on a non-dict raises AttributeError, caught internally
        assert parse_cap_alert(None, _LOGGER) is None
