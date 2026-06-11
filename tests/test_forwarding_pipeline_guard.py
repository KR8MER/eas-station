"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Regression tests for the forwarding-pipeline guard.

On 2026-06-10 a statewide Ohio RMT (CAPNET-1-14329-20260610034200) was saved
but never aired: process_intersections() sat between the database save and
auto_forward_cap_alert() in _insert_new_alert, and its re-raised PostGIS
failure aborted the pipeline before the forwarding decision was made.  The
alert was left with eas_forwarded=False and eas_forwarding_reason=NULL and,
because forwarding only happens on first insert, it permanently missed its
broadcast window.

These tests pin the three fixes:
1. _insert_new_alert evaluates forwarding BEFORE intersections, and an
   intersection failure no longer aborts the insert.
2. retry_unevaluated_forwards() re-runs the forwarding decision for recent,
   unexpired alerts whose reason was never recorded.
3. The alert trail renders "never evaluated" distinctly from a deliberate
   suppression.
"""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

cp = pytest.importorskip(
    "poller.cap_poller",
    reason="poller.cap_poller dependencies not installed",
)
from poller.cap_poller import CAPPoller  # noqa: E402


class _FakeSession:
    """Minimal stand-in for the poller's SQLAlchemy session."""

    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeQuery:
    def __init__(self, items):
        self._items = items

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._items)


class _FakeSweepSession(_FakeSession):
    """The sweep issues two queries per invocation: missed (expired,
    never-evaluated) first, then pending (unexpired, never-evaluated)."""

    def __init__(self, pending, missed=None):
        super().__init__()
        self._results = [list(missed or []), list(pending)]

    def query(self, model):
        items = self._results.pop(0) if self._results else []
        return _FakeQuery(items)


def _aware(offset_minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)


def _make_poller() -> CAPPoller:
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _FakeSession()
    poller.redis_client = None  # _publish_alert_event becomes a no-op
    poller.eas_config = {"enabled": True}
    poller.location_settings = {"fips_codes": ["039137"]}
    return poller


def _alert_payload() -> dict:
    return {
        "identifier": "TEST-GUARD-0001",
        "sent": _aware(-5),
        "expires": _aware(55),
        "status": "Actual",
        "message_type": "Alert",
        "scope": "Public",
        "event": "Required Monthly Test",
        "severity": "Minor",
        "urgency": "Immediate",
        "certainty": "Observed",
        "headline": "Emergency Alert System Test",
        "raw_json": {"properties": {"geocode": {"SAME": ["039000"]}}},
        "source": "IPAWS",
    }


def test_intersection_failure_does_not_block_forwarding(monkeypatch):
    """_insert_new_alert must reach the auto-forward decision even when
    process_intersections raises, and forwarding must run first."""
    poller = _make_poller()
    call_order = []

    # The fallback (non-Flask) CAPAlert model predates the VTEC columns;
    # give it a benign class-level default so the VTEC supersede check works.
    if not hasattr(cp.CAPAlert, "vtec_action"):
        cp.CAPAlert.vtec_action = None

    monkeypatch.setattr(
        poller, "_try_build_geometry_from_same_codes", lambda alert: True
    )

    def _exploding_intersections(alert):
        call_order.append("intersections")
        raise RuntimeError("simulated PostGIS failure")

    monkeypatch.setattr(poller, "process_intersections", _exploding_intersections)
    monkeypatch.setattr(
        cp, "load_eas_config", lambda db_session=None: {"enabled": True}
    )

    forwarded = {}

    def _fake_auto_forward(**kwargs):
        call_order.append("auto_forward")
        forwarded.update(kwargs)
        return {"forwarded": True, "same_header": "ZCZC-CIV-RMT-039000+0100-1610742-TEST    -"}

    monkeypatch.setattr(cp, "auto_forward_cap_alert", _fake_auto_forward)

    payload = _alert_payload()
    is_new, alert, _ = poller._insert_new_alert(
        payload, None, {"raw_json": payload["raw_json"]}
    )

    assert is_new is True
    assert alert is not None
    # Forwarding was evaluated, and BEFORE the intersection step.
    assert call_order == ["auto_forward", "intersections"]
    assert forwarded["cap_alert"] is alert


