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

"""Tests for the GPIO-triggered "Forward Last Alert" input action."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy


@pytest.fixture
def app_with_messages(monkeypatch):
    """A standalone Flask + Flask-SQLAlchemy app with a minimal EASMessage
    table, mirroring the fixture style used by
    tests/test_gpio_activation_logging.py -- avoids pulling in the full
    PostGIS-typed model set for a test that only needs id/audio_data/created_at.
    """
    db = SQLAlchemy()
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    db.init_app(app)

    class EASMessageStub(db.Model):
        __tablename__ = "eas_messages"
        id = db.Column(db.Integer, primary_key=True)
        audio_data = db.Column(db.LargeBinary)
        created_at = db.Column(db.DateTime(timezone=True))

    with app.app_context():
        db.create_all()

    import app_core.models as app_models
    monkeypatch.setattr(app_models, "EASMessage", EASMessageStub)
    monkeypatch.setattr(app_models, "db", db)

    yield app, db, EASMessageStub

    with app.app_context():
        db.engine.dispose()


def _seed_message(db, model, *, audio_data=b"x", age_seconds=0):
    row = model(
        audio_data=audio_data,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    )
    db.session.add(row)
    db.session.commit()
    return row.id


def test_forwards_most_recent_message_by_created_at(app_with_messages, monkeypatch):
    from app_core.audio import gpio_input_actions

    app, db, model = app_with_messages
    with app.app_context():
        older_id = _seed_message(db, model, age_seconds=120)
        newest_id = _seed_message(db, model, age_seconds=0)

        launched = {}

        def fake_popen(command, **kwargs):
            launched["command"] = command
            class _P:
                pass
            return _P()

        monkeypatch.setattr(gpio_input_actions.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(
            "app_utils.eas.get_broadcast_state", lambda: {"active": False}
        )

        gpio_input_actions.forward_most_recent_alert()

        assert "command" in launched
        assert str(newest_id) in launched["command"]
        assert str(older_id) not in launched["command"]
        assert "--operator" in launched["command"]
        assert "gpio-input" in launched["command"]


def test_skipped_when_broadcast_already_active(app_with_messages, monkeypatch):
    from app_core.audio import gpio_input_actions

    app, db, model = app_with_messages
    with app.app_context():
        _seed_message(db, model)

        launched = {"called": False}

        def fake_popen(command, **kwargs):
            launched["called"] = True

        monkeypatch.setattr(gpio_input_actions.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(
            "app_utils.eas.get_broadcast_state", lambda: {"active": True}
        )

        gpio_input_actions.forward_most_recent_alert()

        assert launched["called"] is False


def test_noop_when_no_message_has_audio(app_with_messages, monkeypatch):
    from app_core.audio import gpio_input_actions

    app, db, model = app_with_messages
    with app.app_context():
        # A message row exists but with no audio_data -- must not be picked.
        row = model(audio_data=None, created_at=datetime.now(timezone.utc))
        db.session.add(row)
        db.session.commit()

        launched = {"called": False}
        monkeypatch.setattr(
            gpio_input_actions.subprocess, "Popen",
            lambda *a, **k: launched.__setitem__("called", True),
        )
        monkeypatch.setattr(
            "app_utils.eas.get_broadcast_state", lambda: {"active": False}
        )

        # Must not raise even though nothing broadcastable exists.
        gpio_input_actions.forward_most_recent_alert()

        assert launched["called"] is False


def test_dispatch_wiring_calls_forward_action(monkeypatch):
    from app_core import gpio_input_listener

    calls = []
    monkeypatch.setattr(
        "app_core.audio.gpio_input_actions.forward_most_recent_alert",
        lambda operator="gpio-input": calls.append(operator),
    )

    gpio_input_listener._dispatch_input_action({"pin": 24, "action": "forward_last_alert"})

    assert len(calls) == 1
