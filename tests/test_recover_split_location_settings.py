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

Regression tests for scripts/database/recover_split_location_settings.py.

The load-bearing bug: the script's "trailing-stamp-only" branch fires
whenever the old location_settings columns are absent and alembic_version
does not literally equal TARGET_REVISION -- which is also true of a
database that has moved on dozens of migrations past it (those columns
were dropped once, by TARGET_REVISION, and stay dropped forever after).
On this station it stamped alembic_version backward to
20260506_split_location_settings on every single run of update.sh, even
though the schema was fully current through the day's latest migration.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.recover_split_location_settings import (  # noqa: E402
    TARGET_REVISION,
    _is_at_or_past_target,
    recover,
)

# A real, later head from this repo's actual migration chain -- walking the
# graph from here must pass through TARGET_REVISION.
_LATER_HEAD = "20260818_dead_air_per_source"

# A real revision that precedes TARGET_REVISION in the chain.
_EARLIER_REVISION = "20260505_add_mdc1200_to_eas_settings"


# ---------------------------------------------------------------------------
# _is_at_or_past_target: the actual bug, isolated
# ---------------------------------------------------------------------------

def test_a_later_head_reads_as_at_or_past_target():
    """The exact bug scenario: current_rev is 47 migrations past target."""
    assert _is_at_or_past_target(_LATER_HEAD, TARGET_REVISION) is True


def test_exact_match_reads_as_at_or_past_target():
    assert _is_at_or_past_target(TARGET_REVISION, TARGET_REVISION) is True


def test_none_does_not_read_as_at_or_past_target():
    """A never-stamped database must still hit the stamp-only branch."""
    assert _is_at_or_past_target(None, TARGET_REVISION) is False


def test_an_earlier_revision_does_not_read_as_at_or_past_target():
    assert _is_at_or_past_target(_EARLIER_REVISION, TARGET_REVISION) is False


def test_an_unrecognized_revision_does_not_read_as_at_or_past_target():
    """Conservative default: an unknown string must not be trusted as 'past'."""
    assert _is_at_or_past_target("not_a_real_revision_id", TARGET_REVISION) is False


# ---------------------------------------------------------------------------
# recover(): the trailing-stamp branches end to end, against a real (SQLite)
# database -- these only exercise the "old columns absent" branches, which
# are portable SQL; the "half-migrated" data-copy branch uses Postgres-only
# ``::jsonb`` casts and is out of scope here.
# ---------------------------------------------------------------------------

def _make_db(tmp_path, *, stamp_version):
    db_path = tmp_path / "recover_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        # location_settings with the OLD columns already gone -- this repo's
        # actual current schema.
        conn.execute(text("CREATE TABLE location_settings (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE alert_filter_settings (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE hardware_settings (id INTEGER PRIMARY KEY, led_default_lines TEXT)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        if stamp_version is not None:
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": stamp_version},
            )
    engine.dispose()
    return f"sqlite:///{db_path}"


def _read_version(database_url):
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            return row[0] if row else None
    finally:
        engine.dispose()


def test_recover_leaves_a_database_already_past_target_untouched(tmp_path):
    """Regression: this is the exact false-positive that corrupted the live
    station's alembic_version on every update.sh run."""
    db_url = _make_db(tmp_path, stamp_version=_LATER_HEAD)

    exit_code = recover(db_url, quiet=True)

    assert exit_code == 0
    assert _read_version(db_url) == _LATER_HEAD, (
        "recover() must not stamp alembic_version backward when the "
        "database has already moved past TARGET_REVISION"
    )


def test_recover_leaves_a_database_already_at_target_untouched(tmp_path):
    db_url = _make_db(tmp_path, stamp_version=TARGET_REVISION)

    exit_code = recover(db_url, quiet=True)

    assert exit_code == 0
    assert _read_version(db_url) == TARGET_REVISION


def test_recover_stamps_a_database_with_no_version_row(tmp_path):
    """The genuine trailing-stamp case this script exists to fix: schema
    reached the target (old columns gone) but the version row was never
    written at all."""
    db_url = _make_db(tmp_path, stamp_version=None)

    exit_code = recover(db_url, quiet=True)

    assert exit_code == 0
    assert _read_version(db_url) == TARGET_REVISION


def test_recover_stamps_a_database_with_an_unrecognized_stale_version(tmp_path):
    """A version row exists but doesn't resolve in this checkout's migration
    graph (e.g. an ancestor from before TARGET_REVISION, or a value from a
    botched db.create_all() fallback) -- must still be corrected forward."""
    db_url = _make_db(tmp_path, stamp_version=_EARLIER_REVISION)

    exit_code = recover(db_url, quiet=True)

    assert exit_code == 0
    assert _read_version(db_url) == TARGET_REVISION


def test_recover_is_a_no_op_on_dry_run_even_when_stamp_is_needed(tmp_path):
    db_url = _make_db(tmp_path, stamp_version=None)

    exit_code = recover(db_url, dry_run=True, quiet=True)

    assert exit_code == 0
    assert _read_version(db_url) is None
