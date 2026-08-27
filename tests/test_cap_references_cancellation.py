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

"""Regression test for CAP <references>-based cancellation.

Per CAP 1.2 sec 3.3.2.3, a Cancel message gets its OWN unique identifier and
points back at the alert(s) it cancels via <references> -- it does not have
to reuse the original identifier. Such a Cancel commonly carries no <info>
block at all (nothing left to describe), which meant it always parsed as
event="Unknown" with empty area codes and got silently dropped by the
geographic-relevance filter *before* the poller ever looked at it as a
cancellation. Confirmed in production 2026-08-27: OHDOT cancelled a "Local
Area Emergency" alert; the Cancel message reached our poller a few minutes
later but was rejected as "not specific enough" -- the original alert kept
showing as active indefinitely because nothing ever marked it cancelled.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytestmark = pytest.mark.unit

from poller.cap_poller import CAPPoller


def _fake_self():
    """A minimal stand-in for a CAPPoller instance -- just enough state for
    _process_cap_references_cancellation to run without a real DB/Flask app.
    """
    return SimpleNamespace(db_session=MagicMock(), logger=MagicMock())


def _cancel_message(references, identifier='OHDOT-cancel-id', sent='2026-08-27T07:05:00-04:00'):
    return {
        'properties': {
            'identifier': identifier,
            'messageType': 'Cancel',
            'sent': sent,
            'references': references,
        }
    }


def test_cancel_with_references_marks_the_referenced_alert_cancelled():
    fake_self = _fake_self()
    stored_alert = SimpleNamespace(
        identifier='OHDOT-original-id',
        event='Local Area Emergency',
        status='Actual',
        cancelled_at=None,
    )
    fake_self.db_session.query.return_value.filter_by.return_value.first.return_value = stored_alert

    references = 'sender@example.com,OHDOT-original-id,2026-08-27T05:52:00-04:00'
    handled = CAPPoller._process_cap_references_cancellation(
        fake_self, _cancel_message(references)
    )

    assert handled is True
    assert stored_alert.status == 'Cancelled'
    assert stored_alert.cancelled_at is not None
    fake_self.db_session.commit.assert_called_once()


def test_cancel_referencing_an_alert_we_never_stored_is_a_safe_no_op():
    """We only store alerts relevant to our area -- a Cancel for something
    we filtered out is expected and must not raise or fabricate a row."""
    fake_self = _fake_self()
    fake_self.db_session.query.return_value.filter_by.return_value.first.return_value = None

    references = 'sender@example.com,SOME-OTHER-STATE-ID,2026-08-27T05:52:00-04:00'
    handled = CAPPoller._process_cap_references_cancellation(
        fake_self, _cancel_message(references)
    )

    assert handled is True
    fake_self.db_session.commit.assert_not_called()


def test_non_cancel_message_type_is_ignored():
    fake_self = _fake_self()
    alert_data = {
        'properties': {
            'identifier': 'OHDOT-some-id',
            'messageType': 'Alert',
            'sent': '2026-08-27T05:52:00-04:00',
            'references': 'sender,OHDOT-original-id,2026-08-27T05:52:00-04:00',
        }
    }

    handled = CAPPoller._process_cap_references_cancellation(fake_self, alert_data)

    assert handled is False
    fake_self.db_session.query.assert_not_called()


def test_cancel_without_references_is_ignored():
    """Falls through to _apply_cancellation_status's same-identifier path instead."""
    fake_self = _fake_self()

    handled = CAPPoller._process_cap_references_cancellation(
        fake_self, _cancel_message(references='')
    )

    assert handled is False
    fake_self.db_session.query.assert_not_called()


def test_already_cancelled_alert_is_not_touched_again():
    fake_self = _fake_self()
    already_cancelled_at = object()
    stored_alert = SimpleNamespace(
        identifier='OHDOT-original-id',
        event='Local Area Emergency',
        status='Cancelled',
        cancelled_at=already_cancelled_at,
    )
    fake_self.db_session.query.return_value.filter_by.return_value.first.return_value = stored_alert

    references = 'sender@example.com,OHDOT-original-id,2026-08-27T05:52:00-04:00'
    handled = CAPPoller._process_cap_references_cancellation(
        fake_self, _cancel_message(references)
    )

    assert handled is True
    assert stored_alert.cancelled_at is already_cancelled_at
    fake_self.db_session.commit.assert_not_called()


def test_multiple_references_in_one_cancel_message():
    fake_self = _fake_self()
    alert_a = SimpleNamespace(identifier='A', event='Local Area Emergency', status='Actual', cancelled_at=None)
    alert_b = SimpleNamespace(identifier='B', event='Local Area Emergency', status='Actual', cancelled_at=None)

    def fake_first():
        # filter_by is called once per identifier; alternate between the two
        calls = fake_self.db_session.query.return_value.filter_by.call_args_list
        last_call = calls[-1]
        ref_id = last_call.kwargs.get('identifier')
        return {'A': alert_a, 'B': alert_b}.get(ref_id)

    fake_self.db_session.query.return_value.filter_by.return_value.first.side_effect = fake_first

    references = (
        'sender@example.com,A,2026-08-27T05:52:00-04:00 '
        'sender@example.com,B,2026-08-27T05:53:00-04:00'
    )
    handled = CAPPoller._process_cap_references_cancellation(
        fake_self, _cancel_message(references)
    )

    assert handled is True
    assert alert_a.status == 'Cancelled'
    assert alert_b.status == 'Cancelled'
