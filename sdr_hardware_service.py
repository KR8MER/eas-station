#!/usr/bin/env python3
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

"""
SDR Hardware Service

This service handles ONLY SDR hardware operations (exclusive USB access):
- SoapySDR device management (open, configure, read)
- Dual-thread USB reading for reliable operation
- Publishing IQ samples to Redis for downstream consumers
- Publishing SDR health metrics to Redis

Architecture:
                    ┌─────────────────┐
                    │   SoapySDR      │
                    │   USB Device    │
                    └────────┬────────┘
                             │
            ┌───────────────────┴─────────────────┐
            │   sdr_hardware_service.py        │
            │   (This file - USB access)       │
            │                                  │
            │  ┌───────────┐  ┌────────────┐  │
            │  │USB Reader │──│Ring Buffer │  │
            │  │  Thread   │  └─────┬──────┘  │
            │  └───────────┘        │         │
            │                       ▼         │
            │              ┌────────────┐     │
            │              │ Publisher  │     │
            │              │   Thread   │     │
            │              └─────┬──────┘     │
            └────────────────────┼────────────┘
                                 │ Redis pub/sub
                                 │ sdr:samples:{id}
                                 ▼
            ┌────────────────────────────────────┐
            │   eas_monitoring_service.py        │
            │   (No USB access needed)           │
            │                                    │
            │  - IQ demodulation (FM/AM/NFM)     │
            │  - EAS/SAME decoding               │
            │  - Icecast streaming               │
            └────────────────────────────────────┘

Benefits:
- SDR crashes don't affect audio processing
- SDR service can be restarted without losing audio pipeline state
- Clear separation of concerns
- USB-specific permissions isolated to SDR container
- Audio processing can run on separate hardware if needed
"""

