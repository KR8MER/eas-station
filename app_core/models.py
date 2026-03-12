"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Database models used by the NOAA alerts application."""

import hashlib
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import current_app, has_app_context
from geoalchemy2 import Geometry
from werkzeug.security import (
    check_password_hash as werkzeug_check_password_hash,
    generate_password_hash as werkzeug_generate_password_hash,
)

from app_utils import ALERT_SOURCE_UNKNOWN, normalize_alert_source, utc_now
from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS

from .extensions import db
from sqlalchemy.engine.url import make_url
from sqlalchemy.dialects.postgresql import JSONB

# Import Role and Permission models to ensure they're available for relationship resolution
# This prevents "failed to locate a name ('Role')" errors when AdminUser mapper is configured
from app_core.auth.roles import Role, Permission


def _spatial_backend_supports_geometry() -> bool:
    database_url = os.getenv("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
    if not database_url:
        return True

    try:
        backend = make_url(database_url).get_backend_name()
    except Exception:
        return True

    return backend == "postgresql"


_GEOMETRY_SUPPORTED = _spatial_backend_supports_geometry()


def _geometry_type(geometry_type: str):
    if _GEOMETRY_SUPPORTED:
        return Geometry(geometry_type, srid=4326)

    if has_app_context():  # pragma: no cover - logging requires app context
        current_app.logger.warning(
            "Spatial functions unavailable; storing %s geometry as plain text", geometry_type
        )
    return db.Text


def _log_warning(message: str) -> None:
    """Log a warning using the configured Flask application logger."""

    if has_app_context():
        current_app.logger.warning(message)


def _log_info(message: str) -> None:
    """Log an info message using the configured Flask application logger."""

    if has_app_context():
        current_app.logger.info(message)


class NWSZone(db.Model):
    """Reference table containing NOAA public forecast zone metadata."""

    __tablename__ = "nws_zones"

    id = db.Column(db.Integer, primary_key=True)
    zone_code = db.Column(db.String(6), nullable=False, unique=True)
    state_code = db.Column(db.String(2), nullable=False, index=True)
    zone_number = db.Column(db.String(3), nullable=False)
    zone_type = db.Column(db.String(1), nullable=False, default="Z")
    cwa = db.Column(db.String(9), nullable=False, index=True)
    time_zone = db.Column(db.String(2))
    fe_area = db.Column(db.String(4))
    name = db.Column(db.String(255), nullable=False)
    short_name = db.Column(db.String(64))
    state_zone = db.Column(db.String(5), nullable=False, index=True)
    longitude = db.Column(db.Float)
    latitude = db.Column(db.Float)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<NWSZone {self.zone_code} {self.name}>"


class Boundary(db.Model):
    __tablename__ = "boundaries"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    geom = db.Column(_geometry_type("GEOMETRY"))
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class CAPAlert(db.Model):
    __tablename__ = "cap_alerts"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(255), unique=True, nullable=False)
    sent = db.Column(db.DateTime(timezone=True), nullable=False)
    expires = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(50), nullable=False)
    message_type = db.Column(db.String(50), nullable=False)
    scope = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(50))
    event = db.Column(db.String(255), nullable=False)
    urgency = db.Column(db.String(50))
    severity = db.Column(db.String(50))
    certainty = db.Column(db.String(50))
    area_desc = db.Column(db.Text)
    headline = db.Column(db.Text)
    description = db.Column(db.Text)
    instruction = db.Column(db.Text)
    raw_json = db.Column(db.JSON)
    geom = db.Column(_geometry_type("POLYGON"))
    source = db.Column(db.String(32), nullable=False, default=ALERT_SOURCE_UNKNOWN)
    
    # EAS forwarding tracking - records whether this alert triggered an EAS broadcast
    eas_forwarded = db.Column(db.Boolean, default=False, nullable=False)
    eas_forwarding_reason = db.Column(db.String(255))  # Why it was or wasn't forwarded
    eas_audio_url = db.Column(db.String(512))  # URL/path to generated EAS audio file

    # IPAWS XML digital signature verification
    signature_verified = db.Column(db.Boolean)  # None=not checked, True=valid, False=invalid
    signature_status = db.Column(db.String(255))  # Human-readable verification result
    certificate_info = db.Column(db.JSON)  # Full X.509 certificate details from IPAWS signature
    ipaws_audio_url = db.Column(db.String(512))  # Path to saved original IPAWS audio file

    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def __setattr__(self, name, value):  # pragma: no cover - passthrough
        if name == "source":
            value = normalize_alert_source(value) if value else ALERT_SOURCE_UNKNOWN
        super().__setattr__(name, value)


class SystemLog(db.Model):
    __tablename__ = "system_log"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now)
    level = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    module = db.Column(db.String(100))
    details = db.Column(db.JSON)


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    salt = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    last_login_at = db.Column(db.DateTime(timezone=True))

    # RBAC fields
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id', ondelete='SET NULL'), nullable=True)

    # Password management
    password_changed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Timestamp of the most recent password change (set by set_password())

    # MFA fields
    mfa_enabled = db.Column(db.Boolean, default=False, nullable=False)
    mfa_secret = db.Column(db.String(255), nullable=True)  # Base32-encoded TOTP secret
    mfa_backup_codes_hash = db.Column(db.Text, nullable=True)  # JSON array of hashed backup codes
    mfa_enrolled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    mfa_last_totp_at = db.Column(db.DateTime(timezone=True), nullable=True)  # Last successful TOTP code timestamp

    # Relationships
    role = db.relationship('Role', back_populates='users', lazy='joined')

    def set_password(self, password: str) -> None:
        self.password_hash = werkzeug_generate_password_hash(password)
        self.salt = "pbkdf2"
        self.password_changed_at = utc_now()

    def check_password(self, password: str) -> bool:
        """Check password and flag for upgrade if using legacy format.

        Note: If using legacy SHA256 format, the password is upgraded in-place
        but NOT committed. The caller is responsible for committing the session
        after a successful authentication flow to avoid mid-request commits.
        """
        if self.password_hash is None:
            return False

        if self.salt and self.salt != "pbkdf2":
            if len(self.salt) == 32 and len(self.password_hash) == 64:
                try:
                    salt_bytes = bytes.fromhex(self.salt)
                except ValueError:
                    return False
                hashed = hashlib.sha256(salt_bytes + password.encode("utf-8")).hexdigest()
                if hashed == self.password_hash:
                    # Upgrade to new password hash format in-place
                    # The session commit happens in the authentication flow,
                    # not here, to avoid race conditions with other requests
                    self.set_password(password)
                    _log_info(f"Password hash for user {self.username} upgraded to pbkdf2 format (pending commit)")
                    return True
            return False

        try:
            return werkzeug_check_password_hash(self.password_hash, password)
        except ValueError:
            _log_warning("Stored admin password hash has an unexpected format.")
            return False

    def to_safe_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "password_changed_at": self.password_changed_at.isoformat() if self.password_changed_at else None,
            "role_name": self.role.name if self.role else None,
            "role_id": self.role_id,
            "mfa_enabled": self.mfa_enabled,
            "mfa_enrolled_at": self.mfa_enrolled_at.isoformat() if self.mfa_enrolled_at else None,
        }

    @property
    def is_authenticated(self) -> bool:
        """Flask-style authentication flag used by templates."""

        return bool(self.is_active)


class AdminSession(db.Model):
    """Tracks individual administrator login sessions for monitoring.

    Created on login, ended on logout or expiry.
    Allows admins to view who is currently active and terminate sessions.
    """
    __tablename__ = "admin_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("admin_users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True, default=utc_now)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ended_reason = db.Column(db.String(32), nullable=True)
    # ended_reason values: 'logout', 'expired', 'admin_terminated'

    # Relationship
    user = db.relationship('AdminUser', lazy='joined', foreign_keys=[user_id])

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'ended_reason': self.ended_reason,
            'is_active': self.ended_at is None,
        }


class EASMessage(db.Model):
    __tablename__ = "eas_messages"

    id = db.Column(db.Integer, primary_key=True)
    cap_alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id", ondelete="SET NULL"), index=True)
    same_header = db.Column(db.String(255), nullable=False)
    audio_filename = db.Column(db.String(255), nullable=False)
    text_filename = db.Column(db.String(255), nullable=False)
    audio_data = db.Column(db.LargeBinary)
    eom_audio_data = db.Column(db.LargeBinary)
    same_audio_data = db.Column(db.LargeBinary)
    attention_audio_data = db.Column(db.LargeBinary)
    tts_audio_data = db.Column(db.LargeBinary)
    buffer_audio_data = db.Column(db.LargeBinary)
    tts_warning = db.Column(db.String(255))
    tts_provider = db.Column(db.String(32))
    text_payload = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    metadata_payload = db.Column(db.JSON, default=dict)

    cap_alert = db.relationship(
        "CAPAlert",
        backref=db.backref("eas_messages", lazy="dynamic"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cap_alert_id": self.cap_alert_id,
            "same_header": self.same_header,
            "audio_filename": self.audio_filename,
            "text_filename": self.text_filename,
            "has_audio_blob": self.audio_data is not None,
            "has_eom_blob": self.eom_audio_data is not None,
            "has_same_audio": self.same_audio_data is not None,
            "has_attention_audio": self.attention_audio_data is not None,
            "has_tts_audio": self.tts_audio_data is not None,
            "has_buffer_audio": self.buffer_audio_data is not None,
            "has_text_payload": bool(self.text_payload),
            "tts_warning": self.tts_warning,
            "tts_provider": self.tts_provider,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": dict(self.metadata_payload or {}),
        }


class EASDecodedAudio(db.Model):
    __tablename__ = "eas_decoded_audio"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    original_filename = db.Column(db.String(255))
    content_type = db.Column(db.String(128))
    raw_text = db.Column(db.Text)
    same_headers = db.Column(db.JSON, default=list)
    quality_metrics = db.Column(db.JSON, default=dict)
    segment_metadata = db.Column(db.JSON, default=dict)
    header_audio_data = db.Column(db.LargeBinary)
    attention_tone_audio_data = db.Column(db.LargeBinary)  # EBS or NWS 1050Hz tone
    narration_audio_data = db.Column(db.LargeBinary)  # Voice narration segment
    eom_audio_data = db.Column(db.LargeBinary)
    buffer_audio_data = db.Column(db.LargeBinary)
    composite_audio_data = db.Column(db.LargeBinary)  # Complete alert audio (all segments combined)
    # Deprecated: kept for backward compatibility with old decodes
    message_audio_data = db.Column(db.LargeBinary)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "raw_text": self.raw_text,
            "same_headers": list(self.same_headers or []),
            "quality_metrics": dict(self.quality_metrics or {}),
            "segment_metadata": dict(self.segment_metadata or {}),
            "has_header_audio": self.header_audio_data is not None,
            "has_attention_tone_audio": self.attention_tone_audio_data is not None,
            "has_narration_audio": self.narration_audio_data is not None,
            "has_eom_audio": self.eom_audio_data is not None,
            "has_buffer_audio": self.buffer_audio_data is not None,
            "has_composite_audio": self.composite_audio_data is not None,
            "has_message_audio": self.message_audio_data is not None,  # Deprecated
        }


