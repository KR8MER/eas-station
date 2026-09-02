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

"""Regression tests for per-item failure isolation in the CAP poller.

Confirmed live in production 2026-08-31: an unhandled data-shape variance
in ONE alert's <references> field crashed the entire poll cycle for ~9
hours -- not just that alert, every alert, on every cycle, because
poll_and_process()'s main per-alert loop had only one try/except around
the WHOLE cycle, not one per alert. That specific field bug was fixed
separately (see tests/test_cap_references_cancellation.py); this file
guards the structural fix -- that a bad item can never again take down its
siblings -- across every per-item loop in the poller:

  1. poll_and_process()'s main per-alert loop
  2. fetch_cap_alerts()'s per-alert dedup/normalize loop
  3. _parse_ipaws_xml_feed()'s per-<alert> XML conversion loop
  4. _process_cap_references_cancellation()'s per-reference loop (a single
     Cancel message can reference several prior alerts; one bad reference
     must not stop the others from being cancelled)
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

from poller.cap_poller import CAPPoller


def _fake_self(**overrides):
    base = dict(
        db_session=MagicMock(),
        logger=MagicMock(),
        session=MagicMock(),
        cap_endpoints=['https://example.invalid/feed'],
        last_fetch_errors=[],
        last_poll_sources=[],
        _should_replace_alert=MagicMock(return_value=False),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# fetch_cap_alerts() -- per-alert normalize/dedup loop
# ---------------------------------------------------------------------------

class _PoisonProps(dict):
    """A properties dict that raises when its 'senderName' is normalized,
    reproducing the exact shape of bug that caused the production outage
    (an unexpected type where a plain string was assumed)."""

    def get(self, key, default=None):
        if key == 'senderName':
            raise AttributeError("simulated malformed field access")
        return super().get(key, default)


def test_fetch_cap_alerts_one_malformed_alert_does_not_drop_the_others():
    good_alert_1 = {'properties': {'identifier': 'GOOD-1', 'senderName': 'NWS', 'sent': '2026-08-31T00:00:00Z', 'headline': 'Test 1'}}
    poison_alert = {'properties': _PoisonProps({'identifier': 'POISON-1'})}
    good_alert_2 = {'properties': {'identifier': 'GOOD-2', 'senderName': 'NWS', 'sent': '2026-08-31T00:01:00Z', 'headline': 'Test 2'}}

    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.raise_for_status = MagicMock()

    fake_self = _fake_self()
    fake_self._parse_feed_payload = MagicMock(
        return_value=[good_alert_1, poison_alert, good_alert_2]
    )
    fake_self.session.get = MagicMock(return_value=response)

    result = CAPPoller.fetch_cap_alerts(fake_self, timeout=5)

    identifiers = {
        (a.get('properties') or {}).get('identifier') for a in result
    }
    assert 'GOOD-1' in identifiers
    assert 'GOOD-2' in identifiers
    assert 'POISON-1' not in identifiers
    fake_self.logger.error.assert_called()


# ---------------------------------------------------------------------------
# _parse_ipaws_xml_feed() -- per-<alert> XML conversion loop
# ---------------------------------------------------------------------------

_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://gov.fema.ipaws.services/feed"
      xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
{alerts}
</feed>
"""

_GOOD_ALERT_XML = """
  <cap:alert>
    <cap:identifier>{identifier}</cap:identifier>
    <cap:sender>sender@example.gov</cap:sender>
    <cap:sent>2026-08-31T00:00:00-04:00</cap:sent>
    <cap:status>Actual</cap:status>
    <cap:msgType>Alert</cap:msgType>
    <cap:scope>Public</cap:scope>
    <cap:info>
      <cap:category>Met</cap:category>
      <cap:event>Test Event</cap:event>
      <cap:urgency>Expected</cap:urgency>
      <cap:severity>Minor</cap:severity>
      <cap:certainty>Likely</cap:certainty>
      <cap:headline>Test headline</cap:headline>
    </cap:info>
  </cap:alert>
"""


