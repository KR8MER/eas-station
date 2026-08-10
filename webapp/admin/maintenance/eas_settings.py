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

"""Ensuring the singleton EAS settings row exists."""

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app_core.extensions import db
from app_core.models import EASSettings


# ============================================================================
# EAS Settings Routes
# ============================================================================

def _ensure_eas_settings_record() -> EASSettings:
    """Ensure there is a single EASSettings row (id=1).

    If the query raises ProgrammingError due to a missing column (migration not
    yet applied), the missing column is added automatically and the query is
    retried — so the app self-heals on first request after a code deploy.
    """
    _PENDING_MIGRATIONS = [
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS endec_fingerprint BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS pre_alert_chime VARCHAR(16) NOT NULL DEFAULT 'none'",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS post_alert_chime VARCHAR(16) NOT NULL DEFAULT 'none'",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS pre_alert_chime_duration DOUBLE PRECISION NOT NULL DEFAULT 2.0",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS post_alert_chime_duration DOUBLE PRECISION NOT NULL DEFAULT 2.0",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS qc2_tone_a_freq DOUBLE PRECISION NOT NULL DEFAULT 1000.0",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS qc2_tone_b_freq DOUBLE PRECISION NOT NULL DEFAULT 1500.0",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS dtmf_sequence VARCHAR(32) NOT NULL DEFAULT ''",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS qc2_long_tone_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS qc2_long_tone_seconds DOUBLE PRECISION NOT NULL DEFAULT 10.0",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS mdc1200_unit_id INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS mdc1200_op_code VARCHAR(32) NOT NULL DEFAULT 'ptt_id_pre'",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS mdc1200_op_code_raw SMALLINT",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS mdc1200_arg_raw SMALLINT",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS mdc1200_target_unit_id INTEGER",
        "ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS relay_narration_source VARCHAR(16) NOT NULL DEFAULT 'auto'",
    ]

    def _query():
        settings = EASSettings.query.get(1)
        if not settings:
            settings = EASSettings(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings

    try:
        return _query()
    except ProgrammingError as exc:
        if "UndefinedColumn" not in type(exc.orig).__name__:
            raise
        db.session.rollback()
        for stmt in _PENDING_MIGRATIONS:
            try:
                db.session.execute(text(stmt))
                db.session.commit()
                current_app.logger.warning("Auto-applied pending migration: %s", stmt)
            except Exception as migration_exc:
                db.session.rollback()
                current_app.logger.error("Failed to auto-apply migration: %s", migration_exc)
                raise
        return _query()