class ReceivedEASAlert(db.Model):
    """
    Tracks EAS alerts received from audio monitoring sources.
    Records forwarding decisions and links to broadcast messages.
    """
    __tablename__ = "received_eas_alerts"

    id = db.Column(db.Integer, primary_key=True)

    # Reception details
    received_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)  # Which audio source detected this

    # SAME header data
    raw_same_header = db.Column(db.Text)  # Raw ZCZC string
    event_code = db.Column(db.String(8), index=True)
    event_name = db.Column(db.String(255))
    originator_code = db.Column(db.String(8))
    originator_name = db.Column(db.String(100))
    fips_codes = db.Column(db.JSON, default=list)  # List of FIPS codes from alert
    issue_datetime = db.Column(db.DateTime(timezone=True))
    purge_datetime = db.Column(db.DateTime(timezone=True))
    callsign = db.Column(db.String(16))

    # Forwarding decision
    forwarding_decision = db.Column(db.String(20), nullable=False, index=True)  # 'forwarded', 'ignored', 'error'
    forwarding_reason = db.Column(db.Text)  # Why it was forwarded or ignored (e.g., "FIPS match: 039137")
    matched_fips_codes = db.Column(db.JSON, default=list)  # Which configured FIPS codes matched

    # Link to generated broadcast (if forwarded)
    generated_message_id = db.Column(db.Integer, db.ForeignKey('eas_messages.id'), nullable=True, index=True)
    generated_message = db.relationship('EASMessage', foreign_keys=[generated_message_id], backref='source_alerts')
    forwarded_at = db.Column(db.DateTime(timezone=True))

    # Full decoded data (JSON)
    full_alert_data = db.Column(JSONB)  # Complete EASAlert object as JSON

    # Quality metrics
    decode_confidence = db.Column(db.Float)  # 0.0 to 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "source_name": self.source_name,
            "raw_same_header": self.raw_same_header,
            "event_code": self.event_code,
            "event_name": self.event_name,
            "originator_code": self.originator_code,
            "originator_name": self.originator_name,
            "fips_codes": list(self.fips_codes or []),
            "issue_datetime": self.issue_datetime.isoformat() if self.issue_datetime else None,
            "purge_datetime": self.purge_datetime.isoformat() if self.purge_datetime else None,
            "callsign": self.callsign,
            "forwarding_decision": self.forwarding_decision,
            "forwarding_reason": self.forwarding_reason,
            "matched_fips_codes": list(self.matched_fips_codes or []),
            "generated_message_id": self.generated_message_id,
            "forwarded_at": self.forwarded_at.isoformat() if self.forwarded_at else None,
            "decode_confidence": self.decode_confidence,
            "full_alert_data": self.full_alert_data,
        }


class ManualEASActivation(db.Model):
    __tablename__ = "manual_eas_activations"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(120), nullable=False)
    event_code = db.Column(db.String(8), nullable=False)
    event_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False)
    message_type = db.Column(db.String(32), nullable=False)
    same_header = db.Column(db.String(255), nullable=False)
    same_locations = db.Column(db.JSON, nullable=False, default=list)
    tone_profile = db.Column(db.String(32), nullable=False)
    tone_seconds = db.Column(db.Float)
    sample_rate = db.Column(db.Integer)
    includes_tts = db.Column(db.Boolean, default=False)
    tts_warning = db.Column(db.String(255))
    sent_at = db.Column(db.DateTime(timezone=True))
    expires_at = db.Column(db.DateTime(timezone=True))
    headline = db.Column(db.String(240))
    message_text = db.Column(db.Text)
    instruction_text = db.Column(db.Text)
    duration_minutes = db.Column(db.Float)
    storage_path = db.Column(db.String(255), nullable=False)
    summary_filename = db.Column(db.String(255))
    components_payload = db.Column(db.JSON, nullable=False, default=dict)
    metadata_payload = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    archived_at = db.Column(db.DateTime(timezone=True))
    triggered_at = db.Column(db.DateTime(timezone=True))
    # Binary audio data cached in database
    composite_audio_data = db.Column(db.LargeBinary)
    same_audio_data = db.Column(db.LargeBinary)
    attention_audio_data = db.Column(db.LargeBinary)
    tts_audio_data = db.Column(db.LargeBinary)
    eom_audio_data = db.Column(db.LargeBinary)
    # Uploaded audio segments (user-provided files)
    narration_upload_audio_data = db.Column(db.LargeBinary)
    pre_alert_audio_data = db.Column(db.LargeBinary)
    post_alert_audio_data = db.Column(db.LargeBinary)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "identifier": self.identifier,
            "event_code": self.event_code,
            "event_name": self.event_name,
            "status": self.status,
            "message_type": self.message_type,
            "same_header": self.same_header,
            "same_locations": list(self.same_locations or []),
            "tone_profile": self.tone_profile,
            "tone_seconds": self.tone_seconds,
            "sample_rate": self.sample_rate,
            "includes_tts": bool(self.includes_tts),
            "tts_warning": self.tts_warning,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "headline": self.headline,
            "message_text": self.message_text,
            "instruction_text": self.instruction_text,
            "duration_minutes": self.duration_minutes,
            "storage_path": self.storage_path,
            "summary_filename": self.summary_filename,
            "components": dict(self.components_payload or {}),
            "metadata": dict(self.metadata_payload or {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
        }


class AlertDeliveryReport(db.Model):
    __tablename__ = "alert_delivery_reports"

    id = db.Column(db.Integer, primary_key=True)
    generated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    window_start = db.Column(db.DateTime(timezone=True), nullable=False)
    window_end = db.Column(db.DateTime(timezone=True), nullable=False)
    scope = db.Column(db.String(16), nullable=False)
    originator = db.Column(db.String(64))
    station = db.Column(db.String(128))
    total_alerts = db.Column(db.Integer, nullable=False, default=0)
    delivered_alerts = db.Column(db.Integer, nullable=False, default=0)
    delayed_alerts = db.Column(db.Integer, nullable=False, default=0)
    average_latency_seconds = db.Column(db.Integer)

    __table_args__ = (
        db.Index(
            "idx_alert_delivery_reports_scope_window",
            "scope",
            "window_start",
            "window_end",
        ),
        db.Index("idx_alert_delivery_reports_originator", "originator"),
        db.Index("idx_alert_delivery_reports_station", "station"),
    )

    def to_dict(self) -> Dict[str, Any]:  # pragma: no cover - convenience helper
        return {
            "id": self.id,
            "generated_at": self.generated_at,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "scope": self.scope,
            "originator": self.originator,
            "station": self.station,
            "total_alerts": self.total_alerts,
            "delivered_alerts": self.delivered_alerts,
            "delayed_alerts": self.delayed_alerts,
            "average_latency_seconds": self.average_latency_seconds,
        }


class Intersection(db.Model):
    __tablename__ = "intersections"

    id = db.Column(db.Integer, primary_key=True)
    cap_alert_id = db.Column(
        db.Integer,
        db.ForeignKey("cap_alerts.id", ondelete="CASCADE"),
    )
    boundary_id = db.Column(
        db.Integer,
        db.ForeignKey("boundaries.id", ondelete="CASCADE"),
    )
    intersection_area = db.Column(db.Float)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)


class PollHistory(db.Model):
    __tablename__ = "poll_history"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now)
    status = db.Column(db.String(20), nullable=False)
    alerts_fetched = db.Column(db.Integer, default=0)
    alerts_new = db.Column(db.Integer, default=0)
    alerts_updated = db.Column(db.Integer, default=0)
    execution_time_ms = db.Column(db.Integer)
    error_message = db.Column(db.Text)
    data_source = db.Column(db.String(64))
    # JSON field for additional details (endpoints polled, zone config, etc.)
    details = db.Column(db.JSON)


