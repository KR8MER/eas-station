#!/usr/bin/env python3
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
import time
import signal
import logging
import threading
import redis
import json
from typing import Optional, Any, Dict
from dotenv import load_dotenv

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

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
    """Convert runtime values to JSON-serializable primitives."""
    try:
        import numpy as np  # type: ignore

        if isinstance(value, (np.floating, np.integer)):
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
    except Exception:
        # numpy is optional in some deployments; ignore if unavailable
        pass

    if isinstance(value, (str, int, float, bool)):
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
    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port = os.getenv("POSTGRES_PORT", "5432")
    postgres_db = os.getenv("POSTGRES_DB", "alerts")
    postgres_user = os.getenv("POSTGRES_USER", "postgres")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")

    # Security warning for default credentials
    if postgres_password == "postgres":
        logger.warning(
            "Using default database password 'postgres'. "
            "Set POSTGRES_PASSWORD environment variable for production deployments."
        )

    # Escape password for URL (handles special characters like @, :, etc.)
    from urllib.parse import quote_plus
    escaped_password = quote_plus(postgres_password)

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{postgres_user}:{escaped_password}@"
        f"{postgres_host}:{postgres_port}/{postgres_db}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    return app


def initialize_radio_receivers(app):
    """DEPRECATED: Do not use in separated architecture.
    
    In separated architecture, sdr-service.py handles all SDR hardware access.
    This function is kept for backward compatibility but should NOT be called
    from audio-service.py as it conflicts with sdr-service.
    
    If you need SDR functionality in audio-service, ensure:
    1. sdr-service.py is running and publishing to Redis
    2. AudioSourceConfigDB entries exist with managed_by='radio'
    3. RedisSDRSourceAdapter will automatically subscribe to sdr:samples:{receiver_id}
    
    The sync_radio_receiver_audio_sources() function handles step 2 automatically.
    """
    logger.warning(
        "initialize_radio_receivers() called but DEPRECATED in separated architecture. "
        "SDR hardware should be managed by sdr-service.py container. "
        "Use sync_radio_receiver_audio_sources() + RedisSDRSourceAdapter instead."
    )
    return  # Do nothing - prevents conflict with sdr-service


