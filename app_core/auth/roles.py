"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""
Role-Based Access Control (RBAC) implementation.

Provides:
- Role and Permission models
- Permission checking decorators
- Default role definitions
"""

from enum import Enum
from functools import wraps
from typing import List, Set, Optional
from urllib.parse import urlencode

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from sqlalchemy import Column, Integer, String, ForeignKey, Table, DateTime, Text
from sqlalchemy.orm import relationship

from app_core.extensions import db
from app_utils import utc_now


# Association table for many-to-many relationship
role_permissions = Table(
    'role_permissions',
    db.metadata,
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)


class Role(db.Model):
    """User role with associated permissions."""
    __tablename__ = 'roles'

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    permissions = relationship('Permission', secondary=role_permissions, back_populates='roles')
    users = relationship('AdminUser', back_populates='role')

    def __repr__(self):
        return f'<Role {self.name}>'

    def has_permission(self, permission_name: str) -> bool:
        """Check if this role has a specific permission."""
        return any(p.name == permission_name for p in self.permissions)

    def get_permission_names(self) -> Set[str]:
        """Get set of all permission names for this role."""
        return {p.name for p in self.permissions}

    def to_dict(self):
        """Convert role to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'permissions': [p.to_dict() for p in self.permissions],
            'user_count': len(self.users),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Permission(db.Model):
    """Permission that can be assigned to roles."""
    __tablename__ = 'permissions'

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    resource = Column(String(64), nullable=False)  # e.g., 'alerts', 'eas', 'system'
    action = Column(String(64), nullable=False)    # e.g., 'view', 'create', 'delete'
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    roles = relationship('Role', secondary=role_permissions, back_populates='permissions')

    def __repr__(self):
        return f'<Permission {self.name}>'

    def to_dict(self):
        """Convert permission to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'resource': self.resource,
            'action': self.action,
            'description': self.description,
        }


class RoleDefinition(Enum):
    """Predefined role names."""
    ADMIN = 'admin'
    OPERATOR = 'operator'
    VIEWER = 'viewer'
    DEMO = 'demo'


class PermissionDefinition(Enum):
    """Predefined permission names (resource.action format)."""
    # Alert permissions
    ALERTS_VIEW = 'alerts.view'
    ALERTS_CREATE = 'alerts.create'
    ALERTS_DELETE = 'alerts.delete'
    ALERTS_EXPORT = 'alerts.export'

    # EAS broadcast permissions
    EAS_VIEW = 'eas.view'
    EAS_BROADCAST = 'eas.broadcast'
    EAS_MANUAL_ACTIVATE = 'eas.manual_activate'
    EAS_CANCEL = 'eas.cancel'

    # System configuration permissions
    SYSTEM_CONFIGURE = 'system.configure'
    SYSTEM_VIEW_CONFIG = 'system.view_config'
    SYSTEM_MANAGE_USERS = 'system.manage_users'
    SYSTEM_VIEW_USERS = 'system.view_users'

    # Log permissions
    LOGS_VIEW = 'logs.view'
    LOGS_EXPORT = 'logs.export'
    LOGS_DELETE = 'logs.delete'

    # Receiver permissions
    RECEIVERS_VIEW = 'receivers.view'
    RECEIVERS_CONFIGURE = 'receivers.configure'
    RECEIVERS_DELETE = 'receivers.delete'

    # GPIO permissions
    GPIO_VIEW = 'gpio.view'
    GPIO_CONTROL = 'gpio.control'

    # API permissions
    API_READ = 'api.read'
    API_WRITE = 'api.write'


# Detailed role descriptions for user guidance
ROLE_DESCRIPTIONS = {
    'admin': 'Full system administrator with unrestricted access to all features, settings, and user management. Can configure system, manage users, control broadcasts, and access all logs and data.',
    'operator': 'Alert operator with access to broadcast operations and monitoring. Can initiate EAS broadcasts, control GPIO relays, view alerts and logs, but cannot modify system configuration or manage users.',
    'viewer': 'Read-only access for monitoring and reporting. Can view alerts, logs, statistics, and system status but cannot make any changes or initiate broadcasts.',
    'demo': 'Limited demonstration access for showcasing system features. Can view alerts, EAS workflow, audio monitoring, and non-sensitive settings but cannot export data, access logs, send alerts, or interrupt broadcasts.',
}

# Detailed permission descriptions for user guidance
PERMISSION_DESCRIPTIONS = {
    'alerts.view': 'View CAP alerts, alert history, and alert details on the map and alerts page',
    'alerts.create': 'Create new manual CAP alerts and override automatic alert filtering',
    'alerts.delete': 'Delete CAP alerts from the system (use with caution)',
    'alerts.export': 'Export alert data to CSV, JSON, or other formats for reporting',

    'eas.view': 'View EAS broadcast operations, message history, and transmission status',
    'eas.broadcast': 'Initiate EAS broadcasts manually or automatically based on alerts',
    'eas.manual_activate': 'Manually activate EAS equipment and override automated triggers',
    'eas.cancel': 'Cancel active or scheduled EAS broadcasts (emergency stop)',

    'system.configure': 'Modify system settings, environment variables, and core configuration',
    'system.view_config': 'View system configuration, settings, and environment status (read-only)',
    'system.manage_users': 'Create, modify, and delete user accounts and assign roles',
    'system.view_users': 'View user list, roles, and login history (read-only)',

    'logs.view': 'View system logs, polling logs, audio logs, and GPIO activation logs',
    'logs.export': 'Export log data for auditing, compliance, or troubleshooting purposes',
    'logs.delete': 'Delete log entries (use with caution, may affect audit trails)',

    'receivers.view': 'View configured receivers, SDR status, and receiver health metrics',
    'receivers.configure': 'Add, modify, or configure SDR receivers and audio sources',
    'receivers.delete': 'Remove receivers from the system configuration',

    'gpio.view': 'View GPIO pin status, relay states, and activation history',
    'gpio.control': 'Control GPIO pins, activate/deactivate relays, and test equipment',

    'api.read': 'Read data via REST API endpoints (GET requests)',
    'api.write': 'Modify data via REST API endpoints (POST, PUT, DELETE requests)',
}

# Default role-permission mappings
DEFAULT_ROLE_PERMISSIONS = {
    RoleDefinition.ADMIN.value: [
        # Full access to everything
        PermissionDefinition.ALERTS_VIEW,
        PermissionDefinition.ALERTS_CREATE,
        PermissionDefinition.ALERTS_DELETE,
        PermissionDefinition.ALERTS_EXPORT,
        PermissionDefinition.EAS_VIEW,
        PermissionDefinition.EAS_BROADCAST,
        PermissionDefinition.EAS_MANUAL_ACTIVATE,
        PermissionDefinition.EAS_CANCEL,
        PermissionDefinition.SYSTEM_CONFIGURE,
        PermissionDefinition.SYSTEM_VIEW_CONFIG,
        PermissionDefinition.SYSTEM_MANAGE_USERS,
        PermissionDefinition.SYSTEM_VIEW_USERS,
        PermissionDefinition.LOGS_VIEW,
        PermissionDefinition.LOGS_EXPORT,
        PermissionDefinition.LOGS_DELETE,
        PermissionDefinition.RECEIVERS_VIEW,
        PermissionDefinition.RECEIVERS_CONFIGURE,
        PermissionDefinition.RECEIVERS_DELETE,
        PermissionDefinition.GPIO_VIEW,
        PermissionDefinition.GPIO_CONTROL,
        PermissionDefinition.API_READ,
        PermissionDefinition.API_WRITE,
    ],
    RoleDefinition.OPERATOR.value: [
        # Can manage alerts and EAS, but not system config
        PermissionDefinition.ALERTS_VIEW,
        PermissionDefinition.ALERTS_CREATE,
        PermissionDefinition.ALERTS_EXPORT,
        PermissionDefinition.EAS_VIEW,
        PermissionDefinition.EAS_BROADCAST,
        PermissionDefinition.EAS_MANUAL_ACTIVATE,
        PermissionDefinition.EAS_CANCEL,
        PermissionDefinition.SYSTEM_VIEW_CONFIG,
        PermissionDefinition.SYSTEM_VIEW_USERS,
        PermissionDefinition.LOGS_VIEW,
        PermissionDefinition.LOGS_EXPORT,
        PermissionDefinition.RECEIVERS_VIEW,
        PermissionDefinition.GPIO_VIEW,
        PermissionDefinition.GPIO_CONTROL,
        PermissionDefinition.API_READ,
        PermissionDefinition.API_WRITE,
    ],
    RoleDefinition.VIEWER.value: [
        # Read-only access
        PermissionDefinition.ALERTS_VIEW,
        PermissionDefinition.ALERTS_EXPORT,
        PermissionDefinition.EAS_VIEW,
        PermissionDefinition.SYSTEM_VIEW_CONFIG,
        PermissionDefinition.SYSTEM_VIEW_USERS,
        PermissionDefinition.LOGS_VIEW,
        PermissionDefinition.LOGS_EXPORT,
        PermissionDefinition.RECEIVERS_VIEW,
        PermissionDefinition.GPIO_VIEW,
        PermissionDefinition.API_READ,
    ],
    RoleDefinition.DEMO.value: [
        # Limited demo access - view-only without export, sensitive data, or configuration
        # Safe for public demonstrations - cannot trigger broadcasts, control equipment,
        # access logs, export data, or view sensitive configuration/environment variables
        PermissionDefinition.ALERTS_VIEW,
        PermissionDefinition.EAS_VIEW,
        PermissionDefinition.RECEIVERS_VIEW,
        PermissionDefinition.GPIO_VIEW,
    ],
}


def get_current_user():
    """Get current user from session."""
    from app_core.models import AdminUser
    user_id = session.get('user_id')
    if not user_id:
        return None
    return AdminUser.query.get(user_id)


def has_permission(permission_name: str, user=None) -> bool:
    """
    Check if current user (or specified user) has a permission.

    Args:
        permission_name: Permission name (e.g., 'alerts.view')
        user: Optional user object (defaults to current session user)

    Returns:
        True if user has permission, False otherwise
    """
    if user is None:
        user = get_current_user()

    if not user or not user.is_active:
        return False

    # If user has no role, deny access
    if not user.role:
        return False

    # Check if role has the permission
    return user.role.has_permission(permission_name)


def _wants_json_response() -> bool:
    """Determine if the current request expects a JSON response."""

    if request.is_json:
        return True

    accept_header = request.headers.get("Accept", "")
    return "application/json" in accept_header.lower()


def _build_login_redirect():
    """Redirect the user to the login page with an informative flash message."""

    if _wants_json_response():
        return (
            jsonify(
                {
                    "error": "authentication_required",
                    "message": "Please sign in to continue.",
                }
            ),
            401,
        )

    flash("Please sign in to continue.")

    login_url = url_for("auth.login")
    next_target = None

    if request.method in {"GET", "HEAD"}:
        next_target = request.full_path or request.path
    elif request.referrer:
        next_target = request.referrer

    if next_target:
        # Flask's full_path appends a trailing '?' when there is no query string.
        if next_target.endswith("?"):
            next_target = next_target[:-1]
        login_url = f"{login_url}?{urlencode({'next': next_target})}"

    return redirect(login_url)


def _permission_denied_response(permission_name: str):
    """Return a friendly permission denied response without exposing a 403 page."""

    if _wants_json_response():
        return (
            jsonify(
                {
                    "error": "permission_denied",
                    "permission": permission_name,
                    "message": "You do not have permission to perform this action.",
                }
            ),
            403,
        )

    flash("You do not have permission to access that page.")
    # Redirect to the admin dashboard route within its blueprint to avoid
    # BuildError when a non-namespaced endpoint is unavailable.
    return redirect(url_for("dashboard.admin"))


def require_permission(permission_name: str):
    """
    Decorator to require a specific permission for a route.

    Usage:
        @app.route('/admin/users')
        @require_permission('system.manage_users')
        def manage_users():
            ...

    Args:
        permission_name: Permission name (e.g., 'system.manage_users')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not has_permission(permission_name):
                user = get_current_user()
                if not user:
                    return _build_login_redirect()

                current_app.logger.warning(
                    f"Permission denied: {permission_name} for user {session.get('user_id')}"
                )
                return _permission_denied_response(permission_name)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_any_permission(*permission_names: str):
    """
    Decorator to require ANY of the specified permissions.

    Usage:
        @app.route('/alerts')
        @require_any_permission('alerts.view', 'alerts.create')
        def view_alerts():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user or not user.is_active:
                return _build_login_redirect()

            if user.role and any(user.role.has_permission(p) for p in permission_names):
                return f(*args, **kwargs)

            current_app.logger.warning(
                f"Permission denied: needs any of {permission_names} for user {session.get('user_id')}"
            )
            return _permission_denied_response(" or ".join(permission_names))
        return decorated_function
    return decorator


def require_all_permissions(*permission_names: str):
    """
    Decorator to require ALL of the specified permissions.

    Usage:
        @app.route('/critical-action')
        @require_all_permissions('alerts.delete', 'system.configure')
        def critical_action():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user or not user.is_active:
                return _build_login_redirect()

            if user.role and all(user.role.has_permission(p) for p in permission_names):
                return f(*args, **kwargs)

            current_app.logger.warning(
                f"Permission denied: needs all of {permission_names} for user {session.get('user_id')}"
            )
            return _permission_denied_response(" and ".join(permission_names))
        return decorated_function
    return decorator