class PollDebugRecord(db.Model):
    __tablename__ = "poll_debug_records"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    poll_run_id = db.Column(db.String(64), nullable=False, index=True)
    poll_started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    poll_status = db.Column(db.String(20), nullable=False, default="UNKNOWN")
    data_source = db.Column(db.String(64))
    alert_identifier = db.Column(db.String(255))
    alert_event = db.Column(db.String(255))
    alert_sent = db.Column(db.DateTime(timezone=True))
    source = db.Column(db.String(64))
    is_relevant = db.Column(db.Boolean, default=False, nullable=False)
    relevance_reason = db.Column(db.String(255))
    relevance_matches = db.Column(db.JSON, default=list)
    ugc_codes = db.Column(db.JSON, default=list)
    area_desc = db.Column(db.Text)
    was_saved = db.Column(db.Boolean, default=False, nullable=False)
    was_new = db.Column(db.Boolean, default=False, nullable=False)
    alert_db_id = db.Column(db.Integer)
    parse_success = db.Column(db.Boolean, default=False, nullable=False)
    parse_error = db.Column(db.Text)
    polygon_count = db.Column(db.Integer)
    geometry_type = db.Column(db.String(64))
    geometry_geojson = db.Column(db.JSON)
    geometry_preview = db.Column(db.JSON)
    raw_properties = db.Column(db.JSON)
    raw_xml_present = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text)