def sync_radio_receiver_audio_sources(app):
    """Ensure audio sources exist for all enabled radio receivers with audio_output=True.
    
    This is critical for the separated architecture where sdr-service publishes IQ samples
    to Redis and audio-service needs AudioSourceConfigDB entries to know which channels
    to subscribe to via RedisSDRSourceAdapter.
    """
    with app.app_context():
        from app_core.models import RadioReceiver, AudioSourceConfigDB, db
        from app_core.audio.ingest import AudioSourceType
        
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
            silence_threshold = float(receiver.squelch_threshold_db or -60.0)
            silence_duration = max(float(receiver.squelch_close_ms or 750) / 1000.0, 0.1)
            
            device_params = {
                'receiver_id': receiver.identifier,
                'receiver_display_name': receiver.display_name,
                'receiver_driver': receiver.driver,
                'receiver_frequency_hz': float(receiver.frequency_hz or 0.0),
                'receiver_modulation': modulation,
                'iq_sample_rate': receiver.sample_rate,
                'demod_mode': receiver.modulation_type or 'FM',
                'rbds_enabled': bool(receiver.enable_rbds),
                'squelch_enabled': bool(receiver.squelch_enabled),
                'squelch_threshold_db': silence_threshold,
                'squelch_open_ms': int(receiver.squelch_open_ms or 150),
                'squelch_close_ms': int(receiver.squelch_close_ms or 750),
                'carrier_alarm_enabled': bool(receiver.squelch_alarm),
            }
            
            config_params = {
                'sample_rate': sample_rate,
                'channels': channels,
                'buffer_size': buffer_size,
                'silence_threshold_db': silence_threshold,
                'silence_duration_seconds': silence_duration,
                'device_params': device_params,
                'managed_by': 'radio',  # CRITICAL: This flag tells audio-service to use RedisSDRSourceAdapter
                'squelch_enabled': bool(receiver.squelch_enabled),
                'squelch_threshold_db': silence_threshold,
                'squelch_open_ms': int(receiver.squelch_open_ms or 150),
                'squelch_close_ms': int(receiver.squelch_close_ms or 750),
                'carrier_alarm_enabled': bool(receiver.squelch_alarm),
            }
            
            freq_display = f"{receiver.frequency_hz/1e6:.3f} MHz" if receiver.frequency_hz else "Unknown"
            description = f"SDR monitor for {receiver.display_name} · {freq_display}"
            
            # Check if audio source exists
            db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
            
            if db_config is None:
                # Create new audio source
                logger.info(f"Creating audio source for receiver '{receiver.identifier}': {source_name}")
                db_config = AudioSourceConfigDB(
                    name=source_name,
                    source_type=AudioSourceType.SDR.value,
                    config_params=config_params,
                    priority=10,
                    enabled=True,
                    auto_start=receiver.auto_start,
                    description=description,
                )
                db.session.add(db_config)
                created += 1
            else:
                # Update existing audio source if config changed
                if (db_config.config_params or {}) != config_params:
                    logger.info(f"Updating audio source for receiver '{receiver.identifier}': {source_name}")
                    db_config.config_params = config_params
                    db_config.enabled = True
                    db_config.auto_start = receiver.auto_start
                    db_config.description = description
                    updated += 1
        
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
        
        # CRITICAL FIX: Sync audio sources for radio receivers before loading from database
        # This ensures that audio sources exist for all enabled receivers with audio_output=True
        sync_radio_receiver_audio_sources(app)

        # Create controller
        _audio_controller = AudioIngestController()

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
                    device_params=config_params.get('device_params', {}),
                )

                # Create and add adapter
                adapter = create_audio_source(runtime_config)
                _audio_controller.add_source(adapter)
                logger.info(f"Loaded audio source: {db_config.name} ({db_config.source_type})")

            except Exception as e:
                logger.error(f"Error loading source '{db_config.name}': {e}", exc_info=True)

        logger.info(f"Loaded {len(_audio_controller._sources)} audio source configurations")

        # Start auto-start sources
        auto_start_sources = [db_config for db_config in saved_configs if db_config.enabled and db_config.auto_start]
        if auto_start_sources:
            logger.info(f"Auto-starting {len(auto_start_sources)} enabled source(s)...")
            for db_config in auto_start_sources:
                try:
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
                    
                    result = _audio_controller.start_source(db_config.name)
                    if result:
                        logger.info(f"✅ Successfully started '{db_config.name}'")
                    else:
                        logger.warning(f"⚠️ Failed to start '{db_config.name}' (start returned False)")
                except Exception as e:
                    logger.error(f"❌ Exception auto-starting '{db_config.name}': {e}", exc_info=True)
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

            auto_config = get_icecast_auto_config()

            if not auto_config.is_enabled():
                logger.info("Icecast auto-streaming is disabled (ICECAST_ENABLED=false)")
                return None

            logger.info(f"Initializing Icecast auto-streaming: {auto_config.server}:{auto_config.port}")

            _auto_streaming_service = AutoStreamingService(
                icecast_server=auto_config.server,
                icecast_port=auto_config.port,
                icecast_password=auto_config.source_password,
                icecast_admin_user=auto_config.admin_user,
                icecast_admin_password=auto_config.admin_password,
                default_bitrate=128,
                enabled=True,
                audio_controller=audio_controller
            )

            # Start the service
            if _auto_streaming_service.start():
                logger.info("✅ Icecast auto-streaming service started successfully")
            else:
                logger.warning("Icecast auto-streaming service failed to start")

            return _auto_streaming_service

    except Exception as exc:
        logger.error(f"Failed to initialize Icecast auto-streaming: {exc}", exc_info=True)
        return None


