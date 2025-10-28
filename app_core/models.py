"""Database models used by the NOAA alerts application."""

from __future__ import annotations

import hashlib
from typing import Any, Dict

from flask import current_app, has_app_context
from geoalchemy2 import Geometry
from werkzeug.security import (
    check_password_hash as werkzeug_check_password_hash,
    generate_password_hash as werkzeug_generate_password_hash,
)

from app_utils import utc_now
from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS

from .extensions import db


def _log_warning(message: str) -> None:
    """Log a warning using the configured Flask application logger."""

    if has_app_context():
        current_app.logger.warning(message)


class Boundary(db.Model):
    __tablename__ = "boundaries"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    geom = db.Column(Geometry("GEOMETRY", srid=4326))
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
    geom = db.Column(Geometry("POLYGON", srid=4326))
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


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
        }


class EASMessage(db.Model):
    __tablename__ = "eas_messages"

    id = db.Column(db.Integer, primary_key=True)
    cap_alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id"), index=True)
    same_header = db.Column(db.String(255), nullable=False)
    audio_filename = db.Column(db.String(255), nullable=False)
    text_filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    metadata = db.Column(db.JSON, default=dict)

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
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata or {},
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
    zone_codes = db.Column(
        db.JSON,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["zone_codes"]),
    )
    area_terms = db.Column(
        db.JSON,
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
        db.JSON,
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
            "zone_codes": list(self.zone_codes or []),
            "area_terms": list(self.area_terms or []),
            "map_center_lat": self.map_center_lat,
            "map_center_lng": self.map_center_lng,
            "map_default_zoom": self.map_default_zoom,
            "led_default_lines": list(self.led_default_lines or []),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


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
]