def initialize_default_roles_and_permissions():
    """
    Initialize default roles and permissions in the database.
    Should be called during application setup.
    """
    # Create all permissions first
    permissions_map = {}
    for perm_def in PermissionDefinition:
        perm_name = perm_def.value
        parts = perm_name.split('.')
        resource = parts[0] if len(parts) > 0 else 'unknown'
        action = parts[1] if len(parts) > 1 else 'unknown'

        perm = Permission.query.filter_by(name=perm_name).first()
        if not perm:
            # Use detailed description from map, or fallback to generic
            description = PERMISSION_DESCRIPTIONS.get(
                perm_name,
                f"Permission to {action} {resource}"
            )
            perm = Permission(
                name=perm_name,
                resource=resource,
                action=action,
                description=description
            )
            db.session.add(perm)
        else:
            # Update description for existing permissions
            new_description = PERMISSION_DESCRIPTIONS.get(perm_name)
            if new_description and perm.description != new_description:
                perm.description = new_description
        permissions_map[perm_name] = perm

    db.session.flush()

    # Create roles and assign permissions
    for role_name, perm_defs in DEFAULT_ROLE_PERMISSIONS.items():
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            # Use detailed description from map, or fallback to generic
            description = ROLE_DESCRIPTIONS.get(
                role_name,
                f"{role_name.capitalize()} role with predefined permissions"
            )
            role = Role(
                name=role_name,
                description=description
            )
            db.session.add(role)
            db.session.flush()
        else:
            # Update description for existing roles
            new_description = ROLE_DESCRIPTIONS.get(role_name)
            if new_description and role.description != new_description:
                role.description = new_description

        # Assign permissions to role
        for perm_def in perm_defs:
            perm_name = perm_def.value
            perm = permissions_map.get(perm_name)
            if perm and perm not in role.permissions:
                role.permissions.append(perm)

    db.session.commit()
    current_app.logger.info("Initialized default roles and permissions")


__all__ = [
    'Role',
    'Permission',
    'RoleDefinition',
    'PermissionDefinition',
    'get_current_user',
    'has_permission',
    'require_permission',
    'require_any_permission',
    'require_all_permissions',
    'initialize_default_roles_and_permissions',
]
