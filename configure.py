#!/usr/bin/env python3
"""
Configuration settings for NOAA CAP Alerts System
"""

import os
from dotenv import load_dotenv
from urllib.parse import quote

# Load environment variables from .env file
load_dotenv()


class Config:
    """Base configuration class"""

    # Flask settings - Require SECRET_KEY to be explicitly set
    _secret_key = os.environ.get('SECRET_KEY', '')
    if not _secret_key or _secret_key == 'dev-key-change-in-production':
        raise ValueError(
            "SECRET_KEY environment variable must be set to a secure random string. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    SECRET_KEY = _secret_key

    # Database settings - Auto-build from POSTGRES_* or use DATABASE_URL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')

    if not SQLALCHEMY_DATABASE_URI:
        # Build from individual POSTGRES_* variables (same logic as app.py)
        user = os.environ.get('POSTGRES_USER', 'postgres') or 'postgres'
        password = os.environ.get('POSTGRES_PASSWORD', '')
        host = os.environ.get('POSTGRES_HOST', 'host.docker.internal') or 'host.docker.internal'
        port = os.environ.get('POSTGRES_PORT', '5432') or '5432'
        database = os.environ.get('POSTGRES_DB', user) or user

        # URL-encode credentials to handle special characters (same as app.py)
        user_part = quote(user, safe='')
        password_part = quote(password, safe='') if password else ''

        if password_part:
            auth_segment = f"{user_part}:{password_part}"
        else:
            auth_segment = user_part

        SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg2://{auth_segment}@{host}:{port}/{database}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # File upload settings
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/tmp/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'geojson', 'json'}

    # NOAA CAP API settings
    NOAA_CAP_API_URL = 'https://api.weather.gov/alerts'
    NOAA_CAP_POLL_INTERVAL = int(os.environ.get('CAP_POLL_INTERVAL', 300))  # 5 minutes
    NOAA_CAP_TIMEOUT = int(os.environ.get('CAP_TIMEOUT', 30))  # 30 seconds

    # NOAA zone catalog
    NWS_ZONE_DBF_PATH = os.environ.get('NWS_ZONE_DBF_PATH', 'assets/z_05mr24.dbf')

    # Logging settings
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = os.environ.get('LOG_FILE', 'logs/noaa_alerts.log')
    LOG_MAX_BYTES = int(os.environ.get('LOG_MAX_BYTES', 10485760))  # 10MB
    LOG_BACKUP_COUNT = int(os.environ.get('LOG_BACKUP_COUNT', 10))

    # Map settings
    DEFAULT_MAP_CENTER = [40.0, -83.5]  # Putnam County, Ohio approximate center
    DEFAULT_MAP_ZOOM = 10

    # Boundary layer colors
    BOUNDARY_COLORS = {
        'fire': '#dc3545',
        'ems': '#007bff',
        'electric': '#ffc107',
        'township': '#28a745',
        'villages': '#17a2b8',
        'telephone': '#6f42c1',
        'school': '#fd7e14',
        'county': '#6c757d'
    }

    # Alert severity colors
    ALERT_COLORS = {
        'extreme': '#8B0000',
        'severe': '#FF0000',
        'moderate': '#FFA500',
        'minor': '#FFFF00',
        'unknown': '#808080'
    }

    # Notification settings
    ENABLE_EMAIL_NOTIFICATIONS = os.environ.get('ENABLE_EMAIL_NOTIFICATIONS', 'False').lower() == 'true'
    ENABLE_SMS_NOTIFICATIONS = os.environ.get('ENABLE_SMS_NOTIFICATIONS', 'False').lower() == 'true'

    # Email settings (if enabled)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'mail')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

    # Audio/TTS settings
    ENABLE_AUDIO_ALERTS = os.environ.get('ENABLE_AUDIO_ALERTS', 'False').lower() == 'true'
    AUDIO_OUTPUT_DIR = os.environ.get('AUDIO_OUTPUT_DIR', '/tmp/audio')

    # Performance settings
    CACHE_TIMEOUT = int(os.environ.get('CACHE_TIMEOUT', 300))  # 5 minutes
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 2))

    @staticmethod
    def init_app(app):
        """Initialize application with config"""
        # Create required directories
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(os.path.dirname(Config.LOG_FILE), exist_ok=True)

        if Config.ENABLE_AUDIO_ALERTS:
            os.makedirs(Config.AUDIO_OUTPUT_DIR, exist_ok=True)


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False

    # More restrictive settings for production
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20
    }


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}