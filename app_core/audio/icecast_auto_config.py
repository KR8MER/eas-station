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
Automatic Icecast Configuration from Environment Variables

Detects Icecast settings from environment and automatically enables streaming
for all audio sources with zero user configuration required.
"""

import logging
import os
from typing import Optional

from .mount_points import build_stream_url, StreamFormat

logger = logging.getLogger(__name__)


class IcecastAutoConfig:
    """Auto-configure Icecast from environment variables."""

    def __init__(self):
        """Initialize and detect Icecast configuration."""
        self.enabled = False
        self.server = "localhost"
        self.port = 8000
        self.source_password = ""
        self.external_port = 8001  # For generating URLs accessible from browser
        self.public_hostname = None  # Public hostname/IP for browser access
        self.admin_user = None
        self.admin_password = None
        self.stream_bitrate = 128  # Default bitrate in kbps
        self.stream_format = "mp3"  # Default format

        self._detect_config()

    def _detect_config(self) -> None:
        """Detect Icecast configuration from database with environment fallback."""
        try:
            # Try to read from database first
            try:
                from app_core.icecast_settings import get_icecast_settings
                settings = get_icecast_settings()

                # Check if enabled
                if not settings.enabled:
                    logger.info("Icecast auto-configuration disabled via database settings")
                    self.enabled = False
                    return

                # Get source password (required)
                self.source_password = settings.source_password or ''
                if not self.source_password or self.source_password in ('changeme_source', 'changeme'):
                    logger.warning(
                        "Icecast auto-configuration: No source password configured "
                        "in database. Icecast streaming will not be enabled automatically."
                    )
                    self.enabled = False
                    return

                # Get server and port
                self.server = settings.server or 'localhost'
                self.port = settings.port or 8000

                # Admin credentials (optional, but required for metadata updates)
                self.admin_user = settings.admin_user
                self.admin_password = settings.admin_password
                if bool(self.admin_user) ^ bool(self.admin_password):
                    logger.warning(
                        "Icecast auto-configuration: Admin username/password mismatch. "
                        "Metadata updates will be disabled until both admin user "
                        "and admin password are provided."
                    )

                # For external URLs (browser access), use the external port
                if settings.external_port:
                    self.external_port = settings.external_port
                else:
                    # Default: use same port for external access
                    self.external_port = self.port

                # Get public hostname for browser access
                self.public_hostname = settings.public_hostname

                # Get stream settings (bitrate and format)
                self.stream_bitrate = settings.stream_bitrate or 128
                self.stream_format = settings.stream_format or 'mp3'

                self.enabled = True

                logger.info(
                    f"Icecast auto-configuration enabled from database: "
                    f"server={self.server}, port={self.port}, "
                    f"external_port={self.external_port}, "
                    f"public_hostname={self.public_hostname or 'localhost (WARNING: may not work remotely)'}, "
                    f"bitrate={self.stream_bitrate}kbps, format={self.stream_format}"
                )
                return

            except ImportError:
                logger.debug("Database not available, falling back to environment variables")
            except Exception as db_err:
                logger.warning(f"Failed to load Icecast settings from database: {db_err}, falling back to environment")

            # Fallback to environment variables
            # Check if Icecast is explicitly disabled
            enabled_str = os.environ.get('ICECAST_ENABLED', 'true').lower()
            if enabled_str in ('false', '0', 'no', 'disabled'):
                logger.info("Icecast auto-configuration disabled via ICECAST_ENABLED")
                self.enabled = False
                return

            # Get Icecast source password (required)
            self.source_password = os.environ.get('ICECAST_SOURCE_PASSWORD', '')
            if not self.source_password or self.source_password in ('changeme_source', 'changeme'):
                logger.warning(
                    "Icecast auto-configuration: No source password configured "
                    "(ICECAST_SOURCE_PASSWORD not set or using insecure default 'changeme'). "
                    "Icecast streaming will not be enabled automatically."
                )
                self.enabled = False
                return

            # Get server and port
            self.server = os.environ.get('ICECAST_SERVER', 'localhost')
            self.port = int(os.environ.get('ICECAST_PORT', '8000'))

            # Admin credentials (optional, but required for metadata updates)
            self.admin_user = os.environ.get('ICECAST_ADMIN_USER')
            self.admin_password = os.environ.get('ICECAST_ADMIN_PASSWORD')
            if bool(self.admin_user) ^ bool(self.admin_password):
                logger.warning(
                    "Icecast auto-configuration: Admin username/password mismatch. "
                    "Metadata updates will be disabled until both ICECAST_ADMIN_USER "
                    "and ICECAST_ADMIN_PASSWORD are provided."
                )

            # For external URLs (browser access), use the external port
            external_port_str = os.environ.get('ICECAST_EXTERNAL_PORT')
            if external_port_str:
                self.external_port = int(external_port_str)
            else:
                # Default: use same port for external access on bare-metal installations
                self.external_port = self.port

            # Get public hostname for browser access (required for remote servers)
            # This should be the public IP or hostname of the server
            self.public_hostname = os.environ.get('ICECAST_PUBLIC_HOSTNAME') or \
                                  os.environ.get('PUBLIC_HOSTNAME') or \
                                  os.environ.get('SERVER_NAME')

            # Get stream settings (bitrate and format)
            bitrate_str = os.environ.get('ICECAST_BITRATE', '128')
            try:
                self.stream_bitrate = int(bitrate_str)
            except ValueError:
                logger.warning(f"Invalid ICECAST_BITRATE '{bitrate_str}', using default 128kbps")
                self.stream_bitrate = 128
            
            self.stream_format = os.environ.get('ICECAST_FORMAT', 'mp3').lower()
            if self.stream_format not in ('mp3', 'ogg'):
                logger.warning(f"Invalid ICECAST_FORMAT '{self.stream_format}', using default 'mp3'")
                self.stream_format = 'mp3'

            self.enabled = True

            logger.info(
                f"Icecast auto-configuration enabled from environment: "
                f"server={self.server}, port={self.port}, "
                f"external_port={self.external_port}, "
                f"public_hostname={self.public_hostname or 'localhost (WARNING: may not work remotely)'}, "
                f"bitrate={self.stream_bitrate}kbps, format={self.stream_format}"
            )

        except Exception as e:
            logger.error(f"Error detecting Icecast configuration: {e}")
            self.enabled = False

    def is_enabled(self) -> bool:
        """Check if Icecast auto-configuration is enabled."""
        return self.enabled

    def get_stream_url(self, source_name: str, external: bool = True, format: StreamFormat = StreamFormat.MP3) -> Optional[str]:
        """
        Get the Icecast stream URL for a source.

        Args:
            source_name: Name of the audio source
            external: If True, return URL for browser access (with external port)
                     If False, return URL for internal app use
            format: Stream format (default: MP3)

        Returns:
            Stream URL if enabled, None otherwise
        """
        if not self.enabled:
            return None

        # Determine hostname and port based on access type
        if external:
            # Browser/external access - use public hostname if configured
            if self.public_hostname:
                hostname = self.public_hostname
            else:
                # Use configured server (defaults to localhost for bare-metal installations)
                # For production remote access, users should set ICECAST_PUBLIC_HOSTNAME
                hostname = self.server
            port = self.external_port
        else:
            # Internal app access - use server hostname and internal port
            hostname = self.server
            port = self.port

        # Use centralized mount point generation
        return build_stream_url(hostname, port, source_name, format=format, use_https=False)

    def get_config_dict(self) -> dict:
        """Get configuration as dictionary."""
        return {
            'enabled': self.enabled,
            'server': self.server,
            'port': self.port,
            'external_port': self.external_port,
            'has_password': bool(self.source_password),
            'has_admin_credentials': bool(self.admin_user and self.admin_password),
        }


# Global instance
_auto_config: Optional[IcecastAutoConfig] = None


def get_icecast_auto_config() -> IcecastAutoConfig:
    """Get the global Icecast auto-configuration instance."""
    global _auto_config
    if _auto_config is None:
        _auto_config = IcecastAutoConfig()
    return _auto_config


__all__ = ['IcecastAutoConfig', 'get_icecast_auto_config']
