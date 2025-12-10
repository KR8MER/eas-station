"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

FastAPI CSRF protection middleware.
Implements double-submit cookie pattern for CSRF protection.
"""

import secrets
import hmac
import hashlib
from typing import Set, Callable
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import MutableHeaders
import logging

logger = logging.getLogger(__name__)

# CSRF configuration
CSRF_SESSION_KEY = '_csrf_token'
CSRF_HEADER_NAME = 'X-CSRF-Token'
CSRF_FORM_FIELD = 'csrf_token'
CSRF_PROTECTED_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
CSRF_EXEMPT_PATHS: Set[str] = set()
CSRF_TOKEN_LENGTH = 32


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """
    Middleware for CSRF protection using double-submit cookie pattern.
    
    - Generates CSRF tokens and stores in session
    - Validates CSRF tokens on protected requests
    - Exempt paths can be configured
    """
    
    def __init__(
        self,
        app,
        exempt_paths: Set[str] = None,
        protected_methods: Set[str] = None,
        session_key: str = CSRF_SESSION_KEY,
        header_name: str = CSRF_HEADER_NAME,
        form_field: str = CSRF_FORM_FIELD,
    ):
        """
        Initialize CSRF protection middleware.
        
        Args:
            app: FastAPI application
            exempt_paths: Set of paths to exempt from CSRF protection
            protected_methods: Set of HTTP methods to protect (default: POST, PUT, PATCH, DELETE)
            session_key: Session key for storing CSRF token
            header_name: HTTP header name for CSRF token
            form_field: Form field name for CSRF token
        """
        super().__init__(app)
        self.exempt_paths = exempt_paths or CSRF_EXEMPT_PATHS
        self.protected_methods = protected_methods or CSRF_PROTECTED_METHODS
        self.session_key = session_key
        self.header_name = header_name
        self.form_field = form_field
        
        logger.info(f"CSRF protection initialized with {len(self.exempt_paths)} exempt paths")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and validate CSRF token if needed.
        
        Args:
            request: Incoming request
            call_next: Next middleware/handler
            
        Returns:
            Response from handler or CSRF error
        """
        # Generate CSRF token if not exists
        if self.session_key not in request.session:
            request.session[self.session_key] = self._generate_token()
        
        # Check if request needs CSRF validation
        needs_validation = (
            request.method in self.protected_methods and
            not self._is_exempt(request)
        )
        
        if needs_validation:
            # Validate CSRF token
            if not await self._validate_csrf(request):
                logger.warning(
                    f"CSRF validation failed for {request.method} {request.url.path} "
                    f"from {request.client.host}"
                )
                raise HTTPException(
                    status_code=403,
                    detail="CSRF validation failed"
                )
        
        # Process request
        response = await call_next(request)
        
        # Rotate CSRF token on successful POST (optional, for extra security)
        # Commented out for now to avoid breaking forms with multiple submissions
        # if request.method == 'POST' and response.status_code < 400:
        #     request.session[self.session_key] = self._generate_token()
        
        return response
    
    def _is_exempt(self, request: Request) -> bool:
        """
        Check if request path is exempt from CSRF protection.
        
        Args:
            request: Incoming request
            
        Returns:
            True if path is exempt
        """
        path = request.url.path
        
        # Check exact path match
        if path in self.exempt_paths:
            return True
        
        # Check prefix matches (for dynamic routes)
        for exempt_path in self.exempt_paths:
            if exempt_path.endswith('*') and path.startswith(exempt_path[:-1]):
                return True
        
        # Check if setup mode (exempt setup routes)
        if hasattr(request.app.state, 'SETUP_MODE') and request.app.state.SETUP_MODE:
            if path.startswith('/setup'):
                return True
        
        return False
    
    async def _validate_csrf(self, request: Request) -> bool:
        """
        Validate CSRF token from request.
        
        Args:
            request: Incoming request
            
        Returns:
            True if token is valid
        """
        # Get session token
        session_token = request.session.get(self.session_key)
        if not session_token:
            logger.debug("No CSRF token in session")
            return False
        
        # Get request token from header
        request_token = request.headers.get(self.header_name)
        
        # If not in header, try to get from form data (for traditional forms)
        if not request_token:
            if request.method == 'POST':
                try:
                    form = await request.form()
                    request_token = form.get(self.form_field)
                except Exception:
                    pass
        
        if not request_token:
            logger.debug("No CSRF token in request")
            return False
        
        # Compare tokens (constant-time comparison to prevent timing attacks)
        return hmac.compare_digest(session_token, request_token)
    
    @staticmethod
    def _generate_token() -> str:
        """
        Generate a new CSRF token.
        
        Returns:
            Random token string
        """
        return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)
    
    def add_exempt_path(self, path: str):
        """
        Add a path to the CSRF exemption list.
        
        Args:
            path: Path to exempt (can end with * for prefix matching)
        """
        self.exempt_paths.add(path)
        logger.debug(f"Added CSRF exempt path: {path}")
    
    def remove_exempt_path(self, path: str):
        """
        Remove a path from the CSRF exemption list.
        
        Args:
            path: Path to remove
        """
        self.exempt_paths.discard(path)
        logger.debug(f"Removed CSRF exempt path: {path}")


def get_csrf_token(request: Request) -> str:
    """
    Get the CSRF token for the current request.
    Use this in templates to include the token.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        CSRF token string
    """
    # Generate token if not exists
    if CSRF_SESSION_KEY not in request.session:
        request.session[CSRF_SESSION_KEY] = secrets.token_urlsafe(CSRF_TOKEN_LENGTH)
    
    return request.session[CSRF_SESSION_KEY]


def csrf_protect(request: Request):
    """
    Decorator/dependency to explicitly require CSRF protection on a route.
    This is redundant if using CSRFProtectionMiddleware, but can be used
    for explicit protection.
    
    Usage:
        @app.post("/sensitive", dependencies=[Depends(csrf_protect)])
        async def sensitive_route(request: Request):
            return {"status": "ok"}
    """
    session_token = request.session.get(CSRF_SESSION_KEY)
    request_token = request.headers.get(CSRF_HEADER_NAME)
    
    if not session_token or not request_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    
    if not hmac.compare_digest(session_token, request_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")


def exempt_from_csrf(exempt_paths: Set[str] = None):
    """
    Factory function to create CSRF middleware with custom exempt paths.
    
    Usage:
        app.add_middleware(
            CSRFProtectionMiddleware,
            exempt_paths={'/api/public', '/webhooks/*'}
        )
    """
    return CSRFProtectionMiddleware(exempt_paths=exempt_paths)


__all__ = [
    'CSRFProtectionMiddleware',
    'get_csrf_token',
    'csrf_protect',
    'exempt_from_csrf',
    'CSRF_SESSION_KEY',
    'CSRF_HEADER_NAME',
    'CSRF_FORM_FIELD',
    'CSRF_PROTECTED_METHODS',
]
