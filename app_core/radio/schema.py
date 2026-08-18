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

"""Database helpers for radio receiver persistence."""

from typing import Callable, Iterable, Sequence, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import RadioReceiver, RadioReceiverStatus


_TABLE_NAMES: Iterable[str] = ("radio_receivers", "radio_receiver_status")


_AUDIO_SAMPLE_RATE_COLUMN_DEFINITION: tuple[str, str] = (
    "audio_sample_rate",
    "INTEGER DEFAULT NULL",
)

_FREQUENCY_CORRECTION_PPM_COLUMN_DEFINITION: tuple[str, str] = (
    "frequency_correction_ppm",
    "DOUBLE PRECISION NOT NULL DEFAULT 0.0",
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


def ensure_radio_audio_sample_rate_column(logger) -> bool:
    """Backfill audio_sample_rate column when migrations haven't run.

    This column separates IQ sample rate (sample_rate) from audio output rate (audio_sample_rate).
    """

    engine = db.engine
    inspector = inspect(engine)

    if "radio_receivers" not in inspector.get_table_names():
        logger.debug(
            "Skipping audio_sample_rate column verification; radio_receivers table missing",
        )
        return True

    try:
        existing_columns = {column["name"] for column in inspector.get_columns("radio_receivers")}

        column_name, column_definition = _AUDIO_SAMPLE_RATE_COLUMN_DEFINITION
        if column_name in existing_columns:
            return True

        logger.info(
            "Adding radio_receivers.%s column to separate IQ and audio sample rates",
            column_name,
        )

        # Add the column
        ddl = f"ALTER TABLE radio_receivers ADD COLUMN {column_name} {column_definition}"
        db.session.execute(text(ddl))

        # Populate with intelligent defaults based on modulation type
        db.session.execute(
            text("""
                UPDATE radio_receivers
                SET audio_sample_rate = CASE
                    WHEN modulation_type IN ('FM', 'WFM', 'WBFM') AND stereo_enabled = true THEN 48000
                    WHEN modulation_type IN ('FM', 'WFM', 'WBFM') THEN 32000
                    WHEN modulation_type IN ('NFM', 'AM') THEN 24000
                    ELSE 44100
                END
                WHERE audio_sample_rate IS NULL
            """)
        )

        # Fix any sample_rate values that are clearly audio rates (< 1 MHz)
        result = db.session.execute(
            text("""
                UPDATE radio_receivers
                SET sample_rate = CASE
                    WHEN driver = 'rtlsdr' AND sample_rate < 1000000 THEN 2400000
                    WHEN driver = 'airspy' AND sample_rate < 1000000 THEN 10000000
                    WHEN sample_rate < 1000000 THEN 2400000
                    ELSE sample_rate
                END
                WHERE sample_rate < 1000000
            """)
        )

        db.session.commit()

        if result.rowcount > 0:
            logger.info(
                "Fixed %d radio receiver(s) with incorrect IQ sample rates (< 1 MHz)",
                result.rowcount,
            )

        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not ensure audio_sample_rate column: %s", exc)
        db.session.rollback()
        return False


def ensure_radio_frequency_correction_column(logger) -> bool:
    """Ensure radio_receivers table has frequency_correction_ppm column.
    
    This column stores PPM (parts per million) frequency correction for
    compensating crystal oscillator drift in low-cost SDRs like RTL-SDR.
    Typical values range from -50 to +50 PPM.
    
    Args:
        logger: Logger instance for status messages
        
    Returns:
        True if column exists or was added successfully, False otherwise
    """
    try:
        inspector = inspect(db.engine)
        columns = {col["name"]: col for col in inspector.get_columns("radio_receivers")}
        
        col_name, col_definition = _FREQUENCY_CORRECTION_PPM_COLUMN_DEFINITION
        
        if col_name not in columns:
            logger.info("Adding %s column to radio_receivers table", col_name)
            db.session.execute(
                text(f"ALTER TABLE radio_receivers ADD COLUMN {col_name} {col_definition}")
            )
            db.session.commit()
            logger.info("✅ Added %s column for PPM frequency correction", col_name)
        
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not ensure %s column: %s", col_name, exc)
        db.session.rollback()
        return False


__all__ = [
    "ensure_radio_tables",
    "ensure_radio_audio_sample_rate_column",
    "ensure_radio_frequency_correction_column",
]
