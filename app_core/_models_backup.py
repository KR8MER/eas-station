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

"""Backup restore verification run history."""

from ._models_base import JSONB, datetime, db, utc_now


class BackupVerificationRun(db.Model):
    """One record of an automated "does this backup actually restore?" check.

    A backup that has never been restored is not a proven backup. This
    table records the outcome of periodically (or manually) restoring the
    latest backup's database dump into a throwaway scratch database and
    running sanity checks against it -- distinct from the purely structural
    "are the expected files present" check already performed on demand by
    ``/api/backups/validate/<name>``.

    This is a log table (one row per run), not a singleton settings row.
    """
    __tablename__ = "backup_verification_runs"

    id = db.Column(db.Integer, primary_key=True)

    started_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    finished_at = db.Column(db.DateTime, nullable=True)

    backup_label = db.Column(db.String(255), nullable=False)
    # Directory/label of the backup that was verified.

    passed = db.Column(db.Boolean, nullable=False, default=False)
    duration_seconds = db.Column(db.Float, nullable=True)

    details = db.Column(JSONB, nullable=False, default=list)
    # List of individual check results, e.g.
    # [{"name": "schema_present", "passed": true, "message": "..."}, ...]

    error_message = db.Column(db.Text, nullable=True)
    # Populated when the run itself errored out (not a normal check
    # failure) -- e.g. couldn't create the scratch database at all.

    triggered_by = db.Column(db.String(32), nullable=False, default='scheduled')
    # 'scheduled' (ran automatically after a backup) or 'manual' (operator
    # clicked "Verify Latest Backup Now").

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "backup_label": self.backup_label,
            "passed": self.passed,
            "duration_seconds": self.duration_seconds,
            "details": self.details or [],
            "error_message": self.error_message,
            "triggered_by": self.triggered_by,
        }
