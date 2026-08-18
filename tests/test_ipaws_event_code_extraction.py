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

Regression tests for a silent-alert-loss bug: an IPAWS-sourced CAP alert
whose raw XML carried a valid <eventCode><valueName>SAME</valueName>
<value>SPW</value></eventCode> block was stored with NO eventCode at all
in `properties` -- CAPPoller._convert_cap_alert() never extracted
<eventCode> from the CAP <info> block, only <parameter> and geocode.

Reproduced live: a county "Natural gas leak" shelter-in-place alert
(instruction "Shelter in place.", severity Extreme, urgency Immediate)
had its event code fall through as unresolved. Downstream, the auto-forward
allowlist check saw an unresolved code and rejected it with "Event
'UNKNOWN' is not in the configured forwarding allowlist" -- even though
the site's allowlist already included SPW -- so a real emergency alert
was never broadcast.

Three call sites were involved and are each covered here:
  1. CAPPoller._extract_cap_event_codes() / _convert_cap_alert() /
     _parse_ipaws_xml_feed() (poller/cap_poller.py) -- didn't extract
     <eventCode> from IPAWS XML at all.
  2. app_utils.eas._collect_event_code_candidates() -- couldn't read the
     dict shape ({"SAME": [...], ...}) NWS's CAP-JSON feed and (once
     fixed) the IPAWS XML parser both produce for eventCode.
  3. app_core.audio.auto_forward._resolve_event_code() -- an independent,
     weaker reimplementation used for the forwarding-allowlist check that
     only matched the CAP `event` name against the registry's canonical
     names, checking neither the eventCode block nor the registry's
     aliases. Now delegates to the shared resolver so both call sites can
     never drift apart again.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from poller.cap_poller import CAPPoller
from app_utils.eas import _collect_event_code_candidates
from app_utils.event_codes import resolve_event_code
from app_core.audio.auto_forward import _resolve_event_code


def _make_test_poller() -> CAPPoller:
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_ipaws_event_code")
    return poller


# The real-world alert this bug was found from (sender/identifier/signature
# redacted; event content, instruction, and the eventCode block are verbatim).
_GAS_LEAK_INFO_XML = """
<info>
  <language>en-US</language>
  <category>Safety</category>
  <event>Natural gas leak</event>
  <urgency>Immediate</urgency>
  <severity>Extreme</severity>
  <certainty>Observed</certainty>
  <eventCode><valueName>SAME</valueName><value>SPW</value></eventCode>
  <expires>2026-08-12T18:36:37-00:00</expires>
  <senderName>OCV</senderName>
  <headline>Natural gas leak</headline>
  <description>Please shelter in place half mile from Sr 190 in the 17000 block of Sr 190</description>
  <instruction>Shelter in place. </instruction>
  <parameter><valueName>BLOCKCHANNEL</valueName><value>EAS</value></parameter>
  <parameter><valueName>BLOCKCHANNEL</valueName><value>NWEM</value></parameter>
  <area><areaDesc>039137</areaDesc><geocode><valueName>SAME</valueName><value>039137</value></geocode></area>
</info>
"""

_NS = {
    'feed': 'http://gov.fema.ipaws.services/feed',
    'cap': 'urn:oasis:names:tc:emergency:cap:1.2',
}


def _parse_info(xml_body: str):
    from app_utils.optimized_parsing import parse_xml_string
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


class TestExtractCapEventCodes:
    """Unit tests for CAPPoller._extract_cap_event_codes()."""

    def test_extracts_same_value(self):
        poller = _make_test_poller()
        info_elem = _parse_info(_GAS_LEAK_INFO_XML)
        result = poller._extract_cap_event_codes(info_elem, _NS)
        assert result == {'SAME': ['SPW']}

    def test_missing_eventcode_returns_empty_dict(self):
        poller = _make_test_poller()
        info_elem = _parse_info('<info><event>Test</event></info>')
        result = poller._extract_cap_event_codes(info_elem, _NS)
        assert result == {}

    def test_multiple_valuenames_preserved_separately(self):
        poller = _make_test_poller()
        xml_body = (
            '<info><event>Severe Thunderstorm Warning</event>'
            '<eventCode><valueName>SAME</valueName><value>SVR</value></eventCode>'
            '<eventCode><valueName>NationalWeatherService</valueName><value>SVW</value></eventCode>'
            '</info>'
        )
        info_elem = _parse_info(xml_body)
        result = poller._extract_cap_event_codes(info_elem, _NS)
        assert result == {'SAME': ['SVR'], 'NationalWeatherService': ['SVW']}

    def test_none_info_elem_returns_empty_dict(self):
        poller = _make_test_poller()
        assert poller._extract_cap_event_codes(None, _NS) == {}

    def test_empty_value_skipped(self):
        poller = _make_test_poller()
        xml_body = '<info><eventCode><valueName>SAME</valueName><value></value></eventCode></info>'
        info_elem = _parse_info(xml_body)
        result = poller._extract_cap_event_codes(info_elem, _NS)
        assert result == {}