def initialize_eas_monitor(app, audio_controller):
    """Initialize EAS monitoring system with per-source monitors.
    
    CRITICAL FIX: Create separate EAS monitor for each audio source to enable
    simultaneous monitoring of multiple streams (LP1, LP2, SP1, etc).
    
    Previously, only ONE source was monitored at a time (highest priority).
    Now ALL sources are monitored simultaneously for EAS alerts.
    """
    global _eas_monitor

    with app.app_context():
        from app_core.audio.eas_monitor import ContinuousEASMonitor, create_fips_filtering_callback
        from app_core.audio.broadcast_adapter import BroadcastAudioAdapter
        from app_core.audio.startup_integration import load_fips_codes_from_config
        from app_core.audio.ingest import AudioSourceStatus

        logger.info("Initializing per-source EAS monitors...")

        # Load FIPS codes
        configured_fips = load_fips_codes_from_config()
        logger.info(f"Loaded {len(configured_fips)} FIPS codes for alert filtering")

        # Create alert callback with filtering (shared by all monitors)
        def forward_alert_handler(alert):
            """Forward matched alerts."""
            from app_core.audio.alert_forwarding import forward_alert_to_api
            source_name = alert.get('source_name', 'unknown')
            event_code = alert.get('event_code', 'UNKNOWN')
            location_codes = alert.get('location_codes', [])
            logger.info(
                f"Forwarding alert from source '{source_name}': "
                f"{event_code} for {location_codes}"
            )
            forward_alert_to_api(alert)

        alert_callback = create_fips_filtering_callback(
            configured_fips_codes=configured_fips,
            forward_callback=forward_alert_handler,
            logger_instance=logger
        )

        # Create dictionary to store all monitors
        monitors = {}
        
        # Create a monitor for each RUNNING audio source
        for source_name, source_adapter in audio_controller._sources.items():
            if source_adapter.status != AudioSourceStatus.RUNNING:
                logger.warning(
                    f"Skipping EAS monitor for '{source_name}' - "
                    f"source not running (status: {source_adapter.status.value})"
                )
                continue
            
            try:
                # Get source's individual broadcast queue (not the main controller queue!)
                source_broadcast_queue = source_adapter.get_broadcast_queue()
                source_sample_rate = source_adapter.config.sample_rate
                
                # Create broadcast adapter for this specific source
                subscriber_id = f"eas-monitor-{source_name}"
                audio_adapter = BroadcastAudioAdapter(
                    broadcast_queue=source_broadcast_queue,
                    subscriber_id=subscriber_id,
                    sample_rate=int(source_sample_rate)
                )
                
                # Create EAS monitor for this source (16 kHz for optimal SAME decoding)
                monitor = ContinuousEASMonitor(
                    audio_manager=audio_adapter,
                    sample_rate=16000,
                    alert_callback=alert_callback,
                    save_audio_files=True,
                    audio_archive_dir="/tmp/eas-audio"
                )
                
                # Start monitoring this source
                if monitor.start():
                    monitors[source_name] = monitor
                    logger.info(f"✅ EAS monitor started for source: {source_name}")
                else:
                    logger.error(f"❌ EAS monitor failed to start for source: {source_name}")
                    
            except Exception as e:
                logger.error(f"❌ Failed to create EAS monitor for '{source_name}': {e}", exc_info=True)
        
        if not monitors:
            logger.warning("⚠️ No EAS monitors started initially - no running sources yet")
            logger.info("   EAS monitors will be created automatically when sources start")
        else:
            logger.info(f"✅ Started {len(monitors)} EAS monitor(s) for sources: {list(monitors.keys())}")

        # Return a monitor manager object instead of attaching to first monitor
        # This avoids fragile coupling and provides cleaner API
        class MultiMonitorManager:
            """Manager for multiple EAS monitor instances.

            Supports dynamically adding monitors for sources started after initialization.
            """
            def __init__(self, monitors_dict, configured_fips, alert_callback, audio_controller):
                self._all_monitors = monitors_dict
                self._configured_fips = configured_fips
                self._alert_callback = alert_callback
                self._audio_controller = audio_controller

            def add_monitor_for_source(self, source_name):
                """Create and start an EAS monitor for a newly started source.

                Args:
                    source_name: Name of the audio source to monitor

                Returns:
                    bool: True if monitor was created and started successfully
                """
                if source_name in self._all_monitors:
                    logger.info(f"EAS monitor already exists for source '{source_name}'")
                    return True

                source_adapter = self._audio_controller._sources.get(source_name)
                if not source_adapter:
                    logger.warning(f"Cannot create EAS monitor - source '{source_name}' not found")
                    return False

                if source_adapter.status != AudioSourceStatus.RUNNING:
                    logger.warning(
                        f"Cannot create EAS monitor - source '{source_name}' not running "
                        f"(status: {source_adapter.status.value})"
                    )
                    return False

                try:
                    # Get source's individual broadcast queue
                    source_broadcast_queue = source_adapter.get_broadcast_queue()
                    source_sample_rate = source_adapter.config.sample_rate

                    # Create broadcast adapter for this specific source
                    subscriber_id = f"eas-monitor-{source_name}"
                    audio_adapter = BroadcastAudioAdapter(
                        broadcast_queue=source_broadcast_queue,
                        subscriber_id=subscriber_id,
                        sample_rate=int(source_sample_rate)
                    )

                    # Create EAS monitor for this source (16 kHz for optimal SAME decoding)
                    monitor = ContinuousEASMonitor(
                        audio_manager=audio_adapter,
                        sample_rate=16000,
                        alert_callback=self._alert_callback,
                        save_audio_files=True,
                        audio_archive_dir="/tmp/eas-audio"
                    )

                    # Start monitoring this source
                    if monitor.start():
                        self._all_monitors[source_name] = monitor
                        logger.info(f"✅ EAS monitor dynamically started for source: {source_name}")
                        return True
                    else:
                        logger.error(f"❌ EAS monitor failed to start for source: {source_name}")
                        return False

                except Exception as e:
                    logger.error(f"❌ Failed to create EAS monitor for '{source_name}': {e}", exc_info=True)
                    return False

            def remove_monitor_for_source(self, source_name):
                """Stop and remove the EAS monitor for a source.

                Args:
                    source_name: Name of the source to stop monitoring

                Returns:
                    bool: True if monitor was stopped and removed
                """
                monitor = self._all_monitors.pop(source_name, None)
                if monitor:
                    try:
                        monitor.stop()
                        logger.info(f"✅ EAS monitor stopped for source: {source_name}")
                        return True
                    except Exception as e:
                        logger.warning(f"Error stopping monitor '{source_name}': {e}")
                return False

            def stop(self):
                """Stop all monitors."""
                for name, monitor in self._all_monitors.items():
                    try:
                        monitor.stop()
                    except Exception as e:
                        logger.warning(f"Error stopping monitor '{name}': {e}")

            def get_status(self):
                """Get aggregated status from all monitors."""
                all_stats = {}
                total_samples = 0
                any_running = False

                for name, monitor in self._all_monitors.items():
                    try:
                        stats = monitor.get_status()
                        all_stats[name] = stats
                        total_samples += stats.get('samples_processed', 0)
                        if stats.get('running', False):
                            any_running = True
                    except Exception as e:
                        logger.debug(f"Error getting status for monitor '{name}': {e}")

                return {
                    "running": any_running,
                    "samples_processed": total_samples,
                    "monitor_count": len(self._all_monitors),
                    "monitors": all_stats
                }

        # Always use MultiMonitorManager for consistent API (even for single/zero monitors)
        _eas_monitor = MultiMonitorManager(monitors, configured_fips, alert_callback, audio_controller)
        logger.info(f"✅ Created EAS monitor manager for {len(monitors)} source(s)")

        return _eas_monitor


