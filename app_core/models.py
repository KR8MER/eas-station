"""Database models used by the NOAA alerts application."""

from __future__ import annotations

import hashlib
import os
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

    # MFA fields
    mfa_enabled = db.Column(db.Boolean, default=False, nullable=False)
    mfa_secret = db.Column(db.String(255), nullable=True)  # Base32-encoded TOTP secret
    mfa_backup_codes_hash = db.Column(db.Text, nullable=True)  # JSON array of hashed backup codes
    mfa_enrolled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    role = db.relationship('Role', back_populates='users', lazy='joined')

    def set_password(self, password: str) -> None:
        self.password_hash = werkzeug_generate_password_hash(password)
        self.salt = "pbkdf2"

    def check_password(self, password: str) -> bool:
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
                    self.set_password(password)
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
            "role": self.role.name if self.role else None,
            "role_id": self.role_id,
            "mfa_enabled": self.mfa_enabled,
            "mfa_enrolled_at": self.mfa_enrolled_at.isoformat() if self.mfa_enrolled_at else None,
        }

    @property
    def is_authenticated(self) -> bool:
        """Flask-style authentication flag used by templates."""

        return bool(self.is_active)


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
    message_audio_data = db.Column(db.LargeBinary)
    eom_audio_data = db.Column(db.LargeBinary)
    buffer_audio_data = db.Column(db.LargeBinary)

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
            "has_message_audio": self.message_audio_data is not None,
            "has_eom_audio": self.eom_audio_data is not None,
            "has_buffer_audio": self.buffer_audio_data is not None,
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
    # Binary audio data cached in database
    composite_audio_data = db.Column(db.LargeBinary)
    same_audio_data = db.Column(db.LargeBinary)
    attention_audio_data = db.Column(db.LargeBinary)
    tts_audio_data = db.Column(db.LargeBinary)
    eom_audio_data = db.Column(db.LargeBinary)

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
            "area_terms": list(self.area_terms or []),
            "map_center_lat": self.map_center_lat,
            "map_center_lng": self.map_center_lng,
            "map_default_zoom": self.map_default_zoom,
            "led_default_lines": list(self.led_default_lines or []),
            "same_codes": list(self.fips_codes or []),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RadioReceiver(db.Model):
    """Persistent configuration for SDR hardware receivers.

    Note: For internet stream sources (HTTP/M3U), use the AudioSource system instead.
    RadioReceiver is exclusively for SDR hardware like RTL-SDR and Airspy.
    """

    __tablename__ = "radio_receivers"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(64), nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    driver = db.Column(db.String(64), nullable=False)
    frequency_hz = db.Column(db.Float, nullable=False)
    sample_rate = db.Column(db.Integer, nullable=False)
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

        return ReceiverConfig(
            identifier=self.identifier,
            driver=self.driver,
            frequency_hz=float(self.frequency_hz),
            sample_rate=int(self.sample_rate),
            gain=self.gain,
            channel=self.channel,
            serial=self.serial,
            enabled=bool(self.enabled and self.auto_start),
            modulation_type=self.modulation_type or 'IQ',
            audio_output=bool(self.audio_output),
            stereo_enabled=bool(self.stereo_enabled),
            deemphasis_us=float(self.deemphasis_us) if self.deemphasis_us else 75.0,
            enable_rbds=bool(self.enable_rbds),
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
    alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id"))
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
    alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id"))
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
    display_type = db.Column(db.String(10), nullable=False, index=True)  # 'led' or 'vfd'

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
    display_type = db.Column(db.String(10), nullable=False, index=True)  # 'led' or 'vfd'

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


__all__ = [
    "Boundary",
    "CAPAlert",
    "SystemLog",
    "AdminUser",
    "EASMessage",
    "Intersection",
    "PollHistory",
    "LocationSettings",
    "LEDMessage",
    "LEDSignStatus",
    "RadioReceiver",
    "RadioReceiverStatus",
    "AudioSourceMetrics",
    "AudioHealthStatus",
    "AudioAlert",
    "AudioSourceConfigDB",
    "GPIOActivationLog",
    "DisplayScreen",
    "ScreenRotation",
    "VFDDisplay",
    "VFDStatus",
]
