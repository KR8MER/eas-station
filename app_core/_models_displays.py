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

"""Screen rotation, GPIO log, RWT scheduling, and local-authority models."""

from ._models_base import Any, Dict, JSONB, db, utc_now


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

    # Manual skip: when set, the scheduler will not fire on any configured
    # day whose local date is on or before ``skip_until``.  Operators set
    # this from the RWT Schedule page to pause automatic RWT broadcasts for
    # one or more upcoming scheduled days (e.g. holiday, planned manual
    # test).  Stored as a calendar DATE in the station's local timezone.
    skip_until = db.Column(db.Date, nullable=True)

    # Heartbeat: updated by the RWT scheduler on every check (~ every
    # minute).  Persisted in the DB rather than kept in-process so the
    # web UI can show "scheduler alive" indication across all Gunicorn
    # workers without coordinating shared memory.
    last_heartbeat_at = db.Column(db.DateTime(timezone=True))

    # Optional spoken station announcements that bracket the automated
    # weekly test -- e.g. "This station is conducting a test of the
    # Emergency Alert System" before the SAME header, and "This concludes
    # this test of the Emergency Alert System" after the EOM. These are
    # synthesized via the configured TTS provider at broadcast time and
    # play outside the encoded SAME/EOM burst itself (see
    # EASAudioGenerator.build_manual_components's lead/trail announcement
    # handling) -- they are station courtesy IDs, not the CAP-message
    # narration §11.61(a)(1)(ii) prohibits during an RWT.
    pre_announcement_enabled = db.Column(db.Boolean, default=False, nullable=False)
    pre_announcement_text = db.Column(db.Text, nullable=True)
    post_announcement_enabled = db.Column(db.Boolean, default=False, nullable=False)
    post_announcement_text = db.Column(db.Text, nullable=True)

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
            'skip_until': self.skip_until.isoformat() if self.skip_until else None,
            'last_heartbeat_at': (
                self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None
            ),
            'pre_announcement_enabled': bool(self.pre_announcement_enabled),
            'pre_announcement_text': self.pre_announcement_text or '',
            'post_announcement_enabled': bool(self.post_announcement_enabled),
            'post_announcement_text': self.post_announcement_text or '',
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
    name = db.Column(db.String(128), nullable=False)  # e.g. "Example County Sheriff's Office"
    short_name = db.Column(db.String(32))  # e.g. "Example Co SO"

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


