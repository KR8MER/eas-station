#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recover from a half-applied 20260506_split_location_settings migration.

Background
----------
Migration ``20260506_split_location_settings`` reorganises the
``location_settings`` table into three tables:

* ``location_settings``     – geographic identity only
* ``alert_filter_settings`` – fips/zone/storage_zone/area_terms (NEW)
* ``hardware_settings``     – gains ``led_default_lines``

Older versions of ``update.sh`` would, on any Alembic failure, silently fall
back to ``db.create_all()``. That fallback is destructive in this case: it
creates the new ``alert_filter_settings`` table empty, adds the new
``hardware_settings.led_default_lines`` column with its default ``[]``, and
*leaves the old columns* on ``location_settings`` untouched. ``alembic_version``
is also never advanced. Visible symptoms:

* FIPS code list / broadcast zones / storage zones / area terms appear empty
  in the UI even though the operator never cleared them.
* ``alembic current`` still reports ``20260505_add_mdc1200_to_eas_settings``
  (or earlier) instead of ``20260506_split_location_settings``.
* ``location_settings`` still has ``fips_codes``, ``zone_codes``,
  ``storage_zone_codes``, ``area_terms``, and ``led_default_lines`` columns
  alongside the new tables.

This script detects that exact half-migrated state and finishes the job:

1. Copies non-empty filtering data from ``location_settings`` into
   ``alert_filter_settings`` (only if the destination row would otherwise be
   defaulted/empty — never overwrites populated user data).
2. Copies a non-empty ``location_settings.led_default_lines`` into
   ``hardware_settings.led_default_lines`` (only if the destination is empty).
3. Drops the now-orphaned old columns from ``location_settings``.
4. Stamps ``alembic_version`` to ``20260506_split_location_settings``.

The script is idempotent and a **no-op** on a healthy database — it is safe to
run on every update. With ``--quiet`` it prints nothing when there is nothing
to do.

Usage::

    sudo -u eas-station /opt/eas-station/venv/bin/python \\
        /opt/eas-station/scripts/database/recover_split_location_settings.py [--quiet] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Allow running both via the venv (where /opt/eas-station is on sys.path) and
# directly from a checkout.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Skip the heavy app initialisation when we import the app for its config.
os.environ.setdefault("SKIP_DB_INIT", "1")

from sqlalchemy import create_engine, inspect, text  # noqa: E402

TARGET_REVISION = "20260506_split_location_settings"
LOCATION_TABLE = "location_settings"
FILTER_TABLE = "alert_filter_settings"
HARDWARE_TABLE = "hardware_settings"

OLD_COLUMNS_ON_LOCATION = [
    "fips_codes",
    "zone_codes",
    "storage_zone_codes",
    "area_terms",
    "led_default_lines",
]


