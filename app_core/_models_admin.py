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

"""Admin user, session, and system log models."""

from ._models_base import (
    Any,
    Dict,
    _log_info,
    _log_warning,
    db,
    hashlib,
    utc_now,
    werkzeug_check_password_hash,
    werkzeug_generate_password_hash,
)


class SystemLog(db.Model):
    __tablename__ = "system_log"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now)
    level = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    module = db.Column(db.String(100))
    details = db.Column(db.JSON)
    # Correlation ID tying this row to the alert lifecycle it belongs to.
    # Auto-populated from the logging_context ContextVar when a row is
    # inserted while an alert is being processed; left NULL otherwise.
    alert_identifier = db.Column(db.String(255), nullable=True, index=True)


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
    # RFC 6238 time step of the last accepted TOTP code.  Replay prevention
    # compares against this counter rather than elapsed wall-clock time, so a
    # newly rotated code is accepted immediately while a reused one is not.
    mfa_last_totp_counter = db.Column(db.BigInteger, nullable=True)

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


