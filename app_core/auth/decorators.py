"""
Authentication and role-checking decorators for route protection.

Provides simple decorators for:
- Authentication checking (require_auth)
- Role-based access control (require_role)
"""

from functools import wraps
from typing import Callable, Any
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

from .roles import get_current_user


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

    login_url = url_for("login")
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


def _role_denied_response(required_roles: tuple[str, ...]):
    """Return a friendly role denied response."""
    roles_str = ", ".join(required_roles)

    if _wants_json_response():
        return (
            jsonify(
                {
                    "error": "insufficient_role",
                    "required_roles": list(required_roles),
                    "message": f"You need one of these roles: {roles_str}",
                }
            ),
            403,
        )

    flash(f"You do not have permission to access that page. Required role: {roles_str}")
    return redirect(url_for("admin"))


def require_auth(f: Callable) -> Callable:
    """
    Decorator to require user authentication for a route.

    Usage:
        @app.route('/admin/dashboard')
        @require_auth
        def dashboard():
            ...

    Returns:
        Decorated function that checks authentication before execution
    """
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        user = get_current_user()
        if not user or not user.is_active:
            current_app.logger.warning(
                f"Authentication required for {request.endpoint}, session user_id: {session.get('user_id')}"
            )
            return _build_login_redirect()
        return f(*args, **kwargs)
    return decorated_function


def require_role(*role_names: str) -> Callable:
    """
    Decorator to require specific roles for a route.

    The user must have at least one of the specified roles.

    Usage:
        @app.route('/admin/users')
        @require_auth
        @require_role("Admin", "Operator")
        def manage_users():
            ...

    Args:
        *role_names: One or more role names (case-insensitive)

    Returns:
        Decorator function that checks role membership
    """
    # Normalize role names to lowercase for comparison
    normalized_roles = tuple(role.lower() for role in role_names)

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            user = get_current_user()

            # Check authentication first
            if not user or not user.is_active:
                current_app.logger.warning(
                    f"Authentication required for {request.endpoint}"
                )
                return _build_login_redirect()

            # Check if user has a role assigned
            if not user.role:
                current_app.logger.warning(
                    f"User {user.id} has no role assigned, denying access to {request.endpoint}"
                )
                return _role_denied_response(role_names)

            # Check if user's role matches any of the required roles
            user_role_name = user.role.name.lower()
            if user_role_name not in normalized_roles:
                current_app.logger.warning(
                    f"User {user.id} with role '{user.role.name}' denied access to {request.endpoint}. Required: {role_names}"
                )
                return _role_denied_response(role_names)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


__all__ = ['require_auth', 'require_role']
