#!/usr/bin/env python3
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

"""Prove that a backup actually restores.

A backup that has never been restored is not a proven backup. This script
restores a backup's ``alerts_database.sql`` dump into a throwaway scratch
PostgreSQL database (never the live one), runs a handful of sanity checks
against it, and always drops the scratch database afterward -- deliberately
scoped to a DB-only check rather than spinning up a shadow app instance,
which would risk contending for GPIO/SDR/hardware singletons on a running
appliance.

Exit codes (mirrors tools/validate_restore.py's convention):
    0 - all checks passed
    1 - one or more checks failed
    2 - could not run the verification at all (bad args, DB unreachable, ...)
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit


def _run(cmd: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _scratch_url(database_url: str, scratch_name: str) -> str:
    """Return *database_url* with its path (database name) replaced."""
    parts = urlsplit(database_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{scratch_name}", parts.query, parts.fragment))


def _maintenance_url(database_url: str) -> str:
    """Return *database_url* pointed at the always-present 'postgres' database."""
    return _scratch_url(database_url, "postgres")


def _add_check(details: List[Dict[str, Any]], name: str, passed: bool, message: str) -> None:
    details.append({"name": name, "passed": passed, "message": message})


def verify(backup_dir: Path, database_url: str) -> Dict[str, Any]:
    """Run the full verification. Returns a result dict; never raises for
    an ordinary check failure (only for setup errors, caught by main())."""

    started = time.time()
    details: List[Dict[str, Any]] = []

    dump_path = backup_dir / "alerts_database.sql"
    if not dump_path.exists() or dump_path.stat().st_size == 0:
        _add_check(details, "dump_present", False, f"Missing or empty database dump: {dump_path}")
        return {"passed": False, "details": details, "duration_seconds": time.time() - started}
    _add_check(details, "dump_present", True, f"Found dump ({dump_path.stat().st_size} bytes)")

    scratch_pgdump_url = database_url.replace("postgresql+psycopg2://", "postgresql://")
    scratch_name = f"eas_verify_{int(time.time())}"
    scratch_url = _scratch_url(scratch_pgdump_url, scratch_name)
    maintenance_url = _maintenance_url(scratch_pgdump_url)

    created = False
    try:
        create = _run(["psql", maintenance_url, "-v", "ON_ERROR_STOP=1",
                        "-c", f'CREATE DATABASE "{scratch_name}"'])
        if create.returncode != 0:
            _add_check(details, "scratch_db_create", False, create.stderr.strip()[:500])
            return {"passed": False, "details": details, "duration_seconds": time.time() - started}
        created = True
        _add_check(details, "scratch_db_create", True, f"Created scratch database {scratch_name}")

        restore = _run(["psql", scratch_url, "-v", "ON_ERROR_STOP=1", "-f", str(dump_path)], timeout=600)
        restore_ok = restore.returncode == 0
        _add_check(
            details, "restore_completes", restore_ok,
            "Restore completed without error" if restore_ok else restore.stderr.strip()[-1000:],
        )
        if not restore_ok:
            return {"passed": False, "details": details, "duration_seconds": time.time() - started}

        table_count = _run(["psql", scratch_url, "-t", "-A", "-c",
                             "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"])
        try:
            n_tables = int((table_count.stdout or "0").strip())
        except ValueError:
            n_tables = 0
        _add_check(details, "schema_present", n_tables > 0, f"{n_tables} tables in public schema")

        alembic = _run(["psql", scratch_url, "-t", "-A", "-c", "SELECT version_num FROM alembic_version"])
        alembic_version = (alembic.stdout or "").strip()
        _add_check(
            details, "alembic_version_present", bool(alembic_version),
            f"alembic_version = {alembic_version or '(none)'}",
        )

        for table in ("cap_alerts", "users"):
            probe = _run(["psql", scratch_url, "-t", "-A", "-c", f"SELECT count(*) FROM {table}"])
            _add_check(
                details, f"table_queryable_{table}", probe.returncode == 0,
                f"SELECT count(*) FROM {table} -> {(probe.stdout or probe.stderr).strip()[:200]}",
            )
    finally:
        if created:
            _run(["psql", maintenance_url, "-v", "ON_ERROR_STOP=1",
                  "-c", f'DROP DATABASE IF EXISTS "{scratch_name}"'])

    passed = all(c["passed"] for c in details)
    return {"passed": passed, "details": details, "duration_seconds": time.time() - started}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a backup actually restores")
    parser.add_argument("backup_dir", help="Path to a backup directory (containing alerts_database.sql)")
    parser.add_argument("--database-url", default=None,
                         help="DATABASE_URL to use (defaults to $DATABASE_URL)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON to stdout")
    args = parser.parse_args()

    import os
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: --database-url or $DATABASE_URL is required", file=sys.stderr)
        return 2

    backup_dir = Path(args.backup_dir)
    if not backup_dir.is_dir():
        print(f"ERROR: not a directory: {backup_dir}", file=sys.stderr)
        return 2

    try:
        result = verify(backup_dir, database_url)
    except Exception as exc:
        result = {"passed": False, "details": [], "duration_seconds": 0.0, "error": str(exc)}
        if args.json:
            print(json.dumps(result))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result))
    else:
        for check in result["details"]:
            mark = "PASS" if check["passed"] else "FAIL"
            print(f"[{mark}] {check['name']}: {check['message']}")
        print(f"\nOverall: {'PASSED' if result['passed'] else 'FAILED'} "
              f"({result['duration_seconds']:.1f}s)")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
