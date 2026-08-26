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
Audio Ingest Pipeline for EAS Station

This module provides unified audio capture from multiple sources including
SDR receivers, ALSA/PulseAudio devices, and file inputs with standardized
metering, monitoring, and diagnostics capabilities.
"""

from .ingest import AudioIngestController, AudioSourceAdapter
from .sources import ALSASourceAdapter, FileSourceAdapter
from .metering import AudioMeter, SilenceDetector
from .eas_monitor import (
    EASMonitor,
    ContinuousEASMonitor,  # Backwards compatibility alias
    MonitorHealth,
    create_fips_filtering_callback,
    compute_alert_signature,
)
from .alert_forwarding import forward_alert_to_api, ALERT_CHANNEL
from .archiver import AudioArchiver, AudioArchiverConfig

__all__ = [
    'AudioIngestController',
    'AudioSourceAdapter',
    'ALSASourceAdapter',
    'FileSourceAdapter',
    'AudioMeter',
    'SilenceDetector',
    'EASMonitor',
    'ContinuousEASMonitor',  # Backwards compatibility alias
    'MonitorHealth',
    'create_fips_filtering_callback',
    'compute_alert_signature',
    'forward_alert_to_api',
    'ALERT_CHANNEL',
    'AudioArchiver',
    'AudioArchiverConfig',
]