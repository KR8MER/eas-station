#!/usr/bin/env python3
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
EAS Monitoring Service

This service handles EAS/SAME monitoring and audio processing (NO SDR hardware access).

This service handles:
- Audio demodulation from IQ samples (received via Redis from sdr-service)
- EAS/SAME header monitoring and decoding
- HTTP/Icecast stream ingestion
- Icecast streaming output
- Metrics publishing to Redis

Architecture (Separated):
┌────────────────────────┐      Redis       ┌──────────────────────────┐
│ sdr_hardware_service.py│ ──> IQ samples ──>│ eas_monitoring_service.py│
│ (USB access)           │   (pub/sub)      │ (NO USB access)          │
│ - SDR hardware         │                  │ - Demodulation           │
│ - IQ sampling          │                  │ - EAS monitoring         │
└────────────────────────┘                  │ - Icecast streaming      │
                                            └──────────────────────────┘
  
The web application reads metrics from Redis and serves the UI.
"""

import os
import sys
import math
import time
import uuid
import signal
import logging
import threading
import redis
import json
from typing import Optional, Any, Dict
from dotenv import load_dotenv

from app_utils.system.sd_notify import notify as sd_notify, Watchdog

# Configure logging early
from app_core.logging_context import (
    LOG_FORMAT_WITH_ALERT,
    install_alert_filter,
)
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT_WITH_ALERT,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
install_alert_filter()

logger = logging.getLogger(__name__)

# This process runs a CPU-bound numpy-heavy monitor loop (SAME/FSK decode
# across every audio source) continuously alongside I/O-bound threads that
# need to run promptly -- the EAS decoder stream's ffmpeg-feeder thread
# (stream_eas_decoder() below) chief among them. Python's default GIL
# switch interval (5ms) lets one long-running CPU-bound thread hold the GIL
# for stretches long enough that a sibling I/O thread trying to keep an
# ffmpeg subprocess fed in real time falls behind -- observed live as
# /api/eas/decoder-stream producing zero audio bytes for 15+ seconds while
# this process's CPU briefly spiked well past 100% on the request. Shortening
# the interval makes the interpreter hand off the GIL more often, at a small
# constant cost in context-switch overhead, which is worth paying here since
# audio timing correctness matters more than raw throughput.
sys.setswitchinterval(0.001)

# Constants
FFT_MIN_MAGNITUDE = 1e-10  # Minimum magnitude to avoid log(0) in dB conversion
MIN_AUDIO_SAMPLE_RATE = 8000  # Minimum valid audio sample rate (Hz)

# Load environment variables from persistent config volume
# This must happen before initializing audio sources
_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    if os.path.exists(_config_path):
        load_dotenv(_config_path, override=True)
        logger.info(f"✅ Loaded environment from: {_config_path}")
    else:
        logger.warning(f"⚠️  CONFIG_PATH set but file not found: {_config_path}")
        load_dotenv(override=True)  # Fall back to default .env
else:
    load_dotenv(override=True)  # Use default .env location

# Global state with thread-safe access
_state_lock = threading.Lock()
_running = True
_redis_client: Optional[redis.Redis] = None
_audio_controller = None
_eas_monitor = None
_auto_streaming_service = None
# NOTE: _radio_manager removed - audio-service does NOT access SDR hardware
# SDR hardware is managed exclusively by sdr-service.py container

# Registry of running AudioArchiver instances: source_name -> AudioArchiver
_archivers: dict = {}


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _running
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _running = False


def get_redis_client() -> redis.Redis:
    """
    Get or create Redis client with retry logic.

    Uses app_core.redis_client for robust connection handling with
    exponential backoff and circuit breaker pattern.
    """
    global _redis_client

    # Use robust Redis client with retry logic
    from app_core.redis_client import get_redis_client as get_robust_client

    try:
        _redis_client = get_robust_client(
            max_retries=5,
            initial_backoff=1.0,
            max_backoff=30.0
        )
        return _redis_client
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
        raise


def _sanitize_value(value: Any) -> Any:
    """Convert runtime values to JSON-serializable primitives.

    Handles numpy types and Python float inf/nan values that would
    otherwise cause json.dumps() to raise ValueError.
    """
    try:
        import numpy as np  # type: ignore

        if isinstance(value, (np.floating, np.integer)):
            v = float(value)
            if math.isinf(v):
                return -120.0 if v < 0 else 120.0
            if math.isnan(v):
                return -120.0
            return v
        if isinstance(value, np.bool_):
            return bool(value)
    except Exception:
        # numpy is optional in some deployments; ignore if unavailable
        pass

    if isinstance(value, bool):
        return value

    if isinstance(value, float):
        if math.isinf(value):
            return -120.0 if value < 0 else 120.0
        if math.isnan(value):
            return -120.0
        return value

    if isinstance(value, (str, int)):
        return value

    if isinstance(value, dict):
        return {str(k): _sanitize_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(v) for v in value]

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    try:
        return float(value)
    except Exception:
        return str(value)


def initialize_database():
    """Initialize database connection for configuration."""
    from app_core.extensions import db
    from flask import Flask

    # Create minimal Flask app for database access
    app = Flask(__name__)

    # Database configuration
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    return app


def _ensure_raw_audio_column(app) -> None:
    """Add raw_audio_data column to received_eas_alerts if it does not exist.

    This is a lightweight idempotent guard for the migration introduced in
    20260325_add_raw_audio_to_received_alerts.py.  Installations that have
    not run ``alembic upgrade head`` since that migration was released will
    have a missing column, causing every OTA-alert database write to fail
    (silently losing the record).  Running the guard at startup ensures the
    column is present regardless of whether the user has run alembic.
    """
    try:
        from app_core.extensions import db
        with app.app_context():
            with db.engine.connect() as conn:
                result = conn.execute(
                    db.text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='received_eas_alerts' "
                        "AND column_name='raw_audio_data'"
                    )
                ).fetchone()
                if result is None:
                    conn.execute(
                        db.text(
                            "ALTER TABLE received_eas_alerts "
                            "ADD COLUMN raw_audio_data BYTEA"
                        )
                    )
                    conn.commit()
                    logger.info(
                        "Applied missing migration: added raw_audio_data column "
                        "to received_eas_alerts"
                    )
                else:
                    logger.debug("raw_audio_data column already present")
    except Exception as exc:
        logger.warning(
            "Could not verify/apply raw_audio_data column migration "
            "(alerts will still be stored without audio): %s", exc
        )


def sync_radio_receiver_audio_sources(app):
    """Ensure audio sources exist for all enabled radio receivers with audio_output=True.
    
    This is critical for the separated architecture where sdr-service publishes IQ samples
    to Redis and audio-service needs AudioSourceConfigDB entries to know which channels
    to subscribe to via RedisSDRSourceAdapter.
    """
    with app.app_context():
        from app_core.models import RadioReceiver, AudioSourceConfigDB, db
        from app_core.audio.ingest import AudioSourceConfig, AudioSourceType
        from app_core.audio.source_config import merge_managed_config_params

        logger.info("Syncing audio sources for radio receivers...")
        
        # Get all radio receivers that should have audio sources
        receivers = RadioReceiver.query.filter_by(enabled=True, audio_output=True).all()
        
        if not receivers:
            logger.info("No radio receivers with audio output enabled")
            return
        
        created = 0
        updated = 0
        
        for receiver in receivers:
            source_name = f"sdr-{receiver.identifier}"
            
            # Determine audio sample rate - use explicit setting or auto-detect from modulation
            modulation = (receiver.modulation_type or 'IQ').upper()
            
            # Use explicit audio_sample_rate if configured, otherwise auto-detect
            if receiver.audio_sample_rate and receiver.audio_sample_rate >= MIN_AUDIO_SAMPLE_RATE:
                sample_rate = receiver.audio_sample_rate
                # Channels based on stereo setting
                channels = 2 if (modulation in ('FM', 'WFM', 'WBFM') and receiver.stereo_enabled) else 1
                logger.debug(f"Using configured audio_sample_rate for {receiver.identifier}: {sample_rate} Hz")
            else:
                # Auto-detect based on modulation type
                if modulation in ('FM', 'WFM', 'WBFM') and receiver.stereo_enabled:
                    channels = 2
                    sample_rate = 48000
                elif modulation in ('FM', 'WFM', 'WBFM'):
                    channels = 1
                    sample_rate = 32000
                elif modulation in ('NFM', 'AM'):
                    channels = 1
                    sample_rate = 24000
                else:
                    channels = 1
                    sample_rate = 44100
                logger.debug(f"Auto-detected audio settings for {receiver.identifier}: {sample_rate} Hz, {channels} ch")
            
            buffer_size = 4096 if channels == 1 else 8192
            # Legacy instantaneous `silence_detected` thresholds. Formerly
            # derived from the retired squelch columns; the debounced
            # dead-air alarm uses its own station-wide policy instead.
            silence_threshold = AudioSourceConfig.silence_threshold_db
            silence_duration = AudioSourceConfig.silence_duration_seconds
            
            device_params = {
                'receiver_id': receiver.identifier,
                'receiver_display_name': receiver.display_name,
                'receiver_driver': receiver.driver,
                'receiver_frequency_hz': float(receiver.frequency_hz or 0.0),
                'receiver_modulation': modulation,
                'iq_sample_rate': receiver.sample_rate,
                'demod_mode': receiver.modulation_type or 'FM',
                # RBDS and demodulation settings - use both key names for compatibility
                'enable_rbds': bool(receiver.enable_rbds),
                'rbds_enabled': bool(receiver.enable_rbds),
                'stereo_enabled': bool(receiver.stereo_enabled),
                'deemphasis_us': float(receiver.deemphasis_us or 75.0),  # 75μs for North America
            }
            
            managed_params = {
                'sample_rate': sample_rate,
                'channels': channels,
                'buffer_size': buffer_size,
                'silence_threshold_db': silence_threshold,
                'silence_duration_seconds': silence_duration,
                'device_params': device_params,
                'managed_by': 'radio',  # CRITICAL: This flag tells audio-service to use RedisSDRSourceAdapter
            }
            
            freq_display = f"{receiver.frequency_hz/1e6:.3f} MHz" if receiver.frequency_hz else "Unknown"
            description = f"SDR monitor for {receiver.display_name} · {freq_display}"
            
            # DEBUG: Log RBDS setting being synced
            logger.info(f"Syncing receiver '{receiver.identifier}': enable_rbds={receiver.enable_rbds}")

            # Check if audio source exists
            db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()

            if db_config is None:
                # Create new audio source
                logger.info(f"Creating audio source for receiver '{receiver.identifier}': {source_name}")
                db_config = AudioSourceConfigDB(
                    name=source_name,
                    source_type=AudioSourceType.SDR.value,
                    config_params=dict(managed_params),
                    priority=10,
                    enabled=True,
                    auto_start=receiver.auto_start,
                    description=description,
                )
                db.session.add(db_config)
                created += 1
            else:
                # Update existing audio source if config changed.  Merge rather
                # than replace — config_params also carries user-owned settings
                # (Audio Archives retention/format) that this startup sync must
                # not delete, or archiving silently resets on every upgrade.
                existing_params = db_config.config_params or {}
                merged_params = merge_managed_config_params(existing_params, managed_params)
                existing_rbds = existing_params.get('device_params', {}).get('enable_rbds', 'NOT_SET')
                new_rbds = managed_params.get('device_params', {}).get('enable_rbds', 'NOT_SET')
                logger.debug(f"Comparing configs for '{receiver.identifier}': existing_rbds={existing_rbds}, new_rbds={new_rbds}")

                if existing_params != merged_params:
                    logger.info(f"Updating audio source for receiver '{receiver.identifier}': {source_name} (rbds: {existing_rbds} -> {new_rbds})")
                    db_config.config_params = merged_params
                    db_config.enabled = True
                    db_config.auto_start = receiver.auto_start
                    db_config.description = description
                    updated += 1
                else:
                    logger.debug(f"No config change for '{receiver.identifier}' (rbds={new_rbds})")
        
        if created > 0 or updated > 0:
            db.session.commit()
            logger.info(f"✅ Synced audio sources: {created} created, {updated} updated")
        else:
            logger.info("✅ All audio sources already in sync")


def initialize_audio_controller(app):
    """Initialize audio ingestion controller."""
    global _audio_controller

    with app.app_context():
        from app_core.audio.ingest import AudioIngestController, AudioSourceConfig, AudioSourceType
        from app_core.audio.sources import create_audio_source
        from app_core.models import AudioSourceConfigDB

        logger.info("Initializing audio controller...")
        
        # Sync audio sources for radio receivers before loading from database.
        # This ensures that audio sources exist for all enabled receivers with
        # audio_output=True.  Run inside a try/except so that a bad receiver
        # config (e.g. a DB commit error) degrades gracefully rather than
        # crashing the entire audio service.
        try:
            sync_radio_receiver_audio_sources(app)
        except Exception as sync_exc:
            logger.error(
                "sync_radio_receiver_audio_sources failed (continuing without SDR sync): %s",
                sync_exc, exc_info=True,
            )

        # Create controller — use 30s stall threshold so HTTP streams have enough
        # time for DNS + TCP + HTTP + FFmpeg -analyzeduration before the health
        # monitor fires a false "stalled capture" and restarts them.  The default
        # of 5 s is far too short for network radio streams.
        _audio_controller = AudioIngestController(stall_seconds=30)

        # Load audio sources from database
        saved_configs = AudioSourceConfigDB.query.all()
        logger.info(f"Loading {len(saved_configs)} audio source configurations from database")

        for db_config in saved_configs:
            try:
                # Parse source type
                source_type_str = db_config.source_type
                
                # CRITICAL: In separated architecture, convert 'sdr' to redis_sdr
                # Database stores 'sdr' for radio-managed sources, but audio-service
                # must use RedisSDRSourceAdapter to subscribe to IQ samples from sdr-service
                if source_type_str == 'sdr':
                    # Check if this is a radio-managed source (from RadioReceiver)
                    config_params = db_config.config_params or {}
                    if config_params.get('managed_by') == 'radio':
                        # This is an SDR receiver - use Redis adapter in separated architecture
                        from app_core.audio.redis_sdr_adapter import RedisSDRSourceAdapter
                        
                        runtime_config = AudioSourceConfig(
                            source_type=AudioSourceType.STREAM,  # Use STREAM as placeholder
                            name=db_config.name,
                            enabled=db_config.enabled,
                            priority=db_config.priority,
                            sample_rate=config_params.get('sample_rate', 44100),
                            channels=config_params.get('channels', 1),
                            buffer_size=config_params.get('buffer_size', 4096),
                            silence_threshold_db=config_params.get('silence_threshold_db', -60.0),
                            silence_duration_seconds=config_params.get('silence_duration_seconds', 5.0),
                            dead_air_enabled=config_params.get('dead_air_enabled', False),
                            dead_air_level_threshold_db=config_params.get('dead_air_level_threshold_db', -65.0),
                            dead_air_detect_open_carrier=config_params.get('dead_air_detect_open_carrier', True),
                            dead_air_flatness_threshold_pct=config_params.get('dead_air_flatness_threshold_pct', 25),
                            dead_air_duration_seconds=config_params.get('dead_air_duration_seconds', 20.0),
                            device_params=config_params.get('device_params', {}),
                        )

                        # Create Redis SDR adapter directly (subscribes to IQ samples)
                        adapter = RedisSDRSourceAdapter(runtime_config)
                        _audio_controller.add_source(adapter)
                        
                        # Log with receiver details for debugging
                        device_params = config_params.get('device_params', {})
                        receiver_id = device_params.get('receiver_id', 'unknown')
                        receiver_name = device_params.get('receiver_display_name', 'unknown')
                        receiver_freq = device_params.get('receiver_frequency_hz', 0)
                        freq_display = f"{receiver_freq/1e6:.3f} MHz" if receiver_freq else "unknown"
                        
                        logger.info(
                            f"✅ Loaded Redis SDR source: {db_config.name} "
                            f"(receiver: {receiver_name} @ {freq_display}, "
                            f"subscribes to sdr:samples:{receiver_id})"
                        )
                        continue
                
                # Normal source type handling
                source_type = AudioSourceType(source_type_str)

                # Create runtime configuration from database config
                config_params = db_config.config_params or {}
                runtime_config = AudioSourceConfig(
                    source_type=source_type,
                    name=db_config.name,
                    enabled=db_config.enabled,
                    priority=db_config.priority,
                    sample_rate=config_params.get('sample_rate', 44100),
                    channels=config_params.get('channels', 1),
                    buffer_size=config_params.get('buffer_size', 4096),
                    silence_threshold_db=config_params.get('silence_threshold_db', -60.0),
                    silence_duration_seconds=config_params.get('silence_duration_seconds', 5.0),
                    dead_air_enabled=config_params.get('dead_air_enabled', False),
                    dead_air_level_threshold_db=config_params.get('dead_air_level_threshold_db', -65.0),
                    dead_air_detect_open_carrier=config_params.get('dead_air_detect_open_carrier', True),
                    dead_air_flatness_threshold_pct=config_params.get('dead_air_flatness_threshold_pct', 25),
                    dead_air_duration_seconds=config_params.get('dead_air_duration_seconds', 20.0),
                    device_params=config_params.get('device_params', {}),
                )

                # Create and add adapter
                adapter = create_audio_source(runtime_config)
                _audio_controller.add_source(adapter)
                logger.info(f"Loaded audio source: {db_config.name} ({db_config.source_type})")

            except Exception as e:
                logger.error(f"Error loading source '{db_config.name}': {e}", exc_info=True)

        logger.info(f"Loaded {len(_audio_controller.get_all_sources())} audio source configurations")

        # Start auto-start sources IN PARALLEL.  Starting a stream source can
        # block for 10-30 s on URL resolution / FFmpeg connection when the
        # remote end is dead or the network is down.  The old serial loop let
        # ONE dead source delay startup — and therefore decoding and metrics
        # for every healthy source — by that long per broken source.
        auto_start_sources = [db_config for db_config in saved_configs if db_config.enabled and db_config.auto_start]
        if auto_start_sources:
            logger.info(f"Auto-starting {len(auto_start_sources)} enabled source(s) in parallel...")

            def _auto_start_one(source_name: str) -> None:
                try:
                    with app.app_context():
                        result = _audio_controller.start_source(source_name)
                    if result:
                        logger.info(f"✅ Successfully started '{source_name}'")
                    else:
                        logger.warning(f"⚠️ Failed to start '{source_name}' (start returned False)")
                except Exception as e:
                    logger.error(f"❌ Exception auto-starting '{source_name}': {e}", exc_info=True)

            start_threads = []
            for db_config in auto_start_sources:
                # Extract receiver info for SDR sources
                if db_config.source_type == 'sdr':
                    config_params = db_config.config_params or {}
                    device_params = config_params.get('device_params', {})
                    receiver_id = device_params.get('receiver_id', 'unknown')
                    receiver_name = device_params.get('receiver_display_name', 'unknown')
                    logger.info(
                        f"Auto-starting source: '{db_config.name}' "
                        f"(type: {db_config.source_type}, receiver: {receiver_name}, id: {receiver_id})"
                    )
                else:
                    logger.info(f"Auto-starting source: '{db_config.name}' (type: {db_config.source_type})")

                thread = threading.Thread(
                    target=_auto_start_one,
                    args=(db_config.name,),
                    daemon=True,
                    name=f"auto-start-{db_config.name}",
                )
                thread.start()
                start_threads.append(thread)

            # Wait briefly so fast sources are RUNNING before the Icecast
            # wiring below, but never let a dead source block service startup:
            # sources that finish late are picked up by the auto-streaming
            # monitor, the EAS monitor's discovery, and the Redis publisher
            # monitor, all of which poll for newly-RUNNING sources.
            deadline = time.time() + 10.0
            for thread in start_threads:
                thread.join(timeout=max(0.0, deadline - time.time()))
            still_starting = [t.name for t in start_threads if t.is_alive()]
            if still_starting:
                logger.warning(
                    "Sources still starting in background: %s — continuing startup "
                    "without waiting (they will be picked up once RUNNING)",
                    ', '.join(still_starting),
                )
        else:
            logger.info("No sources configured for auto-start")

        logger.info("✅ Audio controller initialized")
        return _audio_controller


def initialize_auto_streaming(app, audio_controller):
    """Initialize Icecast auto-streaming service."""
    global _auto_streaming_service

    try:
        with app.app_context():
            from app_core.audio.icecast_auto_config import get_icecast_auto_config
            from app_core.audio.auto_streaming import AutoStreamingService
            from app_core.audio.stream_profiles import StreamFormat

            auto_config = get_icecast_auto_config()

            if not auto_config.is_enabled():
                logger.info("Icecast auto-streaming is disabled (ICECAST_ENABLED=false)")
                return None

            logger.info(f"Initializing Icecast auto-streaming: {auto_config.server}:{auto_config.port}")

            # Map format string to enum
            stream_format = StreamFormat.MP3 if auto_config.stream_format.lower() == 'mp3' else StreamFormat.OGG

            _auto_streaming_service = AutoStreamingService(
                icecast_server=auto_config.server,
                icecast_port=auto_config.port,
                icecast_password=auto_config.source_password,
                icecast_admin_user=auto_config.admin_user,
                icecast_admin_password=auto_config.admin_password,
                default_bitrate=auto_config.stream_bitrate,  # Use configured bitrate from database/env
                default_format=stream_format,  # Use configured format from database/env
                enabled=True,
                audio_controller=audio_controller
            )

            # Start the service
            if _auto_streaming_service.start():
                logger.info("✅ Icecast auto-streaming service started successfully")
            else:
                logger.warning("Icecast auto-streaming service failed to start")

            # Register with the alert-metadata coordinator so the auto-forwarder
            # can override stream titles with the alert text mid-broadcast.
            try:
                from app_core.audio import alert_metadata
                alert_metadata.set_service(_auto_streaming_service)
            except Exception as exc:
                logger.warning("Failed to register alert metadata coordinator: %s", exc)

            return _auto_streaming_service

    except Exception as exc:
        logger.error(f"Failed to initialize Icecast auto-streaming: {exc}", exc_info=True)
        return None


def _make_metadata_log_callback(flask_app):
    """Return a thread-safe callback that persists ICY metadata changes to the DB."""
    import threading

    def _callback(source_name: str, updates: dict) -> None:
        def _write() -> None:
            try:
                with flask_app.app_context():
                    from app_core.extensions import db
                    from app_core.models import StreamMetadataLog

                    now_playing = updates.get('now_playing', {})
                    record = StreamMetadataLog(
                        source_name=source_name,
                        # updates['title'] / updates['artist'] are only set when a clean
                        # value was actually parsed out of the ICY StreamTitle.
                        # now_playing['title'] can be the full raw ICY blob (it is
                        # initialised from stream_title before any pattern matching),
                        # so we must NOT fall back to it for the title column.
                        # now_playing['artist'] is safe because it starts as None and is
                        # only populated when a real artist string was extracted.
                        title=updates.get('title'),
                        artist=updates.get('artist') or now_playing.get('artist'),
                        album=updates.get('album'),
                        artwork_url=updates.get('artwork_url'),
                        length=updates.get('length'),
                        display=updates.get('song'),
                        raw=updates.get('song_raw'),
                        stream_url=updates.get('stream_url'),
                    )
                    db.session.add(record)
                    db.session.commit()
            except Exception as exc:
                logger.warning("Failed to log stream metadata for '%s': %s", source_name, exc)

        threading.Thread(target=_write, daemon=True).start()

    return _callback


def _make_audio_alert_log_callback(flask_app):
    """Return a thread-safe callback that persists audio source events to the AudioAlert DB table.

    The callback signature is ``(source_name: str, event_type: str, message: str)``.
    ``event_type`` is one of: ``'stall'``, ``'error'``, ``'disconnected'``.
    """
    import threading

    # Map event types to alert levels recognised by the DB model
    _LEVEL_MAP = {
        'stall': 'warning',
        'error': 'error',
        'disconnected': 'warning',
    }

    # Deduplicate rapid-fire alerts: only write one record per source per
    # event type within a short window to avoid flooding the table.
    _last_written: dict = {}  # key: (source_name, event_type) → timestamp
    _dedup_seconds = 30.0
    _lock = threading.Lock()

    def _callback(source_name: str, event_type: str, message: str) -> None:
        import time as _time
        now = _time.time()
        key = (source_name, event_type)
        with _lock:
            if now - _last_written.get(key, 0) < _dedup_seconds:
                return
            _last_written[key] = now

        def _write() -> None:
            try:
                with flask_app.app_context():
                    from app_core.extensions import db
                    from app_core.models import AudioAlert

                    record = AudioAlert(
                        source_name=source_name,
                        alert_level=_LEVEL_MAP.get(event_type, 'warning'),
                        alert_type=event_type,
                        message=message,
                    )
                    db.session.add(record)
                    db.session.commit()
            except Exception as exc:
                logger.warning("Failed to log audio alert for '%s' (%s): %s", source_name, event_type, exc)

        threading.Thread(target=_write, daemon=True).start()

    return _callback


def _snapshot_audio_metrics_once(flask_app) -> None:
    """Persist one AudioSourceMetrics row per running source, synchronously.

    Split out from _make_audio_metrics_snapshot_writer() below so tests can
    call it directly on their own thread instead of racing (or mocking) the
    background thread that wraps it in production.
    """
    if not _audio_controller:
        return
    try:
        with flask_app.app_context():
            from app_core.extensions import db
            from app_core.models import AudioSourceMetrics
            from app_core.audio.ingest import AudioSourceStatus

            for name, source in _audio_controller.get_all_sources().items():
                if source.status != AudioSourceStatus.RUNNING:
                    continue
                metrics_obj = getattr(source, "metrics", None)
                if metrics_obj is None:
                    continue

                # peak/rms are true dB (can be -inf for digital silence);
                # 10 ** (-inf / 20) evaluates to 0.0, no special case needed.
                # A missing metrics_obj value (None) is the only case that
                # would break the NOT NULL float columns.
                #
                # metrics_obj is computed from numpy arrays (see
                # AudioSourceAdapter._update_metrics in app_core/audio/ingest.py:
                # `20 * np.log10(...)`, `-np.inf` defaults, etc.), so every
                # field here -- not just the two dB values -- can arrive as a
                # numpy scalar (np.float32/np.float64/np.int64) rather than a
                # native Python type. psycopg2 cannot adapt those directly
                # ("can't adapt type 'numpy.float32'"), which silently failed
                # this entire commit -- and therefore this whole snapshot,
                # every second, since this writer was added: the
                # audio_source_metrics table has never actually been
                # populated in production. float()/int() below force native
                # types before they ever reach SQLAlchemy.
                peak_db = float(metrics_obj.peak_level_db) if metrics_obj.peak_level_db is not None else -120.0
                rms_db = float(metrics_obj.rms_level_db) if metrics_obj.rms_level_db is not None else -120.0

                source_type = getattr(getattr(source, "config", None), "source_type", None)
                source_type_value = source_type.value if hasattr(source_type, "value") else str(source_type or "unknown")

                db.session.add(AudioSourceMetrics(
                    source_name=name,
                    source_type=source_type_value,
                    peak_level_db=peak_db,
                    rms_level_db=rms_db,
                    peak_level_linear=float(10 ** (peak_db / 20.0)),
                    rms_level_linear=float(10 ** (rms_db / 20.0)),
                    sample_rate=int(getattr(metrics_obj, "sample_rate", None) or 0),
                    channels=int(getattr(metrics_obj, "channels", None) or 0),
                    frames_captured=int(getattr(metrics_obj, "frames_captured", None) or 0),
                    silence_detected=bool(getattr(metrics_obj, "silence_detected", False)),
                    buffer_utilization=float(getattr(metrics_obj, "buffer_utilization", None) or 0.0),
                    source_metadata=_sanitize_value(getattr(metrics_obj, "metadata", None)),
                ))
            db.session.commit()
    except Exception as exc:
        logger.warning("Failed to snapshot audio metrics to DB: %s", exc)


def _make_audio_metrics_snapshot_writer(flask_app):
    """Return a callable that triggers _snapshot_audio_metrics_once() on a
    short-lived background thread. Intended to be called at ~1 Hz from the
    main loop.

    The RBDS History API (webapp/admin/audio_ingest/routes_rbds.py) and the
    audio-health analytics aggregator both read the audio_source_metrics
    table on the assumption that it is populated roughly once a second --
    but nothing ever wrote to it in production; only tests instantiated
    AudioSourceMetrics. RBDS History always showed "No stored RBDS
    snapshots" regardless of how long a station had been running. Dispatch
    onto a thread here (rather than in _snapshot_audio_metrics_once itself)
    so a slow commit can never stall the 4 Hz Redis publish loop that VU
    meters, RSSI, and RBDS/RDS updates depend on.
    """
    import threading

    def _trigger() -> None:
        threading.Thread(target=_snapshot_audio_metrics_once, args=(flask_app,), daemon=True).start()

    return _trigger


def initialize_archivers(app, audio_controller):
    """Start AudioArchivers for sources that have archiving enabled in their config_params.

    Each AudioSourceConfigDB record may carry an ``"archive"`` key inside
    ``config_params``.  When ``archive.enabled`` is true, an AudioArchiver is
    created and started, then stored in ``_archivers``.
    """
    global _archivers

    try:
        from app_core.audio.archiver import AudioArchiver, AudioArchiverConfig
        from app_core.audio.ingest import AudioSourceStatus
        from app_core.models import AudioSourceConfigDB

        with app.app_context():
            db_configs = AudioSourceConfigDB.query.all()

        started = 0
        for db_config in db_configs:
            config_params = db_config.config_params or {}
            archive_cfg = config_params.get('archive', {})
            if not archive_cfg.get('enabled', False):
                continue

            source_name = db_config.name
            adapter = audio_controller._sources.get(source_name)
            if adapter is None:
                logger.debug("initialize_archivers: source '%s' not loaded yet – skipping", source_name)
                continue

            if adapter.status != AudioSourceStatus.RUNNING:
                logger.debug(
                    "initialize_archivers: source '%s' not running (status=%s) – skipping",
                    source_name, adapter.status,
                )
                continue

            try:
                broadcast_queue = adapter.get_broadcast_queue()
            except AttributeError:
                broadcast_queue = None
            if broadcast_queue is None:
                logger.warning("initialize_archivers: source '%s' has no broadcast queue", source_name)
                continue

            try:
                cfg = AudioArchiverConfig(
                    output_dir=archive_cfg.get('output_dir', 'archives'),
                    segment_duration_seconds=int(archive_cfg.get('segment_duration_seconds', 3600)),
                    retention_days=int(archive_cfg.get('retention_days', 7)),
                    max_disk_bytes=int(archive_cfg.get('max_disk_bytes', 0)),
                    format=archive_cfg.get('format', 'wav'),
                    bitrate=int(archive_cfg.get('bitrate', 128)),
                    silence_threshold=float(archive_cfg.get('silence_threshold', 0.0)),
                )
                archiver = AudioArchiver(
                    source_name=source_name,
                    config=cfg,
                    broadcast_queue=broadcast_queue,
                    sample_rate=getattr(adapter.config, 'sample_rate', 44100),
                    channels=getattr(adapter.config, 'channels', 1),
                )
                if archiver.start():
                    _archivers[source_name] = archiver
                    started += 1
                    logger.info("✅ Archiver started for source '%s'", source_name)
                else:
                    logger.warning("⚠️ Archiver failed to start for source '%s'", source_name)
            except Exception as exc:
                logger.error("❌ Error starting archiver for '%s': %s", source_name, exc, exc_info=True)

        logger.info("initialize_archivers: started %d archiver(s)", started)
        return _archivers

    except Exception as exc:
        logger.error("Failed to initialize archivers: %s", exc, exc_info=True)
        return _archivers


def _source_watchdog_loop(app, audio_controller, stop_event, interval_seconds: float = 30.0) -> None:
    """Background watchdog: restart ERROR sources and auto-start STOPPED sources.

    Runs in its OWN thread so stopping/starting a stalled capture can never
    block the metrics-publishing loop.  (The previous inline implementation
    ran this inside the main loop: one blocked restart froze metrics
    publishing, the Redis ``eas:metrics`` key expired, and the entire UI
    reported the audio service — and all decoding — as unavailable.)

    Individual restarts are dispatched through the controller's per-source
    recovery threads (``spawn_recovery``), so one blocked source cannot delay
    recovery of the others either.
    """
    from app_core.audio.ingest import AudioSourceStatus

    logger.info("Source watchdog started (interval: %.0fs)", interval_seconds)

    while not stop_event.wait(interval_seconds):
        try:
            # Re-read dead-air thresholds each cycle so a change in
            # Admin -> Hardware takes effect without a service restart.
            # This loop already owns an app context per iteration and runs
            # on a fixed schedule, unlike the FIPS refresh which only fires
            # when an alert happens to arrive.
            _install_dead_air_criteria(app)
        except Exception as exc:
            logger.debug("Dead-air criteria refresh failed: %s", exc)

        try:
            # Look up which sources should be running.  This query MUST run
            # inside a Flask app context — the previous inline implementation
            # ran it without one, so Flask-SQLAlchemy raised on every cycle,
            # the exception was silently swallowed, auto_start_names stayed
            # empty forever, and STOPPED auto-start sources were never
            # restarted.
            auto_start_names = set()
            try:
                from app_core.models import AudioSourceConfigDB
                with app.app_context():
                    auto_start_names = {
                        cfg.name
                        for cfg in AudioSourceConfigDB.query.all()
                        if cfg.enabled and cfg.auto_start
                    }
            except Exception as exc:
                logger.warning("Source watchdog: could not load auto-start config: %s", exc)

            for source_name, source_adapter in audio_controller.get_all_sources().items():
                try:
                    if source_adapter.status == AudioSourceStatus.ERROR:
                        if source_adapter.is_quarantined():
                            continue
                        logger.warning(
                            f"Source watchdog: '{source_name}' is in ERROR state – "
                            f"attempting automatic restart"
                        )

                        def _recover(adapter=source_adapter, name=source_name):
                            adapter.stop()
                            time.sleep(0.5)
                            if adapter.start():
                                logger.info(f"Source watchdog: ✅ restarted '{name}' successfully")
                            else:
                                logger.warning(f"Source watchdog: ⚠️ restart of '{name}' returned False")

                        audio_controller.spawn_recovery(source_name, _recover, "watchdog ERROR restart")

                    elif (
                        source_adapter.status == AudioSourceStatus.STOPPED
                        and source_name in auto_start_names
                    ):
                        logger.warning(
                            f"Source watchdog: '{source_name}' is STOPPED but has "
                            f"auto_start=True – restarting"
                        )

                        def _autostart(adapter=source_adapter, name=source_name):
                            if adapter.start():
                                logger.info(f"Source watchdog: ✅ auto-restarted '{name}'")
                            else:
                                logger.warning(f"Source watchdog: ⚠️ auto-restart of '{name}' returned False")

                        audio_controller.spawn_recovery(source_name, _autostart, "watchdog auto-start")

                except Exception as exc:
                    logger.error(
                        f"Source watchdog: ❌ error evaluating '{source_name}': {exc}",
                        exc_info=True,
                    )

        except Exception as exc:
            logger.error("Source watchdog loop error: %s", exc, exc_info=True)

    logger.info("Source watchdog stopped")


def initialize_eas_monitor(app, audio_controller):
    """Initialize EAS monitoring system with unified monitor service.
    
    V3 ARCHITECTURE: Single-threaded unified monitor that replaces the previous
    multi-monitor architecture. Benefits:
    - 1 thread instead of N threads (reduced CPU/memory)
    - Auto-discovery of sources (no manual add/remove)
    - Centralized health tracking
    - No status aggregation overhead
    
    The UnifiedEASMonitorService automatically discovers and monitors all running
    audio sources in a single monitoring thread.
    """
    global _eas_monitor

    with app.app_context():
        from app_core.audio.eas_monitor_v3 import UnifiedEASMonitorService
        from app_core.audio.eas_monitor import create_fips_filtering_callback
        from app_core.audio.startup_integration import load_fips_codes_from_config

        logger.info("Initializing unified EAS monitor service (V3 architecture)...")

        # Install station-wide dead-air criteria before any source starts,
        # so monitors are built already configured rather than defaulting
        # to disabled until the first settings refresh.
        _install_dead_air_criteria(app)

        # Load FIPS codes into a mutable list so in-place updates are reflected
        # in the FIPS-filtering callback without rebuilding it.
        _live_fips: list = load_fips_codes_from_config()
        logger.info(f"Loaded {len(_live_fips)} FIPS codes for alert filtering")

        # Refresh state: reload configured FIPS codes from the database every
        # 60 seconds so that changes made via the admin UI take effect without
        # requiring a full service restart.  Uses a single-element dict so the
        # timestamp can be mutated inside a nested function without 'nonlocal'.
        _fips_refresh = {'last_loaded': time.time()}
        _FIPS_REFRESH_SECS = 60

        # Create alert callback with filtering.
        # forward_alert_handler runs inside the EAS monitor thread which has no
        # Flask application context.  Pushing an app context here (as the
        # _make_metadata_log_callback helper does) lets forward_alert_to_api
        # reach Flask-SQLAlchemy and the air-chain broadcast pipeline.
        def forward_alert_handler(alert):
            """Forward matched alerts to API and air chain broadcast."""
            from app_core.audio.alert_forwarding import forward_alert_to_api
            source_name = alert.get('source_name', 'unknown')
            event_code = alert.get('event_code', 'UNKNOWN')
            location_codes = alert.get('location_codes', [])
            logger.info(
                f"Forwarding alert from source '{source_name}': "
                f"{event_code} for {location_codes}"
            )
            return forward_alert_to_api(alert)

        # The FIPS-filtering callback calls forward_alert_handler AND then
        # _store_received_alert, both of which need Flask context.  Wrap the
        # whole callback so _store_received_alert also runs inside a context.
        # Pass _live_fips by reference — determine_fips_matches() iterates it
        # on every call, so in-place updates are picked up automatically.
        _alert_callback_inner = create_fips_filtering_callback(
            configured_fips_codes=_live_fips,
            forward_callback=forward_alert_handler,
            logger_instance=logger
        )

        def alert_callback(alert):
            with app.app_context():
                # Periodically refresh FIPS codes from the database so that
                # counties added or removed via the admin UI take effect within
                # one refresh cycle without requiring a service restart.
                now = time.time()
                if now - _fips_refresh['last_loaded'] >= _FIPS_REFRESH_SECS:
                    try:
                        fresh = load_fips_codes_from_config()
                        if set(fresh) != set(_live_fips):
                            logger.info(
                                "FIPS filter updated: %d configured codes (was %d) — "
                                "new: %s",
                                len(fresh),
                                len(_live_fips),
                                sorted(set(fresh) - set(_live_fips)) or '(none)',
                            )
                            _live_fips.clear()
                            _live_fips.extend(fresh)
                    except Exception as _exc:
                        logger.warning(
                            "FIPS code refresh failed, keeping %d cached codes: %s",
                            len(_live_fips), _exc,
                        )
                    _fips_refresh['last_loaded'] = now
                return _alert_callback_inner(alert)


        # Create unified monitor service (replaces MultiMonitorManager)
        _eas_monitor = UnifiedEASMonitorService(
            audio_controller=audio_controller,
            alert_callback=alert_callback,
            configured_fips_codes=_live_fips,
            discovery_interval_seconds=5.0,  # Check for new/removed sources every 5s
            chunk_duration_ms=100  # 100ms chunks at 16kHz
        )

        # Start unified monitor (auto-discovers sources)
        if _eas_monitor.start():
            logger.info("✅ UnifiedEASMonitorService started successfully")
        else:
            logger.error("❌ UnifiedEASMonitorService failed to start")

        return _eas_monitor


def _install_dead_air_criteria(app) -> None:
    """Retune every source's dead-air monitor from its own per-source config.

    Called at startup and on a fixed watchdog interval (see the source
    watchdog loop above), so an operator's change in the audio source
    editor takes effect without a service restart -- same as it always
    did, just per source now instead of one station-wide policy applied
    to everyone. See AudioSourceConfig.dead_air_* in app_core/audio/ingest.py
    for why a single shared policy doesn't fit: a source that's supposed
    to be silent except when relaying an actual alert (a state relay, an
    alert-only feed) must never alarm on silence, while a continuous
    broadcast monitor going silent is a real fault -- one shared enabled
    flag cannot express both at once.

    ``app`` is accepted for signature compatibility with the pre-per-source
    version; per-source criteria come from each adapter's own in-memory
    config, so no app context / DB round trip is needed here.
    """
    try:
        from app_core.audio.silence import (
            SilenceCriteria,
            criteria_from_source_config,
            set_default_criteria,
        )

        # Brand new sources are constructed with SilenceMonitor(name) (no
        # explicit criteria), which falls back to this module-level
        # default until this function retunes them below. Keep it
        # disabled so a source never briefly alarms on a policy it
        # hasn't actually been given.
        set_default_criteria(SilenceCriteria(enabled=False))

        if _audio_controller is None:
            return

        enabled_count = 0
        for source in _audio_controller.get_all_sources().values():
            monitor = getattr(source, "_silence_monitor", None)
            if monitor is None:
                continue
            criteria = criteria_from_source_config(source.config)
            monitor.update_criteria(criteria)
            if criteria.enabled:
                enabled_count += 1

        logger.info(
            "Dead-air monitoring retuned: %d of %d source(s) have it enabled",
            enabled_count, len(_audio_controller.get_all_sources()),
        )
    except Exception as exc:
        logger.warning("Could not install dead-air criteria: %s", exc)


#: Identifier for the current continuous dead-air episode, or None when no
#: source is silent. See _publish_dead_air_state().
_dead_air_episode: Optional[str] = None


def _publish_dead_air_state(sources: Dict[str, Any]) -> None:
    """Publish the aggregate dead-air state for the GPIO indicator service.

    Aggregates every source's debounced monitor into one flag plus a
    per-source breakdown, so the tower light and rack buzzer can be driven
    without the GPIO process knowing anything about audio internals.

    The key carries a short TTL. If this service dies the key expires and
    the GPIO side stops asserting the alarm, which is the safe direction:
    a buzzer stuck on because a publisher vanished is worse than a missed
    indication, and audio-service liveness already has its own monitoring.
    """
    from app_core.config.redis_config import RedisChannels

    global _dead_air_episode

    silent_sources = {}
    any_enabled = False
    for name, stats in (sources or {}).items():
        meta = (stats or {}).get("metadata") or {}
        dead_air = meta.get("dead_air") or {}
        if not dead_air.get("enabled"):
            continue
        any_enabled = True
        if dead_air.get("silent"):
            silent_sources[name] = {
                "reason": dead_air.get("reason"),
                "detail": dead_air.get("detail"),
                "duration_seconds": dead_air.get("silence_duration_seconds"),
            }

    # Episode id: a token minted when the alarm goes active and held for
    # the whole continuous outage. The acknowledgement is stored as this
    # value, so an ack from an earlier outage cannot mute a later one --
    # without it a stale ack would sit in Redis for its TTL and silence the
    # next genuine failure.
    if silent_sources:
        if not _dead_air_episode:
            _dead_air_episode = uuid.uuid4().hex[:12]
    else:
        _dead_air_episode = None

    payload = {
        "active": bool(silent_sources),
        "enabled": any_enabled,
        "sources": silent_sources,
        "episode": _dead_air_episode,
        "updated": time.time(),
    }

    client = get_redis_client()
    client.setex(
        RedisChannels.DEAD_AIR_KEY,
        RedisChannels.DEAD_AIR_TTL_SECONDS,
        json.dumps(payload),
    )
    # Clear a stale acknowledgement once audio is back, so the next
    # outage sounds the buzzer instead of starting pre-silenced.
    if not silent_sources:
        try:
            client.delete(RedisChannels.DEAD_AIR_ACK_KEY)
        except Exception:
            pass


def collect_metrics():
    """Collect metrics from audio controller, radio manager, and EAS monitor."""
    metrics = {
        "audio_controller": None,
        "eas_monitor": None,
        "broadcast_queue": None,
        "radio_manager": None,  # Add radio manager metrics for web application process
        "timestamp": time.time()
    }

    try:
        # Radio manager stats are now collected by sdr-service.py
        # audio-service.py does NOT access SDR hardware
        metrics["radio_manager"] = None  # Will be published by sdr-service if needed
        
        # Get audio controller stats
        if _audio_controller:
            controller_stats: Dict[str, Any] = {
                "sources": {},
                "active_source": _audio_controller._active_source,
            }

            streaming_status: Optional[Dict[str, Any]] = None
            active_streams: Dict[str, Any] = {}

            # Include Icecast streaming stats so the UI can show bitrate, mount, metadata, etc.
            if _auto_streaming_service:
                try:
                    streaming_status = _auto_streaming_service.get_status()
                    active_streams = streaming_status.get("active_streams", {}) if streaming_status else {}
                    controller_stats["streaming"] = _sanitize_value(streaming_status)
                except Exception as e:
                    logger.error(f"Error getting streaming stats: {e}")

            for name, source in _audio_controller.get_all_sources().items():
                try:
                    metrics_obj = getattr(source, "metrics", None)
                    source_stats: Dict[str, Any] = {
                        "status": source.status.value if hasattr(source.status, "value") else str(source.status),
                        "sample_rate": _sanitize_value(getattr(metrics_obj, "sample_rate", getattr(source, "sample_rate", None))),
                        "channels": _sanitize_value(getattr(metrics_obj, "channels", getattr(source, "channels", None))),
                        "frames_captured": _sanitize_value(getattr(metrics_obj, "frames_captured", None)),
                        "peak_level_db": _sanitize_value(getattr(metrics_obj, "peak_level_db", None)),
                        "rms_level_db": _sanitize_value(getattr(metrics_obj, "rms_level_db", None)),
                        "buffer_utilization": _sanitize_value(getattr(metrics_obj, "buffer_utilization", None)),
                        "silence_detected": bool(getattr(metrics_obj, "silence_detected", False)),
                        "timestamp": _sanitize_value(getattr(metrics_obj, "timestamp", None)),
                        "metadata": _sanitize_value(getattr(metrics_obj, "metadata", None)),
                        "error_message": _sanitize_value(getattr(source, "error_message", None)),
                    }

                    if hasattr(source, "config"):
                        source_stats["config"] = _sanitize_value({
                            "sample_rate": getattr(source.config, "sample_rate", None),
                            "channels": getattr(source.config, "channels", None),
                            "buffer_size": getattr(source.config, "buffer_size", None),
                        })

                    if active_streams and name in active_streams:
                        # Provide per-source streaming stats (includes bitrate, mount, metadata)
                        source_stats["streaming"] = {"icecast": _sanitize_value(active_streams[name])}

                    controller_stats["sources"][name] = source_stats
                except Exception as e:
                    logger.error(f"Error getting source stats for '{name}': {e}")

            metrics["audio_controller"] = controller_stats

            # Publish a compact dead-air summary for the GPIO service.
            # Kept separate from the metrics hash because the GPIO process
            # needs one small, cheap read on every indicator refresh and
            # should not have to parse the whole flattened metrics blob.
            try:
                _publish_dead_air_state(controller_stats.get("sources", {}))
            except Exception as exc:
                logger.debug("Failed to publish dead-air state: %s", exc)

            # Get broadcast queue stats from all sources
            # Note: Each source has its own broadcast queue (architecture change)
            try:
                broadcast_queues = {}
                for name, source in _audio_controller.get_all_sources().items():
                    if hasattr(source, 'get_broadcast_queue'):
                        bq = source.get_broadcast_queue()
                        if bq:
                            broadcast_queues[name] = _sanitize_value(bq.get_stats())
                
                if broadcast_queues:
                    metrics["broadcast_queue"] = broadcast_queues
            except Exception as e:
                logger.error(f"Error getting broadcast queue stats: {e}")

        # Get EAS monitor stats (supports both single and multi-monitor)
        if _eas_monitor:
            try:
                metrics["eas_monitor"] = _sanitize_value(_eas_monitor.get_status())
            except Exception as e:
                logger.error(f"Error getting EAS monitor stats: {e}")
                metrics["eas_monitor"] = {"running": False, "error": str(e)}

    except Exception as e:
        logger.error(f"Error collecting metrics: {e}")

    return metrics


#: Tracks the alert label currently applied to every Icecast stream's
#: metadata, so _reconcile_broadcast_metadata() only calls
#: set_alert_metadata()/clear_alert_metadata() on an actual transition
#: rather than every 0.25s tick. None means "no override applied".
_applied_broadcast_metadata_label = None


def _reconcile_broadcast_metadata() -> None:
    """Mirror the on-air broadcast marker onto every Icecast stream's title.

    Every broadcast path in this project -- manual Send (webapp/eas/
    workflow.py), RWT (app_core/rwt_scheduler.py), resend (scripts/
    resend_eas_broadcast.py), and live auto-forward (app_core/audio/
    auto_forward.py via EASBroadcaster.handle_alert() in app_utils/eas.py)
    -- already calls set_broadcast_active()/clear_broadcast_active() to key
    the GPIO relay and drive the countdown overlay. That marker already
    carries a human-readable ``label`` for exactly this purpose. Polling it
    here (from the one process that actually owns the live IcecastStreamer
    objects) means every current and future broadcast path gets its stream
    metadata overridden with the alert text automatically -- no per-caller
    wiring needed, unlike the old approach where only auto_forward.py
    called app_core.audio.alert_metadata directly (and could only do so
    because it happens to run in this same process; RWT/manual-send/resend
    run in the web process or a standalone script, where that call would
    silently no-op -- alert_metadata's target is a module-level singleton
    that only exists inside this process).

    Called from the main loop's existing ~4 Hz tick (see metrics_interval
    below) rather than its own thread/pub-sub subscription -- get_broadcast_
    state() is one cheap Redis GET, so riding the loop that's already
    ticking at this cadence is simpler than adding a second listener.
    """
    global _applied_broadcast_metadata_label
    try:
        from app_core.audio.alert_metadata import clear_alert_metadata, set_alert_metadata
        from app_utils.eas import get_broadcast_state

        state = get_broadcast_state() or {}
        if state.get('active'):
            label = (state.get('label') or state.get('event_code') or 'EAS Alert').strip()
            if label and label != _applied_broadcast_metadata_label:
                set_alert_metadata(label)
                _applied_broadcast_metadata_label = label
        elif _applied_broadcast_metadata_label is not None:
            clear_alert_metadata()
            _applied_broadcast_metadata_label = None
    except Exception as exc:
        logger.debug("Broadcast metadata reconcile failed: %s", exc)


def publish_metrics_to_redis(metrics):
    """Publish metrics to Redis for web application.

    Uses HSET (merge) instead of DELETE+HSET so the key is never momentarily
    absent between the two pipeline steps.  Deep-sanitizes every value before
    JSON serialisation so that inf/nan/numpy types never cause a silent failure
    that would leave the key absent and the web-app thinking the service is
    down.
    """
    try:
        r = get_redis_client()

        # Add heartbeat timestamp and process ID (required by web application)
        metrics["_heartbeat"] = time.time()
        metrics["_master_pid"] = os.getpid()

        # Deep-sanitize the whole metrics tree so json.dumps() can never throw.
        # _sanitize_value() handles inf, nan, numpy scalars and nested dicts/lists.
        sanitized = _sanitize_value(metrics)

        # Flatten one level: nested dicts/lists → JSON strings, scalars → str.
        flat_metrics = {}
        for key, value in sanitized.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                try:
                    flat_metrics[key] = json.dumps(value)
                except Exception as json_err:
                    logger.debug("Skipping metric '%s' – not JSON serialisable: %s", key, json_err)
            else:
                flat_metrics[key] = str(value)

        if not flat_metrics:
            logger.warning("publish_metrics_to_redis: nothing to publish after sanitisation")
            return

        # Use HSET merge (no DELETE) so the key is never temporarily absent.
        # Reset TTL on each write; 120 s gives headroom for transient hiccups.
        pipe = r.pipeline()
        pipe.hset("eas:metrics", mapping=flat_metrics)
        pipe.expire("eas:metrics", 120)
        pipe.execute()

        # Notify real-time subscribers
        r.publish("eas:metrics:update", "1")

    except Exception as e:
        logger.error(f"Error publishing metrics to Redis: {e}")


def main():
    """Main service loop."""
    global _running, _audio_controller

    logger.info("=" * 80)
    logger.info("EAS Station - Standalone Audio Processing Service")
    logger.info("=" * 80)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Initialize Redis
        logger.info("Connecting to Redis...")
        r = get_redis_client()

        # Initialize database
        logger.info("Initializing database connection...")
        app = initialize_database()

        # Ensure the raw_audio_data column exists on received_eas_alerts.
        # This column was added in migration 20260325; if the migration has
        # not been applied yet the column is absent and _store_received_alert
        # fails on every OTA decode, silently losing all received-alert records.
        _ensure_raw_audio_column(app)

        # CRITICAL: Do NOT initialize RadioManager here!
        # In separated architecture, sdr-service.py handles SDR hardware access.
        # This service (audio-service) only subscribes to Redis channels for IQ samples.
        # The sync_radio_receiver_audio_sources() function will create AudioSourceConfigDB
        # entries that trigger RedisSDRSourceAdapter creation (which subscribes to Redis).
        logger.info("Skipping RadioManager initialization - using separated architecture")
        logger.info("SDR hardware is managed by SDR hardware service process")
        logger.info("This service will subscribe to Redis channels for IQ samples")

        # Initialize audio controller
        logger.info("Initializing audio controller...")
        try:
            audio_controller = initialize_audio_controller(app)
        except Exception as ctrl_exc:
            logger.error("initialize_audio_controller raised an exception: %s", ctrl_exc, exc_info=True)
            audio_controller = None
        _audio_controller = audio_controller  # Store globally for command subscriber

        # Register the controller with the EAS stream injector so that
        # inject_eas_audio() can push generated alert audio into the
        # Icecast broadcast queues running in this process.
        if audio_controller:
            try:
                from app_core.audio import eas_stream_injector
                eas_stream_injector.set_controller(audio_controller)
                logger.info("EAS stream injector: controller registered")
            except Exception as _inj_exc:
                logger.warning("Failed to register EAS stream injector controller: %s", _inj_exc)

        if not audio_controller:
            logger.error("Failed to initialize audio controller — cannot continue")
            return 1

        # Initialize Icecast auto-streaming
        logger.info("Initializing Icecast auto-streaming...")
        auto_streaming = initialize_auto_streaming(app, audio_controller)

        # Add all RUNNING audio sources to Icecast streaming
        if auto_streaming and audio_controller:
            from app_core.audio.ingest import AudioSourceStatus

            logger.info("Checking audio sources for Icecast streaming...")

            # Log status of all sources for diagnostics
            total_sources = len(audio_controller.get_all_sources())
            logger.info(f"Total configured sources: {total_sources}")

            for source_name, source_adapter in audio_controller.get_all_sources().items():
                status_str = source_adapter.status.name if hasattr(source_adapter.status, 'name') else str(source_adapter.status)
                logger.info(f"Source '{source_name}' status: {status_str}")

                if source_adapter.status == AudioSourceStatus.ERROR:
                    error_msg = source_adapter.error_message or "Unknown error"
                    logger.error(f"❌ Source '{source_name}' failed to start: {error_msg}")
                    continue

                # Only add sources that are actually running
                if source_adapter.status != AudioSourceStatus.RUNNING:
                    logger.warning(f"⚠️ Skipping '{source_name}' - not running (status: {status_str})")
                    continue

                try:
                    if auto_streaming.add_source(source_name, source_adapter):
                        logger.info(f"✅ Added source '{source_name}' to Icecast streaming")
                    else:
                        logger.warning(f"⚠️ Failed to add '{source_name}' to Icecast streaming")
                except Exception as e:
                    logger.error(f"❌ Error adding '{source_name}' to Icecast: {e}", exc_info=True)

        # Initialize audio archivers for sources that have archiving enabled
        logger.info("Initializing audio archivers...")
        initialize_archivers(app, audio_controller)

        # Attach metadata-logging callback to every source (current and future)
        # so now-playing changes are persisted to stream_metadata_log
        metadata_log_callback = _make_metadata_log_callback(app)
        audio_controller.set_metadata_change_callback(metadata_log_callback)
        logger.info("Stream metadata logging callbacks registered")

        # Attach audio-alert callback so stall/error/disconnect events are
        # persisted to the audio_alerts table (shown in Logs → Audio tab)
        audio_alert_callback = _make_audio_alert_log_callback(app)
        audio_controller.set_source_alert_callback(audio_alert_callback)
        logger.info("Audio alert logging callbacks registered")

        # Build the ~1 Hz AudioSourceMetrics snapshot writer used by the main
        # loop below (RBDS/BLER history and the audio-health aggregator read
        # this table; see _make_audio_metrics_snapshot_writer for why it
        # didn't exist before).
        snapshot_audio_metrics = _make_audio_metrics_snapshot_writer(app)

        # Initialize EAS monitor
        logger.info("Initializing EAS monitor...")
        try:
            eas_monitor = initialize_eas_monitor(app, audio_controller)
        except Exception as eas_exc:
            logger.error("initialize_eas_monitor raised an exception: %s", eas_exc, exc_info=True)
            eas_monitor = None

        # Start the gated-alerts release scheduler (OTA path).  Releases
        # pending gated alerts once their hold-off timer expires; a no-op
        # sweep when the gated-alerts feature is disabled or no alerts are
        # pending.  Must run in this process (has a Flask app + owns the
        # OTA auto-forward path) -- never in the Gunicorn web app.
        try:
            from app_core.gating_scheduler import start_scheduler as start_gating_scheduler
            start_gating_scheduler(app)
            logger.info("✅ Gated-alerts release scheduler started")
        except Exception as gating_sched_exc:
            logger.warning("Gated-alerts release scheduler could not be started: %s", gating_sched_exc)

        if not eas_monitor:
            logger.error("Failed to initialize EAS monitor")
            return 1

        # Initialize Redis Pub/Sub command subscriber
        logger.info("Starting Redis command subscriber...")
        command_subscriber = None
        subscriber_thread = None
        try:
            from app_core.audio.redis_commands import AudioCommandSubscriber

            command_subscriber = AudioCommandSubscriber(
                audio_controller, auto_streaming, eas_monitor,
                archiver_registry=_archivers, app=app,
            )

            # Start subscriber in background thread
            subscriber_thread = threading.Thread(
                target=command_subscriber.start,
                daemon=True,
                name="RedisCommandSubscriber"
            )
            subscriber_thread.start()
            logger.info("✅ Redis command subscriber started")
        except Exception as e:
            logger.warning(f"Failed to start command subscriber: {e}")
            logger.warning("   Audio control commands from app will not work")
            # Continue - metrics publishing still works

        # Start HTTP streaming server for VU meter support
        logger.info("Starting HTTP streaming server...")
        streaming_server_thread = None
        try:
            from flask import Flask, Response, stream_with_context, jsonify
            from werkzeug.serving import make_server
            
            # Create Flask app for streaming endpoints
            stream_app = Flask(__name__)
            
            @stream_app.route('/api/audio/stream/<source_name>')
            def stream_audio(source_name):
                """Stream live audio for web browser playback using uncompressed WAV.
                
                Streams uncompressed WAV at native sample rate (~705 kbps for 44.1kHz mono).
                WAV format is used for maximum compatibility and reliability.
                
                Args:
                    source_name: Name of the audio source to stream
                
                Returns:
                    Response: Streaming WAV audio
                """
                import struct
                import io
                import numpy as np
                import queue as queue_module
                from app_core.audio.ingest import AudioSourceStatus
                
                def generate_wav_stream(adapter, source_name):
                    """Generator that yields WAV chunks at native sample rate.

                    Uses BroadcastQueue subscription to avoid competing with other audio consumers
                    (Icecast, EAS monitor, etc). Each subscriber gets independent copy of all audio chunks.
                    
                    No resampling is performed - audio is passed through at native rate to ensure
                    accurate pitch and playback speed.
                    """
                    # For StreamSourceAdapter with preserve_native_rate=True, FFmpeg runs
                    # without -ar and outputs at the stream's actual sample rate.  The
                    # actual rate is detected from FFmpeg's stderr output in a background
                    # thread (_stderr_pump) which then updates config.sample_rate and
                    # metrics.sample_rate.  That detection happens *before* the first
                    # audio packet reaches _read_audio_chunk, so waiting until
                    # _last_connection_time is set (i.e. the first audio packet has
                    # arrived) guarantees the rate is already correct.
                    #
                    # Without this wait, a freshly-started source (e.g. configured as
                    # 44100 Hz but actually streaming at 48000 Hz) would cause the WAV
                    # header to be written with the wrong rate.  The browser would then
                    # play 48000 Hz audio as if it were 44100 Hz — about 91.9% speed —
                    # making 10 minutes of audio take ~11 minutes.
                    if hasattr(adapter, '_last_connection_time'):  # StreamSourceAdapter
                        deadline = time.time() + 5.0
                        while time.time() < deadline and adapter._last_connection_time is None:
                            time.sleep(0.05)

                    # Source configuration — prefer metrics.sample_rate which is
                    # updated asynchronously when the stream's native rate is
                    # detected by FFmpeg.  config.sample_rate is also updated but
                    # checking both provides a safety net.
                    source_sample_rate = adapter.config.sample_rate
                    if hasattr(adapter, 'metrics') and getattr(adapter.metrics, 'sample_rate', 0) > 0:
                        source_sample_rate = adapter.metrics.sample_rate
                    stream_sample_rate = source_sample_rate  # Use native source rate
                    stream_channels = 1  # Mono saves 50% bandwidth
                    bits_per_sample = 16

                    # Validate source sample rate
                    if source_sample_rate <= 0:
                        logger.error(f"Invalid source sample rate: {source_sample_rate} Hz. Using 44100 Hz as fallback.")
                        source_sample_rate = 44100
                        stream_sample_rate = 44100
                    
                    logger.debug(
                        f"Web stream for {source_name}: {stream_sample_rate}Hz (native rate, no resampling)"
                    )

                    # Subscribe to BroadcastQueue for non-competitive audio access
                    subscriber_id = f"web-stream-{source_name}-{threading.current_thread().ident}"
                    if not (hasattr(adapter, 'get_broadcast_queue') and callable(getattr(adapter, 'get_broadcast_queue', None))):
                        logger.error(f"Audio source '{source_name}' does not support broadcast queue")
                        raise RuntimeError(f'Audio source "{source_name}" does not support streaming')
                    
                    broadcast_queue = adapter.get_broadcast_queue()
                    subscription_queue = broadcast_queue.subscribe(subscriber_id)

                    try:
                        # Send WAV header
                        wav_header = io.BytesIO()
                        wav_header.write(b'RIFF')
                        wav_header.write(struct.pack('<I', 0xFFFFFFFF))
                        wav_header.write(b'WAVE')
                        wav_header.write(b'fmt ')
                        wav_header.write(struct.pack('<I', 16))
                        wav_header.write(struct.pack('<H', 1))  # PCM
                        wav_header.write(struct.pack('<H', stream_channels))
                        wav_header.write(struct.pack('<I', stream_sample_rate))
                        wav_header.write(struct.pack('<I', stream_sample_rate * stream_channels * bits_per_sample // 8))
                        wav_header.write(struct.pack('<H', stream_channels * bits_per_sample // 8))
                        wav_header.write(struct.pack('<H', bits_per_sample))
                        wav_header.write(b'data')
                        wav_header.write(struct.pack('<I', 0xFFFFFFFF))
                        yield wav_header.getvalue()

                        # Stream audio chunks.
                        #
                        # STUTTER FIX: the old loop yielded a 50 ms block of zeros on
                        # EVERY 200 ms queue timeout and every None chunk.  Chunks
                        # arrive at ~100 ms cadence, so ordinary scheduling/network
                        # jitter spliced silence into the middle of continuous audio
                        # several times a minute (audible stutter) while the real
                        # chunk played AFTER the injected gap — and every injection
                        # pushed the stream permanently further behind live.  Now
                        # transient jitter emits nothing (the browser just waits a
                        # few ms); keep-alive silence is emitted only when the
                        # source has been genuinely quiet for several seconds.
                        from app_core.audio.stream_keepalive import KeepAliveGate
                        keepalive = KeepAliveGate(quiet_seconds=2.0)
                        # Keep-alive silence is paced to the 200 ms read timeout so
                        # a dead source streams silence at roughly real time.
                        keepalive_samples = int(stream_sample_rate * stream_channels * 0.2)

                        logger.debug(f"Web stream '{subscriber_id}' started, subscribed to broadcast queue")

                        while _running:
                            try:
                                # Read from subscription queue (non-competitive)
                                audio_chunk = subscription_queue.get(timeout=0.2)
                                if audio_chunk is None:
                                    continue

                                if not isinstance(audio_chunk, np.ndarray):
                                    audio_chunk = np.array(audio_chunk, dtype=np.float32)

                                # Detect actual audio format (mono 1D array vs stereo 2D array)
                                if audio_chunk.ndim == 2 and stream_channels == 1:
                                    # True stereo (Nx2 array) - mix to mono
                                    audio_chunk = np.mean(audio_chunk, axis=1)
                                elif audio_chunk.ndim == 1:
                                    # Already mono - no conversion needed
                                    pass
                                else:
                                    # Unexpected format - flatten to mono
                                    audio_chunk = audio_chunk.flatten()

                                # Convert to int16 PCM (no resampling - use native sample rate)
                                pcm_data = (np.clip(audio_chunk, -1.0, 1.0) * 32767).astype(np.int16)
                                keepalive.audio_received()
                                yield pcm_data.tobytes()

                            except queue_module.Empty:
                                # Late chunk (jitter): emit nothing — never splice
                                # silence into continuous audio.  Only a source that
                                # has been quiet for seconds gets keep-alive silence.
                                if keepalive.should_emit_silence():
                                    yield np.zeros(keepalive_samples, dtype=np.int16).tobytes()
                            except Exception as e:
                                logger.debug(f"Error in stream generator: {e}")
                                time.sleep(0.05)
                    finally:
                        # Unsubscribe when client disconnects
                        broadcast_queue.unsubscribe(subscriber_id)
                        logger.debug(f"Web stream '{subscriber_id}' ended, unsubscribed from broadcast queue")
                
                try:
                    if not _audio_controller:
                        return jsonify({'error': 'Audio controller not initialized'}), 503
                    
                    adapter = _audio_controller.get_source(source_name)
                    if not adapter:
                        return jsonify({'error': f'Audio source "{source_name}" not found'}), 404
                    
                    if adapter.status != AudioSourceStatus.RUNNING:
                        return jsonify({
                            'error': f'Audio source "{source_name}" is not running',
                            'status': adapter.status.value
                        }), 503
                    
                    return Response(
                        stream_with_context(generate_wav_stream(adapter, source_name)),
                        mimetype='audio/wav',
                        headers={
                            'Content-Disposition': f'inline; filename="{source_name}.wav"',
                            'Cache-Control': 'no-cache, no-store, must-revalidate',
                            'Pragma': 'no-cache',
                            'Expires': '0',
                            'X-Content-Type-Options': 'nosniff',
                            'Access-Control-Allow-Origin': '*',
                            'Accept-Ranges': 'none',
                            'Connection': 'keep-alive',
                        }
                    )
                except Exception as exc:
                    logger.error(f'Error setting up audio stream for {source_name}: {exc}')
                    return jsonify({'error': str(exc)}), 500
            
            @stream_app.route('/api/eas/decoder-stream')
            def stream_eas_decoder():
                """Stream the actual 16kHz audio being fed to the EAS decoder.

                This endpoint allows users to listen to exactly what the EAS decoder processes,
                which is critical for debugging detection issues. The audio is resampled to 16kHz
                for decoder CPU efficiency.

                Returns:
                    Response: Streaming MP3 audio at 16kHz (what the decoder actually sees).
                    MP3 (audio/mpeg) is used because streaming WAV with unknown file sizes is
                    not supported by Safari on iOS.
                """
                import queue as queue_module
                import numpy as np

                if not _audio_controller:
                    logger.error("Audio controller not initialized")
                    return jsonify({'error': 'Audio controller not initialized'}), 503

                # Collect every running source that exposes an EAS broadcast queue.
                # Primary: use every source the EAS monitor is actively watching.
                # Fallback: scan all RUNNING sources when the monitor hasn't discovered any yet
                #   (discovery runs every 5 seconds; sources may already be running at connect time).
                from app_core.audio.ingest import AudioSourceStatus
                source_broadcast_queues = {}  # {source_name: BroadcastQueue}

                if _eas_monitor:
                    status = _eas_monitor.get_status()
                    if status and status.get('monitors'):
                        for s_name in status['monitors']:
                            _adapter = _audio_controller.get_source(s_name)
                            if (
                                _adapter
                                and _adapter.status == AudioSourceStatus.RUNNING
                                and hasattr(_adapter, 'get_eas_broadcast_queue')
                                and callable(getattr(_adapter, 'get_eas_broadcast_queue', None))
                            ):
                                source_broadcast_queues[s_name] = _adapter.get_eas_broadcast_queue()

                if not source_broadcast_queues:
                    for _name, _adapter in _audio_controller.get_all_sources().items():
                        if (
                            _adapter.status == AudioSourceStatus.RUNNING
                            and hasattr(_adapter, 'get_eas_broadcast_queue')
                            and callable(getattr(_adapter, 'get_eas_broadcast_queue', None))
                        ):
                            source_broadcast_queues[_name] = _adapter.get_eas_broadcast_queue()
                    if source_broadcast_queues:
                        logger.info(
                            f"EAS decoder stream: EAS monitor has no active watchers yet; "
                            f"falling back to running sources {list(source_broadcast_queues)}"
                        )

                if not source_broadcast_queues:
                    logger.error("No running audio sources available for EAS decoder stream")
                    return jsonify({
                        'error': (
                            'No running audio sources available. '
                            'Start an audio source to enable the EAS decoder stream.'
                        )
                    }), 503

                # Pre-flight the encoder while we can still choose a status code.
                # The generator below cannot: once Response() starts streaming the
                # headers are already sent, so a missing ffmpeg simply ended the
                # generator and the browser received "200 OK" with an empty body.
                # The player reported a generic media error and the UI blamed the
                # audio source — the one thing that was not wrong.
                import shutil as _shutil

                if _shutil.which('ffmpeg') is None:
                    logger.error("ffmpeg not found; cannot stream EAS decoder audio")
                    return jsonify({
                        'error': (
                            'ffmpeg is not installed on the server, so the decoder '
                            'feed cannot be encoded. Install ffmpeg and restart the '
                            'audio service.'
                        )
                    }), 503

                def generate_eas_decoder_mp3():
                    """Stream all active EAS decoder sources mixed together as MP3.

                    Subscribes to every running source's 16kHz EAS broadcast queue and
                    mixes them into a single stream so the listener hears all sources at
                    once.  Uses ffmpeg to encode the mixed PCM to MP3 for broad browser
                    compatibility (including Safari on iOS).

                    The generator seeds ffmpeg with ~200 ms of silence before pulling
                    from the queues.  This ensures the first MP3 frame is available
                    before the browser's play() call times out.
                    """
                    import subprocess as _subprocess

                    stream_sample_rate = 16000  # EAS decoder always uses 16kHz
                    stream_channels = 1
                    silence_duration = 0.1  # 100 ms — matches chunk cadence
                    silence_samples = int(stream_sample_rate * stream_channels * silence_duration)
                    silence_pcm = np.zeros(silence_samples, dtype=np.int16).tobytes()

                    tid = threading.current_thread().ident

                    # Subscribe to every source before starting ffmpeg so cleanup is always possible.
                    subscriptions = {}  # {source_name: (BroadcastQueue, Queue)}
                    for s_name, bq in source_broadcast_queues.items():
                        sub_id = f"eas-decoder-stream-{tid}-{s_name}"
                        subscriptions[s_name] = (bq, bq.subscribe(sub_id))

                    subscription_items = list(subscriptions.values())  # [(bq, q), ...]

                    ffmpeg_proc = None
                    feeder = None
                    try:
                        try:
                            ffmpeg_proc = _subprocess.Popen(
                                [
                                    'ffmpeg', '-loglevel', 'error',
                                    '-f', 's16le',
                                    '-ar', str(stream_sample_rate),
                                    '-ac', str(stream_channels),
                                    '-i', 'pipe:0',
                                    '-c:a', 'libmp3lame',
                                    '-b:a', '32k',
                                    '-reservoir', '0',
                                    '-write_xing', '0',
                                    '-id3v2_version', '0',
                                    '-f', 'mp3',
                                    'pipe:1',
                                ],
                                stdin=_subprocess.PIPE,
                                stdout=_subprocess.PIPE,
                                stderr=_subprocess.DEVNULL,
                            )
                        except FileNotFoundError:
                            logger.error("ffmpeg not found; cannot stream EAS decoder audio")
                            return

                        source_names = ', '.join(source_broadcast_queues.keys())
                        logger.info(
                            f"EAS decoder stream started "
                            f"(16kHz MP3 via ffmpeg, sources=[{source_names}])"
                        )

                        # Seed ffmpeg with ~200 ms of silence so the first MP3 frame is
                        # ready before the browser's play() call needs data.
                        pre_silence_samples = int(stream_sample_rate * stream_channels * 0.20)
                        try:
                            ffmpeg_proc.stdin.write(np.zeros(pre_silence_samples, dtype=np.int16).tobytes())
                        except (BrokenPipeError, OSError):
                            pass

                        def _to_mono_float32(chunk):
                            """Normalize an audio chunk to 1D float32 mono."""
                            if not isinstance(chunk, np.ndarray):
                                chunk = np.array(chunk, dtype=np.float32)
                            if chunk.ndim == 2:
                                chunk = np.mean(chunk, axis=1)
                            elif chunk.ndim != 1:
                                chunk = chunk.flatten()
                            return chunk.astype(np.float32)

                        # Writer thread: mixed PCM from all broadcast queues → ffmpeg stdin
                        #
                        # STUTTER FIX: the old loop wrote 100 ms of zeros on every
                        # queue timeout, with the timeout (0.1 s) racing the ~100 ms
                        # producer cadence.  A chunk arriving a few ms late became
                        # an injected silence block spliced into continuous audio —
                        # audible stutter, several times per second under jitter —
                        # while the real chunk played after the gap and the stream
                        # drifted ever further behind live.  Transient jitter now
                        # emits nothing (ffmpeg simply waits); keep-alive silence is
                        # only written when every source has been quiet for seconds.
                        from app_core.audio.stream_keepalive import KeepAliveGate

                        def _feed_ffmpeg():
                            keepalive = KeepAliveGate(quiet_seconds=1.5)
                            try:
                                while _running and ffmpeg_proc.poll() is None:
                                    try:
                                        chunks = []

                                        if subscription_items:
                                            # Block on the first queue to drive timing;
                                            # generous timeout so late chunks are waited
                                            # for instead of replaced with silence.
                                            _, first_q = subscription_items[0]
                                            try:
                                                raw = first_q.get(timeout=0.25)
                                                if raw is not None and len(raw) > 0:
                                                    chunks.append(_to_mono_float32(raw))
                                            except queue_module.Empty:
                                                pass

                                            # Non-blocking drain of all remaining source queues.
                                            for _, q in subscription_items[1:]:
                                                try:
                                                    raw = q.get_nowait()
                                                    if raw is not None and len(raw) > 0:
                                                        chunks.append(_to_mono_float32(raw))
                                                except queue_module.Empty:
                                                    pass

                                        if not chunks:
                                            if keepalive.should_emit_silence():
                                                ffmpeg_proc.stdin.write(silence_pcm)
                                            continue

                                        keepalive.audio_received()

                                        # Mix sources: average to prevent clipping.
                                        # All sources produce equal-sized 100ms chunks (1600 samples
                                        # at 16 kHz) so n will match in practice.  The min() guard
                                        # handles the rare case of variable-sized source chunks:
                                        # truncating to the shortest keeps the stream clock accurate
                                        # (zero-padding would silently accumulate latency over time).
                                        if len(chunks) == 1:
                                            mixed = chunks[0]
                                        else:
                                            n = min(len(c) for c in chunks)
                                            mixed = np.mean([c[:n] for c in chunks], axis=0)

                                        ffmpeg_proc.stdin.write(
                                            (np.clip(mixed, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                                        )

                                    except (BrokenPipeError, OSError):
                                        break
                                    except Exception as exc:
                                        logger.error(f"EAS decoder feeder error: {exc}")
                            finally:
                                try:
                                    ffmpeg_proc.stdin.close()
                                except OSError:
                                    pass

                        feeder = threading.Thread(target=_feed_ffmpeg, daemon=True, name="eas-decoder-feeder")
                        feeder.start()

                        # Main generator: yield MP3 in small chunks for smooth, low-latency
                        # playback.  512 bytes ≈ 1–2 MP3 frames (~128 ms at 32 kbps) vs the
                        # previous 4096 bytes (~1 s) which caused the browser to receive audio
                        # in 1-second bursts, making the stream feel sluggish and stuttery.
                        while True:
                            mp3_chunk = ffmpeg_proc.stdout.read(512)
                            if not mp3_chunk:
                                break
                            yield mp3_chunk

                    except GeneratorExit:
                        pass
                    except Exception as exc:
                        logger.error(f"Error reading EAS decoder MP3 stream: {exc}")
                    finally:
                        for s_name, (bq, _) in subscriptions.items():
                            bq.unsubscribe(f"eas-decoder-stream-{tid}-{s_name}")
                        if ffmpeg_proc is not None:
                            try:
                                ffmpeg_proc.kill()
                            except OSError:
                                pass
                        if feeder is not None:
                            feeder.join(timeout=2)
                            if feeder.is_alive():
                                logger.warning("EAS decoder feeder thread did not stop within timeout")
                        logger.info("EAS decoder stream ended")

                return Response(
                    stream_with_context(generate_eas_decoder_mp3()),
                    mimetype='audio/mpeg',
                    headers={
                        'Content-Disposition': 'inline; filename="eas-decoder-16khz.mp3"',
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                        'Pragma': 'no-cache',
                        'Expires': '0',
                        'X-Content-Type-Options': 'nosniff',
                        'Access-Control-Allow-Origin': '*',
                        'Accept-Ranges': 'none',
                        'Connection': 'keep-alive',
                    }
                )

            def _eas_decoder_monitor_settings():
                """Read EASDecoderMonitorSettings via the main app's DB context.

                Returns ``(enabled, stream_name)``.  Defaults to (False,
                'eas-decoder-monitor') if the row doesn't exist or the query
                fails.  The audio service runs in its own process so the only
                way to reach the settings is through the Flask `app` created
                by initialize_database().
                """
                try:
                    from app_core.models import EASDecoderMonitorSettings
                    with app.app_context():
                        row = EASDecoderMonitorSettings.query.first()
                        if row is None:
                            return (False, 'eas-decoder-monitor')
                        return (bool(row.enabled), row.stream_name or 'eas-decoder-monitor')
                except Exception as exc:
                    logger.debug(f"EAS decoder monitor settings unavailable: {exc}")
                    return (False, 'eas-decoder-monitor')

            @stream_app.route('/api/eas/decoder-stream/sources')
            def list_decoder_stream_sources():
                """List per-source decoder-tap stream URLs for running sources.

                Returns the same 16 kHz EAS-decoder audio as
                ``/api/eas/decoder-stream`` but split out per source.  The
                ``enabled`` flag from EASDecoderMonitorSettings is included so
                the admin UI can show whether the per-source streams are
                currently being served.
                """
                enabled, stream_name = _eas_decoder_monitor_settings()
                sources = []
                if _audio_controller:
                    from app_core.audio.ingest import AudioSourceStatus
                    for s_name, adapter in _audio_controller.get_all_sources().items():
                        if (
                            adapter.status == AudioSourceStatus.RUNNING
                            and hasattr(adapter, 'get_eas_broadcast_queue')
                            and callable(getattr(adapter, 'get_eas_broadcast_queue', None))
                        ):
                            sources.append({
                                'name': s_name,
                                'mount_name': f"{stream_name}-{s_name}",
                                'stream_url': f"/api/eas/decoder-stream/{s_name}",
                                'sample_rate': 16000,
                                'channels': 1,
                            })
                return jsonify({
                    'enabled': enabled,
                    'stream_name_prefix': stream_name,
                    'mixed_stream_url': '/api/eas/decoder-stream',
                    'sources': sources,
                    'count': len(sources),
                })

            @stream_app.route('/api/eas/decoder-stream/<source_name>')
            def stream_eas_decoder_per_source(source_name):
                """Stream a single source's 16 kHz decoder-tap audio as MP3.

                Subscribes to the named source's EAS broadcast queue (the
                same 16 kHz signal fed to the SAME decoder) and pipes it
                through ffmpeg.  Gated by EASDecoderMonitorSettings.enabled
                so per-source taps are only available when the operator has
                explicitly turned them on (the mixed stream at
                /api/eas/decoder-stream remains available unconditionally).
                """
                import queue as queue_module
                import numpy as np
                import subprocess as _subprocess
                from app_core.audio.ingest import AudioSourceStatus

                enabled, _ = _eas_decoder_monitor_settings()
                if not enabled:
                    return jsonify({
                        'error': (
                            'Per-source decoder monitor streams are disabled. '
                            'Enable them in Admin → EAS Decoder Monitor.'
                        )
                    }), 403

                if not _audio_controller:
                    return jsonify({'error': 'Audio controller not initialized'}), 503

                adapter = _audio_controller.get_source(source_name)
                if not adapter:
                    return jsonify({'error': f'Audio source "{source_name}" not found'}), 404
                if adapter.status != AudioSourceStatus.RUNNING:
                    return jsonify({
                        'error': f'Audio source "{source_name}" is not running',
                        'status': adapter.status.value,
                    }), 503
                if not (
                    hasattr(adapter, 'get_eas_broadcast_queue')
                    and callable(getattr(adapter, 'get_eas_broadcast_queue', None))
                ):
                    return jsonify({
                        'error': f'Audio source "{source_name}" does not expose an EAS broadcast queue'
                    }), 400

                broadcast_queue = adapter.get_eas_broadcast_queue()

                def generate_per_source_mp3():
                    stream_sample_rate = 16000
                    stream_channels = 1
                    silence_samples = int(stream_sample_rate * stream_channels * 0.1)
                    silence_pcm = np.zeros(silence_samples, dtype=np.int16).tobytes()
                    tid = threading.current_thread().ident
                    sub_id = f"eas-decoder-stream-{source_name}-{tid}"
                    sub_q = broadcast_queue.subscribe(sub_id)

                    ffmpeg_proc = None
                    feeder = None
                    try:
                        try:
                            ffmpeg_proc = _subprocess.Popen(
                                [
                                    'ffmpeg', '-loglevel', 'error',
                                    '-f', 's16le',
                                    '-ar', str(stream_sample_rate),
                                    '-ac', str(stream_channels),
                                    '-i', 'pipe:0',
                                    '-c:a', 'libmp3lame',
                                    '-b:a', '32k',
                                    '-reservoir', '0',
                                    '-write_xing', '0',
                                    '-id3v2_version', '0',
                                    '-f', 'mp3',
                                    'pipe:1',
                                ],
                                stdin=_subprocess.PIPE,
                                stdout=_subprocess.PIPE,
                                stderr=_subprocess.DEVNULL,
                            )
                        except FileNotFoundError:
                            logger.error("ffmpeg not found; cannot stream EAS decoder audio")
                            return

                        logger.info(
                            f"EAS decoder per-source stream started "
                            f"(source={source_name}, 16kHz MP3)"
                        )

                        # Pre-roll silence so the browser sees an MP3 frame quickly.
                        try:
                            ffmpeg_proc.stdin.write(
                                np.zeros(int(stream_sample_rate * 0.20), dtype=np.int16).tobytes()
                            )
                        except (BrokenPipeError, OSError):
                            pass

                        def _to_mono_int16(chunk):
                            if not isinstance(chunk, np.ndarray):
                                chunk = np.array(chunk, dtype=np.float32)
                            if chunk.ndim == 2:
                                chunk = np.mean(chunk, axis=1)
                            elif chunk.ndim != 1:
                                chunk = chunk.flatten()
                            return (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

                        # STUTTER FIX: identical policy to the mixed decoder stream —
                        # never replace a late chunk with silence (that splices an
                        # audible 100 ms gap into continuous audio and pushes the
                        # stream behind live); only emit keep-alive silence once the
                        # source has been genuinely quiet for seconds.
                        from app_core.audio.stream_keepalive import KeepAliveGate

                        def _feed_ffmpeg():
                            keepalive = KeepAliveGate(quiet_seconds=1.5)
                            try:
                                while _running and ffmpeg_proc.poll() is None:
                                    try:
                                        raw = sub_q.get(timeout=0.25)
                                        if raw is None or len(raw) == 0:
                                            continue
                                        ffmpeg_proc.stdin.write(_to_mono_int16(raw))
                                        keepalive.audio_received()
                                    except queue_module.Empty:
                                        if keepalive.should_emit_silence():
                                            ffmpeg_proc.stdin.write(silence_pcm)
                                    except (BrokenPipeError, OSError):
                                        break
                                    except Exception as exc:
                                        logger.error(f"EAS per-source feeder error ({source_name}): {exc}")
                            finally:
                                try:
                                    ffmpeg_proc.stdin.close()
                                except OSError:
                                    pass

                        feeder = threading.Thread(
                            target=_feed_ffmpeg, daemon=True,
                            name=f"eas-decoder-feeder-{source_name}",
                        )
                        feeder.start()

                        while True:
                            mp3_chunk = ffmpeg_proc.stdout.read(512)
                            if not mp3_chunk:
                                break
                            yield mp3_chunk

                    except GeneratorExit:
                        pass
                    except Exception as exc:
                        logger.error(f"Error in per-source EAS stream ({source_name}): {exc}")
                    finally:
                        broadcast_queue.unsubscribe(sub_id)
                        if ffmpeg_proc is not None:
                            try:
                                ffmpeg_proc.kill()
                            except OSError:
                                pass
                        if feeder is not None:
                            feeder.join(timeout=2)
                            if feeder.is_alive():
                                logger.warning(
                                    f"EAS per-source feeder did not stop within timeout ({source_name})"
                                )
                        logger.info(f"EAS decoder per-source stream ended ({source_name})")

                return Response(
                    stream_with_context(generate_per_source_mp3()),
                    mimetype='audio/mpeg',
                    headers={
                        'Content-Disposition': f'inline; filename="eas-decoder-{source_name}-16khz.mp3"',
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                        'Pragma': 'no-cache',
                        'Expires': '0',
                        'X-Content-Type-Options': 'nosniff',
                        'Access-Control-Allow-Origin': '*',
                        'Accept-Ranges': 'none',
                        'Connection': 'keep-alive',
                    },
                )

            # Start Flask server in background thread
            # Use AUDIO_STREAMING_PORT env var (default 5002)
            streaming_port = int(os.environ.get('AUDIO_STREAMING_PORT', '5002'))
            server = make_server('0.0.0.0', streaming_port, stream_app, threaded=True)
            streaming_server_thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
                name="StreamingHTTPServer"
            )
            streaming_server_thread.start()
            logger.info(f"✅ HTTP streaming server started on port {streaming_port}")
        except Exception as e:
            logger.warning(f"Failed to start HTTP streaming server: {e}")
            logger.warning("   VU meter real-time streaming will not be available")

        logger.info("=" * 80)
        logger.info("✅ Audio service started successfully")
        logger.info("   - Audio ingestion: ACTIVE")
        logger.info(f"   - Icecast streaming: {'ACTIVE' if auto_streaming else 'DISABLED'}")
        
        # Show EAS monitoring status
        if eas_monitor:
            try:
                status = eas_monitor.get_status()
                monitor_count = status.get('monitor_count', 1)
                if monitor_count > 1 and 'monitors' in status:
                    monitor_names = ', '.join(status['monitors'].keys())
                    logger.info(f"   - EAS monitoring: ACTIVE ({monitor_count} sources: {monitor_names})")
                else:
                    logger.info("   - EAS monitoring: ACTIVE (single source)")
            except Exception:
                logger.info("   - EAS monitoring: ACTIVE")
        else:
            logger.info("   - EAS monitoring: FAILED")
        
        logger.info("   - Metrics publishing: ACTIVE")
        logger.info(f"   - Command subscriber: {'ACTIVE' if command_subscriber else 'DISABLED'}")
        streaming_port = int(os.environ.get('AUDIO_STREAMING_PORT', '5002'))
        logger.info(f"   - HTTP streaming: {'ACTIVE' if streaming_server_thread else 'DISABLED'} (port {streaming_port})")
        logger.info("=" * 80)

        # Source watchdog: restart ERROR sources and auto-start STOPPED sources.
        # Network streams drop after consecutive errors; SDR sources lose lock.
        # Runs in its OWN thread (see _source_watchdog_loop) so that a stalled
        # capture being stopped/restarted can NEVER block the metrics loop
        # below — a blocked metrics loop lets the Redis key expire and the
        # whole UI (and EAS Continuous Monitor status) reports the audio
        # service as unavailable.
        _watchdog_stop = threading.Event()
        if audio_controller:
            _watchdog_thread = threading.Thread(
                target=_source_watchdog_loop,
                args=(app, audio_controller, _watchdog_stop),
                daemon=True,
                name="SourceWatchdog",
            )
            _watchdog_thread.start()
            logger.info("✅ Source watchdog thread started")

        # Tell systemd we're up (Type=notify + WatchdogSec= on this unit) and
        # start kicking the watchdog from inside the loop below -- a hang
        # here (not just a crash) now gets systemd to kill + restart us.
        sd_notify("READY=1")
        systemd_watchdog = Watchdog()

        # Main loop: publish metrics at 4 Hz so VU meters, RSSI and RBDS/RDS
        # updates reach the UI as fast as a car radio refreshes its display.
        # The WebSocket push worker already polls Redis at 4 Hz, so anything
        # slower than this becomes the end-to-end bottleneck.  Nothing in this
        # loop is allowed to block on source stop/start work: stalled-capture
        # recovery lives in the watchdog thread and the controller's
        # per-source recovery threads.
        last_metrics_time = 0
        metrics_interval = 0.25
        last_db_snapshot_time = 0
        db_snapshot_interval = 1.0

        while _running:
            try:
                current_time = time.time()

                # Publish metrics periodically
                if current_time - last_metrics_time >= metrics_interval:
                    metrics = collect_metrics()
                    publish_metrics_to_redis(metrics)
                    _reconcile_broadcast_metadata()
                    last_metrics_time = current_time

                # Snapshot AudioSourceMetrics to the DB at a slower ~1 Hz --
                # this is history (RBDS/BLER trend, audio-health aggregates),
                # not the live UI feed, so it doesn't need the 4 Hz rate above.
                if current_time - last_db_snapshot_time >= db_snapshot_interval:
                    snapshot_audio_metrics()
                    last_db_snapshot_time = current_time

                    # Log health status
                    if metrics.get("eas_monitor"):
                        eas_metrics = metrics["eas_monitor"]
                        if "monitors" in eas_metrics:
                            # Multi-monitor mode
                            monitor_count = eas_metrics.get("monitor_count", 0)
                            total_samples = eas_metrics.get("samples_processed", 0)
                            logger.debug(
                                f"EAS Monitors: {monitor_count} active, "
                                f"total samples processed={total_samples}"
                            )
                        else:
                            # Legacy single monitor
                            samples = eas_metrics.get("samples_processed", 0)
                            running = eas_metrics.get("running", False)
                            logger.debug(f"EAS Monitor: running={running}, samples={samples}")

                # Sleep briefly. Command handling runs on its own Redis
                # pub/sub subscriber thread, not this loop -- this sleep only
                # paces the metrics_interval check above, so it needs to be
                # shorter than metrics_interval or the publish rate silently
                # halves (a 0.5s sleep here previously made the "4 Hz" target
                # above only achievable at 2 Hz).
                time.sleep(0.1)
                systemd_watchdog.kick()

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(5)

        logger.info("Shutting down audio service...")

        # Stop the source watchdog thread
        _watchdog_stop.set()

        # Stop command subscriber
        if command_subscriber:
            logger.info("Stopping command subscriber...")
            try:
                command_subscriber.stop()
            except Exception as e:
                logger.warning(f"Error stopping command subscriber: {e}")

        # Stop the gated-alerts release scheduler
        try:
            from app_core.gating_scheduler import stop_scheduler as stop_gating_scheduler
            stop_gating_scheduler()
        except Exception as e:
            logger.warning(f"Error stopping gated-alerts release scheduler: {e}")

        # Stop EAS monitor(s) - works for both single and multi-monitor
        if _eas_monitor:
            logger.info("Stopping EAS monitor(s)...")
            _eas_monitor.stop()

        # Stop audio controller
        if _audio_controller:
            logger.info("Stopping audio controller...")
            # Audio controller doesn't have explicit stop, sources will be cleaned up

        # Close Redis connection
        if _redis_client:
            logger.info("Closing Redis connection...")
            _redis_client.close()

        logger.info("✅ Audio service shut down gracefully")
        return 0

    except Exception as e:
        logger.error(f"Fatal error in audio service: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    _exit_code = main()
    # Bypass normal interpreter finalization: numba/llvmlite's native JIT
    # teardown races with CPython shutdown on aarch64 and can abort the
    # process (SIGABRT / "terminate called without an active exception")
    # *after* the graceful-shutdown code above has already completed. That
    # abort happens outside any Python exception handler and is invisible
    # to the app's own logging, and because it occurs while systemd already
    # has a stop job in flight for this unit, Restart=always does not fire.
    # os._exit() skips the problematic native teardown entirely.
    logging.shutdown()
    os._exit(_exit_code)
