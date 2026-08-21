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

"""Tests for relay interlock (mutual-exclusion) group enforcement.

Covers the false-positive-free mutual-exclusion guarantee: two relays in the
same interlock group must never both read ACTIVE at once, whether activated
manually or via the alert-driven behavior pipeline.
"""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

import app_core.models as app_models
from app_utils.gpio import (
    GPIOActivationType,
    GPIOBehavior,
    GPIOBehaviorManager,
    GPIOController,
    GPIOInterlockGroup,
    GPIOPinConfig,
    GPIOState,
)
from app_utils.gpio.config_loaders import load_gpio_interlock_groups_from_db


class _FakeDevice:
    def __init__(self):
        self.value = False

    def on(self):
        self.value = True

    def off(self):
        self.value = False

    def close(self):
        pass


@pytest.fixture
def audit_db(monkeypatch):
    """A standalone Flask + Flask-SQLAlchemy app with a GPIO activation table.

    Mirrors ``tests/test_gpio_activation_logging.py``'s fixture: a minimal
    stand-in for ``gpio_activation_logs`` so ``_save_activation_event`` (called
    by the controller for an interlock refusal, same as any other failed
    activation) has somewhere to write.
    """
    db = SQLAlchemy()
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
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

    with app.app_context():
        db.engine.dispose()


def _rows(audit_db):
    app, _db, model = audit_db
    with app.app_context():
        return model.query.order_by(model.id).all()


def _make_controller(audit_db, monkeypatch, group, pins=(17, 27)):
    """A controller with two configured pins, wired into one interlock group."""
    app, db, _model = audit_db
    controller = GPIOController(db_session=db.session, db_app=app, logger=None)

    device_a, device_b = _FakeDevice(), _FakeDevice()
    devices = {pins[0]: device_a, pins[1]: device_b}
    monkeypatch.setattr(
        GPIOController,
        "_get_or_create_device",
        lambda self, config: devices[config.pin],
    )

    controller.add_pin(GPIOPinConfig(pin=pins[0], name="Main PTT", debounce_ms=0))
    controller.add_pin(GPIOPinConfig(pin=pins[1], name="Backup PTT", debounce_ms=0))
    controller.interlock_groups = [group]
    return controller


def _group(pins=(17, 27), force_deactivate_conflict=False):
    return GPIOInterlockGroup(
        name="Main/Backup PTT",
        pins=frozenset(pins),
        force_deactivate_conflict=force_deactivate_conflict,
    )


# ---------------------------------------------------------------------------
# Core mutual-exclusion behavior
# ---------------------------------------------------------------------------


def test_second_pin_refused_while_first_is_active(audit_db, monkeypatch):
    controller = _make_controller(audit_db, monkeypatch, _group())

    assert controller.activate(17, activation_type=GPIOActivationType.MANUAL) is True
    assert controller.activate(27, activation_type=GPIOActivationType.MANUAL) is False

    assert controller.get_state(17) == GPIOState.ACTIVE
    assert controller.get_state(27) == GPIOState.INACTIVE


def test_refusal_is_audited_with_interlock_reason(audit_db, monkeypatch):
    controller = _make_controller(audit_db, monkeypatch, _group())

    controller.activate(17, activation_type=GPIOActivationType.MANUAL)
    controller.activate(27, activation_type=GPIOActivationType.MANUAL, reason="test")

    rows = _rows(audit_db)
    refusal_rows = [r for r in rows if r.pin == 27]
    assert len(refusal_rows) == 1
    assert refusal_rows[0].success is False
    assert "interlock" in refusal_rows[0].error_message.lower()
    assert "Main/Backup PTT" in refusal_rows[0].error_message


def test_force_deactivate_conflict_releases_the_active_sibling(audit_db, monkeypatch):
    controller = _make_controller(
        audit_db, monkeypatch, _group(force_deactivate_conflict=True)
    )

    assert controller.activate(17, activation_type=GPIOActivationType.MANUAL) is True
    assert controller.activate(27, activation_type=GPIOActivationType.MANUAL) is True

    assert controller.get_state(17) == GPIOState.INACTIVE
    assert controller.get_state(27) == GPIOState.ACTIVE