def test_insert_succeeds_when_intersections_raise(monkeypatch):
    """The insert must complete (no exception to the caller) even when the
    intersection step fails after forwarding."""
    poller = _make_poller()

    if not hasattr(cp.CAPAlert, "vtec_action"):
        cp.CAPAlert.vtec_action = None

    monkeypatch.setattr(
        poller, "_try_build_geometry_from_same_codes", lambda alert: True
    )
    monkeypatch.setattr(
        poller,
        "process_intersections",
        lambda alert: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        cp, "load_eas_config", lambda db_session=None: {"enabled": True}
    )
    monkeypatch.setattr(
        cp,
        "auto_forward_cap_alert",
        lambda **kwargs: {"forwarded": False, "reason": "test"},
    )

    payload = _alert_payload()
    is_new, alert, _ = poller._insert_new_alert(
        payload, None, {"raw_json": payload["raw_json"]}
    )
    assert is_new is True
    assert alert is not None


def test_retry_unevaluated_forwards_reevaluates_pending_alert(monkeypatch):
    """An alert with eas_forwarded=False and a NULL reason must be pushed
    back through auto_forward_cap_alert by the catch-up sweep."""
    pending = SimpleNamespace(
        identifier="CAPNET-1-14329-20260610034200",
        raw_json={"properties": {"geocode": {"SAME": ["039000"]}}},
        eas_forwarded=False,
        eas_forwarding_reason=None,
        created_at=_aware(-10),
        expires=_aware(50),
    )

    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _FakeSweepSession([pending])
    poller.eas_config = {"enabled": True}
    poller.location_settings = {"fips_codes": ["039137"]}

    monkeypatch.setattr(
        cp, "load_eas_config", lambda db_session=None: {"enabled": True}
    )

    calls = []
    system_events = []
    poller.log_system_event = lambda level, message, details=None: system_events.append(
        (level, message, details)
    )

    def _fake_auto_forward(**kwargs):
        calls.append(kwargs)
        return {"forwarded": True, "same_header": "ZCZC-CIV-RMT-039000+0100-1610742-TEST    -"}

    monkeypatch.setattr(cp, "auto_forward_cap_alert", _fake_auto_forward)

    evaluated = poller.retry_unevaluated_forwards()

    assert evaluated == 1
    assert len(calls) == 1
    assert calls[0]["cap_alert"] is pending
    assert calls[0]["alert_data"]["raw_json"] == pending.raw_json
    assert calls[0]["alert_data"]["identifier"] == pending.identifier
    # The pipeline fault itself must be surfaced as a system-log ERROR,
    # not just silently repaired.
    assert len(system_events) == 1
    level, message, details = system_events[0]
    assert level == "ERROR"
    assert pending.identifier in details["identifiers"]


def test_missed_broadcast_is_stamped_and_alarmed(monkeypatch):
    """An alert that expired while never evaluated must get a terminal
    'Never evaluated' reason and a system-log ERROR — and must NOT be
    pushed to the air chain (its window is gone)."""
    missed = SimpleNamespace(
        identifier="CAPNET-MISSED-0001",
        raw_json={},
        eas_forwarded=False,
        eas_forwarding_reason=None,
        created_at=_aware(-120),
        expires=_aware(-60),
    )

    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _FakeSweepSession(pending=[], missed=[missed])
    poller.eas_config = {"enabled": True}
    poller.location_settings = {}

    system_events = []
    poller.log_system_event = lambda level, message, details=None: system_events.append(
        (level, message, details)
    )

    def _must_not_run(**kwargs):
        raise AssertionError("expired alert must not be forwarded")

    monkeypatch.setattr(cp, "auto_forward_cap_alert", _must_not_run)

    evaluated = poller.retry_unevaluated_forwards()

    assert evaluated == 0
    assert missed.eas_forwarding_reason.startswith("Never evaluated")
    assert poller.db_session.commits == 1
    assert len(system_events) == 1
    level, message, details = system_events[0]
    assert level == "ERROR"
    assert "MISSED BROADCAST" in message
    assert missed.identifier in details["identifiers"]


