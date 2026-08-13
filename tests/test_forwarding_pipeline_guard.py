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
# retry_missing_intersections() — catch-up sweep for intersection calc
#
# process_intersections() failures at ingest are deliberately non-fatal (see
# the tests above pinning that a bad intersection calc must not block
# forwarding), which means a failure is otherwise silent and nothing retries
# it. This sweep, run once per poll cycle alongside retry_unevaluated_forwards,
# is that retry.
# ---------------------------------------------------------------------------

class _FakeIntersectionSweepSession(_FakeSession):
    """retry_missing_intersections issues one query: geometry-bearing
    alerts created since the cutoff window."""

    def __init__(self, candidates):
        super().__init__()
        self._candidates = list(candidates)

    def query(self, model):
        return _FakeQuery(self._candidates)


def _intersection_alert(identifier: str) -> SimpleNamespace:
    return SimpleNamespace(id=abs(hash(identifier)) % 100000, identifier=identifier,
                            geom="POLYGON((0 0,0 1,1 1,1 0,0 0))", created_at=_aware(-10))


def test_retry_missing_intersections_processes_alerts_with_no_rows():
    alert = _intersection_alert("CAP-INT-1")
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _FakeIntersectionSweepSession([alert])
    poller._needs_intersection_calculation = lambda a: True

    processed = []
    poller.process_intersections = lambda a: processed.append(a)

    count = poller.retry_missing_intersections()

    assert count == 1
    assert processed == [alert]


def test_retry_missing_intersections_skips_alerts_that_already_have_rows():
    alert = _intersection_alert("CAP-INT-2")
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _FakeIntersectionSweepSession([alert])
    poller._needs_intersection_calculation = lambda a: False

    def _must_not_run(a):
        raise AssertionError("process_intersections must not be called")

    poller.process_intersections = _must_not_run

    assert poller.retry_missing_intersections() == 0


def test_retry_missing_intersections_noop_on_query_failure():
    class _BoomSession(_FakeSession):
        def query(self, model):
            raise RuntimeError("db gone")

    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _BoomSession()

    assert poller.retry_missing_intersections() == 0
    assert poller.db_session.rollbacks == 1


def test_retry_missing_intersections_one_failure_does_not_abort_sweep():
    """One alert's recalculation blowing up must not stop the rest."""
    a1 = _intersection_alert("CAP-INT-3")
    a2 = _intersection_alert("CAP-INT-4")
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _FakeIntersectionSweepSession([a1, a2])
    poller._needs_intersection_calculation = lambda a: True

    processed = []

    def _process(a):
        if a is a1:
            raise RuntimeError("simulated PostGIS failure")
        processed.append(a)

    poller.process_intersections = _process

    count = poller.retry_missing_intersections()

    assert count == 1
    assert processed == [a2]
    # The failed alert's half-done work must be rolled back so it doesn't
    # poison the session for the next alert or the next poll cycle.
    assert poller.db_session.rollbacks == 1


# ---------------------------------------------------------------------------
# Regression: geometry bind parameters must be stringified
#
# process_intersections() and _has_geometry_changed() pass alert/boundary
# geometry into raw text() SQL as bind parameters. psycopg2 has no adapter
# registered for geoalchemy2.elements.WKBElement -- the type the ORM hands
# back for any already-persisted geometry column -- so passing it directly
# always raised "can't adapt type 'WKBElement'" in production, on every
# single call, silently defeating both automatic intersection calculation at
# ingest and the retry sweep above (confirmed against a real PostGIS
# database: identical failure with the pre-fix code, resolved by stringifying
# the geometry before binding). str(WKBElement) gives its EWKB hex encoding
# (.desc), which PostGIS parses natively as raw SQL text.
# ---------------------------------------------------------------------------

class _GeomLike:
    """Stand-in for geoalchemy2.elements.WKBElement: stringifies to its EWKB
    hex representation and nothing else. In particular it does NOT support
    being passed directly as a psycopg2 bind parameter -- if the code under
    test ever regresses to passing this object instead of str(this), the
    fake session below will record the raw object instead of a string and
    the assertions will catch it."""

    def __init__(self, hex_str: str):
        self._hex = hex_str

    def __str__(self) -> str:
        return self._hex

    def __bool__(self) -> bool:
        return True


class _IntersectionQueryStub:
    def filter_by(self, **kwargs):
        return self

    def delete(self):
        return 0

    def count(self):
        return 0


class _CapturingGeometrySession(_FakeSession):
    """Records every execute() call's bind parameters so tests can assert
    geometry values were stringified before being bound, and stubs out the
    query()/bulk_save_objects() calls process_intersections() also makes."""

    def __init__(self):
        super().__init__()
        self.executed_params = []

    def query(self, model):
        return _IntersectionQueryStub()

    def execute(self, statement, params=None):
        self.executed_params.append(dict(params or {}))

        class _Result:
            def scalar(self_inner):
                return True  # ST_IsValid -> geometry is valid, proceed

            def fetchall(self_inner):
                return []  # no intersecting boundaries -- irrelevant to this test

        return _Result()

    def bulk_save_objects(self, objs):  # pragma: no cover - not reached (fetchall() is empty)
        pass


def test_process_intersections_stringifies_geometry_before_binding():
    geom = _GeomLike("0103000020E6100000DEADBEEF")
    alert = SimpleNamespace(id=1, identifier="CAP-GEOM-1", geom=geom)

    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    session = _CapturingGeometrySession()
    poller.db_session = session

    poller.process_intersections(alert)

    geom_params = [
        (key, value)
        for params in session.executed_params
        for key, value in params.items()
        if "geom" in key
    ]
    assert geom_params, "expected at least one geometry bind parameter"
    for key, value in geom_params:
        assert isinstance(value, str), (
            f"bind param {key!r} must be str(geom) -- psycopg2 cannot adapt "
            f"a raw WKBElement -- got {type(value).__name__}"
        )
        assert value == str(geom)


def test_has_geometry_changed_stringifies_both_geometries():
    old = _GeomLike("OLD_HEX_GEOM")
    new = _GeomLike("NEW_HEX_GEOM")

    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    session = _CapturingGeometrySession()
    poller.db_session = session

    poller._has_geometry_changed(old, new)

    assert session.executed_params, "expected an ST_Equals execute() call"
    params = session.executed_params[0]
    assert params["old"] == "OLD_HEX_GEOM"
    assert params["new"] == "NEW_HEX_GEOM"
    assert isinstance(params["old"], str) and isinstance(params["new"], str)


def test_has_geometry_changed_none_handling_unaffected():
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_forwarding_pipeline_guard")
    poller.db_session = _CapturingGeometrySession()

    assert poller._has_geometry_changed(None, None) is False
    assert poller._has_geometry_changed(None, _GeomLike("X")) is True
    assert poller._has_geometry_changed(_GeomLike("X"), None) is True
    # Neither None/None nor either-None path should have touched the DB.
    assert poller.db_session.executed_params == []


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
