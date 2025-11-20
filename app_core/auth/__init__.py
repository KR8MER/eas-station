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
Authentication and authorization module for EAS Station.

This module provides:
- Role-based access control (RBAC)
- Multi-factor authentication (MFA/TOTP)
- Security audit logging
- Permission decorators
- Authentication decorators
"""

from .roles import Role, Permission, require_permission, has_permission
from .mfa import MFAManager, generate_totp_secret, verify_totp_code
from .audit import AuditLogger, AuditAction
from .decorators import require_auth, require_role

__all__ = [
    'Role',
    'Permission',
    'require_permission',
    'has_permission',
    'require_auth',
    'require_role',
    'MFAManager',
    'generate_totp_secret',
    'verify_totp_code',
    'AuditLogger',
    'AuditAction',
]
