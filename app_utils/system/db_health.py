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

"""Database connectivity probe: version, size, active connections."""

from typing import Any, Dict

from sqlalchemy import text


def _collect_database_health(db, logger) -> Dict[str, Any]:
    """Probe the database connection and a few cheap health figures.

    If a prior query in the same scoped session left the PostgreSQL
    transaction in the aborted state (``InFailedSqlTransaction``), every
    subsequent statement raises until a rollback. The websocket push loop
    reuses one session across many emits, so a single failed query elsewhere
    would otherwise wedge this probe forever.
    """

    db_status = "unknown"
    db_info: Dict[str, Any] = {}

    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        version_result = db.session.execute(text("SELECT version()"))
        if version_result:
            db_status = "connected"
            version_value = version_result.scalar()
            db_info["version"] = version_value if version_value else "Unknown"

            try:
                size_result = db.session.execute(
                    text("SELECT pg_size_pretty(pg_database_size(current_database()))")
                ).fetchone()
                if size_result:
                    db_info["size"] = size_result[0]
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                db_info["size"] = "Unknown"

            try:
                conn_result = db.session.execute(
                    text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                ).fetchone()
                if conn_result:
                    db_info["active_connections"] = conn_result[0]
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                db_info["active_connections"] = "Unknown"
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.warning("Database health probe failed: %s", exc)
        db_status = "error"
        db_info["error"] = str(exc)[:200]

    return {"status": db_status, "info": db_info}