def process_commands():
    """DEPRECATED: SDR commands handled by sdr-service.py.
    
    In separated architecture, all SDR hardware commands go to sdr-service.py.
    This function is kept for backward compatibility but does nothing.
    
    Commands should be sent to sdr-service via Redis, not audio-service.
    """
    # Do nothing - all SDR hardware access is in sdr-service.py
    return


def collect_metrics():
    """Collect metrics from audio controller, radio manager, and EAS monitor."""
    metrics = {
        "audio_controller": None,
        "eas_monitor": None,
        "broadcast_queue": None,
        "radio_manager": None,  # Add radio manager metrics for app container
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

            for name, source in _audio_controller._sources.items():
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

            # Get broadcast queue stats
            try:
                broadcast_queue = _audio_controller.get_broadcast_queue()
                if broadcast_queue:
                    metrics["broadcast_queue"] = _sanitize_value(broadcast_queue.get_stats())
            except Exception as e:
                logger.error(f"Error getting broadcast queue stats: {e}")

        # Get EAS monitor stats (supports both single and multi-monitor)
        if _eas_monitor:
            try:
                metrics["eas_monitor"] = _eas_monitor.get_status()
            except Exception as e:
                logger.error(f"Error getting EAS monitor stats: {e}")

    except Exception as e:
        logger.error(f"Error collecting metrics: {e}")

    return metrics


def publish_metrics_to_redis(metrics):
    """Publish metrics to Redis for web application."""
    try:
        r = get_redis_client()

        # Add heartbeat timestamp and process ID (required by app container)
        metrics["_heartbeat"] = time.time()
        metrics["_master_pid"] = os.getpid()

        # Flatten nested dicts to strings for Redis hash
        flat_metrics = {}
        for key, value in metrics.items():
            if isinstance(value, (dict, list)):
                flat_metrics[key] = json.dumps(value)
            else:
                flat_metrics[key] = str(value)

        # Store in Redis with pipeline for atomicity
        pipe = r.pipeline()
        pipe.delete("eas:metrics")  # Use same key as worker coordinator
        pipe.hset("eas:metrics", mapping=flat_metrics)
        pipe.expire("eas:metrics", 60)  # Expire if service dies
        
        # Publish waveform and spectrogram data for each source separately (to keep main metrics lightweight)
        if _audio_controller:
            for name, source in _audio_controller._sources.items():
                try:
                    # Only publish visualization data for running sources
                    from app_core.audio.ingest import AudioSourceStatus
                    if source.status == AudioSourceStatus.RUNNING:
                        # Publish waveform data
                        if hasattr(source, 'get_waveform_data'):
                            waveform_data = source.get_waveform_data()
                            if waveform_data is not None and len(waveform_data) > 0:
                                # Convert numpy array to list for JSON serialization
                                waveform_list = _sanitize_value(waveform_data.tolist())
                                waveform_payload = {
                                    'waveform': waveform_list,
                                    'sample_count': len(waveform_list),
                                    'timestamp': time.time() * 1000,  # Milliseconds for JS
                                    'source_name': name,
                                    'status': 'available'
                                }
                                # Store waveform data with short expiry (10 seconds)
                                pipe.setex(
                                    f"eas:waveform:{name}",
                                    10,
                                    json.dumps(waveform_payload)
                                )
                        
                        # Publish spectrogram data
                        if hasattr(source, 'get_spectrogram_data'):
                            spectrogram_data = source.get_spectrogram_data()
                            if spectrogram_data is not None and spectrogram_data.size > 0:
                                # Convert numpy array to list for JSON serialization
                                spectrogram_list = _sanitize_value(spectrogram_data.tolist())
                                # Get source config for FFT info
                                sample_rate = getattr(source, 'sample_rate', 44100)
                                fft_size = getattr(source, '_fft_size', 2048)
                                
                                spectrogram_payload = {
                                    'spectrogram': spectrogram_list,
                                    'time_frames': len(spectrogram_list),
                                    'frequency_bins': len(spectrogram_list[0]) if len(spectrogram_list) > 0 else 0,
                                    'sample_rate': sample_rate,
                                    'fft_size': fft_size,
                                    'timestamp': time.time() * 1000,  # Milliseconds for JS
                                    'source_name': name,
                                    'status': 'available'
                                }
                                # Store spectrogram data with short expiry (10 seconds)
                                pipe.setex(
                                    f"eas:spectrogram:{name}",
                                    10,
                                    json.dumps(spectrogram_payload)
                                )
                except Exception as e:
                    logger.debug(f"Error publishing visualization data for '{name}': {e}")
        
        # Spectrum data is now published by sdr-service.py
        # audio-service.py does NOT access SDR hardware or IQ samples
        
        pipe.execute()

        # Publish notification for real-time updates
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

        # CRITICAL: Do NOT initialize RadioManager here!
        # In separated architecture, sdr-service.py handles SDR hardware access.
        # This service (audio-service) only subscribes to Redis channels for IQ samples.
        # The sync_radio_receiver_audio_sources() function will create AudioSourceConfigDB
        # entries that trigger RedisSDRSourceAdapter creation (which subscribes to Redis).
        logger.info("Skipping RadioManager initialization - using separated architecture")
        logger.info("SDR hardware is managed by sdr-service container")
        logger.info("This service will subscribe to Redis channels for IQ samples")

        # Initialize audio controller
        logger.info("Initializing audio controller...")
        audio_controller = initialize_audio_controller(app)
        _audio_controller = audio_controller  # Store globally for command subscriber

        if not audio_controller:
            logger.error("Failed to initialize audio controller")
            return 1

        # Initialize Icecast auto-streaming
        logger.info("Initializing Icecast auto-streaming...")
        auto_streaming = initialize_auto_streaming(app, audio_controller)

        # Add all RUNNING audio sources to Icecast streaming
        if auto_streaming and audio_controller:
            from app_core.audio.ingest import AudioSourceStatus

            logger.info("Checking audio sources for Icecast streaming...")

            # Log status of all sources for diagnostics
            total_sources = len(audio_controller._sources)
            logger.info(f"Total configured sources: {total_sources}")

            for source_name, source_adapter in audio_controller._sources.items():
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

        # Initialize EAS monitor
        logger.info("Initializing EAS monitor...")
        eas_monitor = initialize_eas_monitor(app, audio_controller)

        if not eas_monitor:
            logger.error("Failed to initialize EAS monitor")
            return 1

        # Initialize Redis Pub/Sub command subscriber
        logger.info("Starting Redis command subscriber...")
        command_subscriber = None
        subscriber_thread = None
        try:
            from app_core.audio.redis_commands import AudioCommandSubscriber
            import threading

            command_subscriber = AudioCommandSubscriber(audio_controller, auto_streaming, eas_monitor)

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
            import threading
            from werkzeug.serving import make_server
            
            # Create Flask app for streaming endpoints
            stream_app = Flask(__name__)
            
            @stream_app.route('/api/audio/stream/<source_name>')
            def stream_audio(source_name):
                """Stream live audio as downsampled WAV for low bandwidth + zero latency.
                
                VU meters get levels from /api/audio/metrics (published to Redis every 5s).
                This stream is for audio playback, so we downsample to reduce bandwidth
                while maintaining real-time zero-latency streaming:
                - Original: 44.1kHz stereo = 176 KB/s per source
                - Downsampled: 22.05kHz mono = 44 KB/s per source (4x smaller)
                - Still uncompressed = ZERO latency (critical for Pi performance and SAME decoding)
                - No CPU overhead for transcoding (Pi can focus on SAME decoding)
                """
                import struct
                import io
                import numpy as np
                from app_core.audio.ingest import AudioSourceStatus
                
                def generate_wav_stream(adapter, source_name):
                    """Generator that yields downsampled WAV chunks.

                    Uses BroadcastQueue subscription to avoid competing with other audio consumers
                    (Icecast, EAS monitor, etc). Each subscriber gets independent copy of all audio chunks.
                    """
                    import queue as queue_module

                    # Source configuration
                    source_sample_rate = adapter.config.sample_rate
                    source_channels = adapter.config.channels

                    # Stream configuration: 22.05kHz mono (human voice is clear at this rate)
                    stream_sample_rate = 22050
                    stream_channels = 1  # Mono saves 50% bandwidth
                    bits_per_sample = 16

                    # Check if resampling is needed and pre-compute the ratio
                    needs_resample = source_sample_rate != stream_sample_rate
                    resample_ratio = stream_sample_rate / source_sample_rate if needs_resample else 1.0

                    # Subscribe to BroadcastQueue for non-competitive audio access
                    # Use unique subscriber ID per connection
                    subscriber_id = f"web-stream-{source_name}-{threading.current_thread().ident}"
                    broadcast_queue = _audio_controller.get_broadcast_queue()
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

                        # Stream audio chunks
                        silence_duration = 0.05
                        silence_samples = int(stream_sample_rate * stream_channels * silence_duration)

                        logger.info(f"Web stream '{subscriber_id}' started, subscribed to broadcast queue")

                        while _running:
                            try:
                                # Read from subscription queue (non-competitive)
                                audio_chunk = subscription_queue.get(timeout=0.2)
                                if audio_chunk is None:
                                    # Yield silence to keep stream alive
                                    silence_chunk = np.zeros(silence_samples, dtype=np.int16)
                                    yield silence_chunk.tobytes()
                                    time.sleep(0.01)
                                    continue

                                if not isinstance(audio_chunk, np.ndarray):
                                    audio_chunk = np.array(audio_chunk, dtype=np.float32)

                                # Convert stereo to mono if needed (mix channels)
                                if source_channels > 1 and stream_channels == 1:
                                    # Ensure chunk length is divisible by channels
                                    remainder = len(audio_chunk) % source_channels
                                    if remainder != 0:
                                        audio_chunk = audio_chunk[:-remainder]
                                    if len(audio_chunk) > 0:
                                        audio_chunk = np.mean(audio_chunk.reshape(-1, source_channels), axis=1)

                                # Resample to target sample rate using linear interpolation
                                # This ensures the output matches the WAV header sample rate exactly,
                                # fixing the high-pitched squeal caused by sample rate mismatch
                                if needs_resample and len(audio_chunk) > 0:
                                    new_length = max(int(len(audio_chunk) * resample_ratio), 1)
                                    old_indices = np.arange(len(audio_chunk))
                                    new_indices = np.linspace(0, len(audio_chunk) - 1, new_length)
                                    audio_chunk = np.interp(new_indices, old_indices, audio_chunk).astype(np.float32)

                                # Convert to int16 PCM
                                pcm_data = (np.clip(audio_chunk, -1.0, 1.0) * 32767).astype(np.int16)
                                yield pcm_data.tobytes()

                            except queue_module.Empty:
                                # No audio available, yield silence
                                silence_chunk = np.zeros(silence_samples, dtype=np.int16)
                                yield silence_chunk.tobytes()
                                time.sleep(0.01)
                            except Exception as e:
                                logger.debug(f"Error in stream generator: {e}")
                                silence_chunk = np.zeros(silence_samples, dtype=np.int16)
                                yield silence_chunk.tobytes()
                                time.sleep(0.01)
                    finally:
                        # Unsubscribe when client disconnects
                        broadcast_queue.unsubscribe(subscriber_id)
                        logger.info(f"Web stream '{subscriber_id}' ended, unsubscribed from broadcast queue")
                
                try:
                    if not _audio_controller:
                        return jsonify({'error': 'Audio controller not initialized'}), 503
                    
                    adapter = _audio_controller._sources.get(source_name)
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
                        }
                    )
                except Exception as exc:
                    logger.error(f'Error setting up audio stream for {source_name}: {exc}')
                    return jsonify({'error': str(exc)}), 500
            
            # Start Flask server in background thread
            # Use AUDIO_STREAMING_PORT env var (default 5002 matches docker-compose.yml)
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

        # Main loop: publish metrics every 5 seconds
        last_metrics_time = 0
        metrics_interval = 5.0

        while _running:
            try:
                current_time = time.time()

                # Process pending commands from webapp (non-blocking)
                process_commands()

                # Publish metrics periodically
                if current_time - last_metrics_time >= metrics_interval:
                    metrics = collect_metrics()
                    publish_metrics_to_redis(metrics)
                    last_metrics_time = current_time

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

                # Sleep briefly (check for commands every 500ms)
                time.sleep(0.5)

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(5)

        logger.info("Shutting down audio service...")

        # Stop command subscriber
        if command_subscriber:
            logger.info("Stopping command subscriber...")
            try:
                command_subscriber.stop()
            except Exception as e:
                logger.warning(f"Error stopping command subscriber: {e}")

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
    sys.exit(main())
