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

"""Idempotent column/constraint checks run during database initialization."""

from sqlalchemy import text

from app_core.extensions import db


def ensure_eas_audio_columns(logger) -> bool:
    """Ensure blob columns exist for caching generated audio payloads."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    column_check_sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'eas_messages'
          AND column_name = :column
          AND table_schema = current_schema()
        LIMIT 1
        """
    )

    column_definitions = {
        "audio_data": "BYTEA",
        "eom_audio_data": "BYTEA",
        "same_audio_data": "BYTEA",
        "attention_audio_data": "BYTEA",
        "tts_audio_data": "BYTEA",
        "buffer_audio_data": "BYTEA",
        "text_payload": "JSONB",
    }

    try:
        added_columns = []
        with engine.begin() as connection:
            for column, definition in column_definitions.items():
                exists = connection.execute(column_check_sql, {"column": column}).scalar()
                if exists:
                    continue

                logger.info(
                    "Adding eas_messages.%s column for cached message payloads", column
                )
                connection.execute(
                    text(f"ALTER TABLE eas_messages ADD COLUMN IF NOT EXISTS {column} {definition}")
                )
                added_columns.append(column)

        if "text_payload" in added_columns:
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE eas_messages ALTER COLUMN text_payload SET DEFAULT '{}'::jsonb"
                        )
                    )
                    connection.execute(
                        text(
                            "UPDATE eas_messages SET text_payload = '{}'::jsonb WHERE text_payload IS NULL"
                        )
                    )
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning(
                    "Could not initialize default data for eas_messages.text_payload: %s",
                    exc,
                )

        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure EAS audio columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False

def ensure_eas_message_foreign_key(logger) -> bool:
    """Ensure the cap_alert_id foreign key has proper ON DELETE SET NULL behavior."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    # Check if the foreign key constraint exists and what its delete rule is
    constraint_check_sql = text(
        """
        SELECT con.conname, pg_get_constraintdef(con.oid) as constraint_def
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE rel.relname = 'eas_messages'
          AND con.contype = 'f'
          AND nsp.nspname = current_schema()
          AND pg_get_constraintdef(con.oid) LIKE '%cap_alerts%'
        """
    )

    try:
        with engine.begin() as connection:
            result = connection.execute(constraint_check_sql).fetchone()

            if result:
                constraint_name = result[0]
                constraint_def = result[1]

                # Check if it already has ON DELETE SET NULL
                if "ON DELETE SET NULL" in constraint_def.upper():
                    logger.debug("EAS message foreign key constraint already has proper ON DELETE behavior")
                    return True

                # Drop the old constraint
                logger.info("Updating eas_messages.cap_alert_id foreign key constraint to SET NULL on delete")
                connection.execute(
                    text(f"ALTER TABLE eas_messages DROP CONSTRAINT {constraint_name}")
                )

                # Add the new constraint with ON DELETE SET NULL
                connection.execute(
                    text(
                        "ALTER TABLE eas_messages ADD CONSTRAINT eas_messages_cap_alert_id_fkey "
                        "FOREIGN KEY (cap_alert_id) REFERENCES cap_alerts(id) ON DELETE SET NULL"
                    )
                )
                logger.info("Successfully updated foreign key constraint on eas_messages.cap_alert_id")

        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure EAS message foreign key constraint: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False

def ensure_eas_settings_columns(logger) -> bool:
    """Ensure all expected columns exist on the eas_settings table.

    Guards against deployments where the Alembic migration has not yet run
    (e.g. manual git-pull without running update.sh).  Currently handles:
      - forwarded_event_codes  JSONB NOT NULL DEFAULT '[]'::jsonb
    """

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    column_check_sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name   = 'eas_settings'
          AND column_name  = :column
          AND table_schema = current_schema()
        LIMIT 1
        """
    )

    columns_to_ensure = {
        "forwarded_event_codes": "JSONB NOT NULL DEFAULT '[]'::jsonb",
    }

    try:
        with engine.begin() as connection:
            for column, definition in columns_to_ensure.items():
                exists = connection.execute(column_check_sql, {"column": column}).scalar()
                if exists:
                    continue
                logger.info(
                    "Adding eas_settings.%s column (migration not yet applied)", column
                )
                connection.execute(
                    text(f"ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS {column} {definition}")
                )
        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure eas_settings columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False

def ensure_manual_eas_audio_columns(logger) -> bool:
    """Ensure blob columns exist for caching manual EAS audio payloads."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    column_check_sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'manual_eas_activations'
          AND column_name = :column
          AND table_schema = current_schema()
        LIMIT 1
        """
    )

    column_definitions = {
        "composite_audio_data": "BYTEA",
        "same_audio_data": "BYTEA",
        "attention_audio_data": "BYTEA",
        "tts_audio_data": "BYTEA",
        "eom_audio_data": "BYTEA",
    }

    try:
        with engine.begin() as connection:
            for column, definition in column_definitions.items():
                exists = connection.execute(column_check_sql, {"column": column}).scalar()
                if exists:
                    continue

                logger.info(
                    "Adding manual_eas_activations.%s column for cached audio payloads", column
                )
                connection.execute(
                    text(f"ALTER TABLE manual_eas_activations ADD COLUMN IF NOT EXISTS {column} {definition}")
                )

        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure manual EAS audio columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False
