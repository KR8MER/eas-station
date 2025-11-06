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
from flask import session, abort, current_app
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
                current_app.logger.warning(
                    f"Permission denied: {permission_name} for user {session.get('user_id')}"
                )
                abort(403)  # Forbidden
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
                abort(403)

            if user.role and any(user.role.has_permission(p) for p in permission_names):
                return f(*args, **kwargs)

            current_app.logger.warning(
                f"Permission denied: needs any of {permission_names} for user {session.get('user_id')}"
            )
            abort(403)
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
                abort(403)

            if user.role and all(user.role.has_permission(p) for p in permission_names):
                return f(*args, **kwargs)

            current_app.logger.warning(
                f"Permission denied: needs all of {permission_names} for user {session.get('user_id')}"
            )
            abort(403)
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
            perm = Permission(
                name=perm_name,
                resource=resource,
                action=action,
                description=f"Permission to {action} {resource}"
            )
            db.session.add(perm)
        permissions_map[perm_name] = perm

    db.session.flush()

    # Create roles and assign permissions
    for role_name, perm_defs in DEFAULT_ROLE_PERMISSIONS.items():
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            role = Role(
                name=role_name,
                description=f"{role_name.capitalize()} role with predefined permissions"
            )
            db.session.add(role)
            db.session.flush()

        # Assign permissions to role
        for perm_def in perm_defs:
            perm_name = perm_def.value
            perm = permissions_map.get(perm_name)
            if perm and perm not in role.permissions:
                role.permissions.append(perm)

    db.session.commit()
    current_app.logger.info("Initialized default roles and permissions")