def test_parse_ipaws_xml_feed_one_malformed_alert_does_not_drop_the_others():
    # _convert_cap_alert() calls several other instance helper methods
    # (_select_cap_info, _extract_cap_parameters, etc.) that are pure
    # functions of their arguments, not instance state -- a real
    # (uninitialized) instance resolves those normally via the class,
    # unlike a SimpleNamespace stand-in.
    fake_self = CAPPoller.__new__(CAPPoller)
    fake_self.logger = MagicMock()

    xml_text = _XML_TEMPLATE.format(
        alerts=(
            _GOOD_ALERT_XML.format(identifier='GOOD-XML-1')
            # A second "alert" that isn't valid CAP <alert> content at all --
            # _convert_cap_alert must be able to choke on this without
            # aborting the alerts that parse fine on either side of it.
            + "\n  <cap:alert><cap:info><cap:parameter><cap:valueName/></cap:parameter></cap:info></cap:alert>\n"
            + _GOOD_ALERT_XML.format(identifier='GOOD-XML-2')
        )
    )

    # Force _convert_cap_alert to raise specifically for the malformed
    # middle element, while still running the real implementation for the
    # two good ones -- reproduces "the loop must isolate per item" without
    # depending on exactly which internal CAP field trips it up.
    real_convert = CAPPoller._convert_cap_alert

    def _convert_with_injected_failure(self, alert_elem, ns):
        identifier_el = alert_elem.find('cap:identifier', ns)
        if identifier_el is None:
            raise ValueError("simulated malformed <alert> element")
        return real_convert(self, alert_elem, ns)

    fake_self._convert_cap_alert = lambda alert_elem, ns: _convert_with_injected_failure(fake_self, alert_elem, ns)

    result = CAPPoller._parse_ipaws_xml_feed(fake_self, xml_text)

    identifiers = {a['properties']['identifier'] for a in result}
    assert identifiers == {'GOOD-XML-1', 'GOOD-XML-2'}
    fake_self.logger.error.assert_called()


# ---------------------------------------------------------------------------
# _process_cap_references_cancellation() -- per-reference loop
# ---------------------------------------------------------------------------

def test_cancellation_one_bad_reference_does_not_block_the_others():
    fake_self = _fake_self()

    good_alert = SimpleNamespace(identifier='GOOD-REF', event='Test Event', status='Actual', cancelled_at=None)

    def _query_side_effect(model):
        query_mock = MagicMock()

        def _filter_by(**kwargs):
            ref_id = kwargs.get('identifier')
            filtered = MagicMock()
            if ref_id == 'BAD-REF':
                filtered.first = MagicMock(side_effect=RuntimeError("simulated DB error"))
            elif ref_id == 'GOOD-REF':
                filtered.first = MagicMock(return_value=good_alert)
            else:
                filtered.first = MagicMock(return_value=None)
            return filtered

        query_mock.filter_by.side_effect = _filter_by
        return query_mock

    fake_self.db_session.query.side_effect = _query_side_effect

    references = (
        'sender@example.com,BAD-REF,2026-08-31T00:00:00-04:00 '
        'sender@example.com,GOOD-REF,2026-08-31T00:01:00-04:00'
    )
    message = {
        'properties': {
            'identifier': 'CANCEL-MSG-1',
            'messageType': 'Cancel',
            'sent': '2026-08-31T00:05:00-04:00',
            'references': references,
        }
    }

    handled = CAPPoller._process_cap_references_cancellation(fake_self, message)

    assert handled is True
    assert good_alert.status == 'Cancelled'
    assert good_alert.cancelled_at is not None
    fake_self.logger.error.assert_called()
    fake_self.db_session.commit.assert_called()


# ---------------------------------------------------------------------------
# poll_and_process() -- main per-alert loop
#
# Full functional testing of this method needs a real Flask/DB context (it
# touches PollerSettings.query, location settings, save_cap_alert, and
# several catch-up sweeps) -- impractical to mock meaningfully here. Guard
# the fix structurally instead: confirm the per-alert try/except (with a
# session rollback so a failed alert can't leave dirty ORM state for the
# next one) actually wraps the main loop, and that it hasn't silently
# regressed back to one try around the whole cycle.
# ---------------------------------------------------------------------------

def test_poll_and_process_main_loop_has_per_item_try_except():
    import inspect
    source = inspect.getsource(CAPPoller.poll_and_process)

    loop_idx = source.index('for alert_data in alerts_data:')
    cleanup_idx = source.index('self.cleanup_old_poll_history()')
    assert loop_idx < cleanup_idx, "cleanup_old_poll_history() must run after the per-alert loop"

    loop_body = source[loop_idx:cleanup_idx]
    assert 'try:' in loop_body, (
        "poll_and_process()'s main per-alert loop must wrap each iteration "
        "in its own try/except -- this is the exact loop that crashed the "
        "poller for ~9 hours on 2026-08-31 when it had none."
    )
    assert 'except Exception' in loop_body
    assert 'continue' in loop_body
    assert 'self.db_session.rollback()' in loop_body, (
        "the per-alert except block must roll back the session so a failed "
        "alert (e.g. one that mutated but never committed an ORM object in "
        "_process_cap_references_cancellation) can't leave dirty state for "
        "the next alert in the same cycle."
    )
