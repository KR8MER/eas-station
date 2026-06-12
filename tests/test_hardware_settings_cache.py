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

"""Regression tests for the hardware-settings module-level instance cache.

The cache in app_core/hardware_settings.py holds a live HardwareSettings ORM
instance. Under gunicorn/gevent each request runs with its own scoped
session, so the cached instance can still be *persistent* in another
request's session when a new request comes in. Handing that instance out and
re-adding it to the current session raised:

    InvalidRequestError: Object '<HardwareSettings ...>' is already attached
    to session 'N' (this is 'M')

which broke Admin -> Hardware Settings "Save" / "Save & Restart".
"""

import threading

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app_core import hardware_settings as hw
from app_core._models_settings import HardwareSettings
from app_core.extensions import db


# SQLite cannot render the PostgreSQL JSONB columns the model declares;
# map them to plain JSON for the test database.
@compiles(JSONB, "sqlite")
def _render_jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def app(tmp_path):
    """Minimal Flask app bound to a file-backed SQLite database.

    A file (rather than :memory:) is used so two concurrent sessions on
    different threads see the same database, mirroring production where
    concurrent requests share one PostgreSQL instance.
    """
    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'hw.db'}"
    flask_app.config["TESTING"] = True
    db.init_app(flask_app)

    with flask_app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[HardwareSettings.__table__])

    # The module-level cache persists across tests; start each test clean.
    hw._settings_cache = None
    hw._cache_dirty = False
    yield flask_app
    hw._settings_cache = None
    hw._cache_dirty = False


def test_update_hardware_settings_same_context(app):
    """Plain read-then-update within a single request context works."""
    with app.app_context():
        settings = hw.get_hardware_settings()
        assert settings.id == 1

        updated = hw.update_hardware_settings(
            {"tower_light_serial_port": "/dev/ttyUSB1"}
        )
        assert updated.tower_light_serial_port == "/dev/ttyUSB1"
        db.session.remove()


def test_update_while_cache_attached_to_other_session(app):
    """Regression: cached instance owned by another live session.

    A holder thread populates the module cache inside its own app context
    (its own scoped session) and keeps that session open — exactly the
    state two overlapping gevent requests produce. The main thread must
    still be able to update settings without raising
    "Object is already attached to session".
    """
    cache_populated = threading.Event()
    release_holder = threading.Event()
    holder_errors = []

    def hold_session_open():
        with app.app_context():
            try:
                hw.get_hardware_settings()
            except Exception as exc:  # pragma: no cover - failure path
                holder_errors.append(exc)
            finally:
                cache_populated.set()
            release_holder.wait(timeout=10)

    holder = threading.Thread(target=hold_session_open)
    holder.start()
    assert cache_populated.wait(timeout=10), "holder thread never populated cache"

    try:
        with app.app_context():
            updated = hw.update_hardware_settings(
                {"tower_light_serial_port": "/dev/ttyACM0"}
            )
            assert updated.tower_light_serial_port == "/dev/ttyACM0"
            db.session.remove()
    finally:
        release_holder.set()
        holder.join(timeout=10)

    assert not holder_errors, f"holder thread failed: {holder_errors}"

    # The value must have actually been persisted, visible to a fresh read.
    with app.app_context():
        hw.invalidate_hardware_settings_cache()
        fresh = hw.get_tower_light_settings()
        assert fresh["serial_port"] == "/dev/ttyACM0"
        db.session.remove()
