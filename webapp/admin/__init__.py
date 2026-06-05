"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

from __future__ import annotations

"""Organised registration helpers for legacy admin routes."""

from app_utils.eas import load_eas_config

from .audio import register_audio_routes
from .audio_ingest import register_audio_ingest_routes
from .audio_sdr_fix import register_audio_sdr_fix_routes
from .api import register_api_routes
from .auth import register_auth_routes
from .boundaries import register_boundary_routes
from .coverage import calculate_coverage_percentages, try_build_geometry_from_same_codes
from .dashboard import register_dashboard_routes
from .environment import register_environment_routes
from .notifications import notifications_bp
from .application_settings import application_settings_bp
from .intersections import register_intersection_routes
from .maintenance import register_maintenance_routes
from .health_endpoints import register_health_routes
from .network import register_network_routes
from .zigbee import register_zigbee_routes
from .zones import zones_bp
from .county_boundaries import county_boundaries_bp
from .hardware import hardware_bp
from .icecast import register_icecast_routes
from .certbot import register_certbot_routes
from .tts import register_tts_routes
from .tts_pronunciation import register_pronunciation_routes
from .local_authorities import register_local_authority_routes
from .tailscale import register_tailscale_routes
from .poller import poller_bp
from .mail_server import register_mail_server_routes
from .eas_decoder_monitor import register_blueprint as register_eas_decoder_monitor_routes
from .endec_feeds import register_blueprint as register_endec_feeds_routes


def register(app, logger):
    """Register all admin-related routes on the Flask app."""

    eas_config = load_eas_config(app.root_path)

    register_audio_routes(app, logger, eas_config)
    register_audio_ingest_routes(app, logger)
    register_audio_sdr_fix_routes(app)  # Audio/SDR configuration fix utility
    register_api_routes(app, logger)
    register_environment_routes(app, logger)
    register_maintenance_routes(app, logger)
    register_intersection_routes(app, logger)
    register_boundary_routes(app, logger)
    register_auth_routes(app, logger)
    register_dashboard_routes(app, logger, eas_config)
    register_health_routes(app)  # New health check endpoints for separated architecture
    register_network_routes(app, logger)  # WiFi configuration management
    register_zigbee_routes(app, logger)  # Zigbee monitoring and status
    app.register_blueprint(zones_bp, url_prefix='/admin')  # Zone catalog management
    logger.info("Zone management routes registered")
    app.register_blueprint(county_boundaries_bp, url_prefix='/admin')  # US county boundary management
    logger.info("County boundary management routes registered")
    app.register_blueprint(hardware_bp, url_prefix='/admin')  # Hardware settings management
    logger.info("Hardware settings routes registered")
    register_icecast_routes(app, logger)  # Icecast streaming configuration
    register_certbot_routes(app, logger)  # Certbot/SSL certificate management
    register_tts_routes(app, logger)  # Text-to-Speech configuration
    register_pronunciation_routes(app, logger)  # TTS pronunciation dictionary
    app.register_blueprint(poller_bp)  # Poller settings management
    logger.info("Poller settings routes registered")
    app.register_blueprint(notifications_bp)  # Notification settings management
    logger.info("Notification settings routes registered")
    app.register_blueprint(application_settings_bp)  # Application settings management
    logger.info("Application settings routes registered")
    register_local_authority_routes(app, logger)  # Local authority EAS access management
    register_tailscale_routes(app, logger)  # Tailscale VPN configuration
    register_mail_server_routes(app, logger)  # Local Postfix mail server management
    register_eas_decoder_monitor_routes(app)  # EAS decoder audio monitor settings
    register_endec_feeds_routes(app)  # Sage-ENDEC-compatible TCP device feeds

    # Note: Audio controller initialization removed for separated architecture.
    # In separated architecture, audio processing runs in dedicated audio-service process.
    # The web application process only serves the web UI and reads metrics from Redis.


__all__ = ['register', 'calculate_coverage_percentages',
           'notifications_bp', 'application_settings_bp']
