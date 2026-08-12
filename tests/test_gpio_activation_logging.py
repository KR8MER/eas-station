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

Tests for the GPIO activation audit trail and relay release pairing.

Relay keying lives in the ``eas-station-gpio`` subprocess and runs entirely on
background threads (the alert-indicator loop and its pub/sub listener, the
per-pin watchdogs, the behavior manager's hold/pulse threads).  Two failures
followed from that and are covered here:

* Flask-SQLAlchemy scopes ``db.session`` to the application context, so audit
  writes from those threads raised ``RuntimeError: Working outside of
  application context`` and every activation was silently dropped from the
  Logs -> GPIO view.
* A relay keyed through a path that ``end_alert()`` does not release stayed
  energised until the 300 s watchdog fired instead of dropping at
  end-of-broadcast.
"""

import threading
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

import app_core.models as app_models
import app_utils.gpio as gpio
import services.gpio.alert_indicators as indicators
from app_utils.gpio import (
    GPIOActivationType,
    GPIOBehavior,
    GPIOBehaviorManager,
    GPIOController,
    GPIOPinConfig,
    GPIOState,
)
from app_utils.gpio_logs import gpio_log_duration, gpio_log_level, gpio_log_message
from services.gpio.alert_indicators import AlertIndicatorMonitor


# ---------------------------------------------------------------------------
# Audit-trail persistence
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_db(monkeypatch):
    """A standalone Flask + Flask-SQLAlchemy app with a GPIO activation table.

    Mirrors the real ``gpio_activation_logs`` columns the controller writes,
    without pulling in the PostGIS-typed models.  ``app_core.models
    .GPIOActivationLog`` is patched to this model because
    ``_save_activation_event`` imports it by name at call time.
    """
    db = SQLAlchemy()
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        # One shared in-memory database across threads.
        "connect_args": {"check_same_thread": False},
    }
    db.init_app(app)

    class GPIOActivationLogStub(db.Model):
        __tablename__ = "gpio_activation_logs"

        id = db.Column(db.Integer, primary_key=True)
        pin = db.Column(db.Integer, nullable=False)
        activation_type = db.Column(db.String(20))
        activated_at = db.Column(db.DateTime(timezone=True))
        deactivated_at = db.Column(db.DateTime(timezone=True))
        duration_seconds = db.Column(db.Float)
        operator = db.Column(db.String(100))
        alert_id = db.Column(db.String(255))
        reason = db.Column(db.Text)
        success = db.Column(db.Boolean, default=True)
        error_message = db.Column(db.Text)

    with app.app_context():
        db.create_all()

    monkeypatch.setattr(app_models, "GPIOActivationLog", GPIOActivationLogStub)

    yield app, db, GPIOActivationLogStub

    # Explicit teardown: a `return`-only fixture leaves the in-memory
    # sqlite3.Connection to be closed whenever the garbage collector gets
    # around to it, which pytest's own end-of-session gc.collect() flags as
    # "ResourceWarning: unclosed database". Disposing the engine here closes
    # it deterministically, in the same test run that opened it.
    with app.app_context():
        db.engine.dispose()


def _make_controller(audit_db, monkeypatch):
    """A controller with one configured pin and a no-op GPIO device."""
    app, db, _model = audit_db
    controller = GPIOController(db_session=db.session, db_app=app, logger=None)

    class _FakeDevice:
        def __init__(self):
            self.value = False

        def on(self):
            self.value = True

        def off(self):
            self.value = False

        def close(self):
            pass

    device = _FakeDevice()
    monkeypatch.setattr(
        GPIOController, "_get_or_create_device", lambda self, config: device
    )
    controller.add_pin(GPIOPinConfig(pin=17, name="Transmitter PTT", debounce_ms=0))
    return controller


def _rows(audit_db):
    app, _db, model = audit_db
    with app.app_context():
        return model.query.order_by(model.id).all()


def test_activation_is_audited_from_a_thread_without_app_context(audit_db, monkeypatch):
    """Regression: the subprocess keys relays from threads with no app context.

    Before the fix ``db.session.add()`` raised ``RuntimeError: Working outside
    of application context``, the exception was swallowed, and the activation
    never reached ``gpio_activation_logs`` — the Logs -> GPIO view went silent.
    """
    controller = _make_controller(audit_db, monkeypatch)

    results = {}

    def key_the_relay():
        results["activated"] = controller.activate(
            pin=17,
            activation_type=GPIOActivationType.AUTOMATIC,
            alert_id="urn:oid:test-1",
            reason="Broadcast playout (TOR)",
        )

    worker = threading.Thread(target=key_the_relay)
    worker.start()
    worker.join(timeout=10)

    # Assert liveness first: a timed-out or crashed worker would otherwise
    # surface as a bare KeyError below, hiding the real cause.
    assert not worker.is_alive(), "activation thread did not finish"
    assert results["activated"] is True

    rows = _rows(audit_db)
    assert len(rows) == 1
    assert rows[0].pin == 17
    assert rows[0].alert_id == "urn:oid:test-1"
    assert rows[0].success is True


def test_release_updates_the_activation_row_instead_of_adding_one(audit_db, monkeypatch):
    """One activation produces one row, completed with a duration on release."""
    controller = _make_controller(audit_db, monkeypatch)

    controller.activate(
        pin=17,
        activation_type=GPIOActivationType.AUTOMATIC,
        alert_id="urn:oid:test-2",
        reason="Broadcast playout (RWT)",
    )

    # While on air the row exists but has no duration yet.
    rows = _rows(audit_db)
    assert len(rows) == 1
    assert rows[0].duration_seconds is None
    assert rows[0].deactivated_at is None

    controller.deactivate(17, force=True)

    rows = _rows(audit_db)
    assert len(rows) == 1, "release must update the activation row, not insert a new one"
    assert rows[0].deactivated_at is not None
    assert rows[0].duration_seconds is not None


def test_failed_activation_is_audited_as_a_failure(audit_db, monkeypatch):
    """A relay that could not be keyed is recorded with the error."""
    app, db, _model = audit_db
    controller = GPIOController(db_session=db.session, db_app=app, logger=None)
    monkeypatch.setattr(GPIOController, "_get_or_create_device", lambda self, config: None)
    controller.add_pin(GPIOPinConfig(pin=17, name="Transmitter PTT", debounce_ms=0))

    assert controller.activate(pin=17, reason="Broadcast playout") is False

    rows = _rows(audit_db)
    assert len(rows) == 1
    assert rows[0].success is False
    assert "not available" in (rows[0].error_message or "")


# ---------------------------------------------------------------------------
# Hold bookkeeping — relays must drop at end-of-broadcast, not at the watchdog
# ---------------------------------------------------------------------------


class _StubController:
    """Controller stub tracking per-pin active state like the real one."""

    def __init__(self):
        self.active = set()
        self.deactivated = []
        self.behavior_manager = None

    def activate(self, *, pin, activation_type=None, operator=None, alert_id=None,
                 reason=None, flash=None):
        if pin in self.active:
            return False  # the real controller refuses an already-active pin
        self.active.add(pin)
        return True

    def deactivate(self, pin, force=False):
        self.deactivated.append(pin)
        self.active.discard(pin)
        return True

    def get_state(self, pin):
        return GPIOState.ACTIVE if pin in self.active else GPIOState.INACTIVE


def _manager(controller, matrix):
    return GPIOBehaviorManager(
        controller=controller,
        pin_configs=[GPIOPinConfig(pin=pin, name=f"Pin {pin}") for pin in matrix],
        behavior_matrix=matrix,
        logger=None,
    )


def test_hold_adopts_an_already_energised_pin(monkeypatch):
    """A pin already ON (pulse overlap / second behavior) is still released.

    ``activate()`` refuses an active pin, so the hold used to be dropped on the
    floor and ``end_alert()`` had nothing to release — the relay stayed keyed
    until the watchdog timed out.
    """
    controller = _StubController()
    manager = _manager(
        controller,
        {17: {GPIOBehavior.TRANSMITTER_PTT, GPIOBehavior.DURATION_OF_ALERT}},
    )

    # Something already energised the pin (e.g. an in-flight incoming pulse).
    controller.active.add(17)

    assert manager.start_alert(alert_id="a1", event_code="TOR") is True
    manager.end_alert(alert_id="a1", event_code="TOR")

    assert 17 in controller.deactivated
    assert 17 not in controller.active


def test_pulse_does_not_release_a_pin_a_hold_adopted(monkeypatch):
    """A finishing 3 s pulse must not un-key a relay the broadcast now holds."""
    controller = _StubController()
    manager = _manager(controller, {17: {GPIOBehavior.INCOMING_ALERT}})

    # ``gpio.behavior.time`` is the stdlib module, so the patch below is process-wide.
    # Scope the stub to this thread and delegate everything else to the real
    # sleep, so a concurrently running test can never pick it up.
    real_sleep = gpio.behavior.time.sleep
    test_thread = threading.get_ident()

    def _broadcast_starts_during_the_pulse(seconds):
        if threading.get_ident() != test_thread:
            real_sleep(seconds)
            return
        # The alert went to air while the incoming pulse was still running, so
        # the broadcast hold adopted the already-energised pin.
        manager._hold_map[17] = {GPIOBehavior.TRANSMITTER_PTT}

    monkeypatch.setattr(gpio.behavior.time, "sleep", _broadcast_starts_during_the_pulse)
    manager._pulse_pin(pin=17, duration=3.0, label="Incoming Alert", alert_id="a1")

    assert controller.deactivated == [], "the pulse must not un-key the transmitter"
    assert 17 in controller.active


# ---------------------------------------------------------------------------
# Rising/falling edge pairing in the subprocess
# ---------------------------------------------------------------------------


class _EdgeController:
    def __init__(self, behavior_manager=None):
        self.behavior_manager = behavior_manager
        self.activate_all_calls = []
        self.deactivate_all_calls = []

    def activate_all(self, *, activation_type=None, operator=None, alert_id=None, reason=None):
        self.activate_all_calls.append(alert_id)
        return {1: True}

    def deactivate_all(self, *, force=False):
        self.deactivate_all_calls.append(force)
        return {1: True}


class _UnhandledBehaviorManager:
    """A configured matrix that holds nothing for this broadcast."""

    def __init__(self):
        self.ends = 0

    def start_alert(self, **_kwargs):
        return False

    def end_alert(self, **_kwargs):
        self.ends += 1

    def trigger_incoming_alert(self, **_kwargs):
        pass


def _patch_state(monkeypatch, *, active):
    import app_utils.eas as eas

    payload = {"active": True, "identifier": "a1", "event_code": "TOR", "source": "auto"} \
        if active else {"active": False}
    monkeypatch.setattr(eas, "get_broadcast_state", lambda: dict(payload))
    monkeypatch.setattr(eas, "get_incoming_alert_state", lambda: {"incoming": False})
    monkeypatch.setattr(indicators, "_redis_ok", lambda: True)


def test_activate_all_fallback_is_released_on_the_falling_edge(monkeypatch):
    """Regression: the fallback keyed every pin but nothing ever dropped them.

    ``end_alert()`` only releases pins the behavior manager holds, so a rising
    edge that fell back to ``activate_all()`` left the whole relay bank keyed
    until each pin's 300 s watchdog fired.
    """
    bm = _UnhandledBehaviorManager()
    controller = _EdgeController(behavior_manager=bm)
    monitor = AlertIndicatorMonitor(gpio_controller=controller)

    _patch_state(monkeypatch, active=True)
    monitor.refresh()
    assert controller.activate_all_calls == ["a1"]

    _patch_state(monkeypatch, active=False)
    monitor.refresh()
    assert controller.deactivate_all_calls == [True]
    # end_alert still runs so the manager's own bookkeeping stays in step.
    assert bm.ends == 1


def test_falling_edge_without_a_known_rising_edge_releases_both_paths(monkeypatch):
    """Started mid-broadcast: release through both paths rather than guess."""

    class _Manager(_UnhandledBehaviorManager):
        def start_alert(self, **_kwargs):
            return True

    bm = _Manager()
    controller = _EdgeController(behavior_manager=bm)
    monitor = AlertIndicatorMonitor(gpio_controller=controller)

    # Seed the monitor as though the rising edge happened before it was watching.
    monitor._broadcast_was_active = True

    _patch_state(monkeypatch, active=False)
    monitor.refresh()

    assert bm.ends == 1
    assert controller.deactivate_all_calls == [True]


def test_managed_broadcast_does_not_force_deactivate_all(monkeypatch):
    """A cleanly managed alert releases via end_alert only."""

    class _Manager(_UnhandledBehaviorManager):
        def start_alert(self, **_kwargs):
            return True

    bm = _Manager()
    controller = _EdgeController(behavior_manager=bm)
    monitor = AlertIndicatorMonitor(gpio_controller=controller)

    _patch_state(monkeypatch, active=True)
    monitor.refresh()
    assert controller.activate_all_calls == []

    _patch_state(monkeypatch, active=False)
    monitor.refresh()
    assert bm.ends == 1
    assert controller.deactivate_all_calls == []


# ---------------------------------------------------------------------------
# Logs hub rendering
# ---------------------------------------------------------------------------


class _Row:
    def __init__(self, **kwargs):
        self.activation_type = kwargs.get("activation_type", "automatic")
        self.operator = kwargs.get("operator")
        self.duration_seconds = kwargs.get("duration_seconds")
        self.reason = kwargs.get("reason")
        self.success = kwargs.get("success", True)
        self.error_message = kwargs.get("error_message")


def test_failed_activation_renders_as_an_error():
    row = _Row(success=False, error_message="GPIO hardware not available for pin 17")
    assert gpio_log_level(row) == "ERROR"
    assert "FAILED: GPIO hardware not available for pin 17" in gpio_log_message(row)


def test_successful_activation_renders_as_info_with_a_rounded_duration():
    row = _Row(duration_seconds=61.872045, reason="Broadcast playout (TOR)")
    assert gpio_log_level(row) == "INFO"
    message = gpio_log_message(row)
    assert "Duration: 61.9s" in message
    assert "Reason: Broadcast playout (TOR)" in message
    assert "FAILED" not in message


def test_in_flight_activation_renders_as_active():
    assert gpio_log_duration(_Row(duration_seconds=None)) == "Active"


def test_failed_activation_is_never_reported_as_active():
    """A failed activation also has no duration — but the relay never moved."""
    row = _Row(duration_seconds=None, success=False, error_message="no hardware")
    assert gpio_log_duration(row) == "N/A"
    assert "Duration: Active" not in gpio_log_message(row)
