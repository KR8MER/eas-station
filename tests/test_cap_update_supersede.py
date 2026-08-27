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

"""Regression test for CAP <references>-based Update linking.

Per CAP 1.2 sec 3.3.2.3, a msgType=Update message gets its OWN unique
identifier and points back at the alert(s) it updates via <references>
rather than reusing the original's -- the same rule that made the Cancel
bug in tests/test_cap_references_cancellation.py possible. VTEC-based chain
linking (_mark_vtec_chain_superseded) only works for NWS products carrying
VTEC identity; a source with no VTEC data (a state DOT's IPAWS feed, for
example) had no way at all to link an Update back to the alert it updates --
both the stale original and the new Update showed up as separate active
alerts on the dashboard indefinitely.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytestmark = pytest.mark.unit

from poller.cap_poller import CAPPoller


def _fake_self():
    return SimpleNamespace(db_session=MagicMock(), logger=MagicMock())


def test_update_marks_the_referenced_original_superseded():
    fake_self = _fake_self()
    new_alert = SimpleNamespace(id=42, identifier='OHDOT-update-id')
    prior_alert = SimpleNamespace(
        id=7, identifier='OHDOT-original-id', event='Local Area Emergency',
        superseded_by_id=None,
    )
    fake_self.db_session.query.return_value.filter_by.return_value.first.return_value = prior_alert

    references = 'sender@example.com,OHDOT-original-id,2026-08-27T05:52:00-04:00'
    updated = CAPPoller._mark_cap_references_superseded(fake_self, new_alert, references)

    assert updated == 1
    assert prior_alert.superseded_by_id == 42
    fake_self.db_session.commit.assert_called_once()


def test_update_with_no_references_is_a_no_op():
    fake_self = _fake_self()
    new_alert = SimpleNamespace(id=42, identifier='OHDOT-update-id')

    updated = CAPPoller._mark_cap_references_superseded(fake_self, new_alert, None)

    assert updated == 0
    fake_self.db_session.query.assert_not_called()
    fake_self.db_session.commit.assert_not_called()


def test_update_referencing_an_alert_we_never_stored_is_a_safe_no_op():
    fake_self = _fake_self()
    new_alert = SimpleNamespace(id=42, identifier='OHDOT-update-id')
    fake_self.db_session.query.return_value.filter_by.return_value.first.return_value = None

    references = 'sender@example.com,SOME-OTHER-ID,2026-08-27T05:52:00-04:00'
    updated = CAPPoller._mark_cap_references_superseded(fake_self, new_alert, references)

    assert updated == 0
    fake_self.db_session.commit.assert_not_called()


def test_already_superseded_alert_is_not_reassigned():
    """First Update to supersede an alert wins -- a later, unrelated Update
    naming the same identifier must not overwrite the existing chain link."""
    fake_self = _fake_self()
    new_alert = SimpleNamespace(id=99, identifier='OHDOT-later-update')
    prior_alert = SimpleNamespace(
        id=7, identifier='OHDOT-original-id', event='Local Area Emergency',
        superseded_by_id=42,  # already linked to an earlier update
    )
    fake_self.db_session.query.return_value.filter_by.return_value.first.return_value = prior_alert

    references = 'sender@example.com,OHDOT-original-id,2026-08-27T06:00:00-04:00'
    updated = CAPPoller._mark_cap_references_superseded(fake_self, new_alert, references)

    assert updated == 0
    assert prior_alert.superseded_by_id == 42
    fake_self.db_session.commit.assert_not_called()


def test_a_reference_to_itself_is_ignored():
    """Defensive: a message must never mark itself as its own predecessor."""
    fake_self = _fake_self()
    new_alert = SimpleNamespace(id=42, identifier='OHDOT-update-id')

    references = 'sender@example.com,OHDOT-update-id,2026-08-27T05:52:00-04:00'
    updated = CAPPoller._mark_cap_references_superseded(fake_self, new_alert, references)

    assert updated == 0
    fake_self.db_session.query.assert_not_called()
