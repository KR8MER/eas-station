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

"""Tests for app_core.minimal_app.create_minimal_app().

Covers the GitHub issue #2581 fix: CLI/timer scripts that only need
db.session get a bare Flask app bound to the shared SQLAlchemy extension,
with no routes and no subsystem initialization -- unlike app.py's
create_app(), which registers ~260 routes and every subsystem regardless
of whether the caller needs any of it.
"""

import pytest
from sqlalchemy import text

from app_core.minimal_app import create_minimal_app


def test_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_minimal_app()


def test_registers_no_routes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    app = create_minimal_app()
    rule_endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    # Flask always registers its own 'static' endpoint; nothing else should be present.
    assert rule_endpoints == {"static"}


def test_db_session_is_usable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    app = create_minimal_app()
    with app.app_context():
        from app_core.extensions import db

        assert db.session.execute(text("SELECT 1")).scalar() == 1


def test_sqlite_engine_options_avoid_postgres_only_kwargs(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    app = create_minimal_app()
    options = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
    # pool_size/max_overflow/pool_timeout are meaningless to pysqlite and
    # raise TypeError if passed through to create_engine() for a sqlite URL.
    assert "pool_size" not in options
    assert options["connect_args"] == {"check_same_thread": False}


def test_postgres_engine_options_use_a_small_pool(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg2://user:pass@localhost:5432/alerts"
    )
    app = create_minimal_app()
    options = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
    # A one-shot script never needs the gunicorn-worker-sized pool app.py
    # configures (pool_size=10, max_overflow=10) for long-lived workers.
    assert options["pool_size"] == 1
    assert options["max_overflow"] == 1
