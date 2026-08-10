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

"""Database health check and the optimize (VACUUM/ANALYZE) action."""

from typing import Union

from flask import current_app, jsonify
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import SystemLog
from app_utils import format_bytes, local_now, utc_now

from .blueprint import maintenance_bp


@maintenance_bp.route("/admin/check_db_health", methods=["GET"])
def check_db_health():
    """Provide a quick health check of the database connection and size."""

    try:
        db.session.execute(text("SELECT 1"))
        connectivity_status = "Connected"
    except OperationalError as exc:
        current_app.logger.error("Database connectivity check failed: %s", exc)
        return jsonify({"error": "Database connectivity check failed."}), 500
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.error("Unexpected error during database health check: %s", exc)
        return (
            jsonify(
                {
                    "error": "Database health check encountered an unexpected error.",
                }
            ),
            500,
        )

    database_size = "Unavailable"
    try:
        size_bytes = db.session.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()
        if size_bytes is not None:
            database_size = format_bytes(size_bytes)
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.warning("Could not determine database size: %s", exc)

    active_connections: Union[str, int] = "Unavailable"
    try:
        connection_count = db.session.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database()"
            )
        ).scalar()
        if connection_count is not None:
            active_connections = int(connection_count)
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.warning("Could not determine active connection count: %s", exc)

    return jsonify(
        {
            "connectivity": connectivity_status,
            "database_size": database_size,
            "active_connections": active_connections,
            "checked_at": utc_now().isoformat(),
        }
    )

@maintenance_bp.route("/admin/optimize_db", methods=["POST"])
@require_permission('system.configure')
def optimize_database():
    """Optimize database performance using VACUUM and ANALYZE."""

    try:
        # Get database size before optimization
        size_before = db.session.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()

        # Run VACUUM to reclaim space and optimize
        # Note: VACUUM cannot run inside a transaction block
        db.session.commit()  # Ensure any pending transaction is committed
        connection = db.engine.raw_connection()
        try:
            connection.set_isolation_level(0)  # AUTOCOMMIT mode
            cursor = connection.cursor()
            cursor.execute("VACUUM ANALYZE")
            cursor.close()
        finally:
            connection.close()

        # Important: Remove the session after raw connection usage
        # This ensures the next query gets a fresh connection
        db.session.remove()

        # Get database size after optimization (with fresh session)
        size_after = db.session.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()

        space_reclaimed = size_before - size_after if size_before and size_after else 0

        # Log the optimization
        log_entry = SystemLog(
            level="INFO",
            message="Database optimization completed",
            module="admin",
            details={
                "optimized_at_utc": utc_now().isoformat(),
                "optimized_at_local": local_now().isoformat(),
                "size_before": format_bytes(size_before) if size_before else "Unknown",
                "size_after": format_bytes(size_after) if size_after else "Unknown",
                "space_reclaimed": format_bytes(space_reclaimed) if space_reclaimed > 0 else "0 bytes",
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        current_app.logger.info("Database optimized successfully. Space reclaimed: %s", format_bytes(space_reclaimed) if space_reclaimed > 0 else "0 bytes")

        return jsonify({
            "message": "Database optimized successfully",
            "size_before": format_bytes(size_before) if size_before else "Unknown",
            "size_after": format_bytes(size_after) if size_after else "Unknown",
            "space_reclaimed": format_bytes(space_reclaimed) if space_reclaimed > 0 else "0 bytes",
        })

    except Exception as exc:
        current_app.logger.error("Error optimizing database: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Database optimization failed: {str(exc)}"}), 500
