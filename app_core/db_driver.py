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

"""Keep bare ``postgresql://`` URLs on the psycopg2 driver.

SQLAlchemy 2.1 changed the default DBAPI for a driverless ``postgresql://``
URL from psycopg2 to psycopg (3). This project installs only
``psycopg2-binary``, and ``DATABASE_URL`` is read raw in several entry
points (app.py, the poller, the audio/SDR services, service bootstrap),
so on 2.1 every one of them failed at ``create_engine`` with
``ModuleNotFoundError: No module named 'psycopg'``. Registering psycopg2
for the bare ``postgresql`` name restores the 2.0 behaviour in one place;
URLs that name a driver explicitly are unaffected.
"""

from sqlalchemy.dialects import registry


def pin_postgres_driver() -> None:
    """Resolve driverless ``postgresql://`` URLs to psycopg2."""
    registry.register(
        "postgresql", "sqlalchemy.dialects.postgresql.psycopg2", "PGDialect_psycopg2"
    )


__all__ = ["pin_postgres_driver"]
