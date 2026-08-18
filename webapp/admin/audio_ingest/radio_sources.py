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

from __future__ import annotations

"""Provisioning of the audio sources backing SDR receivers."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from app_core.extensions import db
from app_core.models import (
    AudioSourceConfigDB,
    RadioReceiver,
)
from app_core.audio.ingest import AudioSourceConfig, AudioSourceType
from app_core.audio.sources import create_audio_source
from app_core.audio.redis_commands import get_audio_command_publisher
from app_core.audio.mount_points import generate_mount_point, StreamFormat
from app_core.audio.source_config import merge_managed_config_params

from .controller import _get_audio_controller, _peek_audio_controller
from .streaming import _get_auto_streaming_service

logger = logging.getLogger(__name__)


def _derive_sdr_source_name(identifier: str) -> str:
    """Generate a deterministic audio source name for a receiver identifier."""

    slug = re.sub(r"[^a-z0-9]+", "-", identifier.strip().lower()).strip("-")
    if not slug:
        slug = "receiver"
    return f"sdr-{slug}"


def _recommend_audio_stream(receiver: RadioReceiver) -> Tuple[int, int]:
    """Return (sample_rate, channels) best suited for the receiver's modulation.
    
    These are the NATIVE sample rates for the audio sources/streams.
    The EAS monitor will resample to 16 kHz internally for SAME decoding.
    """

    modulation = (receiver.modulation_type or "IQ").upper()

    if modulation in {"FM", "WFM"}:
        # FM broadcast quality - native rate for demodulated audio
        return (48000 if receiver.stereo_enabled else 32000, 2 if receiver.stereo_enabled else 1)
    if modulation in {"AM", "NFM"}:
        # AM/NFM - narrower bandwidth, lower sample rate sufficient
        return 24000, 1

    # Default for IQ/unknown - standard audio rate
    return 44100, 1


def _format_receiver_frequency(frequency_hz: float) -> str:
    """Format an arbitrary receiver frequency for human-readable display."""

    if frequency_hz >= 1_000_000:
        return f"{frequency_hz / 1_000_000:.3f} MHz"
    if frequency_hz >= 1_000:
        return f"{frequency_hz / 1_000:.0f} kHz"
    return f"{frequency_hz:.0f} Hz"


def _base_radio_metadata(receiver: RadioReceiver, source_name: str) -> Dict[str, Any]:
    """Build baseline metadata payload for SDR-backed audio sources."""

    frequency_hz = float(receiver.frequency_hz or 0.0)
    frequency_mhz = frequency_hz / 1_000_000 if frequency_hz else 0.0
    return {
        'receiver_identifier': receiver.identifier,
        'receiver_display_name': receiver.display_name,
        'receiver_driver': receiver.driver,
        'receiver_frequency_hz': frequency_hz,
        'receiver_frequency_mhz': round(frequency_mhz, 6),
        'receiver_frequency_display': _format_receiver_frequency(frequency_hz) if frequency_hz else None,
        'receiver_modulation': (receiver.modulation_type or "IQ").upper(),
        'receiver_audio_output': bool(receiver.audio_output),
        'receiver_auto_start': bool(receiver.auto_start),
        'rbds_enabled': bool(receiver.enable_rbds),
        'source_category': 'sdr',
        'icecast_mount': generate_mount_point(source_name, format=StreamFormat.MP3),
    }


def list_radio_managed_audio_sources() -> List[AudioSourceConfigDB]:
    """Return AudioSourceConfig rows that are managed automatically for SDR receivers."""

    configs = AudioSourceConfigDB.query.filter_by(source_type=AudioSourceType.SDR.value).all()
    managed: List[AudioSourceConfigDB] = []
    for config in configs:
        params = config.config_params or {}
        if params.get('managed_by') == 'radio':
            managed.append(config)
    return managed


def remove_radio_managed_audio_source(
    source_name: str,
    *,
    commit: bool = True,
    stop_stream: bool = True,
) -> bool:
    """Remove a radio-managed SDR audio source from memory, streaming, and database."""

    db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
    if not db_config:
        return False

    params = db_config.config_params or {}
    if params.get('managed_by') != 'radio':
        return False

    # Notify sdr-service to remove the source via Redis
    try:
        publisher = get_audio_command_publisher()
        result = publisher.delete_source(source_name)
        if result.get('success'):
            logger.info(f"Sent source_delete command to sdr-service for {source_name}")
        else:
            logger.warning(f"Failed to send source_delete to sdr-service: {result.get('message')}")
    except Exception as exc:
        logger.warning('Failed to notify sdr-service about removing %s: %s', source_name, exc)
        # Fall back to local controller if Redis communication fails
        controller = _peek_audio_controller()
        if controller and source_name in controller._sources:
            controller.remove_source(source_name)

        if stop_stream:
            auto_streaming = _get_auto_streaming_service()
            if auto_streaming:
                try:
                    auto_streaming.remove_source(source_name)
                except Exception as e:
                    logger.warning('Failed to stop Icecast stream for %s: %s', source_name, e)

    db.session.delete(db_config)
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    logger.info('Removed SDR audio monitor %s', source_name)
    return True


def ensure_sdr_audio_monitor_source(
    receiver: RadioReceiver,
    *,
    start_immediately: Optional[bool] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """Ensure an SDR receiver has a corresponding audio monitor source configured."""

    source_name = _derive_sdr_source_name(receiver.identifier)
    should_enable = bool(receiver.audio_output and receiver.enabled)

    if not should_enable:
        removed = remove_radio_managed_audio_source(source_name, commit=commit)
        return {
            'source_name': source_name,
            'created': False,
            'updated': False,
            'started': False,
            'icecast_started': False,
            'removed': removed,
        }

    controller = _get_audio_controller()
    sample_rate, channels = _recommend_audio_stream(receiver)
    buffer_size = 4096 if channels == 1 else 8192
    # Thresholds for the legacy instantaneous `silence_detected` metric.
    # These used to be derived from the retired squelch columns, which was
    # always a coincidence of naming rather than a real relationship -- the
    # debounced dead-air alarm reads its own station-wide policy (see
    # app_core/audio/silence.py) and is unaffected by these.
    silence_threshold = AudioSourceConfig.silence_threshold_db
    silence_duration = AudioSourceConfig.silence_duration_seconds

    device_params = {
        'receiver_id': receiver.identifier,
        'receiver_display_name': receiver.display_name,
        'receiver_driver': receiver.driver,
        'receiver_frequency_hz': float(receiver.frequency_hz or 0.0),
        'receiver_modulation': (receiver.modulation_type or 'IQ').upper(),
        'iq_sample_rate': receiver.sample_rate,
        'rbds_enabled': bool(receiver.enable_rbds),
    }

    managed_params = {
        'sample_rate': sample_rate,
        'channels': channels,
        'buffer_size': buffer_size,
        'silence_threshold_db': silence_threshold,
        'silence_duration_seconds': silence_duration,
        'device_params': device_params,
        'managed_by': 'radio',
    }

    start_flag = bool(start_immediately if start_immediately is not None else receiver.auto_start)

    freq_display = _format_receiver_frequency(float(receiver.frequency_hz or 0.0)) if receiver.frequency_hz else "Unknown"
    description = f"SDR monitor for {receiver.display_name} · {freq_display}"

    created = False
    updated = False

    db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
    priority = 10

    if db_config is None:
        db_config = AudioSourceConfigDB(
            name=source_name,
            source_type=AudioSourceType.SDR.value,
            config_params=dict(managed_params),
            priority=priority,
            enabled=True,
            auto_start=start_flag,
            description=description,
        )
        db.session.add(db_config)
        created = True
    else:
        # Merge rather than replace: config_params also carries user-owned
        # settings (Audio Archives retention/format) that this sync must not
        # delete on every service start.
        merged_params = merge_managed_config_params(db_config.config_params, managed_params)
        if (db_config.config_params or {}) != merged_params:
            db_config.config_params = merged_params
            updated = True
        if not db_config.enabled:
            db_config.enabled = True
            updated = True
        if db_config.auto_start != start_flag:
            db_config.auto_start = start_flag
            updated = True
        if (db_config.description or '') != description:
            db_config.description = description
            updated = True
        if db_config.priority != priority:
            db_config.priority = priority
            updated = True
        if db_config.source_type != AudioSourceType.SDR.value:
            db_config.source_type = AudioSourceType.SDR.value
            updated = True

    if commit and (created or updated):
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    # In separated architecture, audio processing happens in SDR hardware service process.
    # We need to notify the sdr-service via Redis to reload/start the source.
    # The local controller in webapp is only used for metrics display, not audio processing.
    started = False
    icecast_started = False
    
    if start_flag:
        try:
            # Send command to sdr-service to reload and start the source
            publisher = get_audio_command_publisher()
            
            # Build the source config that audio-service can use
            # CRITICAL: Use 'redis_sdr' type for separated architecture
            # audio-service will create RedisSDRSourceAdapter to subscribe to IQ samples
            source_config = {
                'source_type': 'redis_sdr',  # NOT AudioSourceType.SDR - use redis_sdr for separated arch
                'name': source_name,
                'enabled': True,
                'priority': priority,
                'sample_rate': sample_rate,
                'channels': channels,
                'buffer_size': buffer_size,
                'silence_threshold_db': silence_threshold,
                'silence_duration_seconds': silence_duration,
                'device_params': device_params,
            }
            
            # Send add_source command (sdr-service will create adapter and start it)
            result = publisher.add_source(source_config)
            if result.get('success'):
                logger.info(f"Sent source_add command to sdr-service for {source_name}")
                # Also send start command to ensure it starts
                start_result = publisher.start_source(source_name)
                if start_result.get('success'):
                    started = True
                    logger.info(f"Sent source_start command to sdr-service for {source_name}")
                else:
                    logger.warning(f"Failed to send source_start to sdr-service: {start_result.get('message')}")
            else:
                logger.warning(f"Failed to send source_add to sdr-service: {result.get('message')}")
                
        except Exception as exc:
            logger.warning('Failed to notify sdr-service about SDR audio source %s: %s', source_name, exc)
            # Fall back to local controller if Redis communication fails
            try:
                controller = _get_audio_controller()
                auto_streaming = _get_auto_streaming_service()

                if controller._sources.get(source_name):
                    if auto_streaming:
                        try:
                            auto_streaming.remove_source(source_name)
                        except Exception as e:
                            logger.debug('Auto-stream removal for %s during reconfigure failed: %s', source_name, e)
                    controller.remove_source(source_name)

                runtime_config = AudioSourceConfig(
                    source_type=AudioSourceType.SDR,
                    name=source_name,
                    enabled=True,
                    priority=priority,
                    sample_rate=sample_rate,
                    channels=channels,
                    buffer_size=buffer_size,
                    silence_threshold_db=silence_threshold,
                    silence_duration_seconds=silence_duration,
                    device_params=device_params,
                )

                adapter = create_audio_source(runtime_config)
                metadata = adapter.metrics.metadata or {}
                metadata.update({k: v for k, v in _base_radio_metadata(receiver, source_name).items() if v is not None})
                metadata.setdefault('rbds_program_type_name', None)
                metadata.setdefault('rbds_last_updated', None)
                adapter.metrics.metadata = metadata
                controller.add_source(adapter)

                started = controller.start_source(source_name)
                if started and auto_streaming and auto_streaming.is_available():
                    icecast_started = bool(auto_streaming.add_source(source_name, adapter))
            except Exception as fallback_exc:
                logger.error('Fallback to local controller also failed: %s', fallback_exc)

    return {
        'source_name': source_name,
        'created': created,
        'updated': updated,
        'started': started,
        'icecast_started': icecast_started,
        'removed': False,
    }
