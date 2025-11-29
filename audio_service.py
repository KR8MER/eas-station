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
Standalone Audio Processing Service

This service handles ALL audio processing independently from the web application:
- Audio source ingestion (SDR, Icecast streams, etc.)
- EAS monitoring and SAME decoding
- Icecast streaming output
- Metrics publishing to Redis

Architecture Benefits:
- Web crashes don't affect audio monitoring
- Audio service can be restarted independently
- Simpler, more focused codebase
- Better resource management
- Easier debugging

The web application reads metrics from Redis and serves the UI.
"""

import os
import sys
import time
import signal
import logging
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

# Constants for spectrum computation
FFT_MIN_MAGNITUDE = 1e-10  # Minimum magnitude to avoid log(0) in dB conversion

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

# Global state
_running = True
_redis_client: Optional[redis.Redis] = None
_audio_controller = None
_eas_monitor = None
_auto_streaming_service = None
_radio_manager = None  # Reference to RadioManager for metrics collection


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
    """Initialize and start radio receivers (low-level SoapySDR) from database configuration."""
    global _radio_manager
    
    try:
        with app.app_context():
            from app_core.models import RadioReceiver
            from app_core.extensions import get_radio_manager

            # Get all configured receivers from database
            receivers = RadioReceiver.query.filter_by(enabled=True).all()
            if not receivers:
                logger.info("No radio receivers configured in database")
                return

            # Get or create the radio manager
            radio_manager = get_radio_manager()
            _radio_manager = radio_manager  # Store reference for metrics collection

            # Configure receivers from database records
            radio_manager.configure_from_records(receivers)
            logger.info(f"Configured {len(receivers)} radio receiver(s) from database")

            # Start all receivers that have auto_start enabled
            auto_start_receivers = [r for r in receivers if r.auto_start]
            if auto_start_receivers:
                radio_manager.start_all()
                logger.info(f"✅ Started {len(auto_start_receivers)} radio receiver(s) with auto_start enabled")
            else:
                logger.info("No radio receivers have auto_start enabled")

    except Exception as exc:
        logger.error(f"Failed to initialize radio receivers: {exc}", exc_info=True)
        raise


def initialize_audio_controller(app):
    """Initialize audio ingestion controller."""
    global _audio_controller

    with app.app_context():
        from app_core.audio.ingest import AudioIngestController, AudioSourceConfig, AudioSourceType
        from app_core.audio.sources import create_audio_source
        from app_core.models import AudioSourceConfigDB

        logger.info("Initializing audio controller...")

        # Create controller
        _audio_controller = AudioIngestController()

        # Load audio sources from database
        saved_configs = AudioSourceConfigDB.query.all()
        logger.info(f"Loading {len(saved_configs)} audio source configurations from database")

        for db_config in saved_configs:
            try:
                # Parse source type
                source_type = AudioSourceType(db_config.source_type)

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
    """Initialize EAS monitoring system."""
    global _eas_monitor

    with app.app_context():
        from app_core.audio.eas_monitor import ContinuousEASMonitor, create_fips_filtering_callback
        from app_core.audio.broadcast_adapter import BroadcastAudioAdapter
        from app_core.audio.startup_integration import load_fips_codes_from_config

        logger.info("Initializing EAS monitor...")

        # Get broadcast queue for non-destructive audio access
        broadcast_queue = audio_controller.get_broadcast_queue()
        ingest_sample_rate = audio_controller.get_active_sample_rate() or 44100

        # Create broadcast adapter
        audio_adapter = BroadcastAudioAdapter(
            broadcast_queue=broadcast_queue,
            subscriber_id="eas-monitor",
            sample_rate=int(ingest_sample_rate)
        )

        # Load FIPS codes
        configured_fips = load_fips_codes_from_config()
        logger.info(f"Loaded {len(configured_fips)} FIPS codes for alert filtering")

        # Create alert callback with filtering
        def forward_alert_handler(alert):
            """Forward matched alerts."""
            from app_core.audio.alert_forwarding import forward_alert_to_api
            logger.info(f"Forwarding alert: {alert.get('event_code')} for {alert.get('location_codes')}")
            forward_alert_to_api(alert)

        alert_callback = create_fips_filtering_callback(
            configured_fips_codes=configured_fips,
            forward_callback=forward_alert_handler,
            logger_instance=logger
        )

        # Create EAS monitor (16 kHz for optimal SAME decoding)
        _eas_monitor = ContinuousEASMonitor(
            audio_manager=audio_adapter,
            sample_rate=16000,
            alert_callback=alert_callback,
            save_audio_files=True,
            audio_archive_dir="/tmp/eas-audio"
        )

        # Start monitoring
        if _eas_monitor.start():
            logger.info("✅ EAS monitor started successfully")
        else:
            logger.error("❌ EAS monitor failed to start")
            return None

        return _eas_monitor


def process_commands():
    """Process commands from Redis command queue.

    Supports commands from webapp container:
    - restart: Restart a receiver
    - get_spectrum: Get IQ samples for waterfall display
    """
    global _radio_manager, _redis_client

    if not _radio_manager or not _redis_client:
        return

    try:
        # Check for pending commands (non-blocking)
        command_json = _redis_client.lpop("sdr:commands")
        if not command_json:
            return

        command = json.loads(command_json)
        action = command.get("action")
        receiver_id = command.get("receiver_id")
        command_id = command.get("command_id", "unknown")

        logger.info(f"Processing command: {action} for receiver {receiver_id} (command_id={command_id})")

        if action == "restart":
            # Restart receiver
            instance = _radio_manager.get_receiver(receiver_id)
            if not instance:
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": f"Receiver '{receiver_id}' not found in RadioManager",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            else:
                try:
                    # Stop and restart
                    instance.stop()
                    time.sleep(0.5)  # Brief pause
                    instance.start()

                    status = instance.get_status()
                    result = {
                        "command_id": command_id,
                        "success": True,
                        "receiver_id": receiver_id,
                        "status": {
                            "locked": status.locked,
                            "signal_strength": status.signal_strength,
                            "running": instance.is_running() if hasattr(instance, 'is_running') else False,
                        },
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    logger.info(f"✅ Successfully restarted receiver {receiver_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to restart receiver {receiver_id}: {e}")
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": str(e),
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }

            # Publish result
            _redis_client.setex(
                f"sdr:command_result:{command_id}",
                30,  # 30 second TTL
                json.dumps(result)
            )

        elif action == "get_spectrum":
            # Get spectrum data for waterfall
            instance = _radio_manager.get_receiver(receiver_id)
            if not instance:
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": f"Receiver '{receiver_id}' not found",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            else:
                try:
                    num_samples = command.get("num_samples", 2048)
                    iq_samples = instance.get_samples(num_samples=num_samples)

                    if iq_samples is None or len(iq_samples) == 0:
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": "No samples available from receiver",
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }
                    else:
                        # Convert complex samples to list of [real, imag] pairs
                        samples_list = [[float(s.real), float(s.imag)] for s in iq_samples[:num_samples]]
                        result = {
                            "command_id": command_id,
                            "success": True,
                            "samples": samples_list,
                            "num_samples": len(samples_list),
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }
                except Exception as e:
                    logger.error(f"❌ Failed to get spectrum for receiver {receiver_id}: {e}")
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": str(e),
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }

            # Publish result
            _redis_client.setex(
                f"sdr:command_result:{command_id}",
                30,  # 30 second TTL
                json.dumps(result)
            )

        else:
            logger.warning(f"Unknown command action: {action}")

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse command JSON: {e}")
    except Exception as e:
        logger.error(f"Error processing command: {e}", exc_info=True)


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
        # Get radio manager stats (for app container to read via Redis)
        if _radio_manager:
            try:
                radio_stats: Dict[str, Any] = {
                    "available_drivers": list(_radio_manager.available_drivers().keys()),
                    "loaded_receiver_count": 0,
                    "running_receiver_count": 0,
                    "locked_receiver_count": 0,
                    "receivers_with_samples": 0,
                    "receivers": {}
                }
                
                if hasattr(_radio_manager, '_receivers'):
                    radio_stats["loaded_receiver_count"] = len(_radio_manager._receivers)
                    
                    for identifier, receiver_instance in _radio_manager._receivers.items():
                        try:
                            status = receiver_instance.get_status()
                            is_running = receiver_instance._running.is_set() if hasattr(receiver_instance, '_running') else False
                            is_locked = status.locked
                            
                            # Check if samples are available
                            samples_available = False
                            sample_count = 0
                            if hasattr(receiver_instance, 'get_samples'):
                                try:
                                    samples = receiver_instance.get_samples(num_samples=100)
                                    if samples is not None:
                                        samples_available = True
                                        sample_count = len(samples)
                                except Exception:
                                    pass
                            
                            if is_running:
                                radio_stats["running_receiver_count"] += 1
                            if is_locked:
                                radio_stats["locked_receiver_count"] += 1
                            if samples_available:
                                radio_stats["receivers_with_samples"] += 1
                            
                            radio_stats["receivers"][identifier] = {
                                "identifier": identifier,
                                "running": is_running,
                                "locked": is_locked,
                                "signal_strength": _sanitize_value(status.signal_strength),
                                "last_error": status.last_error,
                                "reported_at": status.reported_at.isoformat() if status.reported_at else None,
                                "samples_available": samples_available,
                                "sample_count": sample_count,
                                "config": {
                                    "frequency_hz": receiver_instance.config.frequency_hz,
                                    "sample_rate": receiver_instance.config.sample_rate,
                                    "driver": receiver_instance.config.driver,
                                    "modulation_type": receiver_instance.config.modulation_type,
                                } if hasattr(receiver_instance, 'config') else {}
                            }
                        except Exception as e:
                            logger.debug(f"Error getting receiver stats for '{identifier}': {e}")
                
                metrics["radio_manager"] = radio_stats
            except Exception as e:
                logger.error(f"Error getting radio manager stats: {e}")
        
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

        # Get EAS monitor stats (use get_status for comprehensive health metrics)
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
                                    'timestamp': time.time(),
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
                                    'timestamp': time.time(),
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
        
        # Publish spectrum data for each SDR receiver (for waterfall display in web UI)
        if _radio_manager:
            try:
                import numpy as np
                
                if hasattr(_radio_manager, '_receivers'):
                    for identifier, receiver_instance in _radio_manager._receivers.items():
                        try:
                            # Check if receiver is running
                            is_running = receiver_instance._running.is_set() if hasattr(receiver_instance, '_running') else False

                            # Get status for diagnostics
                            status = receiver_instance.get_status() if hasattr(receiver_instance, 'get_status') else None

                            # Always publish spectrum status (even if not running or no samples)
                            # This allows the UI to show appropriate messages
                            if not is_running:
                                # Receiver is stopped - publish minimal status
                                spectrum_payload = {
                                    'receiver_identifier': identifier,
                                    'timestamp': time.time(),
                                    'status': 'stopped',
                                    'spectrum': [],
                                    'fft_size': 0,
                                    'sample_rate': 0,
                                    'center_frequency': 0,
                                    'error': 'Receiver is not running'
                                }
                                pipe.setex(
                                    f"eas:spectrum:{identifier}",
                                    5,
                                    json.dumps(spectrum_payload)
                                )
                                continue

                            # Get IQ samples for spectrum
                            if hasattr(receiver_instance, 'get_samples'):
                                iq_samples = receiver_instance.get_samples(num_samples=2048)

                                if iq_samples is not None and len(iq_samples) > 0:
                                    # Compute FFT for spectrum display
                                    fft_size = min(len(iq_samples), 2048)
                                    window = np.hanning(fft_size)
                                    windowed = iq_samples[:fft_size] * window
                                    fft_result = np.fft.fftshift(np.fft.fft(windowed))
                                    
                                    # Convert to magnitude (dB)
                                    magnitude = np.abs(fft_result)
                                    magnitude = np.where(magnitude > 0, magnitude, FFT_MIN_MAGNITUDE)
                                    magnitude_db = 20 * np.log10(magnitude)
                                    
                                    # Normalize to 0-1 range for display
                                    min_db = float(magnitude_db.min())
                                    max_db = float(magnitude_db.max())
                                    if max_db > min_db:
                                        normalized = (magnitude_db - min_db) / (max_db - min_db)
                                    else:
                                        normalized = np.zeros_like(magnitude_db)
                                    
                                    # Get receiver config for frequency info
                                    config = receiver_instance.config if hasattr(receiver_instance, 'config') else None
                                    frequency_hz = config.frequency_hz if config else 0
                                    sample_rate = config.sample_rate if config else 0
                                    
                                    spectrum_payload = {
                                        'identifier': identifier,
                                        'spectrum': _sanitize_value(normalized.tolist()),
                                        'fft_size': fft_size,
                                        'sample_rate': sample_rate,
                                        'center_frequency': frequency_hz,
                                        'freq_min': frequency_hz - (sample_rate / 2) if sample_rate else 0,
                                        'freq_max': frequency_hz + (sample_rate / 2) if sample_rate else 0,
                                        'timestamp': time.time(),
                                        'status': 'available'
                                    }
                                    
                                    # Store spectrum data with short expiry (5 seconds - waterfall needs frequent updates)
                                    pipe.setex(
                                        f"eas:spectrum:{identifier}",
                                        5,
                                        json.dumps(spectrum_payload)
                                    )
                                    logger.debug(f"Published spectrum data for receiver '{identifier}'")
                                else:
                                    # Receiver is running but no samples available - publish status
                                    config = receiver_instance.config if hasattr(receiver_instance, 'config') else None
                                    sample_rate = config.sample_rate if config else 2400000
                                    center_freq = config.frequency_hz if config else 0

                                    error_msg = "Starting up" if status and status.locked else "Waiting for signal lock"
                                    spectrum_payload = {
                                        'identifier': identifier,
                                        'spectrum': [],
                                        'fft_size': 0,
                                        'sample_rate': sample_rate,
                                        'center_frequency': center_freq,
                                        'freq_min': center_freq - (sample_rate / 2) if sample_rate else 0,
                                        'freq_max': center_freq + (sample_rate / 2) if sample_rate else 0,
                                        'timestamp': time.time(),
                                        'status': 'no_samples',
                                        'error': error_msg
                                    }
                                    pipe.setex(
                                        f"eas:spectrum:{identifier}",
                                        5,
                                        json.dumps(spectrum_payload)
                                    )
                                    logger.debug(f"Published no-samples status for receiver '{identifier}': {error_msg}")

                        except Exception as e:
                            logger.debug(f"Error publishing spectrum for receiver '{identifier}': {e}")
            except ImportError:
                logger.debug("NumPy not available for spectrum generation")
            except Exception as e:
                logger.debug(f"Error publishing spectrum data: {e}")
        
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

        # Initialize radio receivers (SoapySDR)
        logger.info("Initializing radio receivers (SDR hardware)...")
        try:
            initialize_radio_receivers(app)
            logger.info("✅ Radio receivers initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize radio receivers: {e}", exc_info=True)
            logger.warning("⚠️ Continuing without radio receivers - SDR audio sources will not work!")
            # Continue - other audio sources (streams, files) might still work

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

            command_subscriber = AudioCommandSubscriber(audio_controller, auto_streaming)

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
        streaming_port = 5002  # Default port, will be overwritten if server starts
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
            # Use port 5002 to avoid conflict with hardware-service (which uses port 5001)
            streaming_port_str = os.environ.get('AUDIO_STREAMING_PORT', '5002')
            try:
                streaming_port = int(streaming_port_str)
                if streaming_port < 1 or streaming_port > 65535:
                    raise ValueError(f"Port {streaming_port} out of valid range (1-65535)")
            except ValueError as ve:
                logger.error(f"Invalid AUDIO_STREAMING_PORT '{streaming_port_str}': {ve}. Using default 5002.")
                streaming_port = 5002
            
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
        logger.info("   - EAS monitoring: ACTIVE")
        logger.info("   - Metrics publishing: ACTIVE")
        logger.info(f"   - Command subscriber: {'ACTIVE' if command_subscriber else 'DISABLED'}")
        logger.info(f"   - HTTP streaming: {'ACTIVE' if streaming_server_thread else 'DISABLED'} (port {streaming_port if streaming_server_thread else 'N/A'})")
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
                        samples = metrics["eas_monitor"].get("samples_processed", 0)
                        running = metrics["eas_monitor"].get("running", False)
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

        # Stop EAS monitor
        if _eas_monitor:
            logger.info("Stopping EAS monitor...")
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
