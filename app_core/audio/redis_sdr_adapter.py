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
        self._audio_chunk_queue: queue.Queue = queue.Queue(maxsize=100)
        # Last-known RBDS data so cleared-on-this-cycle fields keep displaying
        # the most recent decoded value until something new arrives, and so the
        # `rbds_last_updated` timestamp only advances when data actually changes.
        self._rbds_data: Optional[Any] = None
        self._rbds_signature: Optional[tuple] = None
        # Track the previously-seen center frequency so we can reset RBDS
        # state (and clear the cached PS/RT from the old station) whenever
        # the operator tunes somewhere new.  Without this, the UI keeps
        # showing the previous station's metadata until the new station's
        # first RBDS group is decoded.
        self._last_rbds_reset_frequency: Optional[int] = None

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
                    prev_center_frequency = self._center_frequency
                    self._center_frequency = data.get('center_frequency', self._center_frequency)

                    # Reset RBDS on frequency change.  The M&M / Costas loop
                    # state, the 57 kHz carrier phase reference and the
                    # decoded PS/PI/radiotext all belong to the previous
                    # station; keeping them around both delays re-lock and
                    # leaves the UI showing stale metadata until the new
                    # station's first group is decoded.  We treat the first
                    # message (prev==0) as an initial tune and reset too so
                    # nothing leaks across receiver restarts.
                    if (
                        self._center_frequency
                        and self._center_frequency != self._last_rbds_reset_frequency
                    ):
                        if prev_center_frequency and prev_center_frequency != self._center_frequency:
                            logger.info(
                                "Frequency change detected for %s: %d Hz -> %d Hz; resetting RBDS state",
                                self._receiver_id,
                                prev_center_frequency,
                                self._center_frequency,
                            )
                        self._rbds_data = None
                        self._rbds_signature = None
                        if self._demodulator is not None and hasattr(self._demodulator, 'reset_rbds'):
                            try:
                                self._demodulator.reset_rbds()
                            except Exception as exc:  # pragma: no cover - defensive
                                logger.debug("reset_rbds failed: %s", exc)
                        self._last_rbds_reset_frequency = self._center_frequency

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
                                self._audio_chunk_queue.put(audio_samples, timeout=0.1)
                                self._samples_received += len(audio_samples)
                                self._last_sample_time = time.time()
                                
                                # Log first successful sample
                                if messages_received == 1:
                                    logger.info(
                                        f"✅ First audio chunk decoded for {self._receiver_id}: "
                                        f"{len(audio_samples)} samples"
                                    )
                            except queue.Full:
                                logger.warning(f"Audio chunk queue full for {self._receiver_id}, dropping samples")
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

                # RBDS lock state.  Lets the UI render a LOCKING / LOCKED /
                # DISABLED badge so users know whether a missing PS/RT means
                # no data yet (still locking), the decoder isn't even trying
                # (disabled in receiver config), or the modulation isn't FM.
                rbds_synced = bool(getattr(status, 'rbds_synced', False))
                rbds_enabled_runtime = bool(getattr(status, 'rbds_enabled', False))
                self.metrics.metadata['rbds_synced'] = rbds_synced
                self.metrics.metadata['rbds_enabled'] = rbds_enabled_runtime
                if rbds_synced:
                    lock_state = 'LOCKED'
                elif not modulation_supports_stereo:
                    lock_state = 'UNAVAILABLE'
                elif not rbds_enabled_runtime:
                    # FM modulation but RBDS decoding is off — without this
                    # branch the UI showed "Acquiring sync…" indefinitely
                    # for receivers configured with enable_rbds=False.
                    lock_state = 'DISABLED'
                else:
                    lock_state = 'LOCKING'
                self.metrics.metadata['rbds_lock_state'] = lock_state

                decoder_stats = getattr(status, 'rbds_decoder_stats', None)
                if decoder_stats is not None:
                    self.metrics.metadata['rbds_blocks_total'] = decoder_stats.blocks_total
                    self.metrics.metadata['rbds_blocks_ok'] = decoder_stats.blocks_ok
                    self.metrics.metadata['rbds_blocks_fec_single'] = decoder_stats.blocks_fec_single
                    self.metrics.metadata['rbds_blocks_fec_burst'] = decoder_stats.blocks_fec_burst
                    self.metrics.metadata['rbds_blocks_uncorrected'] = decoder_stats.blocks_uncorrected
                    self.metrics.metadata['rbds_blocks_bit_slips'] = decoder_stats.blocks_bit_slips
                    self.metrics.metadata['rbds_groups_decoded'] = decoder_stats.groups_decoded
                    self.metrics.metadata['rbds_sync_acquired_unix'] = decoder_stats.sync_acquired_unix
                    self.metrics.metadata['rbds_sync_lost_count'] = decoder_stats.sync_lost_count
                    self.metrics.metadata['rbds_chunks_dropped'] = decoder_stats.chunks_dropped
                    self.metrics.metadata['rbds_raw_bler'] = decoder_stats.raw_block_error_rate
                    self.metrics.metadata['rbds_net_bler'] = decoder_stats.net_block_error_rate
                    self.metrics.metadata['rbds_group_type_counts'] = (
                        dict(decoder_stats.group_type_counts)
                        if decoder_stats.group_type_counts else None
                    )
                    # Field-churn / false-read telemetry from the two-sighting
                    # confirmation gate (see RBDSDecoderStats).
                    self.metrics.metadata['rbds_pi_change_count'] = decoder_stats.pi_change_count
                    self.metrics.metadata['rbds_pty_change_count'] = decoder_stats.pty_change_count
                    self.metrics.metadata['rbds_ta_toggle_count'] = decoder_stats.ta_toggle_count
                    self.metrics.metadata['rbds_glitches_rejected'] = decoder_stats.glitches_rejected

                # RF RSSI (mean IQ magnitude).  Linear value; the UI converts to
                # dBFS for the signal meter.  Without this the RSSI indicator is
                # permanently blank on Redis-backed SDR sources.
                if getattr(status, 'signal_strength', None) is not None:
                    self.metrics.metadata['rf_signal_strength'] = float(status.signal_strength)
                    self.metrics.metadata['rf_signal_strength_updated'] = time.time()

                # Extract RBDS/RDS data if available.  We cache the last decoded
                # object so that between decoder poll cycles we can keep showing
                # the most recent values (RBDS groups arrive every ~100 ms, so a
                # given _update_metrics() call very often sees the same object
                # as the previous one — we must not restamp rbds_last_updated in
                # that case, otherwise "last updated" looks fresh forever).
                rbds = status.rbds_data
                from .sources import RBDS_PROGRAM_TYPES
                if rbds is not None:
                    signature = (
                        rbds.ps_name,
                        rbds.pi_code,
                        rbds.call_sign,
                        rbds.pty_name,
                        rbds.radio_text,
                        rbds.pty,
                        rbds.tp,
                        rbds.ta,
                        rbds.ms,
                        rbds.clock_time_local,
                    )
                    self._rbds_data = rbds
                    # Write all fields unconditionally so cleared values propagate
                    self.metrics.metadata['rbds_ps_name'] = rbds.ps_name
                    self.metrics.metadata['rbds_pi_code'] = rbds.pi_code
                    self.metrics.metadata['rbds_call_sign'] = rbds.call_sign
                    self.metrics.metadata['rbds_pty_name'] = rbds.pty_name
                    self.metrics.metadata['rbds_radio_text'] = rbds.radio_text
                    self.metrics.metadata['rbds_pty'] = rbds.pty
                    self.metrics.metadata['rbds_program_type_name'] = (
                        RBDS_PROGRAM_TYPES.get(int(rbds.pty), f"Unknown ({rbds.pty})")
                        if rbds.pty is not None else None
                    )
                    self.metrics.metadata['rbds_tp'] = rbds.tp
                    self.metrics.metadata['rbds_ta'] = rbds.ta
                    self.metrics.metadata['rbds_ms'] = rbds.ms
                    self.metrics.metadata['rbds_di_stereo'] = rbds.di_stereo
                    self.metrics.metadata['rbds_di_artificial_head'] = rbds.di_artificial_head
                    self.metrics.metadata['rbds_di_compressed'] = rbds.di_compressed
                    self.metrics.metadata['rbds_di_dynamic_pty'] = rbds.di_dynamic_pty
                    self.metrics.metadata['rbds_clock_time_utc'] = rbds.clock_time_utc
                    self.metrics.metadata['rbds_clock_time_local'] = rbds.clock_time_local
                    self.metrics.metadata['rbds_af_list'] = rbds.af_list
                    self.metrics.metadata['rbds_pin_day'] = rbds.pin_day
                    self.metrics.metadata['rbds_pin_hour'] = rbds.pin_hour
                    self.metrics.metadata['rbds_pin_minute'] = rbds.pin_minute
                    self.metrics.metadata['rbds_ecc'] = rbds.ecc
                    self.metrics.metadata['rbds_language_code'] = rbds.language_code
                    self.metrics.metadata['rbds_language_name'] = rbds.language_name
                    self.metrics.metadata['rbds_linkage_set_number'] = rbds.linkage_set_number
                    self.metrics.metadata['rbds_linkage_actuator'] = rbds.linkage_actuator
                    self.metrics.metadata['rbds_linkage_soft_coupling'] = rbds.linkage_soft_coupling
                    self.metrics.metadata['rbds_oda_apps'] = rbds.oda_apps
                    self.metrics.metadata['rbds_tdc_data'] = (
                        rbds.tdc_data.hex() if rbds.tdc_data else None
                    )
                    self.metrics.metadata['rbds_in_house_data'] = rbds.in_house_data
                    self.metrics.metadata['rbds_tmc_present'] = rbds.tmc_present
                    self.metrics.metadata['rbds_ews_channel'] = rbds.ews_channel
                    self.metrics.metadata['rbds_ews_message_c'] = rbds.ews_message_c
                    self.metrics.metadata['rbds_ews_message_d'] = rbds.ews_message_d
                    self.metrics.metadata['rbds_eon_list'] = rbds.eon_list
                    self.metrics.metadata['rbds_fast_tp'] = rbds.fast_tp
                    self.metrics.metadata['rbds_fast_ta'] = rbds.fast_ta
                    self.metrics.metadata['rbds_fast_ms'] = rbds.fast_ms
                    self.metrics.metadata['rbds_fast_di_bits'] = rbds.fast_di_bits
                    self.metrics.metadata['rbds_rt_plus_item_running'] = rbds.rt_plus_item_running
                    self.metrics.metadata['rbds_rt_plus_item_toggle'] = rbds.rt_plus_item_toggle
                    self.metrics.metadata['rbds_rt_plus_tags'] = rbds.rt_plus_tags
                    self.metrics.metadata['rbds_radio_text_ab'] = rbds.radio_text_ab
                    self.metrics.metadata['rbds_pi_country_code'] = rbds.pi_country_code
                    self.metrics.metadata['rbds_pi_area_code'] = rbds.pi_area_code
                    self.metrics.metadata['rbds_pi_program_ref'] = rbds.pi_program_ref
                    self.metrics.metadata['rbds_oda_assignments'] = rbds.oda_assignments
                    self.metrics.metadata['rbds_oda_payloads'] = rbds.oda_payloads
                    self.metrics.metadata['rbds_af_method_a_count'] = rbds.af_method_a_count
                    self.metrics.metadata['rbds_af_follow_on_indicator'] = rbds.af_follow_on_indicator
                    self.metrics.metadata['rbds_af_method_b'] = rbds.af_method_b
                    self.metrics.metadata['rbds_af_tuning_frequency'] = rbds.af_tuning_frequency
                    self.metrics.metadata['rbds_paging_messages'] = rbds.paging_messages
                    self.metrics.metadata['rbds_enhanced_paging_messages'] = rbds.enhanced_paging_messages
                    self.metrics.metadata['rbds_paging_tmc_id'] = rbds.paging_tmc_id
                    self.metrics.metadata['rbds_paging_operator_code'] = rbds.paging_operator_code
                    self.metrics.metadata['rbds_ews_channel_identifier'] = rbds.ews_channel_identifier
                    self.metrics.metadata['rbds_slow_labelling_raw'] = (
                        {str(k): v for k, v in rbds.slow_labelling_raw.items()}
                        if rbds.slow_labelling_raw else None
                    )
                    self.metrics.metadata['rbds_tdc_channels'] = (
                        {str(ch): buf.hex() for ch, buf in rbds.tdc_channels.items()}
                        if rbds.tdc_channels else None
                    )
                    # rbds_last_seen advances every time we observe a decoded
                    # group, even if the content is identical to the last one.
                    # This is the "decoder is alive" heartbeat: it lets the
                    # UI distinguish "station is just playing stable content"
                    # from "sync died and we're showing stale data".
                    now = time.time()
                    self.metrics.metadata['rbds_last_seen'] = now
                    # rbds_last_updated only advances when decoded content
                    # actually changes — this is the "content freshness" time
                    # the user cares about for RT / PS rotation.
                    if signature != self._rbds_signature:
                        self.metrics.metadata['rbds_last_updated'] = now
                        self._rbds_signature = signature
                        logger.debug(
                            f"RBDS data updated: PS={rbds.ps_name}, "
                            f"PI={rbds.pi_code} ({rbds.call_sign}), PTY={rbds.pty}"
                        )
                elif self._rbds_data is not None:
                    # No new decode this cycle — keep last-known values on display
                    last = self._rbds_data
                    self.metrics.metadata['rbds_ps_name'] = last.ps_name
                    self.metrics.metadata['rbds_pi_code'] = last.pi_code
                    self.metrics.metadata['rbds_call_sign'] = last.call_sign
                    self.metrics.metadata['rbds_pty_name'] = last.pty_name
                    self.metrics.metadata['rbds_radio_text'] = last.radio_text
                    self.metrics.metadata['rbds_pty'] = last.pty
                    self.metrics.metadata['rbds_program_type_name'] = (
                        RBDS_PROGRAM_TYPES.get(int(last.pty), f"Unknown ({last.pty})")
                        if last.pty is not None else None
                    )
                    self.metrics.metadata['rbds_tp'] = last.tp
                    self.metrics.metadata['rbds_ta'] = last.ta
                    self.metrics.metadata['rbds_ms'] = last.ms
                    self.metrics.metadata['rbds_di_stereo'] = last.di_stereo
                    self.metrics.metadata['rbds_di_artificial_head'] = last.di_artificial_head
                    self.metrics.metadata['rbds_di_compressed'] = last.di_compressed
                    self.metrics.metadata['rbds_di_dynamic_pty'] = last.di_dynamic_pty
                    self.metrics.metadata['rbds_clock_time_utc'] = last.clock_time_utc
                    self.metrics.metadata['rbds_clock_time_local'] = last.clock_time_local
                    self.metrics.metadata['rbds_af_list'] = last.af_list
                    self.metrics.metadata['rbds_pin_day'] = last.pin_day
                    self.metrics.metadata['rbds_pin_hour'] = last.pin_hour
                    self.metrics.metadata['rbds_pin_minute'] = last.pin_minute
                    self.metrics.metadata['rbds_ecc'] = last.ecc
                    self.metrics.metadata['rbds_language_code'] = last.language_code
                    self.metrics.metadata['rbds_language_name'] = last.language_name
                    self.metrics.metadata['rbds_linkage_set_number'] = last.linkage_set_number
                    self.metrics.metadata['rbds_linkage_actuator'] = last.linkage_actuator
                    self.metrics.metadata['rbds_linkage_soft_coupling'] = last.linkage_soft_coupling
                    self.metrics.metadata['rbds_oda_apps'] = last.oda_apps
                    self.metrics.metadata['rbds_tdc_data'] = (
                        last.tdc_data.hex() if last.tdc_data else None
                    )
                    self.metrics.metadata['rbds_in_house_data'] = last.in_house_data
                    self.metrics.metadata['rbds_tmc_present'] = last.tmc_present
                    self.metrics.metadata['rbds_ews_channel'] = last.ews_channel
                    self.metrics.metadata['rbds_ews_message_c'] = last.ews_message_c
                    self.metrics.metadata['rbds_ews_message_d'] = last.ews_message_d
                    self.metrics.metadata['rbds_eon_list'] = last.eon_list
                    self.metrics.metadata['rbds_fast_tp'] = last.fast_tp
                    self.metrics.metadata['rbds_fast_ta'] = last.fast_ta
                    self.metrics.metadata['rbds_fast_ms'] = last.fast_ms
                    self.metrics.metadata['rbds_fast_di_bits'] = last.fast_di_bits
                    self.metrics.metadata['rbds_rt_plus_item_running'] = last.rt_plus_item_running
                    self.metrics.metadata['rbds_rt_plus_item_toggle'] = last.rt_plus_item_toggle
                    self.metrics.metadata['rbds_rt_plus_tags'] = last.rt_plus_tags
                    self.metrics.metadata['rbds_radio_text_ab'] = last.radio_text_ab
                    self.metrics.metadata['rbds_pi_country_code'] = last.pi_country_code
                    self.metrics.metadata['rbds_pi_area_code'] = last.pi_area_code
                    self.metrics.metadata['rbds_pi_program_ref'] = last.pi_program_ref
                    self.metrics.metadata['rbds_oda_assignments'] = last.oda_assignments
                    self.metrics.metadata['rbds_oda_payloads'] = last.oda_payloads
                    self.metrics.metadata['rbds_af_method_a_count'] = last.af_method_a_count
                    self.metrics.metadata['rbds_af_follow_on_indicator'] = last.af_follow_on_indicator
                    self.metrics.metadata['rbds_af_method_b'] = last.af_method_b
                    self.metrics.metadata['rbds_af_tuning_frequency'] = last.af_tuning_frequency
                    self.metrics.metadata['rbds_paging_messages'] = last.paging_messages
                    self.metrics.metadata['rbds_enhanced_paging_messages'] = last.enhanced_paging_messages
                    self.metrics.metadata['rbds_paging_tmc_id'] = last.paging_tmc_id
                    self.metrics.metadata['rbds_paging_operator_code'] = last.paging_operator_code
                    self.metrics.metadata['rbds_ews_channel_identifier'] = last.ews_channel_identifier
                    self.metrics.metadata['rbds_slow_labelling_raw'] = (
                        {str(k): v for k, v in last.slow_labelling_raw.items()}
                        if last.slow_labelling_raw else None
                    )
                    self.metrics.metadata['rbds_tdc_channels'] = (
                        {str(ch): buf.hex() for ch, buf in last.tdc_channels.items()}
                        if last.tdc_channels else None
                    )
                else:
                    # No cached data and nothing new this cycle — e.g. right
                    # after a frequency change.  Publish explicit nulls so
                    # the UI clears the previous station's PS/RT instead of
                    # holding on to whatever was there before.
                    self.metrics.metadata['rbds_ps_name'] = None
                    self.metrics.metadata['rbds_pi_code'] = None
                    self.metrics.metadata['rbds_call_sign'] = None
                    self.metrics.metadata['rbds_pty_name'] = None
                    self.metrics.metadata['rbds_radio_text'] = None
                    self.metrics.metadata['rbds_pty'] = None
                    self.metrics.metadata['rbds_program_type_name'] = None
                    self.metrics.metadata['rbds_tp'] = None
                    self.metrics.metadata['rbds_ta'] = None
                    self.metrics.metadata['rbds_di_stereo'] = None
                    self.metrics.metadata['rbds_di_artificial_head'] = None
                    self.metrics.metadata['rbds_di_compressed'] = None
                    self.metrics.metadata['rbds_di_dynamic_pty'] = None
                    self.metrics.metadata['rbds_clock_time_utc'] = None
                    self.metrics.metadata['rbds_clock_time_local'] = None
                    self.metrics.metadata['rbds_ms'] = None