def _resolve_database_url() -> str:
    """Resolve the SQLAlchemy database URL from the application config."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    # Fall back to importing the Flask app, which loads .env via app config.
    from app import app  # type: ignore

    url = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not url:
        raise RuntimeError(
            "Could not determine database URL. Set DATABASE_URL or ensure "
            "/opt/eas-station/.env is readable."
        )
    return url


def _is_empty_jsonb_value(value: Any) -> bool:
    """Return True if a JSONB-shaped value should be considered empty/default."""
    if value is None:
        return True
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return False
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _row_as_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    try:
        return dict(row)
    except Exception:
        return {}


def _alembic_current(connection) -> Optional[str]:
    try:
        result = connection.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        if row is None:
            return None
        return row[0]
    except Exception:
        return None


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _log(message: str, *, quiet: bool) -> None:
    if not quiet:
        print(message)


def recover(database_url: str, *, dry_run: bool = False, quiet: bool = False) -> int:
    """Run the recovery. Returns 0 on success, non-zero on hard error."""
    engine = create_engine(database_url)

    try:
        # Use engine.begin() so all reads and writes share one transaction.
        # SQLAlchemy 2.0 autobegins on .connect(), which means a later
        # explicit conn.begin() call would raise — putting everything inside
        # a single begin() block avoids that and gives us atomicity for free.
        with engine.begin() as conn:
            inspector = inspect(conn)

            if not _has_table(inspector, LOCATION_TABLE):
                _log(
                    f"[recover] {LOCATION_TABLE} not present - nothing to do.",
                    quiet=quiet,
                )
                return 0

            old_cols_present = [
                c for c in OLD_COLUMNS_ON_LOCATION if _has_column(inspector, LOCATION_TABLE, c)
            ]

            current_rev = _alembic_current(conn)
            filter_table_present = _has_table(inspector, FILTER_TABLE)
            hardware_has_led = _has_column(inspector, HARDWARE_TABLE, "led_default_lines")

            # Healthy state: old columns gone AND alembic at or past target revision.
            if not old_cols_present and current_rev == TARGET_REVISION:
                _log(
                    "[recover] Database already migrated to "
                    f"{TARGET_REVISION}. Nothing to do.",
                    quiet=quiet,
                )
                return 0

            # If the old columns are gone but alembic_version disagrees, just
            # stamp alembic_version. This is the trailing-stamp-only case.
            if not old_cols_present:
                if current_rev == TARGET_REVISION:
                    return 0
                _log(
                    "[recover] Old columns already removed but alembic_version is "
                    f"{current_rev!r}. Stamping alembic_version to {TARGET_REVISION}.",
                    quiet=False,
                )
                if dry_run:
                    _log("[recover] (dry-run) would update alembic_version", quiet=quiet)
                    return 0
                conn.execute(
                    text("UPDATE alembic_version SET version_num = :rev"),
                    {"rev": TARGET_REVISION},
                )
                _log("[recover] alembic_version stamped.", quiet=False)
                return 0

            # Otherwise we have a half-migrated DB: old columns still present.
            # First, ensure the destination tables/columns exist (a normal
            # alembic run would have created them; if alembic never ran at all
            # we'd actually need to invoke alembic itself, not this script).
            if not filter_table_present:
                _log(
                    f"[recover] {FILTER_TABLE} table is missing. This script can "
                    "only finish a half-applied migration; please run "
                    f"'alembic upgrade {TARGET_REVISION}' first.",
                    quiet=False,
                )
                return 2

            if not hardware_has_led:
                _log(
                    f"[recover] {HARDWARE_TABLE}.led_default_lines column is "
                    "missing. This script can only finish a half-applied "
                    f"migration; please run 'alembic upgrade {TARGET_REVISION}' first.",
                    quiet=False,
                )
                return 2

            _log(
                "[recover] Half-migrated database detected. "
                f"Old columns still present on {LOCATION_TABLE}: "
                f"{', '.join(old_cols_present)}. Finishing migration"
                f"{' (dry-run)' if dry_run else ''}...",
                quiet=False,
            )

            # Read the source data from location_settings.
            select_cols = ", ".join(old_cols_present)
            location_row = conn.execute(
                text(f"SELECT {select_cols} FROM {LOCATION_TABLE} LIMIT 1")
            ).fetchone()
            location_data = _row_as_dict(location_row)

            # Read current destination state.
            filter_row = conn.execute(
                text(
                    f"SELECT id, fips_codes, zone_codes, storage_zone_codes, area_terms "
                    f"FROM {FILTER_TABLE} ORDER BY id LIMIT 1"
                )
            ).fetchone()
            filter_data = _row_as_dict(filter_row)

            hw_row = conn.execute(
                text(
                    f"SELECT id, led_default_lines FROM {HARDWARE_TABLE} "
                    f"ORDER BY id LIMIT 1"
                )
            ).fetchone()
            hw_data = _row_as_dict(hw_row)

            # Decide which columns to copy. Only copy when the source has
            # meaningful (non-empty) data AND the destination is empty/default.
            filter_updates: Dict[str, Any] = {}
            for src_col in (
                "fips_codes",
                "zone_codes",
                "storage_zone_codes",
                "area_terms",
            ):
                if src_col not in old_cols_present:
                    continue
                src_value = location_data.get(src_col)
                if _is_empty_jsonb_value(src_value):
                    continue
                dest_value = filter_data.get(src_col)
                if not _is_empty_jsonb_value(dest_value):
                    # Destination already populated by a user / restore — do
                    # NOT overwrite.
                    continue
                filter_updates[src_col] = src_value

            led_payload: Optional[Any] = None
            if "led_default_lines" in old_cols_present:
                src_led = location_data.get("led_default_lines")
                dest_led = hw_data.get("led_default_lines") if hw_data else None
                if not _is_empty_jsonb_value(src_led) and _is_empty_jsonb_value(dest_led):
                    led_payload = src_led

            if dry_run:
                if filter_updates:
                    _log(
                        f"[recover] (dry-run) would copy {sorted(filter_updates)} "
                        f"into {FILTER_TABLE} (insert if absent).",
                        quiet=quiet,
                    )
                if led_payload is not None:
                    _log(
                        f"[recover] (dry-run) would copy led_default_lines into "
                        f"{HARDWARE_TABLE}.",
                        quiet=quiet,
                    )
                _log(
                    f"[recover] (dry-run) would drop columns from {LOCATION_TABLE}: "
                    f"{', '.join(old_cols_present)}.",
                    quiet=quiet,
                )
                _log(
                    f"[recover] (dry-run) would stamp alembic_version to {TARGET_REVISION}.",
                    quiet=quiet,
                )
                return 0

            # All mutations happen inside the single transaction opened by
            # engine.begin() above. If anything fails, the half-migrated
            # state is preserved as-is.
            # 1. Populate alert_filter_settings.
            if filter_data:
                if filter_updates:
                    set_clause = ", ".join(
                        f"{col} = (:{col})::jsonb" for col in filter_updates
                    )
                    params = {
                        col: json.dumps(val) if not isinstance(val, str) else val
                        for col, val in filter_updates.items()
                    }
                    params["row_id"] = filter_data["id"]
                    conn.execute(
                        text(
                            f"UPDATE {FILTER_TABLE} SET {set_clause} "
                            f"WHERE id = :row_id"
                        ),
                        params,
                    )
            else:
                # No row in alert_filter_settings yet — insert one with
                # whatever we have, defaulting empty fields to [].
                insert_cols = ["id"]
                insert_values = ["1"]
                params: Dict[str, Any] = {}
                for col in (
                    "fips_codes",
                    "zone_codes",
                    "storage_zone_codes",
                    "area_terms",
                ):
                    insert_cols.append(col)
                    if col in filter_updates:
                        insert_values.append(f"(:{col})::jsonb")
                        value = filter_updates[col]
                        params[col] = (
                            json.dumps(value) if not isinstance(value, str) else value
                        )
                    else:
                        insert_values.append("'[]'::jsonb")
                conn.execute(
                    text(
                        f"INSERT INTO {FILTER_TABLE} "
                        f"({', '.join(insert_cols)}) "
                        f"VALUES ({', '.join(insert_values)})"
                    ),
                    params,
                )

            # 2. Populate hardware_settings.led_default_lines.
            if led_payload is not None:
                led_json = (
                    json.dumps(led_payload)
                    if not isinstance(led_payload, str)
                    else led_payload
                )
                if hw_data:
                    conn.execute(
                        text(
                            f"UPDATE {HARDWARE_TABLE} "
                            f"SET led_default_lines = (:led)::jsonb "
                            f"WHERE id = :row_id"
                        ),
                        {"led": led_json, "row_id": hw_data["id"]},
                    )
                else:
                    conn.execute(
                        text(
                            f"INSERT INTO {HARDWARE_TABLE} "
                            f"(id, led_default_lines) "
                            f"VALUES (1, (:led)::jsonb)"
                        ),
                        {"led": led_json},
                    )

            # 3. Drop the orphaned columns from location_settings.
            for col in old_cols_present:
                conn.execute(
                    text(f"ALTER TABLE {LOCATION_TABLE} DROP COLUMN IF EXISTS {col}")
                )

            # 4. Stamp alembic_version.
            stamp_row = conn.execute(text("SELECT COUNT(*) FROM alembic_version"))
            count = stamp_row.scalar() or 0
            if count == 0:
                conn.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                    {"rev": TARGET_REVISION},
                )
            else:
                conn.execute(
                    text("UPDATE alembic_version SET version_num = :rev"),
                    {"rev": TARGET_REVISION},
                )

            _log(
                f"[recover] Recovery complete. alembic_version = {TARGET_REVISION}.",
                quiet=False,
            )
            return 0
    finally:
        engine.dispose()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Finish a half-applied 20260506_split_location_settings migration. "
            "Idempotent and safe to run on a healthy database."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect and report what would change, but do not modify the database.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational output when nothing needs to be done.",
    )
    args = parser.parse_args(argv)

    try:
        url = _resolve_database_url()
    except Exception as exc:
        print(f"[recover] FATAL: could not resolve database URL: {exc}", file=sys.stderr)
        return 1

    try:
        return recover(url, dry_run=args.dry_run, quiet=args.quiet)
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        print(f"[recover] FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
