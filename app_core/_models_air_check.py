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

"""Off-air self-monitoring ("air-check") records and settings.

An *air-check* receiver is an SDR tuned to this station's own transmitter.
Every time the station puts a SAME activation on the air, an
``AirCheckRecord`` is opened in the ``pending`` state with the exact header
that was sent. When the air-check receiver decodes that header back off the
air the record is closed as ``verified`` (or ``mismatch`` if the decoded
header differs field-for-field). If nothing comes back before the deadline
the record becomes ``missed`` and an error is raised. A header heard on the
air-check receiver that the station never sent is recorded as
``unexpected``.
"""

from ._models_base import db, utc_now


AIR_CHECK_STATUS_PENDING = "pending"
AIR_CHECK_STATUS_VERIFIED = "verified"
AIR_CHECK_STATUS_MISMATCH = "mismatch"
AIR_CHECK_STATUS_MISSED = "missed"
AIR_CHECK_STATUS_UNEXPECTED = "unexpected"

AIR_CHECK_STATUSES = (
    AIR_CHECK_STATUS_PENDING,
    AIR_CHECK_STATUS_VERIFIED,
    AIR_CHECK_STATUS_MISMATCH,
    AIR_CHECK_STATUS_MISSED,
    AIR_CHECK_STATUS_UNEXPECTED,
)


class AirCheckRecord(db.Model):
    """One transmission this station made, and what the air-check heard."""

    __tablename__ = "air_check_records"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # What was sent. origin_type is 'broadcast' (automatic CAP / relay via
    # EASBroadcaster) or 'resend' (origin_id -> eas_messages.id), 'manual' or
    # 'rwt' (origin_id -> manual_eas_activations.id). NULL for 'unexpected'.
    origin_type = db.Column(db.String(16), nullable=True)
    origin_id = db.Column(db.Integer, nullable=True)
    alert_identifier = db.Column(db.String(255), nullable=True)
    expected_header = db.Column(db.String(255), nullable=True)
    event_code = db.Column(db.String(8), nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    deadline_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    status = db.Column(db.String(16), nullable=False, default=AIR_CHECK_STATUS_PENDING, index=True)

    # What came back off the air.
    received_header = db.Column(db.String(255), nullable=True)
    received_at = db.Column(db.DateTime(timezone=True), nullable=True)
    receiver_source = db.Column(db.String(100), nullable=True)
    receiver_identifier = db.Column(db.String(64), nullable=True)
    decode_confidence = db.Column(db.Float, nullable=True)
    mismatch_fields = db.Column(db.JSON, nullable=True)
    detail = db.Column(db.Text, nullable=True)

    # Set once the operator has acknowledged a missed/mismatch/unexpected
    # record on the Air-Check page, so it stops counting as an open problem.
    acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)
    acknowledged_by = db.Column(db.String(100), nullable=True)

    @property
    def latency_seconds(self):
        if self.sent_at and self.received_at:
            return max((self.received_at - self.sent_at).total_seconds(), 0.0)
        return None

    def to_dict(self) -> dict:
        def _iso(value):
            return value.isoformat() if value else None

        return {
            "id": self.id,
            "created_at": _iso(self.created_at),
            "origin_type": self.origin_type,
            "origin_id": self.origin_id,
            "alert_identifier": self.alert_identifier,
            "expected_header": self.expected_header,
            "event_code": self.event_code,
            "sent_at": _iso(self.sent_at),
            "deadline_at": _iso(self.deadline_at),
            "status": self.status,
            "received_header": self.received_header,
            "received_at": _iso(self.received_at),
            "receiver_source": self.receiver_source,
            "receiver_identifier": self.receiver_identifier,
            "decode_confidence": self.decode_confidence,
            "mismatch_fields": list(self.mismatch_fields or []),
            "detail": self.detail,
            "latency_seconds": self.latency_seconds,
            "acknowledged_at": _iso(self.acknowledged_at),
            "acknowledged_by": self.acknowledged_by,
        }


class AirCheckSettings(db.Model):
    """Single-row (id=1) tuning for off-air self-monitoring."""

    __tablename__ = "air_check_settings"

    id = db.Column(db.Integer, primary_key=True)

    grace_seconds = db.Column(db.Integer, nullable=False, default=60)
    # Seconds allowed past the end of playout for the air-check receiver to
    # decode the header before the transmission is declared missed. Covers
    # transmitter/STL/processing delay plus the decoder's EOM hold.

    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        return {
            "grace_seconds": self.grace_seconds,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
