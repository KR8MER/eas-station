"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

FastAPI authentication dependencies and utilities.
Provides session-based authentication with MFA support for FastAPI routes.
"""

from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app_core.fastapi_extensions import get_db
import logging

logger = logging.getLogger(__name__)

# Import models dynamically to avoid circular dependencies
def get_admin_user_model():
    """Lazy import of AdminUser model to avoid circular dependencies"""
    from app_core.models import AdminUser
    return AdminUser

def get_role_model():
    """Lazy import of Role model to avoid circular dependencies"""
    from app_core.auth.models import Role
    return Role


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[object]:
    """
    Dependency to get the current authenticated user from session.
    Returns None if no user is authenticated.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user = Depends(get_current_user)):
            if not user:
                raise HTTPException(401, "Not authenticated")
            return {"username": user.username}
    """
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    
    AdminUser = get_admin_user_model()
    try:
        user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
        if not user:
            # User ID in session but user doesn't exist in DB
            # Clear the invalid session
            request.session.pop('user_id', None)
            return None
        
        return user
    except Exception as e:
        logger.error(f"Error loading user from session: {e}")
        return None


async def get_current_active_user(
    request: Request,
    user = Depends(get_current_user)
) -> object:
    """
    Dependency to get the current authenticated user and ensure they are active.
    Raises HTTPException if user is not authenticated or not active.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user = Depends(get_current_active_user)):
            return {"username": user.username}
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not getattr(user, 'is_active', True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return user


async def require_authentication(
    request: Request,
    user = Depends(get_current_active_user)
) -> object:
    """
    Dependency that requires authentication (alias for get_current_active_user).
    Use this for routes that require a logged-in active user.
    
    Usage:
        @router.get("/admin/dashboard")
        async def dashboard(user = Depends(require_authentication)):
            return {"user": user.username}
    """
    return user


async def check_mfa_verified(
    request: Request,
    user = Depends(get_current_active_user)
) -> object:
    """
    Dependency that checks if user has completed MFA verification (if enabled).
    Raises HTTPException if MFA is required but not verified.
    
    Usage:
        @router.get("/sensitive")
        async def sensitive_route(user = Depends(check_mfa_verified)):
            return {"data": "sensitive"}
    """
    # Check if MFA is required for this user
    if getattr(user, 'mfa_secret', None):
        # MFA is enabled for this user
        mfa_verified = request.session.get('mfa_verified', False)
        if not mfa_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MFA verification required",
                headers={"X-MFA-Required": "true"}
            )
    
    return user


def require_role(role_name: str):
    """
    Factory function to create a dependency that requires a specific role.
    
    Usage:
        @router.get("/admin/users")
        async def list_users(user = Depends(require_role("admin"))):
            return {"users": [...]}
    """
    async def role_checker(
        request: Request,
        user = Depends(get_current_active_user)
    ) -> object:
        # Check if user has the required role
        user_roles = [role.name for role in getattr(user, 'roles', [])]
        if role_name not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role_name}' required"
            )
        return user
    
    return role_checker


def require_any_role(*role_names: str):
    """
    Factory function to create a dependency that requires any of the specified roles.
    
    Usage:
        @router.get("/content")
        async def view_content(user = Depends(require_any_role("editor", "admin"))):
            return {"content": "..."}
    """
    async def role_checker(
        request: Request,
        user = Depends(get_current_active_user)
    ) -> object:
        user_roles = [role.name for role in getattr(user, 'roles', [])]
        if not any(role in user_roles for role in role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of roles {role_names} required"
            )
        return user
    
    return role_checker


def require_permission(permission_name: str):
    """
    Factory function to create a dependency that requires a specific permission.
    
    Usage:
        @router.delete("/alerts/{id}")
        async def delete_alert(
            id: int,
            user = Depends(require_permission("delete_alerts"))
        ):
            return {"deleted": id}
    """
    async def permission_checker(
        request: Request,
        user = Depends(get_current_active_user)
    ) -> object:
        # Check user permissions through roles
        user_permissions = set()
        for role in getattr(user, 'roles', []):
            for perm in getattr(role, 'permissions', []):
                user_permissions.add(perm.name)
        
        if permission_name not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission_name}' required"
            )
        return user
    
    return permission_checker


async def get_optional_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[object]:
    """
    Dependency to optionally get the current user.
    Returns None if not authenticated, but doesn't raise an exception.
    Useful for pages that work differently when logged in vs not.
    
    Usage:
        @router.get("/")
        async def home(user = Depends(get_optional_user)):
            if user:
                return {"message": f"Welcome back, {user.username}"}
            return {"message": "Welcome, guest"}
    """
    return await get_current_user(request, db)


# Helper functions for authentication operations

async def login_user(request: Request, user_id: int, remember: bool = False):
    """
    Log in a user by setting session data.
    
    Args:
        request: FastAPI Request object
        user_id: ID of the user to log in
        remember: Whether to extend session lifetime (not yet implemented)
    """
    request.session['user_id'] = user_id
    request.session['mfa_verified'] = False  # Will be set to True after MFA
    
    logger.info(f"User {user_id} logged in")


async def logout_user(request: Request):
    """
    Log out the current user by clearing session data.
    
    Args:
        request: FastAPI Request object
    """
    user_id = request.session.get('user_id')
    request.session.clear()
    
    if user_id:
        logger.info(f"User {user_id} logged out")


async def set_mfa_verified(request: Request, verified: bool = True):
    """
    Mark MFA as verified (or not) for the current session.
    
    Args:
        request: FastAPI Request object
        verified: Whether MFA is verified
    """
    request.session['mfa_verified'] = verified


async def is_mfa_verified(request: Request) -> bool:
    """
    Check if MFA has been verified for the current session.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        bool: True if MFA is verified
    """
    return request.session.get('mfa_verified', False)


__all__ = [
    'get_current_user',
    'get_current_active_user',
    'require_authentication',
    'check_mfa_verified',
    'require_role',
    'require_any_role',
    'require_permission',
    'get_optional_user',
    'login_user',
    'logout_user',
    'set_mfa_verified',
    'is_mfa_verified',
]