class LocationSettings(db.Model):
    __tablename__ = "location_settings"

    id = db.Column(db.Integer, primary_key=True)
    county_name = db.Column(
        db.String(255),
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["county_name"],
    )
    state_code = db.Column(
        db.String(2),
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["state_code"],
    )
    timezone = db.Column(
        db.String(64),
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["timezone"],
    )
    fips_codes = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["fips_codes"]),
    )
    zone_codes = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["zone_codes"]),
    )
    storage_zone_codes = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["storage_zone_codes"]),
    )
    area_terms = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["area_terms"]),
    )
    map_center_lat = db.Column(
        db.Float,
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["map_center_lat"],
    )
    map_center_lng = db.Column(
        db.Float,
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["map_center_lng"],
    )
    map_default_zoom = db.Column(
        db.Integer,
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["map_default_zoom"],
    )
    led_default_lines = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["led_default_lines"]),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "county_name": self.county_name,
            "state_code": self.state_code,
            "timezone": self.timezone,
            "fips_codes": list(self.fips_codes or []),
            "zone_codes": list(self.zone_codes or []),
            "storage_zone_codes": list(self.storage_zone_codes or []),
            "area_terms": list(self.area_terms or []),
            "map_center_lat": self.map_center_lat,
            "map_center_lng": self.map_center_lng,
            "map_default_zoom": self.map_default_zoom,
            "led_default_lines": list(self.led_default_lines or []),
            "same_codes": list(self.fips_codes or []),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HardwareSettings(db.Model):
    """Unified hardware settings stored in database.

    Replaces environment variables for peripheral hardware configuration.
    All hardware settings are stored in a single row (id=1).
    """
    __tablename__ = "hardware_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # GPIO Settings
    # ========================================================================
    gpio_enabled = db.Column(db.Boolean, nullable=False, default=False)
    gpio_pin_map = db.Column(JSONB, nullable=False, default=dict)
    gpio_behavior_matrix = db.Column(JSONB, nullable=False, default=dict)

    # ========================================================================
    # USB Tower Light Settings (Adafruit #5125 / CH34x serial stack light)
    # ========================================================================
    tower_light_enabled = db.Column(db.Boolean, nullable=False, default=False)
    tower_light_serial_port = db.Column(db.String(100), nullable=False, default='/dev/ttyUSB0')
    tower_light_baudrate = db.Column(db.Integer, nullable=False, default=9600)
    tower_light_alert_buzzer = db.Column(db.Boolean, nullable=False, default=False)
    tower_light_incoming_uses_yellow = db.Column(db.Boolean, nullable=False, default=True)
    tower_light_blink_on_alert = db.Column(db.Boolean, nullable=False, default=True)

    # ========================================================================
    # NeoPixel / WS2812B Addressable LED Strip Settings
    # ========================================================================
    neopixel_enabled = db.Column(db.Boolean, nullable=False, default=False)
    neopixel_gpio_pin = db.Column(db.Integer, nullable=False, default=18)
    neopixel_num_pixels = db.Column(db.Integer, nullable=False, default=1)
    neopixel_brightness = db.Column(db.Integer, nullable=False, default=128)   # 0-255
    neopixel_led_order = db.Column(db.String(10), nullable=False, default='GRB')
    neopixel_standby_color = db.Column(JSONB, nullable=False, default=lambda: {"r": 0, "g": 10, "b": 0})
    neopixel_alert_color = db.Column(JSONB, nullable=False, default=lambda: {"r": 255, "g": 0, "b": 0})
    neopixel_flash_on_alert = db.Column(db.Boolean, nullable=False, default=True)
    neopixel_flash_interval_ms = db.Column(db.Integer, nullable=False, default=500)

    # ========================================================================
    # OLED Display Settings (Argon Industria SSD1306)
    # ========================================================================
    oled_enabled = db.Column(db.Boolean, nullable=False, default=False)
    oled_i2c_bus = db.Column(db.Integer, nullable=False, default=1)
    oled_i2c_address = db.Column(db.Integer, nullable=False, default=0x3C)
    oled_width = db.Column(db.Integer, nullable=False, default=128)
    oled_height = db.Column(db.Integer, nullable=False, default=64)
    oled_rotate = db.Column(db.Integer, nullable=False, default=0)
    oled_contrast = db.Column(db.Integer, nullable=True)
    oled_font_path = db.Column(db.String(255), nullable=True)
    oled_default_invert = db.Column(db.Boolean, nullable=False, default=False)
    oled_button_gpio = db.Column(db.Integer, nullable=False, default=4)
    oled_button_hold_seconds = db.Column(db.Float, nullable=False, default=1.25)
    oled_button_active_high = db.Column(db.Boolean, nullable=False, default=False)
    oled_scroll_effect = db.Column(db.String(50), nullable=False, default='scroll_left')
    oled_scroll_speed = db.Column(db.Integer, nullable=False, default=4)
    oled_scroll_fps = db.Column(db.Integer, nullable=False, default=30)
    screens_auto_start = db.Column(db.Boolean, nullable=False, default=True)

    # ========================================================================
    # LED Sign Settings (BetaBrite/Alpha)
    # ========================================================================
    led_enabled = db.Column(db.Boolean, nullable=False, default=False)
    led_connection_type = db.Column(db.String(20), nullable=False, default='network')  # 'network' or 'serial'
    led_ip_address = db.Column(db.String(50), nullable=False, default='192.168.1.100')
    led_port = db.Column(db.Integer, nullable=False, default=10001)
    led_serial_port = db.Column(db.String(100), nullable=False, default='/dev/ttyUSB1')
    led_baudrate = db.Column(db.Integer, nullable=False, default=9600)
    led_serial_mode = db.Column(db.String(20), nullable=False, default='RS232')
    led_default_text = db.Column(db.Text, nullable=True)

    # ========================================================================
    # VFD Display Settings (Noritake GU140x32F-7000B)
    # ========================================================================
    vfd_enabled = db.Column(db.Boolean, nullable=False, default=False)
    vfd_port = db.Column(db.String(100), nullable=False, default='/dev/ttyUSB0')
    vfd_baudrate = db.Column(db.Integer, nullable=False, default=38400)

    # ========================================================================
    # Zigbee Coordinator Settings
    # ========================================================================
    zigbee_enabled = db.Column(db.Boolean, nullable=False, default=False)
    zigbee_port = db.Column(db.String(100), nullable=False, default='/dev/ttyAMA0')
    zigbee_baudrate = db.Column(db.Integer, nullable=False, default=115200)
    zigbee_channel = db.Column(db.Integer, nullable=False, default=15)
    zigbee_pan_id = db.Column(db.String(20), nullable=False, default='0x1A62')

    # ========================================================================
    # GPS / Time Source Settings (Adafruit Ultimate GPS HAT #2324)
    # ========================================================================
    gps_enabled = db.Column(db.Boolean, nullable=False, default=False)
    gps_serial_port = db.Column(db.String(100), nullable=False, default='/dev/serial0')
    gps_baudrate = db.Column(db.Integer, nullable=False, default=9600)
    gps_pps_gpio_pin = db.Column(db.Integer, nullable=False, default=4)
    gps_use_for_location = db.Column(db.Boolean, nullable=False, default=False)
    gps_use_for_time = db.Column(db.Boolean, nullable=False, default=False)
    gps_min_satellites = db.Column(db.Integer, nullable=False, default=4)

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            "id": self.id,
            # GPIO
            "gpio_enabled": self.gpio_enabled,
            "gpio_pin_map": self.gpio_pin_map or {},
            "gpio_behavior_matrix": self.gpio_behavior_matrix or {},
            # Tower Light
            "tower_light_enabled": self.tower_light_enabled,
            "tower_light_serial_port": self.tower_light_serial_port,
            "tower_light_baudrate": self.tower_light_baudrate,
            "tower_light_alert_buzzer": self.tower_light_alert_buzzer,
            "tower_light_incoming_uses_yellow": self.tower_light_incoming_uses_yellow,
            "tower_light_blink_on_alert": self.tower_light_blink_on_alert,
            # NeoPixel
            "neopixel_enabled": self.neopixel_enabled,
            "neopixel_gpio_pin": self.neopixel_gpio_pin,
            "neopixel_num_pixels": self.neopixel_num_pixels,
            "neopixel_brightness": self.neopixel_brightness,
            "neopixel_led_order": self.neopixel_led_order,
            "neopixel_standby_color": self.neopixel_standby_color or {"r": 0, "g": 10, "b": 0},
            "neopixel_alert_color": self.neopixel_alert_color or {"r": 255, "g": 0, "b": 0},
            "neopixel_flash_on_alert": self.neopixel_flash_on_alert,
            "neopixel_flash_interval_ms": self.neopixel_flash_interval_ms,
            # OLED
            "oled_enabled": self.oled_enabled,
            "oled_i2c_bus": self.oled_i2c_bus,
            "oled_i2c_address": self.oled_i2c_address,
            "oled_width": self.oled_width,
            "oled_height": self.oled_height,
            "oled_rotate": self.oled_rotate,
            "oled_contrast": self.oled_contrast,
            "oled_font_path": self.oled_font_path,
            "oled_default_invert": self.oled_default_invert,
            "oled_button_gpio": self.oled_button_gpio,
            "oled_button_hold_seconds": self.oled_button_hold_seconds,
            "oled_button_active_high": self.oled_button_active_high,
            "oled_scroll_effect": self.oled_scroll_effect,
            "oled_scroll_speed": self.oled_scroll_speed,
            "oled_scroll_fps": self.oled_scroll_fps,
            "screens_auto_start": self.screens_auto_start,
            # LED
            "led_enabled": self.led_enabled,
            "led_connection_type": self.led_connection_type,
            "led_ip_address": self.led_ip_address,
            "led_port": self.led_port,
            "led_serial_port": self.led_serial_port,
            "led_baudrate": self.led_baudrate,
            "led_serial_mode": self.led_serial_mode,
            "led_default_text": self.led_default_text,
            # VFD
            "vfd_enabled": self.vfd_enabled,
            "vfd_port": self.vfd_port,
            "vfd_baudrate": self.vfd_baudrate,
            # Zigbee
            "zigbee_enabled": self.zigbee_enabled,
            "zigbee_port": self.zigbee_port,
            "zigbee_baudrate": self.zigbee_baudrate,
            "zigbee_channel": self.zigbee_channel,
            "zigbee_pan_id": self.zigbee_pan_id,
            # GPS HAT (Adafruit #2324)
            "gps_enabled": self.gps_enabled,
            "gps_serial_port": self.gps_serial_port,
            "gps_baudrate": self.gps_baudrate,
            "gps_pps_gpio_pin": self.gps_pps_gpio_pin,
            "gps_use_for_location": self.gps_use_for_location,
            "gps_use_for_time": self.gps_use_for_time,
            "gps_min_satellites": self.gps_min_satellites,
            # Metadata
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class IcecastSettings(db.Model):
    """Icecast streaming server configuration stored in database.

    Replaces environment variables for Icecast configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "icecast_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Connection Settings
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    server = db.Column(db.String(255), nullable=False, default='localhost')
    port = db.Column(db.Integer, nullable=False, default=8000)
    external_port = db.Column(db.Integer, nullable=True)  # For browser access (optional)
    public_hostname = db.Column(db.String(255), nullable=True)  # Public hostname/IP

    # Authentication
    source_password = db.Column(db.String(255), nullable=False, default='')
    admin_user = db.Column(db.String(255), nullable=True)
    admin_password = db.Column(db.String(255), nullable=True)

    # Stream Settings
    default_mount = db.Column(db.String(255), nullable=False, default='monitor.mp3')
    stream_name = db.Column(db.String(255), nullable=False, default='EAS Station Audio')
    stream_description = db.Column(db.String(500), nullable=False, default='Emergency Alert System Audio Monitor')
    stream_genre = db.Column(db.String(100), nullable=False, default='Emergency')
    stream_bitrate = db.Column(db.Integer, nullable=False, default=128)
    stream_format = db.Column(db.String(10), nullable=False, default='mp3')  # mp3 or ogg
    stream_public = db.Column(db.Boolean, nullable=False, default=False)  # List in directory

    # Server Info (for Icecast XML config)
    server_hostname = db.Column(db.String(255), nullable=True)  # Server hostname for Icecast config
    server_location = db.Column(db.String(255), nullable=True)  # Server location
    admin_contact = db.Column(db.String(255), nullable=True)  # Admin contact email
    
    # Server Limits
    max_sources = db.Column(db.Integer, nullable=True)  # Max concurrent sources (None/0 = unlimited, default: 2)

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "server": self.server,
            "port": self.port,
            "external_port": self.external_port,
            "public_hostname": self.public_hostname,
            "source_password": self.source_password,
            "admin_user": self.admin_user,
            "admin_password": self.admin_password,
            "default_mount": self.default_mount,
            "stream_name": self.stream_name,
            "stream_description": self.stream_description,
            "stream_genre": self.stream_genre,
            "stream_bitrate": self.stream_bitrate,
            "stream_format": self.stream_format,
            "stream_public": self.stream_public,
            "server_hostname": self.server_hostname,
            "server_location": self.server_location,
            "admin_contact": self.admin_contact,
            "max_sources": self.max_sources,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CertbotSettings(db.Model):
    """Certbot/Let's Encrypt SSL certificate configuration stored in database.

    Replaces environment variables for Certbot configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "certbot_settings"

    id = db.Column(db.Integer, primary_key=True)

    # General Settings
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    domain_name = db.Column(db.String(255), nullable=False, default='')
    email = db.Column(db.String(255), nullable=False, default='')

    # Certificate Settings
    staging = db.Column(db.Boolean, nullable=False, default=False)  # Use Let's Encrypt staging server
    auto_renew_enabled = db.Column(db.Boolean, nullable=False, default=True)
    renew_days_before_expiry = db.Column(db.Integer, nullable=False, default=30)

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "domain_name": self.domain_name,
            "email": self.email,
            "staging": self.staging,
            "auto_renew_enabled": self.auto_renew_enabled,
            "renew_days_before_expiry": self.renew_days_before_expiry,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TTSSettings(db.Model):
    """Text-to-Speech configuration stored in database.

    Replaces environment variables for TTS configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "tts_settings"

    id = db.Column(db.Integer, primary_key=True)

    # General Settings
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    provider = db.Column(db.String(50), nullable=False, default='')  # '', 'azure_openai', 'azure', 'pyttsx3'

    # Azure OpenAI Settings
    azure_openai_endpoint = db.Column(db.String(500), nullable=True)
    azure_openai_key = db.Column(db.String(500), nullable=True)
    azure_openai_model = db.Column(db.String(100), nullable=False, default='tts-1')
    azure_openai_voice = db.Column(db.String(50), nullable=False, default='alloy')
    azure_openai_speed = db.Column(db.Float, nullable=False, default=1.0)

    # Azure Cognitive Services Speech Settings
    azure_speech_key = db.Column(db.String(500), nullable=True)
    azure_speech_region = db.Column(db.String(100), nullable=True)
    azure_speech_voice = db.Column(db.String(100), nullable=False, default='en-US-AriaNeural')
    azure_speech_sample_rate = db.Column(db.Integer, nullable=False, default=24000)

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "azure_openai_endpoint": self.azure_openai_endpoint,
            "azure_openai_key": self.azure_openai_key,
            "azure_openai_model": self.azure_openai_model,
            "azure_openai_voice": self.azure_openai_voice,
            "azure_openai_speed": self.azure_openai_speed,
            "azure_speech_key": self.azure_speech_key,
            "azure_speech_region": self.azure_speech_region,
            "azure_speech_voice": self.azure_speech_voice,
            "azure_speech_sample_rate": self.azure_speech_sample_rate,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PollerSettings(db.Model):
    """Alert poller configuration stored in database.

    Replaces environment variables for poller configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "poller_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Poller Configuration
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    # When enabled, the poller service will fetch alerts from CAP feeds

    poll_interval_sec = db.Column(db.Integer, nullable=False, default=120)
    # Seconds between polls (minimum: 30, recommended: 120 for IPAWS, 300 for NOAA)

    cap_timeout = db.Column(db.Integer, nullable=False, default=30)
    # HTTP request timeout in seconds for CAP feed requests

    noaa_user_agent = db.Column(
        db.String(500),
        nullable=False,
        default='EAS Station (+https://github.com/KR8MER/eas-station; support@easstation.com)',
    )
    # User-Agent header sent to NOAA API (required for compliance)

    cap_endpoints = db.Column(JSONB, nullable=False, default=list)
    # List of custom CAP feed URLs to poll (in addition to built-in NOAA feeds)

    ipaws_feed_urls = db.Column(JSONB, nullable=False, default=list)
    # List of IPAWS CAP feed URLs to poll

    ipaws_default_lookback_hours = db.Column(db.Integer, nullable=False, default=12)
    # Hours to look back when constructing IPAWS feed URLs with {timestamp} placeholder

    # Logging Settings
    log_fetched_alerts = db.Column(db.Boolean, nullable=False, default=False)
    # When enabled, poller logs detailed information about each alert fetched
    # including full ID, event type, sent/effective/expires times, urgency/severity/certainty,
    # area description, and headline. Useful for debugging missing alerts.

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "poll_interval_sec": self.poll_interval_sec,
            "cap_timeout": self.cap_timeout,
            "noaa_user_agent": self.noaa_user_agent,
            "cap_endpoints": self.cap_endpoints or [],
            "ipaws_feed_urls": self.ipaws_feed_urls or [],
            "ipaws_default_lookback_hours": self.ipaws_default_lookback_hours,
            "log_fetched_alerts": self.log_fetched_alerts,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EASDecoderMonitorSettings(db.Model):
    """EAS Decoder Monitor Settings - configurable tap to listen to decoder input.
    
    Allows listening to the actual 16 kHz resampled audio fed to the EAS decoder
    to verify sample rate and audio quality.
    """
    __tablename__ = "eas_decoder_monitor_settings"

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    stream_name = db.Column(db.String(255), nullable=False, default="eas-decoder-monitor")
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "stream_name": self.stream_name,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EASSettings(db.Model):
    """EAS Broadcast configuration stored in database.

    Replaces environment variables for EAS encoder/broadcast configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "eas_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # EAS Broadcast Enable/Disable
    # ========================================================================
    broadcast_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for EAS broadcast functionality

    # ========================================================================
    # Station Identity
    # ========================================================================
    originator = db.Column(db.String(8), nullable=False, default='WXR')
    # Originator code: WXR (Weather Radio), EAS, PEP, CIV

    station_id = db.Column(db.String(8), nullable=False, default='EASNODES')
    # 8-character SAME callsign identifier

    # ========================================================================
    # Audio Generation Settings
    # ========================================================================
    output_dir = db.Column(db.String(255), nullable=False, default='static/eas_messages')
    # Directory for generated EAS audio files

    attention_tone_seconds = db.Column(db.Integer, nullable=False, default=8)
    # Duration of the attention tone in seconds (1-25)

    sample_rate = db.Column(db.Integer, nullable=False, default=16000)
    # Audio sample rate for GENERATED EAS alerts: 8000, 16000, 22050, 44100, 48000
    # NOTE: 16kHz is optimal for EAS - lower CPU overhead, adequate quality for SAME tones/voice

    audio_player = db.Column(db.String(255), nullable=False, default='aplay')
    # Command to play audio (aplay, paplay, etc.)

    # ========================================================================
    # Authorized Broadcast Areas
    # ========================================================================
    authorized_fips_codes = db.Column(JSONB, nullable=False, default=list)
    # FIPS codes authorized for manual EAS broadcasts

    authorized_event_codes = db.Column(JSONB, nullable=False, default=list)
    # Event codes authorized for manual broadcasts (RWT, RMT, etc.)

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "broadcast_enabled": self.broadcast_enabled,
            "originator": self.originator,
            "station_id": self.station_id,
            "output_dir": self.output_dir,
            "attention_tone_seconds": self.attention_tone_seconds,
            "sample_rate": self.sample_rate,
            "audio_player": self.audio_player,
            "authorized_fips_codes": list(self.authorized_fips_codes or []),
            "authorized_event_codes": list(self.authorized_event_codes or []),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RadioReceiver(db.Model):
    """Persistent configuration for SDR hardware receivers.

    Note: For internet stream sources (HTTP/M3U), use the AudioSource system instead.
    RadioReceiver is exclusively for SDR hardware like RTL-SDR and Airspy.

    IMPORTANT: sample_rate vs audio_sample_rate
    - sample_rate: IQ sample rate from SDR hardware (e.g., 2.4 MHz for RTL-SDR)
    - audio_sample_rate: Demodulated audio output rate (e.g., 48 kHz for FM stereo)
    """

    __tablename__ = "radio_receivers"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(64), nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    driver = db.Column(db.String(64), nullable=False)
    frequency_hz = db.Column(db.Float, nullable=False)
    sample_rate = db.Column(db.Integer, nullable=False)  # IQ sample rate (MHz range, e.g., 2400000)
    audio_sample_rate = db.Column(db.Integer, nullable=True)  # Audio output rate (kHz range, e.g., 48000)
    frequency_correction_ppm = db.Column(db.Float, nullable=False, default=0.0)  # PPM correction for clock drift
    gain = db.Column(db.Float)
    channel = db.Column(db.Integer)
    serial = db.Column(db.String(128))
    auto_start = db.Column(db.Boolean, nullable=False, default=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    # Audio demodulation settings
    modulation_type = db.Column(db.String(16), nullable=False, default='IQ')  # IQ, FM, AM, NFM, WFM
    audio_output = db.Column(db.Boolean, nullable=False, default=False)  # Enable demodulated audio output
    stereo_enabled = db.Column(db.Boolean, nullable=False, default=True)  # FM stereo decoding
    deemphasis_us = db.Column(db.Float, nullable=False, default=75.0)  # De-emphasis (75μs NA, 50μs EU)
    enable_rbds = db.Column(db.Boolean, nullable=False, default=False)  # Extract RBDS/RDS from FM
    squelch_enabled = db.Column(db.Boolean, nullable=False, default=False)  # Carrier-operated squelch
    squelch_threshold_db = db.Column(db.Float, nullable=False, default=-65.0)  # Threshold in dBFS
    squelch_open_ms = db.Column(db.Integer, nullable=False, default=150)  # Hold time before opening squelch
    squelch_close_ms = db.Column(db.Integer, nullable=False, default=750)  # Hold time before muting
    squelch_alarm = db.Column(db.Boolean, nullable=False, default=False)  # Raise alarm when carrier lost
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    statuses = db.relationship(
        "RadioReceiverStatus",
        back_populates="receiver",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    __table_args__ = (
        db.Index("idx_radio_receivers_identifier", identifier, unique=True),
    )

    def to_receiver_config(self) -> "ReceiverConfig":
        """Translate this database row into a radio manager configuration object."""

        from app_core.radio import ReceiverConfig

        # Determine audio sample rate with intelligent defaults
        audio_rate = self.audio_sample_rate
        if audio_rate is None or audio_rate < 20000:
            # Auto-select based on modulation type and stereo settings
            modulation = (self.modulation_type or 'IQ').upper()
            if modulation in ('FM', 'WFM', 'WBFM'):
                # Wide FM (broadcast): higher quality needed
                audio_rate = 48000 if self.stereo_enabled else 32000
            elif modulation in ('NFM', 'AM'):
                # Narrowband FM or AM: lower rate acceptable
                audio_rate = 24000
            else:
                # IQ or unknown: safe default
                audio_rate = 44100

        return ReceiverConfig(
            identifier=self.identifier,
            driver=self.driver,
            frequency_hz=float(self.frequency_hz),
            sample_rate=int(self.sample_rate),
            audio_sample_rate=int(audio_rate),
            frequency_correction_ppm=float(self.frequency_correction_ppm or 0.0),
            gain=self.gain,
            channel=self.channel,
            serial=self.serial,
            enabled=bool(self.enabled),
            modulation_type=self.modulation_type or 'IQ',
            audio_output=bool(self.audio_output),
            stereo_enabled=bool(self.stereo_enabled),
            deemphasis_us=float(self.deemphasis_us) if self.deemphasis_us else 75.0,
            enable_rbds=bool(self.enable_rbds),
            auto_start=bool(self.auto_start),
            squelch_enabled=bool(self.squelch_enabled),
            squelch_threshold_db=float(self.squelch_threshold_db if self.squelch_threshold_db is not None else -65.0),
            squelch_open_ms=int(self.squelch_open_ms or 150),
            squelch_close_ms=int(self.squelch_close_ms or 750),
            squelch_alarm=bool(self.squelch_alarm),
        )

    def latest_status(self) -> Optional["RadioReceiverStatus"]:
        """Return the most recent status sample if any have been recorded."""

        if self.statuses is None:
            return None

        return self.statuses.order_by(RadioReceiverStatus.reported_at.desc()).first()

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<RadioReceiver id={self.id} identifier={self.identifier!r} "
            f"driver={self.driver!r} frequency_hz={self.frequency_hz}>"
        )


class RadioReceiverStatus(db.Model):
    """Historical status samples emitted by configured receivers."""

    __tablename__ = "radio_receiver_status"

    id = db.Column(db.Integer, primary_key=True)
    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("radio_receivers.id", ondelete="CASCADE"),
        nullable=False,
    )
    reported_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    signal_strength = db.Column(db.Float)
    last_error = db.Column(db.Text)
    capture_mode = db.Column(db.String(16))
    capture_path = db.Column(db.String(255))

    receiver = db.relationship(
        "RadioReceiver",
        back_populates="statuses",
    )

    __table_args__ = (
        db.Index("idx_radio_receiver_status_receiver_id", receiver_id),
        db.Index("idx_radio_receiver_status_reported_at", reported_at.desc()),
    )

    def to_receiver_status(self) -> "ReceiverStatus":
        """Convert the status row into the lightweight dataclass used by the manager."""

        from app_core.radio import ReceiverStatus

        return ReceiverStatus(
            identifier=self.receiver.identifier if self.receiver else "unknown",
            locked=bool(self.locked),
            signal_strength=self.signal_strength,
            last_error=self.last_error,
            capture_mode=self.capture_mode,
            capture_path=self.capture_path,
            reported_at=self.reported_at,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<RadioReceiverStatus receiver_id={self.receiver_id} locked={self.locked} "
            f"signal_strength={self.signal_strength}>"
        )


class LEDMessage(db.Model):
    __tablename__ = "led_messages"

    id = db.Column(db.Integer, primary_key=True)
    message_type = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    priority = db.Column(db.Integer, default=2)
    color = db.Column(db.String(20))
    font_size = db.Column(db.String(20))
    effect = db.Column(db.String(20))
    speed = db.Column(db.String(20))
    display_time = db.Column(db.Integer)
    scheduled_time = db.Column(db.DateTime(timezone=True))
    sent_at = db.Column(db.DateTime(timezone=True))
    is_active = db.Column(db.Boolean, default=True)
    alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id", ondelete="SET NULL"))
    repeat_interval = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)


class LEDSignStatus(db.Model):
    __tablename__ = "led_sign_status"

    id = db.Column(db.Integer, primary_key=True)
    sign_ip = db.Column(db.String(15), nullable=False)
    brightness_level = db.Column(db.Integer, default=10)
    error_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    last_update = db.Column(db.DateTime(timezone=True), default=utc_now)
    is_connected = db.Column(db.Boolean, default=False)
    serial_mode = db.Column(db.String(10), default="RS232")  # RS232 or RS485
    baud_rate = db.Column(db.Integer, default=9600)  # Serial baud rate


class VFDDisplay(db.Model):
    """VFD display content and state tracking."""
    __tablename__ = "vfd_displays"

    id = db.Column(db.Integer, primary_key=True)
    content_type = db.Column(db.String(50), nullable=False)  # text, image, alert, status
    content_data = db.Column(db.Text)  # Text content or image path
    binary_data = db.Column(db.LargeBinary)  # Image binary data
    priority = db.Column(db.Integer, default=2)  # 0=emergency, 1=alert, 2=normal, 3=low
    x_position = db.Column(db.Integer, default=0)
    y_position = db.Column(db.Integer, default=0)
    duration_seconds = db.Column(db.Integer)
    scheduled_time = db.Column(db.DateTime(timezone=True))
    displayed_at = db.Column(db.DateTime(timezone=True))
    is_active = db.Column(db.Boolean, default=True)
    alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)


class VFDStatus(db.Model):
    """VFD display hardware status tracking."""
    __tablename__ = "vfd_status"

    id = db.Column(db.Integer, primary_key=True)
    port = db.Column(db.String(50), nullable=False)
    baudrate = db.Column(db.Integer, default=38400)
    brightness_level = db.Column(db.Integer, default=7)
    is_connected = db.Column(db.Boolean, default=False)
    error_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    last_update = db.Column(db.DateTime(timezone=True), default=utc_now)
    current_content_type = db.Column(db.String(50))  # What's currently displayed


class AudioSourceMetrics(db.Model):
    """Real-time audio source metrics for monitoring and health tracking."""
    __tablename__ = "audio_source_metrics"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)
    source_type = db.Column(db.String(20), nullable=False)
    
    # Audio levels
    peak_level_db = db.Column(db.Float, nullable=False)
    rms_level_db = db.Column(db.Float, nullable=False)
    peak_level_linear = db.Column(db.Float, nullable=False)
    rms_level_linear = db.Column(db.Float, nullable=False)
    
    # Stream information
    sample_rate = db.Column(db.Integer, nullable=False)
    channels = db.Column(db.Integer, nullable=False)
    frames_captured = db.Column(db.BigInteger, nullable=False)
    
    # Health indicators
    silence_detected = db.Column(db.Boolean, default=False)
    clipping_detected = db.Column(db.Boolean, default=False)
    buffer_utilization = db.Column(db.Float, default=0.0)
    
    # Timing
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    # Additional metadata (JSON)
    # Map to existing 'metadata' column to avoid schema drift
    source_metadata = db.Column('metadata', JSONB)


class AudioHealthStatus(db.Model):
    """Overall audio system health status snapshots."""
    __tablename__ = "audio_health_status"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)
    
    # Health score (0-100)
    health_score = db.Column(db.Float, nullable=False)
    
    # Status indicators
    is_active = db.Column(db.Boolean, default=False)
    is_healthy = db.Column(db.Boolean, default=False)
    silence_detected = db.Column(db.Boolean, default=False)
    error_detected = db.Column(db.Boolean, default=False)
    
    # Timing information
    uptime_seconds = db.Column(db.Float, default=0.0)
    silence_duration_seconds = db.Column(db.Float, default=0.0)
    time_since_last_signal_seconds = db.Column(db.Float, default=0.0)
    
    # Trend information
    level_trend = db.Column(db.String(20))  # 'rising', 'falling', 'stable'
    trend_value_db = db.Column(db.Float, default=0.0)
    
    # Timestamps
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    last_update = db.Column(db.DateTime(timezone=True), default=utc_now)

    # Additional metadata (JSON)
    # Map to existing 'metadata' column to avoid schema drift
    health_metadata = db.Column('metadata', JSONB)


class AudioAlert(db.Model):
    """Audio system alerts and notifications."""
    __tablename__ = "audio_alerts"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)
    
    # Alert classification
    alert_level = db.Column(db.String(20), nullable=False)  # 'info', 'warning', 'error', 'critical'
    alert_type = db.Column(db.String(50), nullable=False)   # 'silence', 'clipping', 'disconnect', etc.
    
    # Alert content
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)
    
    # Threshold information
    threshold_value = db.Column(db.Float)
    actual_value = db.Column(db.Float)
    
    # Status
    acknowledged = db.Column(db.Boolean, default=False)
    acknowledged_by = db.Column(db.String(100))
    acknowledged_at = db.Column(db.DateTime(timezone=True))
    
    # Resolution
    resolved = db.Column(db.Boolean, default=False)
    resolved_by = db.Column(db.String(100))
    resolved_at = db.Column(db.DateTime(timezone=True))
    resolution_notes = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Additional metadata (JSON)
    # Map to existing 'metadata' column to avoid schema drift
    alert_metadata = db.Column('metadata', JSONB)


class AudioSourceConfigDB(db.Model):
    """Persistent audio source configurations (database model)."""
    __tablename__ = "audio_source_configs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    source_type = db.Column(db.String(20), nullable=False)  # 'sdr', 'alsa', 'pulse', 'file'

    # Configuration parameters (stored as JSON)
    config_params = db.Column('config', JSONB, nullable=False)

    # Source settings
    priority = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, default=True)
    auto_start = db.Column(db.Boolean, default=False)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Optional description
    description = db.Column(db.Text)

    def to_dict(self):
        """Convert configuration to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'source_type': self.source_type,
            'config': self.config_params or {},
            'priority': self.priority,
            'enabled': self.enabled,
            'auto_start': self.auto_start,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class StreamMetadataLog(db.Model):
    """Persistent log of ICY/stream metadata changes (now-playing events).

    A new row is written every time a source's StreamTitle changes so the
    song-play history can be queried from the web UI.
    """

    __tablename__ = "stream_metadata_log"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    # Parsed fields
    title = db.Column(db.Text)
    artist = db.Column(db.Text)
    album = db.Column(db.Text)
    artwork_url = db.Column(db.Text)
    length = db.Column(db.String(20))
    display = db.Column(db.Text)  # "Artist – Title" display string

    # Raw ICY StreamTitle string
    raw = db.Column(db.Text)

    # Playback URL — populated when the StreamTitle contains a base64-encoded
    # audio/stream URL or an explicit url="" ICY attribute.
    stream_url = db.Column(db.Text)


