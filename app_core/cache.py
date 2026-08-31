"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

from app_core.config.redis_config import get_cache_redis_url

# Initialize cache instance (will be configured by init_cache)
cache = Cache()

# Flask-Caching 2.5.0 dropped its lowercase CACHE_TYPE aliases ('redis',
# 'simple', 'filesystem', ...): Cache._set_cache() builds an import path as
# "flask_caching.backends." + CACHE_TYPE and imports it, but the backends
# package now only exposes the actual class names (RedisCache, SimpleCache,
# FileSystemCache, ...) as attributes -- there is no backends.redis module
# or attribute anymore. CACHE_TYPE stays lowercase everywhere else in this
# app (env var, the Settings -> Environment dropdown, existing .env files
# on already-deployed stations) -- only the value actually handed to
# Flask-Caching is translated here.
_CACHE_TYPE_ALIASES = {
    'redis': 'RedisCache',
    'simple': 'SimpleCache',
    'filesystem': 'FileSystemCache',
    'null': 'NullCache',
}


def init_cache(app):
    """Initialize Flask-Caching with the application.

    Configures caching based on environment variables:
    - CACHE_TYPE: Backend type (simple, redis, filesystem, etc.)
    - CACHE_DEFAULT_TIMEOUT: Default cache timeout in seconds
    - CACHE_DIR: Directory for filesystem cache

    Args:
        app: Flask application instance

    Note: Redis is now the default for production use. Multi-worker deployments
    require Redis to share cache state across workers. Falls back to simple
    cache if Redis is unavailable.
    """
    import logging
    logger = logging.getLogger(__name__)

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
        # Use centralized Redis config
        redis_url = get_cache_redis_url()
        config['CACHE_REDIS_URL'] = redis_url

        # Test Redis connectivity before committing to Redis cache
        try:
            import redis
            # Parse the URL and test connection
            parsed = redis.connection.parse_url(redis_url)
            test_client = redis.Redis(
                host=parsed.get('host', 'localhost'),
                port=parsed.get('port', 6379),
                db=parsed.get('db', 0),
                password=parsed.get('password'),
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            test_client.ping()
            logger.info("Redis cache connection verified")
        except Exception as redis_error:
            logger.warning(
                "Redis unavailable for caching (%s), falling back to simple cache. "
                "This may cause issues in multi-worker deployments.",
                redis_error
            )
            # Fall back to simple in-memory cache
            config['CACHE_TYPE'] = 'simple'
            config.pop('CACHE_REDIS_URL', None)

    logger.info("Cache initialized with type: %s", config['CACHE_TYPE'])

    # Translate the friendly lowercase alias to the class name Flask-Caching
    # 2.5+ actually resolves, right at the boundary -- everything above this
    # point (branching, logging, the env var, the Settings UI) keeps using
    # the lowercase form.
    config['CACHE_TYPE'] = _CACHE_TYPE_ALIASES.get(config['CACHE_TYPE'], config['CACHE_TYPE'])

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