import os
import sys
import time
import signal
import logging
import json
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Configure logging early
logging.basicConfig(
    level=logging.DEBUG,  # Changed from INFO to DEBUG to show diagnostic logs
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Load environment variables from persistent config volume
_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    if os.path.exists(_config_path):
        load_dotenv(_config_path, override=True)
        logger.info(f"✅ Loaded environment from: {_config_path}")
    else:
        logger.warning(f"⚠️  CONFIG_PATH set but file not found: {_config_path}")
        load_dotenv(override=True)
else:
    load_dotenv(override=True)

# Import centralized Redis configuration
from app_core.config.redis_config import get_redis_host, get_redis_port, get_redis_db

# Redis configuration
REDIS_HOST = get_redis_host()
REDIS_PORT = get_redis_port()
REDIS_DB = get_redis_db()

# SDR sample publishing configuration
# IQ samples are published in chunks to balance latency vs overhead
SDR_SAMPLE_CHUNK_SIZE = 32768  # Samples per Redis message
SDR_SAMPLE_CHANNEL = "sdr:samples"  # Redis pub/sub channel for IQ data
SDR_METRICS_KEY = "sdr:metrics"  # Redis hash for SDR health metrics
SDR_SPECTRUM_KEY_PREFIX = "sdr:spectrum:"  # Per-receiver spectrum data

# Publisher loop timing - adaptive based on buffer fill level
PUBLISHER_SLEEP_MIN_MS = 1   # Minimum sleep when buffer is filling up
PUBLISHER_SLEEP_MAX_MS = 10  # Maximum sleep when buffer is low

# Spectrum computation constants
FFT_SIZE = 2048
FFT_MIN_MAGNITUDE = 1e-10
SPECTRUM_DB_MIN = -80.0
SPECTRUM_DB_MAX = 0.0


@dataclass
class SDRServiceState:
    """Global state for the SDR service with thread-safe access via lock."""
    running: bool = True
    redis_client: Optional[Any] = None
    radio_manager: Optional[Any] = None
    publisher_thread: Optional[threading.Thread] = None
    flask_app: Optional[Any] = None  # Store Flask app for database access
    last_metrics_time: float = 0.0
    metrics_interval: float = 1.0  # Publish metrics every second
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = SDRServiceState()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _state.running = False


def verify_soapysdr_installation():
    """Verify SoapySDR and NumPy are properly installed."""
    logger.info("Verifying SDR dependencies...")
    
    # Get Python version for diagnostics
    import sys
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    logger.info(f"Running Python {python_version}")

    # Check SoapySDR Python bindings
    try:
        import SoapySDR
        logger.info(f"✅ SoapySDR Python bindings installed (API version: {SoapySDR.getAPIVersion()})")
    except ImportError as e:
        logger.error("❌ SoapySDR Python bindings NOT installed")
        logger.error("")
        logger.error("=" * 80)
        logger.error("CRITICAL: SoapySDR Python bindings are missing")
        logger.error("=" * 80)
        logger.error("")
        
        # Python 3.13 specific guidance
        if sys.version_info.major == 3 and sys.version_info.minor >= 13:
            logger.error(f"⚠️  You are running Python {python_version}")
            logger.error("   The python3-soapysdr package may not be available for Python 3.13 yet.")
            logger.error("")
            logger.error("Solutions:")
            logger.error("  1. Check if python3-soapysdr is available for your Python version:")
            logger.error(f"     apt-cache policy python3-soapysdr")
            logger.error("")
            logger.error("  2. If not available, you need to build SoapySDR Python bindings from source:")
            logger.error("     # Install build dependencies")
            logger.error("     sudo apt-get install cmake g++ libpython3-dev swig")
            logger.error("     # Clone and build SoapySDR")
            logger.error("     git clone https://github.com/pothosware/SoapySDR.git")
            logger.error("     cd SoapySDR && mkdir build && cd build")
            logger.error(f"     cmake .. -DPYTHON3_EXECUTABLE=/usr/bin/python3")
            logger.error("     make -j4 && sudo make install")
            logger.error("     sudo ldconfig")
            logger.error("")
            logger.error("  3. Alternatively, downgrade to Python 3.11 or 3.12:")
            logger.error("     sudo apt-get install python3.12 python3.12-venv")
            logger.error("     Then reinstall EAS Station using Python 3.12")
        else:
            logger.error("Standard installation (Python 3.11/3.12):")
            logger.error("  1. Install the package:")
            logger.error("     sudo apt-get update")
            logger.error("     sudo apt-get install python3-soapysdr")
            logger.error("")
            logger.error("  2. Verify installation:")
            logger.error(f"     python{python_version} -c 'import SoapySDR; print(SoapySDR.getAPIVersion())'")
        
        logger.error("")
        logger.error("  3. Ensure PYTHONPATH includes system site-packages:")
        logger.error("     Run: sudo ./update.sh")
        logger.error("     This will configure PYTHONPATH for your Python version")
        logger.error("=" * 80)
        logger.error(f"   Error details: {e}")
        return False

    # Check NumPy
    try:
        import numpy as np
        logger.info(f"✅ NumPy installed (version: {np.__version__})")
    except ImportError as e:
        logger.error("❌ NumPy NOT installed")
        logger.error(f"   Error: {e}")
        return False

    # Test USB device enumeration
    try:
        devices = SoapySDR.Device.enumerate()
        logger.info(f"✅ USB device enumeration working ({len(devices)} device(s) found)")
        if devices:
            for idx, dev in enumerate(devices):
                dev_dict = dict(dev)
                driver = dev_dict.get('driver', 'unknown')
                serial = dev_dict.get('serial', 'N/A')
                logger.info(f"   Device {idx}: {driver} (serial: {serial})")
        else:
            logger.warning("⚠️  No SDR devices found - check USB connections and permissions")
    except Exception as e:
        logger.error(f"❌ USB device enumeration failed: {e}")
        logger.error("   Check USB permissions: devices=/dev/bus/usb, privileged=true")
        return False

    return True


def get_redis_client(retry=True):
    """Get or create Redis client with retry logic."""
    if _state.redis_client is not None:
        try:
            # Verify connection is still alive
            _state.redis_client.ping()
            return _state.redis_client
        except Exception:
            logger.warning("Redis connection lost, reconnecting...")
            _state.redis_client = None

    max_retries = 5 if retry else 1
    for attempt in range(max_retries):
        try:
            import redis

            # Use app_core redis client for robust connection handling
            from app_core.redis_client import get_redis_client as get_robust_client

            _state.redis_client = get_robust_client(
                max_retries=5,
                initial_backoff=1.0,
                max_backoff=30.0
            )
            logger.info(f"✅ Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            return _state.redis_client
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = min(2 ** attempt, 30)
                logger.warning(f"Failed to connect to Redis (attempt {attempt + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"❌ Failed to connect to Redis after {max_retries} attempts: {e}")
                raise


def initialize_database():
    """Initialize database connection for receiver configuration with retry logic."""
    from app_core.extensions import db
    from flask import Flask

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    # Log connection info without credentials (extract username@host:port/db from URL)
    import re
    match = re.match(r'postgresql.*://([^:]+):.*@([^:]+):(\d+)/(.+)', database_url)
    if match:
        user, host, port, db_name = match.groups()
        logger.info(f"Connecting to database: {user}@{host}:{port}/{db_name}")
    else:
        logger.info(f"Connecting to database with provided DATABASE_URL")

    # Retry database connection with exponential backoff
    max_retries = 10
    for attempt in range(max_retries):
        try:
            app = Flask(__name__)
            app.config["SQLALCHEMY_DATABASE_URI"] = database_url
            app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
            app.config["SQLALCHEMY_ECHO"] = False

            db.init_app(app)

            # Test connection by executing a simple query
            with app.app_context():
                from sqlalchemy import text
                db.session.execute(text("SELECT 1"))

            logger.info(f"✅ Database connection established")
            # Store app instance for later use (e.g., reload_receivers command)
            _state.flask_app = app
            return app

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = min(2 ** attempt, 30)
                logger.warning(f"Database connection failed (attempt {attempt + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"❌ Failed to connect to database after {max_retries} attempts")
                logger.error(f"   Error: {e}")
                raise


def _auto_detect_and_configure_receivers(app):
    """Auto-detect connected SDR devices and create receiver configurations.

    Called when no receivers are configured in the database. Discovers connected
    SDR hardware and creates default configurations for NOAA Weather Radio monitoring.

    Returns:
        List of RadioReceiver objects that were auto-configured, or empty list if none found.
    """
    from app_core.radio.discovery import enumerate_devices
    from app_core.models import RadioReceiver
    from app_core.extensions import db

    # Default NOAA Weather Radio frequency (WX7 - most common)
    DEFAULT_FREQUENCY_HZ = 162_550_000

    # Driver-specific defaults
    DRIVER_DEFAULTS = {
        'airspy': {
            'sample_rate': 2_500_000,  # Airspy R2 only supports 2.5 MHz or 10 MHz
            'gain': 21,
            'modulation_type': 'NFM',
            'audio_sample_rate': 48000,
        },
        'rtlsdr': {
            'sample_rate': 2_400_000,
            'gain': 49.6,
            'modulation_type': 'NFM',
            'audio_sample_rate': 48000,
        },
        'hackrf': {
            'sample_rate': 2_000_000,
            'gain': 40,
            'modulation_type': 'NFM',
            'audio_sample_rate': 48000,
        },
    }

    try:
        devices = enumerate_devices()
        if not devices:
            logger.info("📡 Auto-detection: No SDR devices found")
            return []

        logger.info(f"📡 Auto-detection: Found {len(devices)} device(s)")

        configured_receivers = []

        # Note: We're already inside an app context from initialize_radio_receivers
        for device in devices:
            driver = device.get('driver', 'unknown').lower()
            serial = device.get('serial')
            label = device.get('label', f'SDR Device')

            if not serial:
                logger.warning(f"  Skipping device without serial: {label}")
                continue

            # Check if already configured (by serial)
            existing = RadioReceiver.query.filter_by(serial=serial).first()
            if existing:
                logger.info(f"  Device {serial} already configured as '{existing.identifier}'")
                if existing.enabled:
                    configured_receivers.append(existing)
                continue

            # Get driver-specific defaults
            defaults = DRIVER_DEFAULTS.get(driver, {
                'sample_rate': 2_400_000,
                'gain': 30,
                'modulation_type': 'NFM',
                'audio_sample_rate': 48000,
            })

            # Create unique identifier
            identifier = f"{driver}-{serial[-8:]}" if len(serial) > 8 else f"{driver}-{serial}"
            display_name = f"{label} (Auto-configured)"

            logger.info(f"  📻 Auto-configuring: {identifier}")
            logger.info(f"     Driver: {driver}, Serial: {serial}")
            logger.info(f"     Frequency: {DEFAULT_FREQUENCY_HZ / 1e6:.3f} MHz (NOAA WX7)")
            logger.info(f"     Sample rate: {defaults['sample_rate'] / 1e6:.1f} MHz")

            # Create receiver configuration
            receiver = RadioReceiver(
                identifier=identifier,
                display_name=display_name,
                driver=driver,
                serial=serial,
                frequency_hz=DEFAULT_FREQUENCY_HZ,
                sample_rate=defaults['sample_rate'],
                audio_sample_rate=defaults.get('audio_sample_rate', 48000),
                gain=defaults.get('gain'),
                modulation_type=defaults.get('modulation_type', 'NFM'),
                audio_output=True,
                enabled=True,
                auto_start=True,
                notes=f"Auto-configured on {time.strftime('%Y-%m-%d %H:%M:%S')}. "
                      f"Tune frequency in Settings → Radio Receivers for your area.",
            )

            db.session.add(receiver)
            configured_receivers.append(receiver)

        if configured_receivers:
            db.session.commit()
            logger.info(f"✅ Auto-configured {len(configured_receivers)} receiver(s)")

            # Publish status to Redis
            try:
                redis_client = get_redis_client(retry=False)
                redis_client.setex(
                    "sdr:status",
                    300,
                    json.dumps({
                        "status": "auto_configured",
                        "message": f"Auto-configured {len(configured_receivers)} receiver(s)",
                        "receivers": [r.identifier for r in configured_receivers],
                        "timestamp": time.time()
                    })
                )
            except Exception:
                pass

        return configured_receivers

    except Exception as e:
        logger.error(f"Auto-detection failed: {e}", exc_info=True)
        return []


def initialize_radio_receivers(app):
    """Initialize and start SDR receivers from database configuration."""
    try:
        with app.app_context():
            from app_core.models import RadioReceiver
            from app_core.extensions import get_radio_manager, db

            receivers = RadioReceiver.query.filter_by(enabled=True).all()
            if not receivers:
                # No receivers configured - try auto-detection
                logger.info("No receivers configured - attempting auto-detection...")
                receivers = _auto_detect_and_configure_receivers(app)

            if not receivers:
                logger.error("=" * 80)
                logger.error("❌ NO SDR RECEIVERS CONFIGURED OR DETECTED")
                logger.error("=" * 80)
                logger.error("The SDR service will run but will NOT receive any radio signals.")
                logger.error("")
                logger.error("To configure receivers:")
                logger.error("  1. Go to the web interface: Settings → Radio Receivers")
                logger.error("  2. Add at least one receiver configuration")
                logger.error("  3. Enable the receiver and set auto_start=true")
                logger.error("  4. Restart the SDR hardware service process")
                logger.error("")
                logger.error("Or connect an SDR device (Airspy, RTL-SDR) and restart the service.")
                logger.error("The service will continue running and wait for configuration via")
                logger.error("the 'reload_receivers' command through Redis.")
                logger.error("=" * 80)

                # Publish warning status to Redis so UI can show alert
                try:
                    redis_client = get_redis_client(retry=False)
                    redis_client.setex(
                        "sdr:status",
                        300,  # 5 minute TTL
                        json.dumps({
                            "status": "no_receivers_configured",
                            "message": "No SDR receivers configured or detected",
                            "timestamp": time.time()
                        })
                    )
                except Exception:
                    pass  # Don't fail if Redis publish fails

                return None

            radio_manager = get_radio_manager()
            _state.radio_manager = radio_manager

            radio_manager.configure_from_records(receivers)
            logger.info(f"Configured {len(receivers)} radio receiver(s) from database")

            auto_start = [r for r in receivers if r.auto_start]
            if auto_start:
                radio_manager.start_all()
                logger.info(f"✅ Started {len(auto_start)} receiver(s) with auto_start")
            else:
                logger.warning("⚠️  No receivers have auto_start enabled - they must be started manually")

            return radio_manager

    except Exception as exc:
        logger.error(f"❌ Failed to initialize radio receivers: {exc}", exc_info=True)
        raise


def compute_spectrum(samples, numpy_module) -> Optional[list]:
    """Compute normalized spectrum from IQ samples."""
    try:
        if len(samples) < FFT_SIZE:
            return None
        
        # Remove DC offset
        samples_slice = samples[:FFT_SIZE]
        samples_centered = samples_slice - numpy_module.mean(samples_slice)
        
        # Apply window and compute FFT
        window = numpy_module.hanning(FFT_SIZE)
        windowed = samples_centered * window
        fft_result = numpy_module.fft.fftshift(numpy_module.fft.fft(windowed))
        
        # Convert to magnitude (dB)
        magnitude = numpy_module.abs(fft_result)
        magnitude = numpy_module.where(magnitude > 0, magnitude, FFT_MIN_MAGNITUDE)
        magnitude_db = 20 * numpy_module.log10(magnitude)
        
        # Normalize to 0-1 range
        normalized = numpy_module.clip(
            (magnitude_db - SPECTRUM_DB_MIN) / (SPECTRUM_DB_MAX - SPECTRUM_DB_MIN),
            0.0, 1.0
        )
        
        return normalized.tolist()
    except Exception as e:
        logger.debug(f"Spectrum computation error: {e}")
        return None


def publish_samples_and_metrics():
    """Publisher thread: reads from receivers and publishes to Redis."""
    logger.info("Sample publisher thread started")
    
    try:
        import numpy as np
        import base64
        import zlib
    except ImportError:
        logger.error("NumPy not available, cannot publish samples")
        return
    
    redis_client = get_redis_client()
    last_spectrum_time = {}  # Per-receiver spectrum update tracking
    spectrum_interval = 0.1  # 100ms spectrum updates
    
    while _state.running:
        try:
            radio_manager = _state.radio_manager
            if radio_manager is None or not hasattr(radio_manager, '_receivers'):
                time.sleep(0.1)
                continue
            
            current_time = time.time()
            
            for identifier, receiver in radio_manager._receivers.items():
                try:
                    # Check if receiver is running
                    is_running = receiver._running.is_set() if hasattr(receiver, '_running') else False
                    if not is_running:
                        continue
                    
                    # Get samples from receiver
                    if hasattr(receiver, 'get_samples'):
                        samples = receiver.get_samples(num_samples=SDR_SAMPLE_CHUNK_SIZE)
                        
                        if samples is not None and len(samples) > 0:
                            # Publish IQ samples to Redis channel
                            # Use compressed base64 encoding for efficiency
                            # Complex samples are interleaved as [real, imag, real, imag, ...]
                            interleaved = np.empty(len(samples) * 2, dtype=np.float32)
                            interleaved[0::2] = samples.real
                            interleaved[1::2] = samples.imag
                            compressed = zlib.compress(interleaved.tobytes(), level=1)  # Fast compression
                            encoded = base64.b64encode(compressed).decode('ascii')
                            
                            # Get effective sample rate (after early decimation for high-rate SDRs)
                            if hasattr(receiver, 'get_effective_sample_rate'):
                                effective_rate = receiver.get_effective_sample_rate()
                            else:
                                effective_rate = receiver.config.sample_rate

                            sample_data = {
                                'receiver_id': identifier,
                                'timestamp': current_time,
                                'sample_count': len(samples),
                                'sample_rate': effective_rate,  # Use effective rate after decimation
                                'center_frequency': receiver.config.frequency_hz,
                                'encoding': 'zlib+base64',  # Indicate encoding method
                                'samples': encoded,
                            }
                            
                            redis_client.publish(
                                f"{SDR_SAMPLE_CHANNEL}:{identifier}",
                                json.dumps(sample_data)
                            )
                            
                            # Compute and publish spectrum (rate-limited)
                            # Note: Spectrum computed from decimated samples, so uses effective rate
                            last_time = last_spectrum_time.get(identifier, 0)
                            if current_time - last_time >= spectrum_interval:
                                spectrum = compute_spectrum(samples, np)
                                if spectrum is not None:
                                    spectrum_payload = {
                                        'identifier': identifier,
                                        'spectrum': spectrum,
                                        'fft_size': FFT_SIZE,
                                        'sample_rate': effective_rate,  # Use effective rate for decimated samples
                                        'center_frequency': receiver.config.frequency_hz,
                                        'timestamp': current_time,
                                        'status': 'available'
                                    }
                                    redis_client.setex(
                                        f"{SDR_SPECTRUM_KEY_PREFIX}{identifier}",
                                        5,  # 5 second TTL
                                        json.dumps(spectrum_payload)
                                    )
                                last_spectrum_time[identifier] = current_time
                    
                    # Get and publish ring buffer stats if available
                    if hasattr(receiver, 'get_ring_buffer_stats'):
                        ring_stats = receiver.get_ring_buffer_stats()
                        if ring_stats:
                            redis_client.hset(
                                f"sdr:ring_buffer:{identifier}",
                                mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                                        for k, v in ring_stats.items()}
                            )
                            redis_client.expire(f"sdr:ring_buffer:{identifier}", 10)
                
                except Exception as e:
                    logger.debug(f"Error publishing for receiver {identifier}: {e}")
            
            # Publish aggregated metrics periodically
            if current_time - _state.last_metrics_time >= _state.metrics_interval:
                publish_sdr_metrics(redis_client)
                _state.last_metrics_time = current_time
            
            # Adaptive sleep based on buffer status
            # Sleep less when buffers are filling up, more when they're low
            sleep_time_ms = PUBLISHER_SLEEP_MAX_MS
            if radio_manager and hasattr(radio_manager, '_receivers'):
                for receiver in radio_manager._receivers.values():
                    if hasattr(receiver, 'get_ring_buffer_stats'):
                        stats = receiver.get_ring_buffer_stats()
                        if stats and stats.get('fill_percentage', 0) > 50:
                            # Buffer filling up, reduce sleep time
                            sleep_time_ms = PUBLISHER_SLEEP_MIN_MS
                            break
            time.sleep(sleep_time_ms / 1000.0)
            
        except Exception as e:
            logger.error(f"Publisher thread error: {e}", exc_info=True)
            time.sleep(1.0)
    
    logger.info("Sample publisher thread exiting")


def publish_sdr_metrics(redis_client):
    """Publish aggregated SDR health metrics to Redis."""
    try:
        radio_manager = _state.radio_manager
        if radio_manager is None:
            return
        
        metrics = {
            'service': 'sdr_service',
            'timestamp': time.time(),
            'pid': os.getpid(),
            'receivers': {}
        }
        
        if hasattr(radio_manager, '_receivers'):
            for identifier, receiver in radio_manager._receivers.items():
                try:
                    status = receiver.get_status()
                    is_running = receiver._running.is_set() if hasattr(receiver, '_running') else False

                    # Check if samples are available
                    samples_available = False
                    sample_count = 0
                    if hasattr(receiver, 'get_samples'):
                        try:
                            # Try to peek at samples without consuming them
                            test_samples = receiver.get_samples(num_samples=1)
                            if test_samples is not None and len(test_samples) > 0:
                                samples_available = True
                                # Get actual buffer stats for sample count
                                if hasattr(receiver, 'get_ring_buffer_stats'):
                                    ring_stats = receiver.get_ring_buffer_stats()
                                    if ring_stats:
                                        sample_count = ring_stats.get('samples_available', 0)
                        except Exception:
                            pass

                    # Build config object (webapp expects nested structure)
                    config = {
                        'frequency_hz': receiver.config.frequency_hz,
                        'sample_rate': receiver.config.sample_rate,
                        'driver': receiver.config.driver,
                        'modulation_type': receiver.config.modulation_type if hasattr(receiver.config, 'modulation_type') else None,
                    }

                    receiver_metrics = {
                        'running': is_running,
                        'locked': status.locked,
                        'signal_strength': float(status.signal_strength) if status.signal_strength else 0.0,
                        'last_error': status.last_error,
                        'samples_available': samples_available,
                        'sample_count': sample_count,
                        'reported_at': time.time(),
                        'config': config,
                    }

                    # Add ring buffer stats if available
                    if hasattr(receiver, 'get_ring_buffer_stats'):
                        ring_stats = receiver.get_ring_buffer_stats()
                        if ring_stats:
                            receiver_metrics['ring_buffer'] = ring_stats

                    # Add connection health if available
                    if hasattr(receiver, 'get_connection_health'):
                        health = receiver.get_connection_health()
                        if health:
                            receiver_metrics['connection_health'] = health

                    metrics['receivers'][identifier] = receiver_metrics
                    
                except Exception as e:
                    logger.debug(f"Error getting metrics for {identifier}: {e}")
        
        # Publish to Redis
        redis_client.setex(
            SDR_METRICS_KEY,
            30,  # 30 second TTL
            json.dumps(metrics)
        )
        
        # Also publish heartbeat
        redis_client.setex(
            "sdr:heartbeat",
            10,
            json.dumps({
                'timestamp': time.time(),
                'pid': os.getpid(),
                'receiver_count': len(metrics.get('receivers', {}))
            })
        )
        
    except Exception as e:
        logger.error(f"Error publishing SDR metrics: {e}")


def process_commands(redis_client):
    """Process control commands from Redis."""
    try:
        command_json = redis_client.lpop("sdr:commands")
        if not command_json:
            return
        
        command = json.loads(command_json)
        action = command.get("action")
        receiver_id = command.get("receiver_id")
        command_id = command.get("command_id", "unknown")
        
        logger.info(f"Processing command: {action} for {receiver_id}")

        # Handle actions that don't require radio_manager first
        if action == "discover_devices":
            # Enumerate all connected SoapySDR devices
            try:
                from app_core.radio.discovery import enumerate_devices
                devices = enumerate_devices()
                if devices:
                    logger.info(f"📡 Device discovery found {len(devices)} device(s):")
                    for dev in devices:
                        driver = dev.get('driver', 'unknown')
                        serial = dev.get('serial', 'N/A')
                        label = dev.get('label', 'Unknown')
                        logger.info(f"   - {driver}: {label} (serial={serial})")
                else:
                    logger.warning("📡 Device discovery: No SDR devices found. Check USB connections and permissions.")
                result = {
                    "command_id": command_id,
                    "success": True,
                    "devices": devices,
                    "count": len(devices)
                }
            except Exception as e:
                logger.error(f"Failed to enumerate devices: {e}")
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": str(e),
                    "devices": []
                }
        elif action == "reload_receivers":
            # Reload receiver configuration from database
            # This is called when receivers are added/updated/deleted via webapp
            try:
                from app_core.models import RadioReceiver
                from app_core.extensions import get_radio_manager

                # Get the Flask app instance (stored during initialization)
                # This ensures proper database session management
                if not _state.flask_app:
                    raise RuntimeError("Flask app not initialized - cannot reload receivers")

                with _state.flask_app.app_context():
                    receivers = RadioReceiver.query.filter_by(enabled=True).all()

                    radio_manager = _state.radio_manager
                    if not radio_manager:
                        radio_manager = get_radio_manager()
                        _state.radio_manager = radio_manager

                    # Stop all existing receivers
                    if hasattr(radio_manager, '_receivers'):
                        for identifier in list(radio_manager._receivers.keys()):
                            try:
                                receiver = radio_manager.get_receiver(identifier)
                                if receiver:
                                    receiver.stop()
                            except Exception as e:
                                logger.warning(f"Error stopping receiver {identifier}: {e}")

                    # Reconfigure from database
                    radio_manager.configure_from_records(receivers)
                    logger.info(f"Reloaded {len(receivers)} receiver(s) from database")

                    # Auto-start enabled receivers
                    auto_start_count = 0
                    for r in receivers:
                        if r.auto_start:
                            instance = radio_manager.get_receiver(r.identifier)
                            if instance:
                                try:
                                    instance.start()
                                    auto_start_count += 1
                                except Exception as e:
                                    logger.error(f"Failed to auto-start {r.identifier}: {e}")

                    result = {
                        "command_id": command_id,
                        "success": True,
                        "receivers_configured": len(receivers),
                        "receivers_started": auto_start_count
                    }
            except Exception as e:
                logger.error(f"Failed to reload receivers: {e}", exc_info=True)
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": str(e)
                }
        else:
            # Actions below require radio_manager to be initialized
            radio_manager = _state.radio_manager
            if not radio_manager:
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": "Radio manager not initialized"
                }
            elif action == "restart":
                receiver = radio_manager.get_receiver(receiver_id)
                if receiver:
                    try:
                        receiver.stop()
                        time.sleep(0.5)
                        receiver.start()
                        status = {
                            "locked": getattr(receiver, 'locked', False),
                            "signal_strength": getattr(receiver, 'signal_strength', 0),
                            "running": getattr(receiver, 'running', False)
                        }
                        result = {
                            "command_id": command_id,
                            "success": True,
                            "message": f"Receiver {receiver_id} restarted",
                            "status": status
                        }
                    except Exception as e:
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": str(e)
                        }
                else:
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": f"Receiver {receiver_id} not found"
                    }
            elif action == "tune_frequency":
                # Live retune of an active receiver — does NOT stop the stream
                # so the audio system keeps decoding without interruption.
                # On failure the webapp can fall back to reload_receivers.
                receiver = radio_manager.get_receiver(receiver_id)
                if not receiver:
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": f"Receiver {receiver_id} not found",
                    }
                else:
                    freq_hz = command.get("frequency_hz")
                    try:
                        freq_hz = float(freq_hz) if freq_hz is not None else None
                    except (TypeError, ValueError):
                        freq_hz = None
                    if freq_hz is None or freq_hz <= 0:
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": "frequency_hz is required and must be positive",
                        }
                    else:
                        try:
                            tuned = receiver.set_frequency(freq_hz)
                        except Exception as e:
                            logger.error(
                                "tune_frequency failed for %s: %s",
                                receiver_id, e, exc_info=True,
                            )
                            tuned = False
                        if tuned:
                            # Persist to database so a future restart keeps the tune.
                            try:
                                if _state.flask_app:
                                    with _state.flask_app.app_context():
                                        from app_core.models import RadioReceiver
                                        from app_core.extensions import db
                                        row = RadioReceiver.query.filter_by(
                                            identifier=receiver_id
                                        ).first()
                                        if row is not None:
                                            row.frequency_hz = freq_hz
                                            db.session.commit()
                            except Exception as e:
                                logger.warning(
                                    "tune_frequency: retune ok but DB update failed for %s: %s",
                                    receiver_id, e,
                                )
                            result = {
                                "command_id": command_id,
                                "success": True,
                                "frequency_hz": freq_hz,
                                "live": True,
                            }
                        else:
                            # Driver can't live-retune (or device not running) —
                            # caller should fall back to reload_receivers.
                            result = {
                                "command_id": command_id,
                                "success": False,
                                "live": False,
                                "error": (
                                    "Live retune not supported or device not running; "
                                    "caller should fall back to reload_receivers"
                                ),
                            }
            elif action == "stop":
                receiver = radio_manager.get_receiver(receiver_id)
                if receiver:
                    receiver.stop()
                    result = {"command_id": command_id, "success": True}
                else:
                    result = {"command_id": command_id, "success": False, "error": "Not found"}
            elif action == "start":
                receiver = radio_manager.get_receiver(receiver_id)
                if receiver:
                    receiver.start()
                    result = {"command_id": command_id, "success": True}
                else:
                    result = {"command_id": command_id, "success": False, "error": "Not found"}
            elif action == "get_spectrum":
                # Get spectrum data for waterfall display
                receiver = radio_manager.get_receiver(receiver_id)
                if not receiver:
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": f"Receiver '{receiver_id}' not found"
                    }
                else:
                    try:
                        num_samples = command.get("num_samples", 2048)
                        iq_samples = receiver.get_samples(num_samples=num_samples)

                        if iq_samples is None or len(iq_samples) == 0:
                            result = {
                                "command_id": command_id,
                                "success": False,
                                "error": "No samples available from receiver"
                            }
                        else:
                            # Convert complex samples to list of [real, imag] pairs
                            samples_list = [[float(s.real), float(s.imag)] for s in iq_samples[:num_samples]]
                            result = {
                                "command_id": command_id,
                                "success": True,
                                "samples": samples_list,
                                "num_samples": len(samples_list)
                            }
                    except Exception as e:
                        logger.error(f"Failed to get spectrum for receiver {receiver_id}: {e}")
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": str(e)
                        }
            else:
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
        
        redis_client.setex(
            f"sdr:command_result:{command_id}",
            30,
            json.dumps(result)
        )
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid command JSON: {e}")
    except Exception as e:
        logger.error(f"Error processing command: {e}")


