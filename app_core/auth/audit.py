"""
Security audit logging for tracking sensitive operations.

Provides:
- Comprehensive audit trail for security events
- IP address and user agent tracking
- Action categorization and filtering
- Retention management
"""

from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from flask import request, session, current_app
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Index

from app_core.extensions import db
from app_utils.timestamp import utc_now


class AuditAction(Enum):
    """Categorized audit actions for security events."""

    # Authentication events
    LOGIN_SUCCESS = 'auth.login.success'
    LOGIN_FAILURE = 'auth.login.failure'
    LOGOUT = 'auth.logout'
    SESSION_EXPIRED = 'auth.session.expired'

    # MFA events
    MFA_ENROLLED = 'mfa.enrolled'
    MFA_DISABLED = 'mfa.disabled'
    MFA_VERIFY_SUCCESS = 'mfa.verify.success'
    MFA_VERIFY_FAILURE = 'mfa.verify.failure'
    MFA_BACKUP_CODE_USED = 'mfa.backup_code.used'

    # User management events
    USER_CREATED = 'user.created'
    USER_UPDATED = 'user.updated'
    USER_DELETED = 'user.deleted'
    USER_ACTIVATED = 'user.activated'
    USER_DEACTIVATED = 'user.deactivated'
    USER_ROLE_CHANGED = 'user.role.changed'
    PASSWORD_CHANGED = 'user.password.changed'

    # Role/Permission management
    ROLE_CREATED = 'role.created'
    ROLE_UPDATED = 'role.updated'
    ROLE_DELETED = 'role.deleted'
    PERMISSION_GRANTED = 'permission.granted'
    PERMISSION_REVOKED = 'permission.revoked'

    # EAS operations
    EAS_BROADCAST = 'eas.broadcast'
    EAS_MANUAL_ACTIVATION = 'eas.manual_activation'
    EAS_CANCELLATION = 'eas.cancellation'

    # System configuration
    CONFIG_UPDATED = 'config.updated'
    RECEIVER_CONFIGURED = 'receiver.configured'
    GPIO_ACTIVATED = 'gpio.activated'
    GPIO_DEACTIVATED = 'gpio.deactivated'

    # Data operations
    ALERT_DELETED = 'alert.deleted'
    LOG_EXPORTED = 'log.exported'
    LOG_DELETED = 'log.deleted'

    # Security events
    PERMISSION_DENIED = 'security.permission_denied'
    INVALID_TOKEN = 'security.invalid_token'
    RATE_LIMIT_EXCEEDED = 'security.rate_limit_exceeded'


