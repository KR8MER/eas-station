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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Global state
_running = True
_redis_client: Optional[redis.Redis] = None
_audio_controller = None
_eas_monitor = None
_auto_streaming_service = None


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

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{postgres_user}:{postgres_password}@"
        f"{postgres_host}:{postgres_port}/{postgres_db}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    return app


def initialize_radio_receivers(app):
    """Initialize and start radio receivers (low-level SoapySDR) from database configuration."""
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
        for db_config in saved_configs:
            if db_config.enabled and db_config.auto_start:
                try:
                    logger.info(f"Auto-starting source: {db_config.name}")
                    _audio_controller.start_source(db_config.name)
                except Exception as e:
                    logger.error(f"Error auto-starting '{db_config.name}': {e}")

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


def collect_metrics():
    """Collect metrics from audio controller and EAS monitor."""
    metrics = {
        "audio_controller": None,
        "eas_monitor": None,
        "broadcast_queue": None,
        "timestamp": time.time()
    }

    try:
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
        logger.info("Initializing radio receivers...")
        try:
            initialize_radio_receivers(app)
        except Exception as e:
            logger.warning(f"Failed to initialize radio receivers: {e}")
            # Continue - audio sources might still work

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

            logger.info("Adding running audio sources to Icecast streaming...")
            for source_name, source_adapter in audio_controller._sources.items():
                # Only add sources that are actually running
                if source_adapter.status != AudioSourceStatus.RUNNING:
                    logger.debug(f"Skipping {source_name} - not running (status: {source_adapter.status})")
                    continue

                try:
                    if auto_streaming.add_source(source_name, source_adapter):
                        logger.info(f"✅ Added running source {source_name} to Icecast streaming")
                    else:
                        logger.warning(f"Failed to add {source_name} to Icecast streaming")
                except Exception as e:
                    logger.error(f"Error adding {source_name} to Icecast: {e}", exc_info=True)

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

            command_subscriber = AudioCommandSubscriber(audio_controller)

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
                """Stream live audio from a specific source as WAV for VU meters."""
                import struct
                import io
                import numpy as np
                from app_core.audio.ingest import AudioSourceStatus
                
                def generate_wav_stream(adapter):
                    """Generator that yields WAV-formatted audio chunks."""
                    # Get configuration
                    sample_rate = adapter.config.sample_rate
                    channels = adapter.config.channels
                    bits_per_sample = 16
                    
                    # Send WAV header
                    wav_header = io.BytesIO()
                    wav_header.write(b'RIFF')
                    wav_header.write(struct.pack('<I', 0xFFFFFFFF))
                    wav_header.write(b'WAVE')
                    wav_header.write(b'fmt ')
                    wav_header.write(struct.pack('<I', 16))
                    wav_header.write(struct.pack('<H', 1))
                    wav_header.write(struct.pack('<H', channels))
                    wav_header.write(struct.pack('<I', sample_rate))
                    wav_header.write(struct.pack('<I', sample_rate * channels * bits_per_sample // 8))
                    wav_header.write(struct.pack('<H', channels * bits_per_sample // 8))
                    wav_header.write(struct.pack('<H', bits_per_sample))
                    wav_header.write(b'data')
                    wav_header.write(struct.pack('<I', 0xFFFFFFFF))
                    yield wav_header.getvalue()
                    
                    # Stream audio chunks
                    silence_chunk_duration = 0.05
                    silence_samples = int(sample_rate * channels * silence_chunk_duration)
                    
                    while _running:
                        try:
                            audio_chunk = adapter.get_audio_chunk(timeout=0.2)
                            if audio_chunk is None:
                                # Yield silence to keep stream alive
                                silence_chunk = np.zeros(silence_samples, dtype=np.int16)
                                yield silence_chunk.tobytes()
                                time.sleep(0.01)
                                continue
                            
                            if not isinstance(audio_chunk, np.ndarray):
                                audio_chunk = np.array(audio_chunk, dtype=np.float32)
                            
                            pcm_data = (np.clip(audio_chunk, -1.0, 1.0) * 32767).astype(np.int16)
                            yield pcm_data.tobytes()
                        except Exception as e:
                            logger.debug(f"Error in stream generator: {e}")
                            silence_chunk = np.zeros(silence_samples, dtype=np.int16)
                            yield silence_chunk.tobytes()
                            time.sleep(0.01)
                
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
                        stream_with_context(generate_wav_stream(adapter)),
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
            server = make_server('0.0.0.0', 5001, stream_app, threaded=True)
            streaming_server_thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
                name="StreamingHTTPServer"
            )
            streaming_server_thread.start()
            logger.info("✅ HTTP streaming server started on port 5001")
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
        logger.info(f"   - HTTP streaming: {'ACTIVE' if streaming_server_thread else 'DISABLED'} (port 5001)")
        logger.info("=" * 80)

        # Main loop: publish metrics every 5 seconds
        last_metrics_time = 0
        metrics_interval = 5.0

        while _running:
            try:
                current_time = time.time()

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

                # Sleep briefly
                time.sleep(1)

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
