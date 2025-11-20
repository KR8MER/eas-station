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
Audio Ingest Pipeline and Playout Queue for EAS Station

This module provides unified audio capture from multiple sources including
SDR receivers, ALSA/PulseAudio devices, and file inputs with standardized
metering, monitoring, and diagnostics capabilities.

It also includes the audio playout queue system with FCC-compliant precedence
logic per 47 CFR Part 11, and the audio output service for deterministic playback.
"""

from .ingest import AudioIngestController, AudioSourceAdapter
from .sources import SDRSourceAdapter, ALSASourceAdapter, FileSourceAdapter
from .metering import AudioMeter, SilenceDetector
from .playout_queue import AudioPlayoutQueue, PlayoutItem, PrecedenceLevel
from .output_service import AudioOutputService, PlayoutEvent, PlayoutStatus
from .monitor_manager import (
    get_eas_monitor_instance,
    initialize_eas_monitor,
    start_eas_monitor,
    stop_eas_monitor,
    shutdown_eas_monitor,
)

__all__ = [
    'AudioIngestController',
    'AudioSourceAdapter',
    'SDRSourceAdapter',
    'ALSASourceAdapter',
    'FileSourceAdapter',
    'AudioMeter',
    'SilenceDetector',
    'AudioPlayoutQueue',
    'PlayoutItem',
    'PrecedenceLevel',
    'AudioOutputService',
    'PlayoutEvent',
    'PlayoutStatus',
    'get_eas_monitor_instance',
    'initialize_eas_monitor',
    'start_eas_monitor',
    'stop_eas_monitor',
    'shutdown_eas_monitor',
]