class AuditLog(db.Model):
    """Comprehensive audit log for security-sensitive operations."""
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)  # Nullable for anonymous actions
    username = Column(String(64), nullable=True)  # Denormalized for historical record
    action = Column(String(128), nullable=False, index=True)
    resource_type = Column(String(64), nullable=True, index=True)  # e.g., 'user', 'role', 'alert'
    resource_id = Column(String(128), nullable=True)  # ID of affected resource
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(512), nullable=True)
    success = Column(db.Boolean, default=True, nullable=False, index=True)
    details = Column(JSON, nullable=True)  # Additional context as JSON
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Indexes for common queries
    __table_args__ = (
        Index('ix_audit_logs_user_action', 'user_id', 'action'),
        Index('ix_audit_logs_timestamp_action', 'timestamp', 'action'),
    )

    def __repr__(self):
        return f'<AuditLog {self.action} by {self.username} at {self.timestamp}>'

    def to_dict(self) -> Dict[str, Any]:
        """Convert audit log to dictionary."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'user_id': self.user_id,
            'username': self.username,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'success': self.success,
            'details': self.details,
        }


class AuditLogger:
    """Utility class for creating audit log entries."""

    @staticmethod
    def log(
        action: AuditAction,
        success: bool = True,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """
        Create an audit log entry.

        Args:
            action: AuditAction enum value
            success: Whether the action succeeded
            user_id: ID of user performing action (auto-detected if None)
            username: Username (auto-detected if None)
            resource_type: Type of resource affected
            resource_id: ID of resource affected
            details: Additional context as dictionary
            ip_address: IP address (auto-detected if None)
            user_agent: User agent (auto-detected if None)

        Returns:
            Created AuditLog instance
        """
        # Auto-detect user from session if not provided
        if user_id is None and session.get('user_id'):
            user_id = session.get('user_id')

        if username is None and user_id:
            try:
                from app_core.models import AdminUser
                user = AdminUser.query.get(user_id)
                if user:
                    username = user.username
            except Exception as e:
                current_app.logger.warning(f"Could not fetch username for audit log: {e}")

        # Auto-detect IP and user agent from request context
        if ip_address is None and request:
            # Try X-Forwarded-For first (for proxy/load balancer scenarios)
            ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
            if ip_address and ',' in ip_address:
                # Take first IP if multiple
                ip_address = ip_address.split(',')[0].strip()

        if user_agent is None and request:
            user_agent = request.headers.get('User-Agent')
            if user_agent and len(user_agent) > 512:
                user_agent = user_agent[:512]  # Truncate to fit column

        # Create audit log entry
        log_entry = AuditLog(
            action=action.value,
            success=success,
            user_id=user_id,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
        )

        db.session.add(log_entry)

        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to write audit log: {e}")
            db.session.rollback()

        return log_entry

    @staticmethod
    def log_login_success(user_id: int, username: str):
        """Log successful login."""
        return AuditLogger.log(
            action=AuditAction.LOGIN_SUCCESS,
            user_id=user_id,
            username=username,
            details={'method': 'password'}
        )

    @staticmethod
    def log_login_failure(username: str, reason: str = 'invalid_credentials'):
        """Log failed login attempt."""
        return AuditLogger.log(
            action=AuditAction.LOGIN_FAILURE,
            success=False,
            username=username,
            details={'reason': reason}
        )

    @staticmethod
    def log_logout(user_id: int, username: str):
        """Log user logout."""
        return AuditLogger.log(
            action=AuditAction.LOGOUT,
            user_id=user_id,
            username=username
        )

    @staticmethod
    def log_mfa_enrolled(user_id: int, username: str):
        """Log MFA enrollment."""
        return AuditLogger.log(
            action=AuditAction.MFA_ENROLLED,
            user_id=user_id,
            username=username
        )

    @staticmethod
    def log_mfa_verify_success(user_id: int, username: str, method: str = 'totp'):
        """Log successful MFA verification."""
        return AuditLogger.log(
            action=AuditAction.MFA_VERIFY_SUCCESS,
            user_id=user_id,
            username=username,
            details={'method': method}
        )

    @staticmethod
    def log_mfa_verify_failure(user_id: int, username: str):
        """Log failed MFA verification."""
        return AuditLogger.log(
            action=AuditAction.MFA_VERIFY_FAILURE,
            success=False,
            user_id=user_id,
            username=username
        )

    @staticmethod
    def log_user_created(creator_id: int, creator_username: str, new_user_id: int, new_username: str):
        """Log user creation."""
        return AuditLogger.log(
            action=AuditAction.USER_CREATED,
            user_id=creator_id,
            username=creator_username,
            resource_type='user',
            resource_id=str(new_user_id),
            details={'new_username': new_username}
        )

    @staticmethod
    def log_permission_denied(user_id: Optional[int], username: Optional[str], permission: str, resource: str):
        """Log permission denied event."""
        return AuditLogger.log(
            action=AuditAction.PERMISSION_DENIED,
            success=False,
            user_id=user_id,
            username=username,
            details={'permission': permission, 'resource': resource}
        )

    @staticmethod
    def cleanup_old_logs(days: int = 90):
        """
        Delete audit logs older than specified days.

        Args:
            days: Number of days to retain logs

        Returns:
            Number of logs deleted
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = db.session.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete()
        db.session.commit()
        current_app.logger.info(f"Cleaned up {result} audit logs older than {days} days")
        return result