class GPIOActivationLog(db.Model):
    """Audit log for GPIO relay activations.

    This table provides a complete history of all GPIO pin activations
    for compliance, debugging, and security auditing purposes.
    """
    __tablename__ = "gpio_activation_logs"

    id = db.Column(db.Integer, primary_key=True)

    # Pin identification
    pin = db.Column(db.Integer, nullable=False, index=True)

    # Activation classification
    activation_type = db.Column(db.String(20), nullable=False, index=True)  # 'manual', 'automatic', 'test', 'override'

    # Timing information
    activated_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    deactivated_at = db.Column(db.DateTime(timezone=True))
    duration_seconds = db.Column(db.Float)

    # Attribution
    operator = db.Column(db.String(100))  # Username for manual/override activations
    alert_id = db.Column(db.String(255))  # Alert identifier for automatic activations

    # Context
    reason = db.Column(db.Text)  # Human-readable reason

    # Status
    success = db.Column(db.Boolean, default=True, nullable=False)
    error_message = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'pin': self.pin,
            'activation_type': self.activation_type,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'deactivated_at': self.deactivated_at.isoformat() if self.deactivated_at else None,
            'duration_seconds': self.duration_seconds,
            'operator': self.operator,
            'alert_id': self.alert_id,
            'reason': self.reason,
            'success': self.success,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class DisplayScreen(db.Model):
    """Custom screen templates for LED and VFD displays.

    Defines reusable screen layouts with dynamic content populated from API endpoints.
    Supports conditional display logic and scheduled rotation.
    """
    __tablename__ = "display_screens"

    id = db.Column(db.Integer, primary_key=True)

    # Screen identification
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    display_type = db.Column(db.String(10), nullable=False, index=True)  # 'led', 'vfd', or 'oled'

    # Screen behavior
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    priority = db.Column(db.Integer, default=2)  # 0=emergency, 1=high, 2=normal, 3=low
    refresh_interval = db.Column(db.Integer, default=30)  # Seconds between data refreshes
    duration = db.Column(db.Integer, default=10)  # Seconds to display screen in rotation

    # Template configuration (JSON)
    template_data = db.Column(JSONB, nullable=False)  # Layout, lines, graphics, formatting
    data_sources = db.Column(JSONB, default=list)  # Array of {endpoint, var_name, params}
    conditions = db.Column(JSONB)  # Display conditions (if/then/else logic)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    last_displayed_at = db.Column(db.DateTime(timezone=True))

    # Statistics
    display_count = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)

    def to_dict(self) -> Dict[str, Any]:
        """Convert screen to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'display_type': self.display_type,
            'enabled': self.enabled,
            'priority': self.priority,
            'refresh_interval': self.refresh_interval,
            'duration': self.duration,
            'template_data': dict(self.template_data or {}),
            'data_sources': list(self.data_sources or []),
            'conditions': dict(self.conditions or {}) if self.conditions else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_displayed_at': self.last_displayed_at.isoformat() if self.last_displayed_at else None,
            'display_count': self.display_count,
            'error_count': self.error_count,
            'last_error': self.last_error,
        }


class ScreenRotation(db.Model):
    """Screen rotation schedule for automatic display cycling.

    Manages ordered sequences of screens that rotate at defined intervals.
    Can be enabled/disabled and supports different rotations for LED vs VFD.
    """
    __tablename__ = "screen_rotations"

    id = db.Column(db.Integer, primary_key=True)

    # Rotation identification
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    display_type = db.Column(db.String(10), nullable=False, index=True)  # 'led', 'vfd', or 'oled'

    # Rotation behavior
    enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Screen sequence (JSON array of screen configurations)
    # Format: [{"screen_id": 1, "duration": 10}, {"screen_id": 2, "duration": 15}, ...]
    screens = db.Column(JSONB, nullable=False, default=list)

    # Advanced settings
    randomize = db.Column(db.Boolean, default=False)  # Randomize screen order
    skip_on_alert = db.Column(db.Boolean, default=True)  # Skip rotation when alert active

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Runtime state
    current_screen_index = db.Column(db.Integer, default=0)
    last_rotation_at = db.Column(db.DateTime(timezone=True))

    def to_dict(self) -> Dict[str, Any]:
        """Convert rotation to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'display_type': self.display_type,
            'enabled': self.enabled,
            'screens': list(self.screens or []),
            'randomize': self.randomize,
            'skip_on_alert': self.skip_on_alert,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'current_screen_index': self.current_screen_index,
            'last_rotation_at': self.last_rotation_at.isoformat() if self.last_rotation_at else None,
        }


