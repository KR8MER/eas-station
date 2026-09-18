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

from __future__ import annotations

"""Lightweight Flask bootstrap for CLI/timer scripts that only need DB access.

``app.py``'s ``create_app()`` imports the full application module -- ~260
routes, TTS, Icecast, hardware proxies, and every other subsystem -- before
returning, and runs the 15-step ``initialize_database()`` schema-migration
sweep on top of that. That's the right cost for the long-lived web/worker
processes, but a one-shot script that just needs ``db.session`` pays the
whole bill every time it runs. ``create_minimal_app()`` builds a bare Flask
app bound only to the shared ``db`` extension (``app_core.extensions.db``)
-- no route registration, no subsystem init, no schema migration -- so a
script gets ORM access without importing ``app.py`` at all.

Not a replacement for ``app.py``'s ``create_app()`` in the web/worker
processes themselves: those need the real routes and subsystems, and their
schema-migration sweep is how the database actually gets kept in sync on
deploy. This is for the handful of standalone scripts (timer-driven or
run-by-hand) that only ever touch the ORM.
"""

import os
from typing import Optional

from flask import Flask

from app_core.extensions import db


def create_minimal_app(*, config_path: Optional[str] = None) -> Flask:
    """Build a Flask app with only the SQLAlchemy extension bound.

    Loads environment variables the same way ``app.py`` does (``CONFIG_PATH``
    if set, else the default ``.env``, both with ``override=True``) so a
    script behaves the same whether it's run under systemd -- where
    ``EnvironmentFile=`` already populates the process environment -- or by
    hand from a checkout that only has a ``.env`` file.

    Args:
        config_path: Overrides the ``CONFIG_PATH`` environment variable for
            callers that want to point at a specific env file explicitly.

    Returns:
        A ``Flask`` app with ``db`` initialized against it. No routes, no
        blueprints, no background workers -- just enough for
        ``with app.app_context(): ...`` to give ORM access.

    Raises:
        ValueError: if ``DATABASE_URL`` isn't set after loading env files.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a real dependency
        def load_dotenv(*_args, **_kwargs):
            return False

    resolved_config_path = config_path or os.environ.get("CONFIG_PATH")
    if resolved_config_path:
        load_dotenv(resolved_config_path, override=True)
    else:
        load_dotenv(override=True)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if database_url.startswith("sqlite"):
        # Matches app.py's own SQLite carve-out: pool_size/max_overflow/
        # pool_timeout and libpq connect_args are meaningless to pysqlite
        # and raise TypeError if passed.
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "connect_args": {"check_same_thread": False},
        }
    else:
        # A one-shot script never needs the gunicorn-worker-sized pool
        # (pool_size=10, max_overflow=10) app.py configures for two
        # long-lived workers -- one or two connections for the life of
        # the process is enough.
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "connect_args": {
                "connect_timeout": 5,
                "options": "-c statement_timeout=30s",
            },
            "pool_pre_ping": False,
            "pool_size": 1,
            "max_overflow": 1,
            "pool_timeout": 10,
        }

    db.init_app(app)
    return app


__all__ = ["create_minimal_app"]