def test_retry_unevaluated_forwards_noop_when_nothing_pending(monkeypatch):
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _FakeSweepSession([])
    poller.eas_config = {"enabled": True}
    poller.location_settings = {}

    def _must_not_run(**kwargs):
        raise AssertionError("auto_forward_cap_alert must not be called")

    monkeypatch.setattr(cp, "auto_forward_cap_alert", _must_not_run)

    assert poller.retry_unevaluated_forwards() == 0


def test_retry_survives_auto_forward_exception(monkeypatch):
    """One alert blowing up must not abort the sweep or the poll cycle."""
    pending = [
        SimpleNamespace(identifier="A-1", raw_json={}, created_at=_aware(-5), expires=_aware(30)),
        SimpleNamespace(identifier="A-2", raw_json={}, created_at=_aware(-5), expires=_aware(30)),
    ]
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _FakeSweepSession(pending)
    poller.eas_config = {"enabled": True}
    poller.location_settings = {}

    monkeypatch.setattr(
        cp, "load_eas_config", lambda db_session=None: {"enabled": True}
    )

    seen = []

    def _fake_auto_forward(**kwargs):
        seen.append(kwargs["cap_alert"].identifier)
        if kwargs["cap_alert"].identifier == "A-1":
            raise RuntimeError("simulated failure")
        return {"forwarded": False, "reason": "test"}

    monkeypatch.setattr(cp, "auto_forward_cap_alert", _fake_auto_forward)

    evaluated = poller.retry_unevaluated_forwards()

    # Both were attempted; only the successful evaluation is counted.
    assert seen == ["A-1", "A-2"]
    assert evaluated == 1


# ---------------------------------------------------------------------------
# Alert-trail rendering of the forwarding outcome
# ---------------------------------------------------------------------------

def _trail_alert(forwarded: bool, reason):
    ts = datetime(2026, 6, 10, 7, 47, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        eas_forwarded=forwarded,
        eas_forwarding_reason=reason,
        created_at=ts,
        updated_at=ts,
    )


def test_trail_event_forwarded():
    pytest.importorskip("flask")
    from app_core.alert_trail import _forwarding_event

    event = _forwarding_event(_trail_alert(True, "Auto-forwarded: SAME ZCZC-..."))
    assert event["summary"] == "Forwarded to air chain"
    assert event["level"] == "INFO"


def test_trail_event_deliberate_suppression():
    pytest.importorskip("flask")
    from app_core.alert_trail import _forwarding_event

    event = _forwarding_event(
        _trail_alert(False, "Alert scope 'Private' is not 'Public'")
    )
    assert event["summary"] == "Forwarding suppressed"
    assert event["level"] == "WARNING"
    assert event["details"]["reason"].startswith("Alert scope")


def test_trail_event_missed_broadcast_stamp():
    """The terminal 'Never evaluated' stamp from the catch-up sweep renders
    as a missed broadcast at ERROR level."""
    pytest.importorskip("flask")
    from app_core.alert_trail import _forwarding_event

    event = _forwarding_event(_trail_alert(
        False,
        "Never evaluated — ingest pipeline fault; alert expired before the "
        "catch-up sweep could retry",
    ))
    assert event["summary"] == "Missed broadcast — never evaluated before expiry"
    assert event["level"] == "ERROR"


def test_trail_event_never_evaluated_is_distinct():
    """NULL reason means the pipeline never reached the forwarding decision;
    the trail must not present that as a deliberate suppression."""
    pytest.importorskip("flask")
    from app_core.alert_trail import _forwarding_event

    event = _forwarding_event(_trail_alert(False, None))
    assert event["summary"] == "Forwarding decision never recorded"
    assert event["level"] == "ERROR"
    assert event["details"]["reason"] is None
    assert "catch-up" in event["details"]["note"]