def test_sequential_use_is_unaffected(audit_db, monkeypatch):
    """The interlock only blocks *concurrent* activation, not later reuse."""
    controller = _make_controller(audit_db, monkeypatch, _group())

    assert controller.activate(17, activation_type=GPIOActivationType.MANUAL) is True
    assert controller.deactivate(17, force=True) is True
    assert controller.activate(27, activation_type=GPIOActivationType.MANUAL) is True


def test_no_interlock_groups_is_a_no_op(audit_db, monkeypatch):
    """A controller with no groups configured behaves exactly as before."""
    app, db, _model = audit_db
    controller = GPIOController(db_session=db.session, db_app=app, logger=None)
    device_a, device_b = _FakeDevice(), _FakeDevice()
    devices = {17: device_a, 27: device_b}
    monkeypatch.setattr(
        GPIOController, "_get_or_create_device", lambda self, config: devices[config.pin]
    )
    controller.add_pin(GPIOPinConfig(pin=17, name="Main PTT", debounce_ms=0))
    controller.add_pin(GPIOPinConfig(pin=27, name="Backup PTT", debounce_ms=0))

    assert controller.activate(17, activation_type=GPIOActivationType.MANUAL) is True
    assert controller.activate(27, activation_type=GPIOActivationType.MANUAL) is True


# ---------------------------------------------------------------------------
# Alert-pipeline integration: GPIOBehaviorManager.start_alert()
# ---------------------------------------------------------------------------


def test_start_alert_with_two_grouped_ptt_pins_activates_exactly_one(audit_db, monkeypatch):
    """Two pins sharing TRANSMITTER_PTT, both in one interlock group: only one
    actually keys, and the "nothing held, key everything" fallback must not
    fire just because the second pin was refused by the interlock."""
    group = _group()
    controller = _make_controller(audit_db, monkeypatch, group)

    behavior_matrix = {
        17: {GPIOBehavior.TRANSMITTER_PTT},
        27: {GPIOBehavior.TRANSMITTER_PTT},
    }
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=[controller._pins[17], controller._pins[27]],
        behavior_matrix=behavior_matrix,
        logger=None,
        interlock_groups=[group],
    )

    handled = manager.start_alert(alert_id="urn:oid:interlock-test", event_code="TOR")

    assert handled is True
    active_pins = [p for p in (17, 27) if controller.get_state(p) == GPIOState.ACTIVE]
    assert len(active_pins) == 1, "exactly one grouped PTT pin should key, not zero or both"


def test_validate_configuration_warns_on_shared_hold_behavior(audit_db, monkeypatch):
    group = _group()
    controller = _make_controller(audit_db, monkeypatch, group)

    behavior_matrix = {
        17: {GPIOBehavior.TRANSMITTER_PTT},
        27: {GPIOBehavior.TRANSMITTER_PTT},
    }
    manager = GPIOBehaviorManager(
        controller=None,
        pin_configs=[controller._pins[17], controller._pins[27]],
        behavior_matrix=behavior_matrix,
        logger=None,
        interlock_groups=[group],
    )

    warnings = manager.validate_configuration()
    assert any("Main/Backup PTT" in w and "interlock" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def test_load_gpio_interlock_groups_from_db_round_trip(monkeypatch):
    """Groups with fewer than 2 pins are dropped; well-formed ones pass through."""
    import app_core.relay_interlocks as relay_interlocks

    def fake_get_groups(enabled_only=True):
        return [
            {"id": 1, "name": "Main/Backup PTT", "enabled": True,
             "force_deactivate_conflict": False, "pins": [17, 27]},
            {"id": 2, "name": "Bad group", "enabled": True,
             "force_deactivate_conflict": False, "pins": [5]},
        ]

    monkeypatch.setattr(relay_interlocks, "get_relay_interlock_groups", fake_get_groups)

    groups = load_gpio_interlock_groups_from_db(logger=None)

    assert len(groups) == 1
    assert groups[0].name == "Main/Backup PTT"
    assert groups[0].pins == frozenset({17, 27})
