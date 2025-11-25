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
Caching configuration and utilities for EAS Station.

Provides Flask-Caching integration with configurable backend and timeouts
for reducing database load and improving API response times.
"""

import os
from flask_caching import Cache

# Initialize cache instance (will be configured by init_cache)
cache = Cache()


def init_cache(app):
    """Initialize Flask-Caching with the application.

    Configures caching based on environment variables:
    - CACHE_TYPE: Backend type (simple, redis, filesystem, etc.)
    - CACHE_DEFAULT_TIMEOUT: Default cache timeout in seconds
    - CACHE_DIR: Directory for filesystem cache
    - CACHE_REDIS_URL: Redis connection URL

    Args:
        app: Flask application instance

    Note: Redis is now the default for production use. Multi-worker deployments
    require Redis to share cache state across workers.
    """
    cache_type = os.environ.get('CACHE_TYPE', 'redis')
    cache_default_timeout = int(os.environ.get('CACHE_DEFAULT_TIMEOUT', '300'))
    
    config = {
        'CACHE_TYPE': cache_type,
        'CACHE_DEFAULT_TIMEOUT': cache_default_timeout,
    }
    
    # Configure based on cache type
    if cache_type == 'filesystem':
        cache_dir = os.environ.get('CACHE_DIR', '/tmp/eas-station-cache')
        config['CACHE_DIR'] = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    elif cache_type == 'redis':
        # Default to 'redis' hostname for Docker, not 'localhost'
        redis_url = os.environ.get('CACHE_REDIS_URL', 'redis://redis:6379/0')
        config['CACHE_REDIS_URL'] = redis_url
    
    app.config.update(config)
    cache.init_app(app)
    
    return cache


def clear_audio_source_cache(source_name=None):
    """Clear cached audio source data.
    
    Args:
        source_name: If provided, clear cache for specific source.
                    If None, clear all audio source caches.
    """
    if source_name:
        # Clear specific source caches
        cache.delete(f'audio_source_{source_name}')
        cache.delete(f'audio_source_list')
    else:
        # Clear all audio source related caches
        cache.delete('audio_source_list')
        # Note: Individual source caches will expire naturally


def clear_boundary_cache():
    """Clear cached boundary data."""
    cache.delete('boundaries_list')


def clear_alert_cache():
    """Clear cached alert data."""
    cache.delete('alerts_historical')
    cache.delete('alerts_active')
