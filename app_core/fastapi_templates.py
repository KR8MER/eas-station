"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

FastAPI template utilities and context processors.
Provides Jinja2 template support with Flask-compatible helpers.
"""

import os
from typing import Dict, Any, Optional, Callable
from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import Environment
import logging

logger = logging.getLogger(__name__)

# Global Jinja2Templates instance
_templates: Optional[Jinja2Templates] = None


def init_templates(template_dir: str = "templates") -> Jinja2Templates:
    """
    Initialize Jinja2Templates with custom filters and context processors.
    
    Args:
        template_dir: Directory containing templates
        
    Returns:
        Jinja2Templates instance
    """
    global _templates
    
    if not os.path.exists(template_dir):
        logger.warning(f"Template directory '{template_dir}' does not exist")
    
    _templates = Jinja2Templates(directory=template_dir)
    
    # Add custom filters
    _add_custom_filters(_templates.env)
    
    # Add custom globals
    _add_custom_globals(_templates.env)
    
    logger.info(f"Template system initialized with directory: {template_dir}")
    return _templates


def get_templates() -> Jinja2Templates:
    """
    Get the global Jinja2Templates instance.
    
    Returns:
        Jinja2Templates instance
        
    Raises:
        RuntimeError: If templates not initialized
    """
    if _templates is None:
        # Auto-initialize with default directory
        return init_templates()
    return _templates


def _add_custom_filters(env: Environment):
    """Add custom Jinja2 filters for FastAPI templates"""
    
    # Import template helpers from existing code
    try:
        from webapp.template_helpers import (
            format_datetime,
            format_timestamp,
            format_duration,
            format_bytes,
            nl2br,
            truncate_words,
        )
        
        env.filters['format_datetime'] = format_datetime
        env.filters['format_timestamp'] = format_timestamp
        env.filters['format_duration'] = format_duration
        env.filters['format_bytes'] = format_bytes
        env.filters['nl2br'] = nl2br
        env.filters['truncate_words'] = truncate_words
        
        logger.debug("Added custom template filters")
    except ImportError as e:
        logger.warning(f"Could not import template helpers: {e}")


def _add_custom_globals(env: Environment):
    """Add custom global functions/variables for Jinja2 templates"""
    
    # Add version info
    try:
        from app_utils.versioning import get_current_version
        env.globals['get_version'] = get_current_version
    except ImportError:
        env.globals['get_version'] = lambda: "unknown"
    
    # Add now() function for templates
    from datetime import datetime
    env.globals['now'] = datetime.utcnow
    
    logger.debug("Added custom template globals")


def create_template_context(
    request: Request,
    extra_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a template context dictionary with standard variables.
    This is the FastAPI equivalent of Flask's template context.
    
    Args:
        request: FastAPI Request object
        extra_context: Additional context variables
        
    Returns:
        Dictionary of context variables for templates
    """
    context = {
        # Required by Jinja2Templates
        'request': request,
        
        # User information (if authenticated)
        'current_user': getattr(request.state, 'current_user', None),
        
        # Session data
        'session': request.session,
        
        # Application state
        'app': request.app.state,
        'config': request.app.state,
        
        # Request helpers
        'url_for': lambda name, **kwargs: url_for(request, name, **kwargs),
        
        # Flash messages
        'get_flashed_messages': lambda: get_flashed_messages(request),
        
        # Setup mode
        'setup_mode': getattr(request.app.state, 'SETUP_MODE', False),
        
        # Theme
        'theme': request.session.get('theme', 'cosmo'),
    }
    
    # Merge extra context
    if extra_context:
        context.update(extra_context)
    
    return context


def url_for(request: Request, name: str, **path_params) -> str:
    """
    FastAPI equivalent of Flask's url_for().
    Generate URL for a named route.
    
    Args:
        request: FastAPI Request object
        name: Route name (e.g., 'dashboard', 'api.get_alerts')
        **path_params: Path parameters for the route
        
    Returns:
        URL string
    """
    try:
        return request.app.url_path_for(name, **path_params)
    except Exception as e:
        logger.error(f"Error generating URL for '{name}': {e}")
        return '#'


def flash(request: Request, message: str, category: str = 'info'):
    """
    FastAPI equivalent of Flask's flash().
    Add a message to be displayed to the user.
    
    Args:
        request: FastAPI Request object
        message: Message text
        category: Message category ('info', 'success', 'warning', 'error')
    """
    if '_flashes' not in request.session:
        request.session['_flashes'] = []
    
    request.session['_flashes'].append({
        'message': message,
        'category': category
    })


def get_flashed_messages(request: Request, with_categories: bool = False):
    """
    FastAPI equivalent of Flask's get_flashed_messages().
    Retrieve and clear flash messages.
    
    Args:
        request: FastAPI Request object
        with_categories: If True, return tuples of (category, message)
        
    Returns:
        List of messages or list of (category, message) tuples
    """
    flashes = request.session.pop('_flashes', [])
    
    if with_categories:
        return [(f['category'], f['message']) for f in flashes]
    else:
        return [f['message'] for f in flashes]


def render_template(
    template_name: str,
    request: Request,
    **context
) -> str:
    """
    Render a template with context.
    This is a helper that combines template loading and rendering.
    
    Args:
        template_name: Template filename
        request: FastAPI Request object
        **context: Template context variables
        
    Returns:
        Rendered HTML string
    """
    templates = get_templates()
    full_context = create_template_context(request, context)
    return templates.TemplateResponse(template_name, full_context)


def template_filter(name: str):
    """
    Decorator to register a function as a Jinja2 filter.
    
    Usage:
        @template_filter('my_filter')
        def my_filter(value):
            return value.upper()
    """
    def decorator(func: Callable) -> Callable:
        templates = get_templates()
        templates.env.filters[name] = func
        return func
    return decorator


def template_global(name: str):
    """
    Decorator to register a function as a Jinja2 global.
    
    Usage:
        @template_global('my_function')
        def my_function():
            return "Hello"
    """
    def decorator(func: Callable) -> Callable:
        templates = get_templates()
        templates.env.globals[name] = func
        return func
    return decorator


def context_processor(func: Callable) -> Callable:
    """
    Decorator to register a context processor function.
    Context processors add variables to all template contexts.
    
    Usage:
        @context_processor
        def inject_user():
            return {'current_user': get_user()}
    """
    # Note: FastAPI doesn't have built-in context processors like Flask
    # This is a placeholder for custom implementation
    # Context should be added in create_template_context() or middleware
    logger.warning("Context processors not yet fully implemented in FastAPI")
    return func


__all__ = [
    'init_templates',
    'get_templates',
    'create_template_context',
    'url_for',
    'flash',
    'get_flashed_messages',
    'render_template',
    'template_filter',
    'template_global',
    'context_processor',
]
