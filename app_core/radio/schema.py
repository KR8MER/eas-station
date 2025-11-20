"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Database helpers for radio receiver persistence."""

from __future__ import annotations

from typing import Callable, Iterable, Sequence, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import RadioReceiver, RadioReceiverStatus


_TABLE_NAMES: Iterable[str] = ("radio_receivers", "radio_receiver_status")

_SQUELCH_COLUMN_DEFINITIONS: tuple[tuple[str, str]] = (
    ("squelch_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("squelch_threshold_db", "DOUBLE PRECISION NOT NULL DEFAULT -65"),
    ("squelch_open_ms", "INTEGER NOT NULL DEFAULT 150"),
    ("squelch_close_ms", "INTEGER NOT NULL DEFAULT 750"),
    ("squelch_alarm", "BOOLEAN NOT NULL DEFAULT FALSE"),
)

_IndexDefinition = Tuple[str, Callable[[], db.Index], Tuple[str, ...], bool]
_INDEX_DEFINITIONS: dict[str, Tuple[_IndexDefinition, ...]] = {
    "radio_receivers": (
        (
            "idx_radio_receivers_identifier",
            lambda: db.Index(
                "idx_radio_receivers_identifier",
                RadioReceiver.identifier,
                unique=True,
            ),
            ("identifier",),
            True,
        ),
    ),
    "radio_receiver_status": (
        (
            "idx_radio_receiver_status_receiver_id",
            lambda: db.Index(
                "idx_radio_receiver_status_receiver_id",
                RadioReceiverStatus.receiver_id,
            ),
            ("receiver_id",),
            False,
        ),
        (
            "idx_radio_receiver_status_reported_at",
            lambda: db.Index(
                "idx_radio_receiver_status_reported_at",
                RadioReceiverStatus.reported_at.desc(),
            ),
            ("reported_at",),
            False,
        ),
    ),
}


def _has_matching_index(
    indexes: Sequence[dict],
    unique_constraints: Sequence[dict],
    column_names: Tuple[str, ...],
    require_unique: bool,
) -> bool:
    """Check whether an index (or unique constraint) already covers the columns."""

    target = tuple(column_names)
    for index in indexes:
        indexed_columns = tuple(index.get("column_names") or ())
        if indexed_columns == target:
            if not require_unique or index.get("unique", False):
                return True
    if require_unique:
        for constraint in unique_constraints:
            constrained_columns = tuple(constraint.get("column_names") or ())
            if constrained_columns == target:
                return True
    return False


def ensure_radio_tables(logger) -> bool:
    """Ensure radio receiver tables exist before accessing them."""

    try:
        RadioReceiver.__table__.create(bind=db.engine, checkfirst=True)
        RadioReceiverStatus.__table__.create(bind=db.engine, checkfirst=True)

        inspector = inspect(db.engine)
        missing = [name for name in _TABLE_NAMES if name not in inspector.get_table_names()]
        if missing:
            logger.error(
                "Radio receiver tables missing after creation attempt: %s",
                ", ".join(sorted(missing)),
            )
            return False

        for table_name, definitions in _INDEX_DEFINITIONS.items():
            inspector = inspect(db.engine)
            existing_indexes = inspector.get_indexes(table_name)
            unique_constraints = inspector.get_unique_constraints(table_name)
            for index_name, factory, columns, require_unique in definitions:
                if _has_matching_index(existing_indexes, unique_constraints, columns, require_unique):
                    continue
                try:
                    factory().create(bind=db.engine)
                    logger.info("Created missing index %s on %s", index_name, table_name)
                except SQLAlchemyError as exc:
                    logger.error(
                        "Failed to create index %s on %s: %s", index_name, table_name, exc
                    )
                    return False
                inspector = inspect(db.engine)
                existing_indexes = inspector.get_indexes(table_name)
                unique_constraints = inspector.get_unique_constraints(table_name)

        return True
    except SQLAlchemyError as exc:
        logger.error("Failed to ensure radio receiver tables: %s", exc)
        return False


def ensure_radio_squelch_columns(logger) -> bool:
    """Backfill squelch configuration columns when migrations haven't run."""

    engine = db.engine
    inspector = inspect(engine)

    if "radio_receivers" not in inspector.get_table_names():
        logger.debug(
            "Skipping radio squelch column verification; radio_receivers table missing",
        )
        return True

    dialect = engine.dialect.name

    try:
        existing_columns = {column["name"] for column in inspector.get_columns("radio_receivers")}
        changed = False

        for column_name, column_definition in _SQUELCH_COLUMN_DEFINITIONS:
            if column_name in existing_columns:
                continue

            logger.info("Adding radio_receivers.%s column for squelch controls", column_name)

            ddl = f"ALTER TABLE radio_receivers ADD COLUMN {column_name} {column_definition}"
            db.session.execute(text(ddl))
            if dialect == "postgresql":
                db.session.execute(
                    text(
                        f"ALTER TABLE radio_receivers ALTER COLUMN {column_name} DROP DEFAULT"
                    )
                )
            changed = True

        if changed:
            db.session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not ensure radio squelch columns: %s", exc)
        db.session.rollback()
        return False


__all__ = ["ensure_radio_tables", "ensure_radio_squelch_columns"]