class RWTScheduleConfig(db.Model):
    """Configuration for automatic Required Weekly Test (RWT) scheduling.

    Allows administrators to configure automatic RWT broadcasts on specific
    days of the week and time windows. The scheduler will automatically generate
    and send RWT tests according to the configured schedule.
    """
    __tablename__ = "rwt_schedule_config"

    id = db.Column(db.Integer, primary_key=True)

    # Schedule configuration
    enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Days of week (0=Monday, 6=Sunday) stored as JSON array
    # Example: [0, 2, 4] for Monday, Wednesday, Friday
    days_of_week = db.Column(JSONB, nullable=False, default=list)

    # Time window configuration
    start_hour = db.Column(db.Integer, nullable=False, default=8)  # 0-23
    start_minute = db.Column(db.Integer, nullable=False, default=0)  # 0-59
    end_hour = db.Column(db.Integer, nullable=False, default=16)  # 0-23
    end_minute = db.Column(db.Integer, nullable=False, default=0)  # 0-59

    # SAME codes to include (JSON array of FIPS codes)
    same_codes = db.Column(JSONB, nullable=False, default=list)

    # Originator code (e.g., 'WXR', 'EAS')
    originator = db.Column(db.String(3), nullable=False, default='WXR')

    # Station identifier
    station_id = db.Column(db.String(8), nullable=False, default='EASNODES')

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Last run tracking
    last_run_at = db.Column(db.DateTime(timezone=True))
    last_run_status = db.Column(db.String(20))  # 'success', 'failed', etc.
    last_run_details = db.Column(JSONB)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for API responses.

        Note: originator and station_id are read from environment variables,
        not from this configuration.
        """
        return {
            'id': self.id,
            'enabled': self.enabled,
            'days_of_week': list(self.days_of_week or []),
            'start_hour': self.start_hour,
            'start_minute': self.start_minute,
            'end_hour': self.end_hour,
            'end_minute': self.end_minute,
            'same_codes': list(self.same_codes or []),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'last_run_status': self.last_run_status,
            'last_run_details': dict(self.last_run_details or {}),
        }


# Snow emergency levels as defined by Ohio law
SNOW_EMERGENCY_LEVELS = {
    0: {
        "name": "None",
        "color": "#28a745",  # Green
        "description": "No snow emergency in effect. Normal driving conditions.",
    },
    1: {
        "name": "Level 1",
        "color": "#ffc107",  # Yellow
        "description": "Roadways are hazardous with blowing and drifting snow. Roads may also be icy. "
                       "Motorists are urged to drive very cautiously.",
    },
    2: {
        "name": "Level 2",
        "color": "#fd7e14",  # Orange
        "description": "Roadways are hazardous with blowing and drifting snow. Only those who feel it is "
                       "necessary to drive should be out on the roadways. Contact your employer to see if "
                       "you should report to work.",
    },
    3: {
        "name": "Level 3",
        "color": "#dc3545",  # Red
        "description": "All roadways are closed to non-emergency personnel. No one should be out during "
                       "these conditions unless it is absolutely necessary to travel. Employees should "
                       "contact their employer to see if they should report to work. Those traveling on "
                       "the roadways may subject themselves to arrest.",
    },
}

# Counties adjoining Putnam County, Ohio with their FIPS codes
# Putnam County borders: Defiance, Henry, Wood, Hancock, Allen, Van Wert, Paulding
PUTNAM_REGION_COUNTIES = {
    "039137": {"name": "Putnam", "state": "OH", "is_primary": True, "order": 0},
    "039003": {"name": "Allen", "state": "OH", "is_primary": False, "order": 1},
    "039039": {"name": "Defiance", "state": "OH", "is_primary": False, "order": 2},
    "039063": {"name": "Hancock", "state": "OH", "is_primary": False, "order": 3},
    "039069": {"name": "Henry", "state": "OH", "is_primary": False, "order": 4},
    "039125": {"name": "Paulding", "state": "OH", "is_primary": False, "order": 5},
    "039161": {"name": "Van Wert", "state": "OH", "is_primary": False, "order": 6},
    "039173": {"name": "Wood", "state": "OH", "is_primary": False, "order": 7},
}


class LocalAuthority(db.Model):
    """A local authority authorized to issue EAS alerts for their political subdivision.

    Each local authority is tied to an AdminUser and defines the jurisdiction
    (FIPS codes), originator code, station identifier, and authorized event
    codes that the authority may use when issuing alerts through the
    Broadcast Builder.
    """
    __tablename__ = "local_authorities"

    id = db.Column(db.Integer, primary_key=True)

    # Link to the admin user account
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Authority identity
    name = db.Column(db.String(128), nullable=False)  # e.g. "Putnam County Sheriff's Office"
    short_name = db.Column(db.String(32))  # e.g. "Putnam Co SO"

    # SAME station identifier (8 characters per EAS plan)
    station_id = db.Column(db.String(8), nullable=False)  # e.g. "PUTNCOSO"

    # Originator code (3 characters: CIV, EAS, WXR, PEP)
    originator = db.Column(db.String(3), nullable=False, default="CIV")

    # Jurisdiction: FIPS codes this authority may broadcast to
    authorized_fips_codes = db.Column(JSONB, nullable=False, default=list)

    # Event codes this authority is allowed to issue (empty = all codes allowed)
    authorized_event_codes = db.Column(JSONB, nullable=False, default=list)

    # Whether this authority is currently enabled
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # Audit fields
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    created_by = db.Column(db.String(128))  # Username of admin who created this authority

    # Relationships
    user = db.relationship("AdminUser", backref=db.backref("local_authority", uselist=False, cascade="all, delete-orphan"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.user.username if self.user else None,
            "name": self.name,
            "short_name": self.short_name,
            "station_id": self.station_id,
            "originator": self.originator,
            "authorized_fips_codes": list(self.authorized_fips_codes or []),
            "authorized_event_codes": list(self.authorized_event_codes or []),
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
        }

    def __repr__(self) -> str:
        return f"<LocalAuthority {self.name} station_id={self.station_id}>"


class SnowEmergency(db.Model):
    """Current snow emergency status for a county.

    Simple tracking of snow emergency levels for Putnam County and adjoining
    counties in Ohio. One row per county, updated when level changes.
    Level 0 means no emergency in effect.

    History of changes is tracked in the history JSONB column.
    """

    __tablename__ = "snow_emergencies"

    id = db.Column(db.Integer, primary_key=True)

    # County identification (unique per county)
    county_fips = db.Column(db.String(6), nullable=False, unique=True, index=True)
    county_name = db.Column(db.String(128), nullable=False)
    state_code = db.Column(db.String(2), nullable=False, default="OH")

    # Current snow emergency level (0 = none, 1-3 = emergency levels)
    level = db.Column(db.Integer, nullable=False, default=0)

    # Whether this county issues snow emergencies (some sheriffs may opt out)
    issues_emergencies = db.Column(db.Boolean, nullable=False, default=True)

    # When the current level was set
    level_set_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    # Who set the current level (username)
    level_set_by = db.Column(db.String(128))

    # Audit fields
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # History tracking (JSON array of {level, set_at, set_by, previous_level})
    history = db.Column(JSONB, default=list)

    def is_active(self) -> bool:
        """Check if a snow emergency is currently in effect (level > 0)."""
        return self.issues_emergencies and self.level > 0

    def get_level_info(self) -> Dict[str, Any]:
        """Get the level information (name, color, description)."""
        return SNOW_EMERGENCY_LEVELS.get(self.level, SNOW_EMERGENCY_LEVELS[0])

    def to_dict(self, include_history: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        level_info = self.get_level_info()
        result = {
            "id": self.id,
            "county_fips": self.county_fips,
            "county_name": self.county_name,
            "state_code": self.state_code,
            "level": self.level,
            "level_name": level_info["name"],
            "level_color": level_info["color"],
            "level_description": level_info["description"],
            "is_active": self.is_active(),
            "issues_emergencies": self.issues_emergencies,
            "level_set_at": self.level_set_at.isoformat() if self.level_set_at else None,
            "level_set_by": self.level_set_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_history:
            result["history"] = list(self.history or [])

        return result

    def set_level(self, new_level: int, set_by: str) -> None:
        """Update the snow emergency level and record in history."""
        if new_level < 0 or new_level > 3:
            raise ValueError(f"Invalid snow emergency level: {new_level}")

        if not self.issues_emergencies and new_level > 0:
            raise ValueError("This county does not issue snow emergencies")

        if new_level != self.level:
            # Record the change in history
            history_entry = {
                "previous_level": self.level,
                "new_level": new_level,
                "set_at": utc_now().isoformat(),
                "set_by": set_by,
            }
            if self.history is None:
                self.history = []
            # Keep last 100 history entries
            self.history = (list(self.history) + [history_entry])[-100:]

            self.level = new_level
            self.level_set_at = utc_now()
            self.level_set_by = set_by

    def __repr__(self) -> str:
        return (
            f"<SnowEmergency county={self.county_name} "
            f"level={self.level}>"
        )


class NotificationSettings(db.Model):
    """Notification configuration stored in database.

    Replaces ENABLE_EMAIL_NOTIFICATIONS, ENABLE_SMS_NOTIFICATIONS, MAIL_URL,
    and COMPLIANCE_ALERT_EMAILS environment variables.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "notification_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # Email Notifications
    # ========================================================================
    email_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for email notifications

    smtp_host = db.Column(db.String(255), nullable=False, default='')
    # SMTP server hostname (e.g. smtp.gmail.com)

    smtp_port = db.Column(db.Integer, nullable=False, default=587)
    # SMTP server port (e.g. 587, 465, 25)

    smtp_username = db.Column(db.String(255), nullable=False, default='')
    # SMTP authentication username / login email

    smtp_password = db.Column(db.String(255), nullable=False, default='')
    # SMTP authentication password

    smtp_security = db.Column(db.String(10), nullable=False, default='starttls')
    # Connection security: "none", "starttls", or "ssl"

    compliance_alert_emails = db.Column(JSONB, nullable=False, default=list)
    # List of email addresses for compliance/health alert notifications

    alert_emails = db.Column(JSONB, nullable=False, default=list)
    # List of email addresses for EAS alert notifications (separate from compliance emails)

    email_attach_audio = db.Column(db.Boolean, nullable=False, default=False)
    # Attach composite EAS audio file to alert notification emails

    # ========================================================================
    # SMS Notifications
    # ========================================================================
    sms_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for SMS notifications

    sms_provider = db.Column(db.String(50), nullable=False, default='twilio')
    # SMS gateway provider: 'twilio'

    sms_account_sid = db.Column(db.String(255), nullable=False, default='')
    # Twilio Account SID

    sms_auth_token = db.Column(db.String(255), nullable=False, default='')
    # Twilio Auth Token

    sms_from_number = db.Column(db.String(50), nullable=False, default='')
    # Twilio sending phone number in E.164 format (e.g. +15555550100)

    sms_recipients = db.Column(JSONB, nullable=False, default=list)
    # List of destination phone numbers in E.164 format

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "email_enabled": self.email_enabled,
            "smtp_host": self.smtp_host or "",
            "smtp_port": self.smtp_port or 587,
            "smtp_username": self.smtp_username or "",
            # smtp_password intentionally omitted from API responses
            "smtp_security": self.smtp_security or "starttls",
            "compliance_alert_emails": self.compliance_alert_emails or [],
            "alert_emails": self.alert_emails or [],
            "email_attach_audio": self.email_attach_audio,
            "sms_enabled": self.sms_enabled,
            "sms_provider": self.sms_provider or "twilio",
            "sms_account_sid": self.sms_account_sid or "",
            # sms_auth_token intentionally omitted from API responses
            "sms_from_number": self.sms_from_number or "",
            "sms_recipients": self.sms_recipients or [],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ApplicationSettings(db.Model):
    """Application-level settings stored in database.

    Replaces LOG_LEVEL, LOG_FILE, and UPLOAD_FOLDER environment variables.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "application_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # Logging
    # ========================================================================
    log_level = db.Column(db.String(16), nullable=False, default='INFO')
    # Application logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL

    log_file = db.Column(db.String(255), nullable=False, default='logs/eas_station.log')
    # Path to the application log file

    # ========================================================================
    # File Storage
    # ========================================================================
    upload_folder = db.Column(db.String(255), nullable=False, default='/opt/eas-station/uploads')
    # Directory for uploaded files

    # ========================================================================
    # Password Policy
    # ========================================================================
    password_min_length = db.Column(db.Integer, nullable=False, default=8)
    # Minimum number of characters required in a password

    password_require_uppercase = db.Column(db.Boolean, nullable=False, default=False)
    # Require at least one uppercase letter (A-Z)

    password_require_lowercase = db.Column(db.Boolean, nullable=False, default=False)
    # Require at least one lowercase letter (a-z)

    password_require_digits = db.Column(db.Boolean, nullable=False, default=False)
    # Require at least one digit (0-9)

    password_require_special = db.Column(db.Boolean, nullable=False, default=False)
    # Require at least one special character (!@#$%^&*...)

    password_expiration_days = db.Column(db.Integer, nullable=False, default=0)
    # Number of days before a password expires (0 = disabled)

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "log_level": self.log_level,
            "log_file": self.log_file,
            "upload_folder": self.upload_folder,
            "password_min_length": self.password_min_length,
            "password_require_uppercase": self.password_require_uppercase,
            "password_require_lowercase": self.password_require_lowercase,
            "password_require_digits": self.password_require_digits,
            "password_require_special": self.password_require_special,
            "password_expiration_days": self.password_expiration_days,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TailscaleSettings(db.Model):
    """Tailscale VPN configuration stored in database.

    Manages Tailscale daemon settings through the web UI.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "tailscale_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # General Settings
    # ========================================================================
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch: when enabled, tailscaled will be started/maintained

    auth_key = db.Column(db.String(500), nullable=False, default='')
    # Pre-authentication key from Tailscale admin console

    hostname = db.Column(db.String(255), nullable=False, default='')
    # Hostname to advertise on the tailnet (blank = system hostname)

    # ========================================================================
    # Network Settings
    # ========================================================================
    advertise_exit_node = db.Column(db.Boolean, nullable=False, default=False)
    # Offer this node as an exit node for the tailnet

    accept_routes = db.Column(db.Boolean, nullable=False, default=True)
    # Accept subnet routes advertised by other nodes

    advertise_routes = db.Column(db.String(1000), nullable=False, default='')
    # Comma-separated CIDR ranges to advertise (e.g. "192.168.1.0/24,10.0.0.0/8")

    shields_up = db.Column(db.Boolean, nullable=False, default=False)
    # Block all incoming connections (outbound-only mode)

    # ========================================================================
    # DNS Settings
    # ========================================================================
    accept_dns = db.Column(db.Boolean, nullable=False, default=True)
    # Accept DNS configuration from the tailnet

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "auth_key": self.auth_key,
            "hostname": self.hostname,
            "advertise_exit_node": self.advertise_exit_node,
            "accept_routes": self.accept_routes,
            "advertise_routes": self.advertise_routes,
            "shields_up": self.shields_up,
            "accept_dns": self.accept_dns,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class USCountyBoundary(db.Model):
    """US Census county boundary for FIPS-based alert geometry lookup.

    Loaded from Census Bureau TIGER/Line shapefiles.  Used to build
    union geometry for multi-county IPAWS alerts that carry SAME geocodes
    but no inline polygon.
    """
    __tablename__ = "us_county_boundaries"

    id = db.Column(db.Integer, primary_key=True)
    statefp = db.Column(db.String(2), nullable=False, index=True)
    countyfp = db.Column(db.String(3), nullable=False)
    geoid = db.Column(db.String(5), nullable=False, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    namelsad = db.Column(db.String(255))
    stusps = db.Column(db.String(2))
    state_name = db.Column(db.String(100))
    aland = db.Column(db.BigInteger)
    awater = db.Column(db.BigInteger)
    geom = db.Column(_geometry_type("MULTIPOLYGON"))

    @property
    def same_code(self) -> str:
        """Return the 6-digit SAME code (0 + STATEFP + COUNTYFP)."""
        return f"0{self.statefp}{self.countyfp}"

    def __repr__(self) -> str:
        return f"<USCountyBoundary {self.geoid} {self.namelsad or self.name}>"


__all__ = [
    "db",
    "AlertDeliveryReport",
    "ApplicationSettings",
    "AudioAlert",
    "AudioHealthStatus",
    "AudioSourceConfigDB",
    "AudioSourceMetrics",
    "AdminUser",
    "Boundary",
    "CAPAlert",
    "CertbotSettings",
    "DisplayScreen",
    "EASDecodedAudio",
    "EASMessage",
    "GPIOActivationLog",
    "IcecastSettings",
    "Intersection",
    "LEDMessage",
    "LEDSignStatus",
    "LocalAuthority",
    "LocationSettings",
    "ManualEASActivation",
    "NotificationSettings",
    "NWSZone",
    "Permission",
    "PollDebugRecord",
    "PollHistory",
    "PUTNAM_REGION_COUNTIES",
    "RadioReceiver",
    "RadioReceiverStatus",
    "ReceivedEASAlert",
    "Role",
    "RWTScheduleConfig",
    "ScreenRotation",
    "SNOW_EMERGENCY_LEVELS",
    "SnowEmergency",
    "StreamMetadataLog",
    "SystemLog",
    "TailscaleSettings",
    "USCountyBoundary",
    "VFDDisplay",
    "VFDStatus",
]