class TestConvertCapAlertIncludesEventCode:
    """_convert_cap_alert() must populate properties['eventCode']."""

    def test_gas_leak_alert_gets_spw_event_code(self):
        """The exact real-world alert this bug was found from."""
        poller = _make_test_poller()
        from app_utils.optimized_parsing import parse_xml_string
        alert_xml = (
            '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
            '<identifier>ad7947940023478ba618a1bf295ca2a0_202933</identifier>'
            '<sender>ocv_ipaws@202933</sender>'
            '<sent>2026-08-12T17:36:37-00:00</sent><status>Actual</status>'
            '<msgType>Alert</msgType><scope>Public</scope>'
            f'{_GAS_LEAK_INFO_XML}'
            '</alert>'
        )
        alert_elem = parse_xml_string(alert_xml)
        feature = poller._convert_cap_alert(alert_elem, _NS)

        assert feature['properties']['eventCode'] == {'SAME': ['SPW']}
        assert feature['properties']['event'] == 'Natural gas leak'

    def test_alert_without_eventcode_gets_empty_dict_not_missing_key(self):
        """properties['eventCode'] must always be present (possibly empty),
        not simply absent -- callers rely on the key existing."""
        poller = _make_test_poller()
        from app_utils.optimized_parsing import parse_xml_string
        alert_xml = (
            '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
            '<identifier>no-eventcode-1</identifier>'
            '<sender>test@example.gov</sender>'
            '<sent>2026-08-12T17:36:37-00:00</sent><status>Actual</status>'
            '<msgType>Alert</msgType><scope>Public</scope>'
            '<info><event>Some Local Alert</event></info>'
            '</alert>'
        )
        alert_elem = parse_xml_string(alert_xml)
        feature = poller._convert_cap_alert(alert_elem, _NS)
        assert feature['properties']['eventCode'] == {}


class TestCollectEventCodeCandidatesDictHandling:
    """_collect_event_code_candidates() must walk the CAP-JSON eventCode
    dict shape ({"SAME": [...], "NationalWeatherService": [...]}) instead
    of silently dropping it."""

    def test_extracts_same_key_from_dict(self):
        alert = SimpleNamespace(raw_json={
            'properties': {'eventCode': {'SAME': ['SPW'], 'NationalWeatherService': ['SPW']}}
        })
        candidates = _collect_event_code_candidates(alert, {})
        assert candidates == ['SPW']

    def test_prefers_same_over_other_valuenames(self):
        """NWS CAP-JSON alerts carry both SAME and NationalWeatherService
        valueNames; SAME is the CAP-standard one and must win."""
        alert = SimpleNamespace(raw_json={
            'properties': {'eventCode': {'SAME': ['SVS'], 'NationalWeatherService': ['SVW']}}
        })
        candidates = _collect_event_code_candidates(alert, {})
        assert candidates == ['SVS']
        assert 'SVW' not in candidates

    def test_falls_back_to_other_keys_when_no_same(self):
        """Missing 'SAME' shouldn't drop the whole block -- fall back to
        whatever else is present (resolve_event_code() will reject it if
        it isn't a real registry code, so this is safe)."""
        alert = SimpleNamespace(raw_json={
            'properties': {'eventCode': {'NationalWeatherService': ['SVW']}}
        })
        candidates = _collect_event_code_candidates(alert, {})
        assert candidates == ['SVW']

    def test_none_eventcode_yields_no_candidates(self):
        alert = SimpleNamespace(raw_json={'properties': {'eventCode': None}})
        assert _collect_event_code_candidates(alert, {}) == []

    def test_string_eventcode_still_works(self):
        """Back-compat: a plain string eventCode value must still work."""
        alert = SimpleNamespace(raw_json={'properties': {'eventCode': 'SVR'}})
        assert _collect_event_code_candidates(alert, {}) == ['SVR']

    def test_list_eventcode_still_works(self):
        """Back-compat: a plain list eventCode value must still work."""
        alert = SimpleNamespace(raw_json={'properties': {'eventCode': ['SVR']}})
        assert _collect_event_code_candidates(alert, {}) == ['SVR']

    def test_resolves_to_spw_end_to_end_via_dict(self):
        """Full pipeline: dict-shaped eventCode -> resolve_event_code() -> SPW,
        with no aliasing -- the event code comes straight from the source."""
        alert = SimpleNamespace(
            event='Natural gas leak',
            raw_json={'properties': {'eventCode': {'SAME': ['SPW']}}},
        )
        candidates = _collect_event_code_candidates(alert, {})
        assert resolve_event_code(alert.event, candidates) == 'SPW'


class TestAutoForwardResolveEventCode:
    """_resolve_event_code() in auto_forward.py must use the shared
    resolver (eventCode block + aliases), not just an exact name match."""

    def test_resolves_via_eventcode_block_not_name(self):
        """Event name alone ("Natural gas leak") wouldn't match any
        registry name -- resolution must come from the eventCode block."""
        alert = SimpleNamespace(
            event='Natural gas leak',
            raw_json={'properties': {'eventCode': {'SAME': ['SPW']}}},
        )
        assert _resolve_event_code(alert) == 'SPW'

    def test_still_resolves_by_name_when_no_eventcode(self):
        """Regression guard: the exact-name-match path this function used
        to be limited to must keep working."""
        alert = SimpleNamespace(
            event='Severe Thunderstorm Warning',
            raw_json=None,
        )
        assert _resolve_event_code(alert) == 'SVR'

    def test_prefers_same_eventcode_over_name_when_they_disagree(self):
        """A VTEC 'CON' continuation statement: event name says the parent
        warning's headline ("Severe Thunderstorm Warning") but the CAP
        eventCode.SAME correctly says SVS (a statement, not a fresh
        warning). The authoritative eventCode must win."""
        alert = SimpleNamespace(
            event='Severe Thunderstorm Warning',
            raw_json={'properties': {'eventCode': {'SAME': ['SVS'], 'NationalWeatherService': ['SVW']}}},
        )
        assert _resolve_event_code(alert) == 'SVS'

    def test_unresolvable_alert_returns_none(self):
        alert = SimpleNamespace(event='', raw_json=None)
        assert _resolve_event_code(alert) is None
