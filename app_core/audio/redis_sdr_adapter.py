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
Redis SDR Source Adapter

Subscribes to Redis pub/sub channels to receive IQ samples from sdr-service,
demodulates them to audio, and provides audio to the audio controller.

This is the bridge between sdr-service (SDR hardware + IQ publishing) and
audio-service (audio processing + EAS monitoring) in separated architecture.
"""

import base64
import json
import logging
import queue
import threading
import time
import zlib
from typing import Optional, Any

import numpy as np
import redis.exceptions

from .ingest import AudioSourceAdapter, AudioSourceConfig, AudioSourceStatus, AudioMetrics

logger = logging.getLogger(__name__)


class RedisSDRSourceAdapter(AudioSourceAdapter):
    """
    Audio source adapter that receives IQ samples from Redis pub/sub.

    Subscribes to sdr:samples:{receiver_id} channel published by sdr-service,
    demodulates IQ samples to audio, and feeds audio to the broadcast queue.

    This enables separated architecture where:
    - sdr-service: SDR hardware access + IQ sample publishing
    - audio-service: IQ demodulation + audio processing + EAS monitoring
    """

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._redis_client: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        # Note: self._audio_queue is created by base class via BroadcastQueue subscription
        # Don't override it - use self._source_broadcast.publish() instead
        self._receiver_id: Optional[str] = None
        self._demodulator: Optional[Any] = None
        self._last_sample_time: float = 0.0
        self._samples_received: int = 0
        self._iq_sample_rate: int = 2500000  # Will be updated from Redis messages
        self._center_frequency: int = 0  # Will be updated from Redis messages
        # Queue for audio chunks from Redis subscriber thread
        # Increased from 100 to 500 to provide more headroom between demodulation and capture threads
        self._audio_chunk_queue: queue.Queue = queue.Queue(maxsize=500)

    def _create_demodulator(self) -> None:
        """Create or recreate demodulator with current settings."""
        try:
            # Stop old demodulator before creating new one to prevent RBDS thread leaks
            if self._demodulator and hasattr(self._demodulator, 'stop'):
                self._demodulator.stop()
                self._demodulator = None

            demod_mode = self.config.device_params.get('demod_mode', 'FM')

            # Normalize modulation type to uppercase for consistent handling
            demod_mode = demod_mode.upper()

            # Determine stereo support based on modulation type
            # WFM (Wide FM for FM broadcast) supports stereo
            # NFM (Narrow FM for NOAA, public safety) is mono only
            stereo_enabled = (demod_mode == 'WFM' or demod_mode == 'FM')

            # Get RBDS and de-emphasis settings from device_params
            # CRITICAL FIX: Enable RBDS extraction for FM broadcast stations
            # Check both 'enable_rbds' and 'rbds_enabled' keys for compatibility
            # (eas_monitoring_service uses 'rbds_enabled', older configs may use 'enable_rbds')
            enable_rbds_key1 = self.config.device_params.get('enable_rbds', False)
            enable_rbds_key2 = self.config.device_params.get('rbds_enabled', False)
            enable_rbds = bool(enable_rbds_key1) or bool(enable_rbds_key2)

            deemphasis_us = self.config.device_params.get('deemphasis_us', 75.0)  # 75μs for North America

            from app_core.radio.demodulation import create_demodulator, DemodulatorConfig

            demod_config = DemodulatorConfig(
                modulation_type=demod_mode,
                sample_rate=self._iq_sample_rate,  # IQ sample rate from SDR
                audio_sample_rate=self.config.sample_rate,  # Audio output rate (e.g., 44100)
                stereo_enabled=stereo_enabled,
                deemphasis_us=deemphasis_us,
                enable_rbds=enable_rbds,
            )

            self._demodulator = create_demodulator(demod_config)
            logger.info(
                f"✅ Created {demod_mode} demodulator: "
                f"{self._iq_sample_rate}Hz IQ → {self.config.sample_rate}Hz audio "
                f"(stereo={'yes' if stereo_enabled else 'no'}, rbds={'yes' if enable_rbds else 'no'}, "
                f"deemphasis={deemphasis_us}μs)"
            )
            # Debug: Log the actual RBDS enabled state from demodulator
            if hasattr(self._demodulator, '_rbds_enabled'):
                logger.debug(f"Demodulator RBDS enabled: {self._demodulator._rbds_enabled}")
                
        except Exception as e:
            logger.error(
                f"❌ Failed to create demodulator for {self._receiver_id}: {e}",
                exc_info=True
            )
            # Re-raise to prevent source from starting with broken demodulator
            raise RuntimeError(f"Demodulator creation failed: {e}") from e

    def _start_capture(self) -> None:
        """Start Redis subscription and audio processing."""
        # Get receiver ID from config
        self._receiver_id = self.config.device_params.get('receiver_id')
        if not self._receiver_id:
            raise ValueError("receiver_id required in device_params for Redis SDR source")

        # Get IQ sample rate from config if provided (preferred method)
        # Otherwise will be set from first Redis message
        config_sample_rate = self.config.device_params.get('iq_sample_rate')
        if config_sample_rate:
            self._iq_sample_rate = int(config_sample_rate)
            logger.info(f"Using IQ sample rate from config: {self._iq_sample_rate}Hz")
        else:
            # Default to common Airspy rate if not specified
            # Will be updated from first Redis message if different
            self._iq_sample_rate = 2_500_000  # Airspy R2 default
            logger.warning(
                f"IQ sample rate not in config for {self._receiver_id}. "
                f"Using default {self._iq_sample_rate}Hz, will update from first sample."
            )

        # Connect to Redis
        from app_core.redis_client import get_redis_client
        try:
            self._redis_client = get_redis_client()
            logger.info(f"Connected to Redis for receiver {self._receiver_id}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Redis: {e}") from e

        # CRITICAL FIX: Don't create demodulator until first Redis message arrives
        # Why: SDR service may use early decimation (2.5MHz -> 250kHz), and we won't
        # know the actual sample rate until first message. Creating with wrong rate
        # causes immediate recreation, which restarts RBDS worker and prevents sync.
        # 
        # The demodulator will be created in _redis_subscriber_thread when first
        # message with actual sample rate is received (see line ~240).
        logger.info(f"Waiting for first sample from {self._receiver_id} to determine IQ rate...")

        # Subscribe to Redis pub/sub channel
        self._pubsub = self._redis_client.pubsub(ignore_subscribe_messages=True)
        channel = f"sdr:samples:{self._receiver_id}"
        self._pubsub.subscribe(channel)
        logger.info(f"Subscribed to Redis channel: {channel}")

        # Start Redis subscriber thread (separate from capture thread)
        # This thread receives IQ samples from Redis and demodulates them
        subscriber_thread = threading.Thread(
            target=self._redis_subscriber_loop,
            name=f"redis-sdr-{self._receiver_id}",
            daemon=True
        )
        subscriber_thread.start()
        logger.info(f"Started Redis SDR subscriber for {self._receiver_id}")

    def _redis_subscriber_loop(self) -> None:
        """Redis pub/sub subscriber loop - receives IQ samples and demodulates to audio."""
        logger.info(f"Redis subscriber loop started for {self._receiver_id}")
        
        last_log_time = time.time()
        messages_received = 0

        try:
            # Use _stop_event from base class instead of undefined _running
            while not self._stop_event.is_set():
                try:
                    # Use get_message with timeout instead of listen() to allow graceful shutdown
                    # Check pubsub availability inside try block to avoid race conditions
                    pubsub = self._pubsub
                    if pubsub is None:
                        logger.debug(f"Redis pubsub closed for {self._receiver_id}, exiting subscriber loop")
                        break
                    
                    message = pubsub.get_message(timeout=1.0)
                except (OSError, ConnectionError, redis.exceptions.ConnectionError) as e:
                    # Handle connection errors gracefully (e.g., socket closed during shutdown)
                    # OSError with errno 9 = Bad file descriptor (socket was closed)
                    # ConnectionError = Built-in connection reset by peer
                    # redis.exceptions.ConnectionError = Redis-specific connection errors (e.g., server closed connection)
                    if self._stop_event.is_set():
                        # Expected during shutdown - log at debug level
                        logger.debug(f"Redis connection closed during shutdown for {self._receiver_id}: {e}")
                    else:
                        # Unexpected connection error - log as error
                        logger.error(f"Redis connection error for {self._receiver_id}: {e}")
                    break

                # Log periodically if no samples received
                current_time = time.time()
                if message is None:
                    if current_time - last_log_time > 10.0:
                        if messages_received == 0:
                            logger.warning(
                                f"No IQ samples received for {self._receiver_id} in {current_time - last_log_time:.1f}s. "
                                f"Check if sdr-service is publishing to sdr:samples:{self._receiver_id}"
                            )
                        last_log_time = current_time
                    continue

                if message.get('type') != 'message':
                    continue

                try:
                    messages_received += 1
                    
                    # Parse message
                    data = json.loads(message['data'])

                    # Update metadata
                    new_sample_rate = data.get('sample_rate', self._iq_sample_rate)
                    self._center_frequency = data.get('center_frequency', self._center_frequency)

                    # CRITICAL FIX: Create demodulator on first message, then only recreate for significant rate changes
                    # This prevents the "restart loop" where demodulator is created with wrong default rate (2.5MHz),
                    # then immediately recreated when first message arrives with actual rate (250kHz after decimation).
                    # RBDS needs ~1-5 seconds to sync, so recreation before sync completes prevents RBDS from ever working.
                    
                    if self._demodulator is None:
                        # First message - create demodulator with actual sample rate from SDR service
                        self._iq_sample_rate = new_sample_rate
                        self._create_demodulator()
                        logger.info(
                            f"✅ Created initial demodulator for {self._receiver_id} at {new_sample_rate}Hz "
                            f"(rate from first Redis message)"
                        )
                    elif new_sample_rate != self._iq_sample_rate:
                        # Sample rate changed - only recreate if difference is significant
                        # Tolerance: 0.1% (well below SDR accuracy ±1 ppm = ±0.0001%)
                        rate_diff_pct = abs(new_sample_rate - self._iq_sample_rate) / self._iq_sample_rate * 100.0
                        
                        if rate_diff_pct > 0.1:
                            logger.warning(
                                f"⚠️  IQ sample rate changed: {self._iq_sample_rate}Hz -> {new_sample_rate}Hz "
                                f"({rate_diff_pct:.3f}% difference). Recreating demodulator (will disrupt RBDS sync)..."
                            )
                            self._iq_sample_rate = new_sample_rate
                            self._create_demodulator()
                            logger.info(f"✅ Demodulator recreated for new rate {new_sample_rate}Hz")
                        else:
                            # Minor variation - ignore to avoid disrupting RBDS
                            logger.debug(
                                f"IQ sample rate variation within tolerance: {self._iq_sample_rate}Hz -> "
                                f"{new_sample_rate}Hz ({rate_diff_pct:.4f}%). Ignoring to preserve RBDS sync."
                            )

                    # Decode IQ samples
                    encoded_samples = data.get('samples', '')
                    if not encoded_samples:
                        logger.warning(f"Empty IQ sample data from {self._receiver_id}")
                        continue

                    # Decompress and decode (zlib + base64)
                    compressed = base64.b64decode(encoded_samples)
                    interleaved_bytes = zlib.decompress(compressed)
                    interleaved = np.frombuffer(interleaved_bytes, dtype=np.float32)

                    # Convert interleaved [real, imag, real, imag, ...] to complex samples
                    iq_samples = interleaved[0::2] + 1j * interleaved[1::2]

                    # Demodulate IQ to audio
                    if self._demodulator:
                        audio_samples = self._demodulator.process(iq_samples)

                        if audio_samples is not None and len(audio_samples) > 0:
                            # Put audio in queue for _read_audio_chunk() to consume
                            # The base class capture loop will handle metrics updates and broadcasting
                            try:
                                # Try non-blocking put first for minimum latency
                                self._audio_chunk_queue.put_nowait(audio_samples)
                            except queue.Full:
                                # Queue full - use longer timeout to prevent sample loss during GC pauses or CPU bursts
                                # Original 0.1s timeout was too aggressive and caused cutouts
                                try:
                                    self._audio_chunk_queue.put(audio_samples, timeout=1.0)
                                    logger.warning(f"Audio chunk queue was full for {self._receiver_id}, used blocking put")
                                except queue.Full:
                                    logger.error(f"Audio chunk queue still full after 1s timeout for {self._receiver_id}, dropping samples")
                                    continue  # Skip updating counters if we dropped samples
                            
                            # Update counters after successful enqueue (either non-blocking or blocking)
                            self._samples_received += len(audio_samples)
                            self._last_sample_time = time.time()
                            
                            # Log first successful sample
                            if messages_received == 1:
                                logger.info(
                                    f"✅ First audio chunk decoded for {self._receiver_id}: "
                                    f"{len(audio_samples)} samples"
                                )
                    else:
                        logger.error(f"No demodulator available for {self._receiver_id} - cannot process IQ samples")

                except Exception as e:
                    logger.error(f"Error processing Redis IQ sample: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Redis subscriber loop error: {e}", exc_info=True)
        finally:
            logger.info(
                f"Redis subscriber loop exited for {self._receiver_id}. "
                f"Processed {messages_received} messages"
            )

    def _stop_capture(self) -> None:
        """Stop Redis subscription."""
        # Stop demodulator to clean up RBDS worker thread
        if self._demodulator and hasattr(self._demodulator, 'stop'):
            self._demodulator.stop()
            self._demodulator = None

        if self._pubsub:
            try:
                self._pubsub.unsubscribe()
                self._pubsub.close()
            except Exception as e:
                # Log at debug level since errors during cleanup are expected
                logger.debug(f"Error closing Redis pub/sub for {self._receiver_id}: {e}")
            finally:
                # Mark pubsub as None to signal subscriber loop to exit
                self._pubsub = None

        # Clear audio chunk queue
        while not self._audio_chunk_queue.empty():
            try:
                self._audio_chunk_queue.get_nowait()
            except queue.Empty:
                break

        logger.info(f"Stopped Redis SDR source for {self._receiver_id}")

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read an audio chunk from the queue filled by Redis subscriber thread.
        
        This method is called by the base class's capture loop.
        The Redis subscriber thread demodulates IQ samples and puts audio in the queue.
        """
        try:
            # Get audio chunk from queue with short timeout
            # This allows the capture loop to check _stop_event periodically
            audio_chunk = self._audio_chunk_queue.get(timeout=0.1)
            return audio_chunk
        except queue.Empty:
            # No audio available yet - this is normal, return None
            return None

    def _update_metrics(self, audio_chunk: Optional[np.ndarray] = None) -> None:
        """Update metrics from Redis SDR source."""
        super()._update_metrics(audio_chunk)

        # Add Redis-specific metadata
        if self.metrics.metadata is None:
            self.metrics.metadata = {}

        self.metrics.metadata['source_type'] = 'redis_sdr'
        self.metrics.metadata['receiver_id'] = self._receiver_id
        self.metrics.metadata['iq_sample_rate'] = self._iq_sample_rate
        self.metrics.metadata['center_frequency'] = self._center_frequency
        self.metrics.metadata['receiver_frequency_hz'] = self._center_frequency  # For waterfall display
        demod_mode = self.config.device_params.get('demod_mode', 'FM')
        self.metrics.metadata['receiver_modulation'] = demod_mode  # For waterfall display
        self.metrics.metadata['demodulation_enabled'] = True  # For waterfall display
        self.metrics.metadata['center_frequency_mhz'] = round(self._center_frequency / 1_000_000, 6)
        self.metrics.metadata['samples_received'] = self._samples_received
        self.metrics.metadata['last_sample_age'] = time.time() - self._last_sample_time if self._last_sample_time > 0 else None

        # Stereo detection from demodulator
        # stereo_enabled = modulation type supports stereo (WFM/FM)
        # stereo_pilot_locked = 19kHz pilot tone actually detected
        # is_stereo = receiving stereo audio (pilot locked and stereo mode)
        modulation_supports_stereo = demod_mode.upper() in ('WFM', 'FM')
        self.metrics.metadata['stereo_enabled'] = modulation_supports_stereo

        # Get actual stereo detection status from demodulator
        if self._demodulator and hasattr(self._demodulator, 'get_last_status'):
            status = self._demodulator.get_last_status()
            if status:
                self.metrics.metadata['stereo_pilot_locked'] = status.stereo_pilot_locked
                self.metrics.metadata['stereo_pilot_strength'] = status.stereo_pilot_strength
                self.metrics.metadata['is_stereo'] = status.is_stereo
                # Override stereo_enabled with actual detection for display
                if modulation_supports_stereo:
                    self.metrics.metadata['stereo_enabled'] = status.stereo_pilot_locked
                
                # Extract RBDS/RDS data if available
                if status.rbds_data:
                    rbds = status.rbds_data
                    logger.debug(f"RBDS data received: PS={rbds.ps_name}, PI={rbds.pi_code}, PTY={rbds.pty}")
                    # Add all RBDS fields to metadata for frontend display
                    if rbds.ps_name:
                        self.metrics.metadata['rbds_ps_name'] = rbds.ps_name
                    if rbds.pi_code:
                        self.metrics.metadata['rbds_pi_code'] = rbds.pi_code
                    if rbds.radio_text:
                        self.metrics.metadata['rbds_radio_text'] = rbds.radio_text
                    if rbds.pty is not None:
                        self.metrics.metadata['rbds_pty'] = rbds.pty
                        # Map PTY code to human-readable name
                        from .sources import RBDS_PROGRAM_TYPES
                        self.metrics.metadata['rbds_program_type_name'] = RBDS_PROGRAM_TYPES.get(rbds.pty, f"Unknown ({rbds.pty})")
                    if rbds.tp is not None:
                        self.metrics.metadata['rbds_tp'] = rbds.tp
                    if rbds.ta is not None:
                        self.metrics.metadata['rbds_ta'] = rbds.ta
                    if rbds.ms is not None:
                        self.metrics.metadata['rbds_ms'] = rbds.ms
                    # Add timestamp for when RBDS was last updated
                    self.metrics.metadata['rbds_last_updated'] = time.time()
