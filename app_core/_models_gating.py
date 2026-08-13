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

"""Gated-alerts hold-off timer models: the pending-alert queue and its settings."""

from typing import Any, Dict

from ._models_base import datetime, db, utc_now

# GatedAlert.status values.
GATE_STATUS_PENDING = "pending"
GATE_STATUS_APPROVED = "approved"
GATE_STATUS_CANCELLED = "cancelled"
GATE_STATUS_RELEASED = "released"


class GatedAlert(db.Model):
    """One row per alert held by the gated-alerts hold-off timer.

    Both the CAP poller and OTA relay paths in ``app_core.audio.auto_forward``
    create a row here instead of broadcasting immediately when gating is
    enabled and the alert doesn't qualify for the Immediate/Extreme bypass.
    ``status`` is the single source of truth the gate re-checks on every
    re-invocation, which is what makes the hold idempotent against the CAP
    poller's forwarding retry sweep and duplicate OTA callbacks.
    """

    __tablename__ = "gated_alerts"
    __table_args__ = (
        db.UniqueConstraint("cap_alert_id", name="uq_gated_alerts_cap_alert_id"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # 'cap' or 'ota' -- which auto_forward_* path created this row.
    source = db.Column(db.String(10), nullable=False, index=True)

    # Populated for CAP-sourced rows; NULL for OTA (no CAPAlert row exists
    # for an off-air decode). ondelete=SET NULL mirrors CAPAlert.superseded_by_id.
    cap_alert_id = db.Column(
        db.Integer,
        db.ForeignKey("cap_alerts.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Dedupe/lookup key: cap_alert.identifier for CAP rows, the decoded SAME
    # identifier for OTA rows.
    identifier = db.Column(db.String(255), nullable=True, index=True)

    event_code = db.Column(db.String(16))
    event = db.Column(db.String(255))
    severity = db.Column(db.String(50))
    urgency = db.Column(db.String(50))
    headline = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default=GATE_STATUS_PENDING, index=True)
    hold_until = db.Column(db.DateTime(timezone=True), nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved_by = db.Column(db.String(100), nullable=True)
    resolved_by_ip = db.Column(db.String(45), nullable=True)
    resolution_reason = db.Column(db.String(255), nullable=True)

    # OTA-only: a JSON-safe copy of the decoded alert_dict (audio bytes
    # excluded -- those live in ota_audio_wav) so the release path can
    # reconstruct the exact payload auto_forward_ota_alert() needs.
    ota_payload = db.Column(db.JSON, nullable=True)
    ota_audio_wav = db.Column(db.LargeBinary, nullable=True)

    # Stashed result dict from the eventual auto_forward_*() call, once
    # the alert is released -- for the UI/audit trail.
    broadcast_result = db.Column(db.JSON, nullable=True)

    AUDIO_BLOB_COLUMNS = ("ota_audio_wav",)

    @classmethod
    def without_audio(cls):
        """Query this model with the captured-audio blob deferred."""
        from sqlalchemy.orm import defer

        return cls.query.options(
            *(defer(getattr(cls, name)) for name in cls.AUDIO_BLOB_COLUMNS)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "cap_alert_id": self.cap_alert_id,
            "identifier": self.identifier,
            "event_code": self.event_code,
            "event": self.event,
            "severity": self.severity,
            "urgency": self.urgency,
            "headline": self.headline,
            "status": self.status,
            "hold_until": self.hold_until.isoformat() if self.hold_until else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_reason": self.resolution_reason,
            "has_captured_audio": self.ota_audio_wav is not None,
        }


class AlertGatingSettings(db.Model):
    """Gated-alerts hold-off timer configuration.

    Single row (id=1), same shape as PollerSettings.
    """

    __tablename__ = "alert_gating_settings"

    id = db.Column(db.Integer, primary_key=True)

    enabled = db.Column(db.Boolean, nullable=False, default=False)
    # When enabled, non-Immediate/non-Extreme alerts are held for
    # hold_off_seconds before auto-forward broadcasts them.

    hold_off_seconds = db.Column(db.Integer, nullable=False, default=120)
    # How long a gated alert waits before it auto-releases.

    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hold_off_seconds": self.hold_off_seconds,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