def main():
    """Main service loop."""
    logger.info("=" * 80)
    logger.info("EAS Station - Standalone SDR Service")
    logger.info("=" * 80)
    logger.info("This service handles ONLY SDR hardware operations:")
    logger.info("  - SoapySDR device management")
    logger.info("  - Dual-thread USB reading for reliability")
    logger.info("  - Publishing IQ samples to Redis")
    logger.info("  - Publishing SDR health metrics")
    logger.info("=" * 80)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Verify SDR dependencies FIRST before anything else
        logger.info("=" * 80)
        if not verify_soapysdr_installation():
            logger.error("=" * 80)
            logger.error("❌ SDR DEPENDENCIES NOT PROPERLY INSTALLED")
            logger.error("=" * 80)
            logger.error("The SDR service cannot start without SoapySDR Python bindings.")
            logger.error("")
            logger.error("Required dependencies:")
            logger.error("  - SoapySDR Python bindings (python3-soapysdr)")
            logger.error("  - NumPy (python3-numpy)")
            logger.error("  - USB device access (/dev/bus/usb)")
            logger.error("")
            logger.error("Install dependencies: sudo apt install python3-soapysdr python3-numpy")
            logger.error("=" * 80)
            return 1
        logger.info("=" * 80)

        # Initialize Redis
        logger.info("Connecting to Redis...")
        redis_client = get_redis_client()
        
        # Initialize database
        logger.info("Initializing database connection...")
        app = initialize_database()
        
        # Initialize radio receivers
        logger.info("Initializing SDR receivers...")
        radio_manager = initialize_radio_receivers(app)
        
        if not radio_manager:
            logger.warning("No radio receivers initialized - service will wait for configuration")
        
        # Start sample publisher thread
        logger.info("Starting sample publisher thread...")
        _state.publisher_thread = threading.Thread(
            target=publish_samples_and_metrics,
            name="SDR-Publisher",
            daemon=True
        )
        _state.publisher_thread.start()
        
        logger.info("=" * 80)
        logger.info("✅ SDR Service started successfully")
        logger.info("   - Redis connection: ACTIVE")
        logger.info(f"   - Receivers configured: {len(radio_manager._receivers) if radio_manager and hasattr(radio_manager, '_receivers') else 0}")
        logger.info("   - Sample publishing: ACTIVE")
        logger.info("=" * 80)
        
        # Main loop: process commands and maintain health
        while _state.running:
            try:
                # Process any pending commands
                process_commands(redis_client)
                
                # Brief sleep
                time.sleep(0.1)
                
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                time.sleep(1.0)
        
        # Shutdown
        logger.info("Shutting down SDR service...")
        
        # Stop all receivers
        if radio_manager and hasattr(radio_manager, '_receivers'):
            for identifier, receiver in radio_manager._receivers.items():
                try:
                    logger.info(f"Stopping receiver: {identifier}")
                    receiver.stop()
                except Exception as e:
                    logger.warning(f"Error stopping receiver {identifier}: {e}")
        
        # Close Redis
        if _state.redis_client:
            _state.redis_client.close()
        
        logger.info("✅ SDR Service shut down gracefully")
        return 0
        
    except Exception as e:
        logger.error(f"Fatal error in SDR service: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
