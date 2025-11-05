"""
Authentication and authorization module for EAS Station.

This module provides:
- Role-based access control (RBAC)
- Multi-factor authentication (MFA/TOTP)
- Security audit logging
- Permission decorators
"""

from .roles import Role, Permission, require_permission, has_permission
from .mfa import MFAManager, generate_totp_secret, verify_totp_code
from .audit import AuditLogger, AuditAction

__all__ = [
    'Role',
    'Permission',
    'require_permission',
    'has_permission',
    'MFAManager',
    'generate_totp_secret',
    'verify_totp_code',
    'AuditLogger',
    'AuditAction',
]
