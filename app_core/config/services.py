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
Centralized service configuration for EAS Station.

All service names and URLs are defined here to avoid hardcoding throughout the codebase.
These can be overridden via environment variables for custom deployments.
"""

import hashlib
import hmac
import os
from typing import List

# Service name prefix (can be overridden for custom installations)
SERVICE_PREFIX = os.environ.get('EAS_SERVICE_PREFIX', 'eas-station')

# Core EAS Station services
# The hardware subsystem split (Phase 4) replaced the single
# eas-station-hardware.service unit with five per-subsystem units bundled
# under eas-station-hardware.target so a Zigbee dongle hang or a GPS
# serial-port wedge can't take down OLED rendering or network config.
EAS_SERVICES = [
    f'{SERVICE_PREFIX}-web.service',
    f'{SERVICE_PREFIX}-sdr.service',
    f'{SERVICE_PREFIX}-audio.service',
    f'{SERVICE_PREFIX}-eas.service',
    f'{SERVICE_PREFIX}-network.service',
    f'{SERVICE_PREFIX}-zigbee.service',
    f'{SERVICE_PREFIX}-gps.service',
    f'{SERVICE_PREFIX}-displays.service',
    f'{SERVICE_PREFIX}-gpio.service',
    f'{SERVICE_PREFIX}-endec-feeds.service',
    f'{SERVICE_PREFIX}-hwsetup.service',
]

# Poller services (Unified poller for NOAA + IPAWS)
POLLER_SERVICES = [
    f'{SERVICE_PREFIX}-poller.service',
]

# Infrastructure services (not prefixed)
INFRASTRUCTURE_SERVICES = [
    'nginx.service',
    'postgresql.service',
    'redis-server.service',
    'icecast2.service',
    'certbot.service',
    'certbot.timer',
]

# All services for log viewing
def get_all_log_services() -> List[str]:
    """Get all services that can be viewed in the logs interface."""
    return EAS_SERVICES + POLLER_SERVICES + INFRASTRUCTURE_SERVICES


def get_eas_services() -> List[str]:
    """Get core EAS services (without infrastructure)."""
    return EAS_SERVICES + POLLER_SERVICES


def get_web_service() -> str:
    """Get the web service name."""
    return f'{SERVICE_PREFIX}-web.service'


def get_sdr_service() -> str:
    """Get the SDR service name."""
    return f'{SERVICE_PREFIX}-sdr.service'


def get_audio_service() -> str:
    """Get the audio service name."""
    return f'{SERVICE_PREFIX}-audio.service'


def get_hardware_service() -> str:
    """Get the hardware service target name.

    Returns the systemd *target* that bundles the five per-subsystem
    hardware units (network/zigbee/gps/displays/gpio).  Used by
    operator-facing 'restart hardware' actions so they bounce every
    subsystem at once.
    """
    return f'{SERVICE_PREFIX}-hardware.target'


def get_network_service() -> str:
    """Get the network subsystem service name (nmcli proxy, port 5101)."""
    return f'{SERVICE_PREFIX}-network.service'


def get_zigbee_service() -> str:
    """Get the Zigbee subsystem service name (zigpy controller, port 5102)."""
    return f'{SERVICE_PREFIX}-zigbee.service'


def get_gps_service() -> str:
    """Get the GPS subsystem service name (GPS manager + trends, port 5103)."""
    return f'{SERVICE_PREFIX}-gps.service'


def get_displays_service() -> str:
    """Get the displays subsystem service name (OLED/LED/VFD, port 5104)."""
    return f'{SERVICE_PREFIX}-displays.service'


def get_gpio_service() -> str:
    """Get the GPIO subsystem service name (relays + indicators, port 5105)."""
    return f'{SERVICE_PREFIX}-gpio.service'


# Service URLs (all with environment variable overrides).
#
# The hardware subsystem was split into per-process units in Phase 4 of
# the hardware_service.py split; each subsystem now listens on its own
# port so a Zigbee dongle hang can't block OLED rendering.
#   * 5101  network    (nmcli proxy)
#   * 5102  zigbee     (zigpy controller + join window)
#   * 5103  gps        (GPS manager + trend archive)
#   * 5104  displays   (OLED/LED/VFD push endpoint)
#   * 5105  gpio       (relays + alert indicators — no HTTP API beyond /health)
NETWORK_SERVICE_URL = os.environ.get('NETWORK_SERVICE_URL', 'http://127.0.0.1:5101')
ZIGBEE_SERVICE_URL = os.environ.get('ZIGBEE_SERVICE_URL', 'http://127.0.0.1:5102')
GPS_SERVICE_URL = os.environ.get('GPS_SERVICE_URL', 'http://127.0.0.1:5103')
DISPLAYS_SERVICE_URL = os.environ.get('DISPLAYS_SERVICE_URL', 'http://127.0.0.1:5104')
GPIO_SERVICE_URL = os.environ.get('GPIO_SERVICE_URL', 'http://127.0.0.1:5105')
AUDIO_SERVICE_URL = os.environ.get('AUDIO_SERVICE_URL', 'http://127.0.0.1:5002')
SDR_SERVICE_URL = os.environ.get('SDR_SERVICE_URL', 'http://127.0.0.1:5003')
REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')


def get_hardware_service_token() -> str:
    """Shared secret the network/zigbee/gps/displays subsystem services use
    to authenticate requests from the webapp (and reject everyone else).

    Those four services bind 0.0.0.0 on ports 5101/5102/5103/5104 so their
    systemd sandboxing stays effective, which otherwise leaves them reachable
    to anything on the LAN with no application-layer check — good enough to
    rewrite WiFi credentials, the hostname, or open the Zigbee join window.

    Rather than provision, generate, and keep yet another secret in sync
    across every process' EnvironmentFile, derive it from SECRET_KEY: it is
    already required (``app.py`` fails fast without it in production) and
    already loaded from the same persistent ``.env`` by every subsystem
    process at startup, so every process lands on the same token with no
    extra config.
    """
    secret_key = os.environ.get('SECRET_KEY', '')
    return hmac.new(
        secret_key.encode('utf-8'),
        b'eas-station-hardware-service-auth-v1',
        hashlib.sha256,
    ).hexdigest()
