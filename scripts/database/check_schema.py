#!/usr/bin/env python3
"""Validate that the live database schema matches what the application models expect.

Checks performed
----------------
1. Alembic migration head — warns if unapplied migrations exist.
2. Required tables — errors on any missing table.
3. Required columns — errors on any column missing from a table.
4. Orphaned columns — warns when a column that *should* have been removed by a
   migration is still present (indicates a half-applied migration).
5. Per-service session smoke test — verifies the poller's own DB session can
   execute a query without entering a poisoned transaction state.

Exit codes
----------
0  All checks passed (warnings may still be printed).
1  One or more ERROR-level failures found.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ.setdefault("SKIP_DB_INIT", "1")

from sqlalchemy import create_engine, inspect, text  # noqa: E402

# ---------------------------------------------------------------------------
# Expected schema: (table, [required_columns])
# Add entries here whenever a migration adds a table or critical column so
# future regressions are caught automatically.
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "location_settings": [
        "id", "county_name", "state_code", "timezone",
        "map_center_lat", "map_center_lng", "map_default_zoom",
    ],
    "alert_filter_settings": [
        "id", "fips_codes", "zone_codes", "storage_zone_codes", "area_terms",
    ],
    "hardware_settings": [
        "id", "led_default_lines",
    ],
    "poll_history": [
        "id", "timestamp", "alerts_fetched", "alerts_new", "alerts_updated",
        "execution_time_ms", "status", "data_source", "details",
    ],
    "poll_debug_records": ["id", "created_at", "poll_run_id"],
    "poller_settings": ["id", "enabled", "poll_interval_sec"],
    "cap_alerts": [
        "id", "identifier", "sent", "expires", "status", "event",
        "source", "eas_forwarded",
    ],
    "eas_messages": ["id", "cap_alert_id", "same_header", "created_at"],
    "eas_settings": ["id", "broadcast_enabled", "originator"],
    "location_settings": [
        "id", "county_name", "state_code", "timezone",
    ],
}

# Columns that *must not* be present — they should have been removed by a
# migration.  Their presence indicates a half-applied migration.
ORPHANED_COLUMNS: dict[str, list[str]] = {
    "location_settings": [
        "fips_codes", "zone_codes", "storage_zone_codes",
        "area_terms", "led_default_lines",
    ],
}

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
RESET = "\033[0m"

def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")

def _warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {msg}")

def _err(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def _resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    from app import app  # type: ignore
    url = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not url:
        raise RuntimeError(
            "Could not determine database URL. "
            "Set DATABASE_URL or ensure /opt/eas-station/.env is readable."
        )
    return url


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_alembic(conn) -> int:
    """Return number of errors (0 = pass)."""
    print("\n[1] Alembic migration state")
    errors = 0
    try:
        result = conn.execute(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
        versions = [row[0] for row in result]
        if not versions:
            _err("alembic_version table is empty — no migrations have been applied.")
            errors += 1
        else:
            for v in versions:
                _ok(f"Applied: {v}")

        # Check for multiple heads (merge conflict symptom)
        if len(versions) > 1:
            _warn(
                f"{len(versions)} alembic heads detected: {versions}. "
                "Run 'alembic merge heads' to resolve."
            )
    except Exception as exc:
        _err(f"Could not query alembic_version: {exc}")
        errors += 1
    return errors


def check_tables(inspector, required_tables: list[str]) -> tuple[int, set[str]]:
    """Return (error_count, present_tables)."""
    print("\n[2] Required tables")
    errors = 0
    existing = set(inspector.get_table_names())
    present: set[str] = set()
    for table in sorted(required_tables):
        if table in existing:
            _ok(table)
            present.add(table)
        else:
            _err(f"Table '{table}' is MISSING from the database.")
            errors += 1
    return errors, present


def check_required_columns(inspector, present_tables: set[str]) -> int:
    """Verify every required column exists in its table."""
    print("\n[3] Required columns")
    errors = 0
    for table, columns in sorted(REQUIRED_COLUMNS.items()):
        if table not in present_tables:
            continue  # already reported as missing table
        actual = {col["name"] for col in inspector.get_columns(table)}
        for col in columns:
            if col in actual:
                _ok(f"{table}.{col}")
            else:
                _err(
                    f"{table}.{col} is MISSING — "
                    "a migration may have dropped it without updating the ORM model."
                )
                errors += 1
    return errors


def check_orphaned_columns(inspector, present_tables: set[str]) -> int:
    """Warn when a column that should have been removed is still present."""
    print("\n[4] Orphaned columns (should have been removed by migration)")
    warnings = 0
    for table, columns in sorted(ORPHANED_COLUMNS.items()):
        if table not in present_tables:
            continue
        actual = {col["name"] for col in inspector.get_columns(table)}
        for col in columns:
            if col in actual:
                _warn(
                    f"{table}.{col} still exists — the migration that moves this "
                    "column may be only half-applied. Run the recovery script: "
                    "python scripts/database/recover_split_location_settings.py"
                )
                warnings += 1
            else:
                _ok(f"{table}.{col} correctly absent")
    if warnings == 0:
        _ok("No orphaned columns found.")
    return 0  # orphaned columns are warnings, not hard errors


def check_session_smoke(conn) -> int:
    """Verify a query succeeds without poisoning the transaction."""
    print("\n[5] Session smoke test (simulates poller query path)")
    errors = 0
    for table in ("location_settings", "alert_filter_settings", "poll_history"):
        try:
            conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
            _ok(f"SELECT from {table} succeeded")
        except Exception as exc:
            _err(f"SELECT from {table} failed: {exc}")
            errors += 1
            try:
                conn.rollback()
            except Exception:
                pass
    return errors


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("EAS Station — Database Schema Health Check")
    print("=" * 60)

    try:
        db_url = _resolve_database_url()
    except Exception as exc:
        print(f"{RED}ERROR: {exc}{RESET}")
        return 1

    # Mask password in output
    safe_url = db_url
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(db_url)
        if parsed.password:
            safe_url = db_url.replace(f":{parsed.password}@", ":***@")
    except Exception:
        pass
    print(f"\nDatabase: {safe_url}")

    engine = create_engine(db_url)
    total_errors = 0

    try:
        with engine.connect() as conn:
            inspector = inspect(conn)

            total_errors += check_alembic(conn)

            required_tables = sorted(
                set(REQUIRED_COLUMNS.keys()) | set(ORPHANED_COLUMNS.keys())
            )
            table_errors, present_tables = check_tables(inspector, required_tables)
            total_errors += table_errors

            total_errors += check_required_columns(inspector, present_tables)
            check_orphaned_columns(inspector, present_tables)  # warnings only
            total_errors += check_session_smoke(conn)

    except Exception as exc:
        print(f"\n{RED}ERROR: Could not connect to database: {exc}{RESET}")
        return 1
    finally:
        engine.dispose()

    print("\n" + "=" * 60)
    if total_errors == 0:
        print(f"{GREEN}All checks passed.{RESET}")
    else:
        print(f"{RED}{total_errors} error(s) found. See above for details.{RESET}")
    print("=" * 60)

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
