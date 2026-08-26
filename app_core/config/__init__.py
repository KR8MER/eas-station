"""
Configuration module for EAS Station.

This module provides configuration management including:
- Environment variable parsing
- Database connection URL construction
- Security configuration (SECRET_KEY, CSRF)

Extracted from app.py as part of the refactoring effort to improve maintainability.
"""

from .environment import parse_env_list, parse_int_env
from .database import build_database_url
from .services import (
    SERVICE_PREFIX,
    EAS_SERVICES,
    POLLER_SERVICES,
    INFRASTRUCTURE_SERVICES,
    get_all_log_services,
    get_eas_services,
    get_web_service,
    get_sdr_service,
    get_demod_service,
    get_audio_service,
    get_hardware_service,
    get_network_service,
    get_zigbee_service,
    get_gps_service,
    get_displays_service,
    get_gpio_service,
    get_hardware_service_token,
    NETWORK_SERVICE_URL,
    ZIGBEE_SERVICE_URL,
    GPS_SERVICE_URL,
    DISPLAYS_SERVICE_URL,
    GPIO_SERVICE_URL,
    DEMOD_SERVICE_URL,
    AUDIO_SERVICE_URL,
    SDR_SERVICE_URL,
    REDIS_URL,
)
from .redis_config import (
    get_redis_host,
    get_redis_port,
    get_redis_db,
    get_redis_password,
    get_redis_url,
    get_cache_redis_url,
    RedisChannels,
    RedisTimeouts,
)

__all__ = [
    'parse_env_list',
    'parse_int_env',
    'build_database_url',
    'SERVICE_PREFIX',
    'EAS_SERVICES',
    'POLLER_SERVICES',
    'INFRASTRUCTURE_SERVICES',
    'get_all_log_services',
    'get_eas_services',
    'get_web_service',
    'get_sdr_service',
    'get_demod_service',
    'get_audio_service',
    'get_hardware_service',
    'get_network_service',
    'get_zigbee_service',
    'get_gps_service',
    'get_displays_service',
    'get_gpio_service',
    'get_hardware_service_token',
    'NETWORK_SERVICE_URL',
    'ZIGBEE_SERVICE_URL',
    'GPS_SERVICE_URL',
    'DISPLAYS_SERVICE_URL',
    'GPIO_SERVICE_URL',
    'DEMOD_SERVICE_URL',
    'AUDIO_SERVICE_URL',
    'SDR_SERVICE_URL',
    'REDIS_URL',
    # Redis config
    'get_redis_host',
    'get_redis_port',
    'get_redis_db',
    'get_redis_password',
    'get_redis_url',
    'get_cache_redis_url',
    'RedisChannels',
    'RedisTimeouts',
]
