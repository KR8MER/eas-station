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

"""Driverless ``postgresql://`` URLs must keep resolving to psycopg2.

SQLAlchemy 2.1 made psycopg (3) the default for a bare ``postgresql://``
URL; only psycopg2 is installed, so every entry point that hands a raw
``DATABASE_URL`` to SQLAlchemy failed with ``No module named 'psycopg'``
(the CI failure on the SQLAlchemy 2.1.2 bump). ``app_core`` pins it.
"""

import sqlalchemy as sa

import app_core  # noqa: F401 -- importing the package applies the pin


def test_bare_postgresql_url_uses_psycopg2():
    engine = sa.create_engine("postgresql://user@localhost/db")
    assert engine.dialect.driver == "psycopg2"


def test_explicit_driver_is_left_alone():
    engine = sa.create_engine("postgresql+psycopg2://user@localhost/db")
    assert engine.dialect.driver == "psycopg2"
