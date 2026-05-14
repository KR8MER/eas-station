"""
Flask template context processor utilities.

This module provides context processor functions that inject variables
into all Flask templates.

Functions:
    inject_global_vars: Inject global variables into all templates
"""

import logging
from flask import g
from app_core.flask.csrf import generate_csrf_token

logger = logging.getLogger(__name__)


def inject_global_vars(app) -> dict:
    """
    Inject global variables into all templates.
    
    This function provides commonly needed variables to all Jinja2 templates,
    including timezone information, system version, location settings, and
    current user information.
    
    Args:
        app: Flask application instance (for config access)
    
    Returns:
        Dictionary of variables to inject into template context
        
    Example:
        >>> from flask import Flask
        >>> app = Flask(__name__)
        >>> app.config['SYSTEM_VERSION'] = '2.7.2'
        >>> @app.context_processor
        ... def inject():
        ...     return inject_global_vars(app)
    """
    # Import here to avoid circular dependencies
    from app_core.auth.roles import has_permission
    from app_core.location import get_location_settings
    from app_utils.time import utc_now, local_now, get_location_timezone_name
    from app_utils.versioning import get_current_version, get_current_commit
    from app_core.boundaries import BOUNDARY_TYPE_CONFIG, BOUNDARY_GROUP_LABELS
    from app_utils.assets import get_shield_logo_data
    
    LED_AVAILABLE = app.config.get('LED_AVAILABLE', False)
    
    setup_mode_active = app.config.get('SETUP_MODE', False)
    location_settings = {}
    if not setup_mode_active:
        try:
            location_settings = get_location_settings()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning('Failed to load location settings; continuing without defaults: %s', exc)
            location_settings = {}
    
    return {
        'current_utc_time': utc_now(),
        'current_local_time': local_now(),
        'timezone_name': get_location_timezone_name(),
        'led_available': LED_AVAILABLE,
        'system_version': app.config.get('SYSTEM_VERSION', get_current_version()),
        'static_asset_version': app.config.get('STATIC_ASSET_VERSION', get_current_version()),
        'git_commit': get_current_commit(7),
        'shield_logos': {
            slug: get_shield_logo_data(slug)
            # Curated set of project marks NOT covered by simple-icons.org
            # (the upstream source for shields.io `logo=` slugs). Each entry
            # has a matching SVG under static/img/tech-stack-logos/<slug>.svg
            # and is referenced from templates/partials/tech_stack_badges.html
            # via the embedded data: URI. Add a slug here when you add a new
            # SVG so the partial can pick it up.
            for slug in (
                # Existing
                'icecast', 'soapysdr',
                # Custom marks for projects not in simple-icons
                'chrony', 'gpsd', 'pyotp',
                'gevent', 'pydub', 'espeak-ng',
                'lxml', 'werkzeug', 'pillow', 'alembic',
                # Major libraries (also rendered on the About page).
                # Kept as local SVGs so we don't depend on simple-icons
                # at runtime and so the About page can <img> them
                # directly without a base64 round-trip.
                'flask', 'jinja2', 'socketio', 'systemd',
                'postgresql', 'redis', 'sqlalchemy', 'gunicorn',
                'nginx', 'letsencrypt', 'ffmpeg',
                'numpy', 'scipy', 'numba',
                'twilio', 'chartjs', 'leaflet',
                'mermaid', 'jquery',
            )
        },
        'location_settings': location_settings,
        'boundary_type_config': BOUNDARY_TYPE_CONFIG,
        'boundary_group_labels': BOUNDARY_GROUP_LABELS,
        'current_user': getattr(g, 'current_user', None),
        'eas_broadcast_enabled': app.config.get('EAS_BROADCAST_ENABLED', False),
        'eas_output_web_subdir': app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages'),
        'setup_mode': setup_mode_active,
        'setup_mode_reasons': app.config.get('SETUP_MODE_REASONS', ()),
        'csrf_token': generate_csrf_token(),
        'has_permission': has_permission,
        'google_site_verification': app.config.get('GOOGLE_SITE_VERIFICATION'),
    }


__all__ = ['inject_global_vars']
