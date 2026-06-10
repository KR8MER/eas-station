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

from __future__ import annotations

"""
Audio Source Adapters

Concrete implementations of AudioSourceAdapter for different input types.
"""

import base64
import copy
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, unquote

import re as _re

import numpy as np

from .ingest import AudioSourceAdapter, AudioSourceConfig, AudioSourceStatus

logger = logging.getLogger(__name__)

# Pre-compiled pattern used by _looks_like_base64_blob
_BASE64_BLOB_RE = _re.compile(r'^[A-Za-z0-9+/=]{20,}$')


def _looks_like_base64_blob(text: str) -> bool:
    """Return True if *text* looks like a raw base64-encoded blob.

    Base64-encoded URLs or binary data occasionally appear in ICY StreamTitle
    fields.  They are not useful display text and should be discarded.

    Criteria: 20+ characters, no whitespace, only base64 alphabet characters.
    """
    return bool(text and not _re.search(r'\s', text) and _BASE64_BLOB_RE.match(text.strip()))


def _decode_base64_url(text: str) -> Optional[str]:
    """Try to base64-decode *text* and return it if it resolves to an HTTP(S) URL.

    Some stream automation systems encode audio/ad URLs in base64 and embed
    them directly as the ICY StreamTitle.  When successfully decoded to a URL
    we can offer playback rather than silently discarding the entry.
    """
    try:
        padded = text.strip()
        # Restore padding stripped during base64 transport
        remainder = len(padded) % 4
        if remainder:
            padded += '=' * (4 - remainder)
        decoded = base64.b64decode(padded).decode('utf-8', errors='strict')
        if decoded.startswith(('http://', 'https://')):
            return decoded
    except Exception:
        pass
    return None

try:
    import alsaaudio
    ALSA_AVAILABLE = True
except ImportError:
    ALSA_AVAILABLE = False
    logger.warning("ALSA not available - ALSA source adapter will be disabled")

try:
    import pyaudio
    PULSE_AVAILABLE = True
except ImportError:
    PULSE_AVAILABLE = False
    logger.warning("PyAudio not available - PulseAudio source adapter will be disabled")

try:
    from app_core.radio.manager import RadioManager
    RADIO_AVAILABLE = True
except ImportError:
    RADIO_AVAILABLE = False
    logger.warning("Radio manager not available - SDR source adapter will be disabled")

try:
    import requests
    import urllib.parse
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("Requests not available - Stream source adapter will be disabled")


# North American RBDS Program Type codes (NRSC-4-B standard)
# These differ from European RDS PTY codes!
RBDS_PROGRAM_TYPES: Dict[int, str] = {
    0: "No program type",
    1: "News",
    2: "Information",
    3: "Sports",
    4: "Talk",
    5: "Rock",
    6: "Classic Rock",
    7: "Adult Hits",
    8: "Soft Rock",
    9: "Top 40",
    10: "Country",
    11: "Oldies",
    12: "Soft",
    13: "Nostalgia",
    14: "Jazz",
    15: "Classical",
    16: "Rhythm & Blues",
    17: "Soft R&B",
    18: "Language",
    19: "Religious Music",
    20: "Religious Talk",
    21: "Personality",
    22: "Public",
    23: "College",
    24: "Spanish Talk",
    25: "Spanish Music",
    26: "Hip Hop",
    27: "Unassigned",
    28: "Unassigned",
    29: "Weather",
    30: "Emergency Test",
    31: "Emergency"
}


class SDRSourceAdapter(AudioSourceAdapter):
    """Audio source adapter for SDR receivers via the radio manager."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._radio_manager: Optional[RadioManager] = None
        self._receiver_id: Optional[str] = None
        self._capture_handle: Optional[Any] = None
        self._demodulator = None  # Audio demodulator (if enabled)
        self._rbds_data = None  # Latest RBDS data
        self._receiver_config = None  # Receiver configuration
        self._squelch_enabled = False
        self._squelch_threshold_db = -65.0
        self._squelch_open_ms = 150
        self._squelch_close_ms = 750
        self._squelch_alarm_enabled = False
        self._squelch_state_open = True
        self._squelch_last_change = time.time()
        self._squelch_open_timer: Optional[float] = None
        self._squelch_close_timer: Optional[float] = None
        self._last_rms_db = float("-inf")

    def _start_capture(self) -> None:
        """Start SDR audio capture via radio manager."""
        if not RADIO_AVAILABLE:
            raise RuntimeError("Radio manager not available")

        receiver_id = self.config.device_params.get('receiver_id')
        if not receiver_id:
            raise ValueError("receiver_id required in device_params")

        # Get the global radio manager instance
        from app_core.extensions import get_radio_manager
        self._radio_manager = get_radio_manager()
        self._receiver_id = receiver_id

        # Get receiver configuration to check demodulation settings
        from app_core.models import RadioReceiver
        from app_core.radio.demodulation import create_demodulator, DemodulatorConfig, DemodulatorStatus

        db_receiver = RadioReceiver.query.filter_by(identifier=receiver_id).first()
        if db_receiver:
            self._receiver_config = db_receiver.to_receiver_config()

            self._squelch_enabled = bool(self._receiver_config.squelch_enabled)
            self._squelch_threshold_db = float(self._receiver_config.squelch_threshold_db)
            self._squelch_open_ms = int(self._receiver_config.squelch_open_ms)
            self._squelch_close_ms = int(self._receiver_config.squelch_close_ms)
            self._squelch_alarm_enabled = bool(self._receiver_config.squelch_alarm)
            self._squelch_state_open = not self._squelch_enabled
            self._squelch_last_change = time.time()
            self._squelch_open_timer = None
            self._squelch_close_timer = None

            metadata = self.metrics.metadata or {}
            metadata.setdefault('receiver_identifier', receiver_id)
            metadata.setdefault('receiver_display_name', db_receiver.display_name)
            metadata.setdefault('receiver_driver', db_receiver.driver)
            metadata.setdefault('source_category', 'sdr')
            metadata.setdefault('icecast_mount', f"/{self.config.name}")
            metadata.setdefault('receiver_audio_output', bool(db_receiver.audio_output))
            metadata.setdefault('receiver_auto_start', bool(db_receiver.auto_start))
            metadata.setdefault('rbds_enabled', bool(db_receiver.enable_rbds))

            freq_hz = float(db_receiver.frequency_hz or 0.0)
            if freq_hz and 'receiver_frequency_hz' not in metadata:
                metadata['receiver_frequency_hz'] = freq_hz
                metadata['receiver_frequency_mhz'] = round(freq_hz / 1_000_000, 6)
                if freq_hz >= 1_000_000:
                    metadata['receiver_frequency_display'] = f"{freq_hz / 1_000_000:.3f} MHz"
                elif freq_hz >= 1_000:
                    metadata['receiver_frequency_display'] = f"{freq_hz / 1_000:.0f} kHz"
                else:
                    metadata['receiver_frequency_display'] = f"{freq_hz:.0f} Hz"

            metadata.setdefault('receiver_modulation', (self._receiver_config.modulation_type or 'IQ').upper())
            metadata.setdefault('squelch_enabled', self._squelch_enabled)
            metadata.setdefault('squelch_threshold_db', self._squelch_threshold_db)
            metadata.setdefault('squelch_open_ms', self._squelch_open_ms)
            metadata.setdefault('squelch_close_ms', self._squelch_close_ms)
            metadata.setdefault('carrier_alarm_enabled', self._squelch_alarm_enabled)
            metadata.setdefault('carrier_present', None if self._squelch_enabled else True)
            metadata.setdefault('squelch_state', 'pending' if self._squelch_enabled else 'open')
            metadata.setdefault('squelch_state_since', self._squelch_last_change)
            metadata.setdefault('squelch_last_rms_db', None)
            metadata.setdefault('carrier_alarm', False)
            self.metrics.metadata = metadata
            self._update_squelch_metadata(float('-inf'))

            # Create demodulator if audio output is enabled and modulation is not IQ
            if self._receiver_config.audio_output and self._receiver_config.modulation_type != 'IQ':
                # Get effective sample rate from receiver (after early decimation)
                # High sample rate SDRs (2.5 MHz+) decimate before the ring buffer
                receiver = self._radio_manager.get_receiver(receiver_id)
                if receiver and hasattr(receiver, 'get_effective_sample_rate'):
                    effective_rate = receiver.get_effective_sample_rate()
                else:
                    effective_rate = self._receiver_config.sample_rate

                demod_config = DemodulatorConfig(
                    modulation_type=self._receiver_config.modulation_type,
                    sample_rate=effective_rate,  # Use effective rate after decimation
                    audio_sample_rate=self.config.sample_rate,
                    stereo_enabled=self._receiver_config.stereo_enabled,
                    deemphasis_us=self._receiver_config.deemphasis_us,
                    enable_rbds=self._receiver_config.enable_rbds,
                )
                self._demodulator = create_demodulator(demod_config)
                if self._receiver_config.stereo_enabled:
                    self.config.channels = 2
                    self.metrics.channels = 2

                # Log demodulator configuration including RBDS status
                logger.info(
                    f"Created {self._receiver_config.modulation_type} demodulator for receiver: {receiver_id} "
                    f"(effective sample rate: {effective_rate} Hz, "
                    f"stereo={self._receiver_config.stereo_enabled}, "
                    f"enable_rbds={self._receiver_config.enable_rbds})"
                )

        # Start IQ capture from the specified receiver
        # When capturing IQ samples, use the receiver's native sample rate
        # The demodulator will resample to the desired audio output rate
        capture_sample_rate = self._receiver_config.sample_rate if self._demodulator else self.config.sample_rate
        self._capture_handle = self._radio_manager.start_audio_capture(
            receiver_id=self._receiver_id,
            sample_rate=capture_sample_rate,
            channels=self.config.channels,
            format='iq' if self._demodulator else 'pcm'
        )

        self.status = AudioSourceStatus.RUNNING
        logger.info(f"Started SDR audio capture from receiver: {receiver_id}")

    def _stop_capture(self) -> None:
        """Stop SDR audio capture."""
        if self._capture_handle and self._radio_manager:
            self._radio_manager.stop_audio_capture(self._capture_handle)
            self._capture_handle = None
        self._radio_manager = None
        self._receiver_id = None

    def _update_squelch_metadata(self, rms_db: float, carrier_present: Optional[bool] = None) -> None:
        """Update metadata reflecting the latest squelch measurements."""

        metadata = self.metrics.metadata or {}
        metadata['squelch_last_rms_db'] = (
            round(float(rms_db), 2)
            if np.isfinite(rms_db)
            else None
        )

        if carrier_present is None:
            carrier_present = self._squelch_state_open if self._squelch_enabled else True

        metadata['carrier_present'] = carrier_present
        metadata['squelch_state'] = 'open' if carrier_present else 'muted'
        metadata['squelch_state_since'] = self._squelch_last_change

        if carrier_present:
            metadata['carrier_alarm'] = False
        elif self._squelch_alarm_enabled:
            metadata['carrier_alarm'] = True
        else:
            metadata.setdefault('carrier_alarm', False)

        self.metrics.metadata = metadata

    def _emit_carrier_event(self, carrier_present: bool, rms_db: float) -> None:
        """Emit structured events when the carrier state changes."""

        self._update_squelch_metadata(rms_db, carrier_present)

        if not self._radio_manager:
            return

        receiver_id = self._receiver_id or self.config.device_params.get('receiver_id')
        source_name = self.config.name

        try:
            self._radio_manager.log_event(
                'INFO' if carrier_present else 'WARNING',
                f"Carrier {'restored' if carrier_present else 'lost'} on {receiver_id or source_name}",
                module='radio.audio',
                details={
                    'receiver_id': receiver_id,
                    'source': source_name,
                    'rms_db': round(float(rms_db), 2) if np.isfinite(rms_db) else None,
                    'threshold_db': self._squelch_threshold_db,
                },
            )
        except Exception:
            logger.debug('Failed to emit carrier state event for %s', receiver_id, exc_info=True)

    def _apply_squelch(self, audio_array: np.ndarray) -> np.ndarray:
        """Mute audio when carrier is lost according to squelch configuration."""

        if audio_array is None or audio_array.size == 0:
            self._update_squelch_metadata(float('-inf'))
            return audio_array

        if isinstance(audio_array, np.ndarray) and audio_array.ndim > 1:
            samples = audio_array.mean(axis=1)
        else:
            samples = audio_array

        samples64 = np.asarray(samples, dtype=np.float64)
        rms = float(np.sqrt(np.mean(samples64 ** 2))) if samples64.size else 0.0
        rms_db = 20.0 * np.log10(max(rms, 1e-10))

        if not self._squelch_enabled:
            self._update_squelch_metadata(rms_db, True)
            return audio_array

        now = time.time()
        previous_state = self._squelch_state_open
        open_threshold = self._squelch_threshold_db + 2.5

        if self._squelch_state_open:
            if rms_db < self._squelch_threshold_db:
                if self._squelch_close_timer is None:
                    self._squelch_close_timer = now
                elif (now - self._squelch_close_timer) * 1000.0 >= self._squelch_close_ms:
                    self._squelch_state_open = False
                    self._squelch_last_change = now
                    self._squelch_close_timer = None
                    self._emit_carrier_event(False, rms_db)
            else:
                self._squelch_close_timer = None
        else:
            if rms_db >= open_threshold:
                if self._squelch_open_timer is None:
                    self._squelch_open_timer = now
                elif (now - self._squelch_open_timer) * 1000.0 >= self._squelch_open_ms:
                    self._squelch_state_open = True
                    self._squelch_last_change = now
                    self._squelch_open_timer = None
                    self._emit_carrier_event(True, rms_db)
            else:
                self._squelch_open_timer = None

        if previous_state == self._squelch_state_open:
            self._update_squelch_metadata(rms_db)

        self._last_rms_db = rms_db

        if not self._squelch_state_open:
            return np.zeros_like(audio_array)

        return audio_array

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from SDR via radio manager."""
        if not self._capture_handle or not self._radio_manager:
            return None

        try:
            # Get data from radio manager (IQ or PCM depending on mode)
            audio_data = self._radio_manager.get_audio_data(
                self._capture_handle,
                chunk_size=self.config.buffer_size
            )

            if audio_data is not None:
                # If we have a demodulator, the data is IQ samples
                if self._demodulator:
                    # Convert to complex IQ samples
                    if isinstance(audio_data, bytes):
                        # Assume interleaved I/Q as float32 or int16
                        try:
                            iq_array = np.frombuffer(audio_data, dtype=np.float32)
                        except (ValueError, TypeError) as exc:
                            # Fallback to int16 if float32 conversion fails
                            try:
                                raw = np.frombuffer(audio_data, dtype=np.int16)
                                iq_array = raw.astype(np.float32) / 32768.0
                            except (ValueError, TypeError) as fallback_exc:
                                logger.error("Failed to convert audio data: %s (fallback also failed: %s)", exc, fallback_exc)
                                return None

                        # Convert interleaved I/Q to complex
                        iq_complex = iq_array[0::2] + 1j * iq_array[1::2]
                    else:
                        iq_complex = np.array(audio_data, dtype=np.complex64)

                    # Demodulate to audio - returns status with stereo pilot and RBDS info
                    audio_array, demod_status = self._demodulator.demodulate(iq_complex)

                    # Update metadata with demodulator status (stereo pilot, RBDS data)
                    if demod_status:
                        if self.metrics.metadata is None:
                            self.metrics.metadata = {}
                        metadata = self.metrics.metadata

                        # Stereo pilot status
                        metadata['stereo_pilot_locked'] = demod_status.stereo_pilot_locked
                        metadata['stereo_pilot_strength'] = demod_status.stereo_pilot_strength
                        metadata['is_stereo'] = demod_status.is_stereo

                        # RF RSSI (mean IQ magnitude).  Linear value; the UI
                        # converts to dBFS for the signal meter.
                        metadata['rf_signal_strength'] = float(demod_status.signal_strength)
                        metadata['rf_signal_strength_updated'] = time.time()

                        # Discriminator click telemetry — fraction of
                        # samples this chunk that the magnitude-aware
                        # click suppressor replaced.  Lets operators see
                        # "decoder noise-limited" vs "RF noise-limited"
                        # at a glance: a strong RSSI paired with a high
                        # click_rate (>0.05) means multipath fades, not a
                        # weak station.
                        metadata['fm_click_rate'] = float(getattr(demod_status, 'click_rate', 0.0))
                        metadata['fm_click_suppression_enabled'] = bool(
                            getattr(demod_status, 'click_suppression_enabled', False)
                        )

                        # RBDS decoder state.  Mirrors what redis_sdr_adapter
                        # publishes so the audio monitor can render the same
                        # LOCKED / LOCKING / DISABLED badge for in-process SDR
                        # sources.  Without this the UI had no signal-of-life
                        # from the decoder: a stuck sync state machine looked
                        # identical to "station doesn't transmit RBDS".
                        rbds_synced = bool(getattr(demod_status, 'rbds_synced', False))
                        rbds_enabled_runtime = bool(getattr(demod_status, 'rbds_enabled', False))
                        prev_synced = metadata.get('rbds_synced')
                        metadata['rbds_synced'] = rbds_synced
                        metadata['rbds_enabled'] = rbds_enabled_runtime
                        modulation_supports_stereo = (
                            (self._receiver_config.modulation_type or '').upper() in ('FM', 'WFM')
                            if self._receiver_config else False
                        )
                        if rbds_synced:
                            lock_state = 'LOCKED'
                        elif not modulation_supports_stereo:
                            lock_state = 'UNAVAILABLE'
                        elif not rbds_enabled_runtime:
                            lock_state = 'DISABLED'
                        else:
                            lock_state = 'LOCKING'
                        metadata['rbds_lock_state'] = lock_state
                        # Surface lock transitions in the journal so users
                        # can watch sync acquisition without enabling debug
                        # logging on the whole demodulator.
                        if rbds_synced and not prev_synced:
                            logger.info(
                                "RBDS LOCKED on %s (effective rate=%d Hz)",
                                self._receiver_id,
                                getattr(self._demodulator, '_intermediate_rate', 0),
                            )
                        elif (prev_synced is True) and not rbds_synced:
                            logger.info("RBDS sync lost on %s", self._receiver_id)

                        # Decoder health stats (block error rate, FEC counts,
                        # group histogram).  Always serialise when present —
                        # the dataclass is independent of whether content
                        # was decoded this cycle.
                        decoder_stats = getattr(demod_status, 'rbds_decoder_stats', None)
                        if decoder_stats is not None:
                            metadata['rbds_blocks_total'] = decoder_stats.blocks_total
                            metadata['rbds_blocks_ok'] = decoder_stats.blocks_ok
                            metadata['rbds_blocks_fec_single'] = decoder_stats.blocks_fec_single
                            metadata['rbds_blocks_fec_burst'] = decoder_stats.blocks_fec_burst
                            metadata['rbds_blocks_uncorrected'] = decoder_stats.blocks_uncorrected
                            metadata['rbds_blocks_bit_slips'] = decoder_stats.blocks_bit_slips
                            metadata['rbds_groups_decoded'] = decoder_stats.groups_decoded
                            metadata['rbds_sync_acquired_unix'] = decoder_stats.sync_acquired_unix
                            metadata['rbds_sync_lost_count'] = decoder_stats.sync_lost_count
                            metadata['rbds_chunks_dropped'] = decoder_stats.chunks_dropped
                            metadata['rbds_raw_bler'] = decoder_stats.raw_block_error_rate
                            metadata['rbds_net_bler'] = decoder_stats.net_block_error_rate
                            metadata['rbds_group_type_counts'] = (
                                dict(decoder_stats.group_type_counts)
                                if decoder_stats.group_type_counts else None
                            )

                        # RBDS data (if available)
                        rbds_data = demod_status.rbds_data
                        if rbds_data:
                            self._rbds_data = rbds_data
                            metadata['rbds_ps_name'] = rbds_data.ps_name
                            metadata['rbds_radio_text'] = rbds_data.radio_text
                            metadata['rbds_pty'] = rbds_data.pty
                            metadata['rbds_pty_name'] = rbds_data.pty_name
                            metadata['rbds_pi_code'] = rbds_data.pi_code
                            metadata['rbds_call_sign'] = rbds_data.call_sign
                            metadata['rbds_tp'] = rbds_data.tp
                            metadata['rbds_ta'] = rbds_data.ta
                            metadata['rbds_ms'] = rbds_data.ms
                            metadata['rbds_di_stereo'] = rbds_data.di_stereo
                            metadata['rbds_di_artificial_head'] = rbds_data.di_artificial_head
                            metadata['rbds_di_compressed'] = rbds_data.di_compressed
                            metadata['rbds_di_dynamic_pty'] = rbds_data.di_dynamic_pty
                            metadata['rbds_clock_time_utc'] = rbds_data.clock_time_utc
                            metadata['rbds_clock_time_local'] = rbds_data.clock_time_local
                            metadata['rbds_af_list'] = rbds_data.af_list
                            metadata['rbds_pin_day'] = rbds_data.pin_day
                            metadata['rbds_pin_hour'] = rbds_data.pin_hour
                            metadata['rbds_pin_minute'] = rbds_data.pin_minute
                            metadata['rbds_ecc'] = rbds_data.ecc
                            metadata['rbds_language_code'] = rbds_data.language_code
                            metadata['rbds_language_name'] = rbds_data.language_name
                            metadata['rbds_linkage_set_number'] = rbds_data.linkage_set_number
                            metadata['rbds_linkage_actuator'] = rbds_data.linkage_actuator
                            metadata['rbds_linkage_soft_coupling'] = rbds_data.linkage_soft_coupling
                            metadata['rbds_oda_apps'] = rbds_data.oda_apps
                            metadata['rbds_tdc_data'] = (
                                rbds_data.tdc_data.hex() if rbds_data.tdc_data else None
                            )
                            metadata['rbds_in_house_data'] = rbds_data.in_house_data
                            metadata['rbds_tmc_present'] = rbds_data.tmc_present
                            metadata['rbds_ews_channel'] = rbds_data.ews_channel
                            metadata['rbds_ews_message_c'] = rbds_data.ews_message_c
                            metadata['rbds_ews_message_d'] = rbds_data.ews_message_d
                            metadata['rbds_eon_list'] = rbds_data.eon_list
                            metadata['rbds_fast_tp'] = rbds_data.fast_tp
                            metadata['rbds_fast_ta'] = rbds_data.fast_ta
                            metadata['rbds_fast_ms'] = rbds_data.fast_ms
                            metadata['rbds_fast_di_bits'] = rbds_data.fast_di_bits
                            metadata['rbds_rt_plus_item_running'] = rbds_data.rt_plus_item_running
                            metadata['rbds_rt_plus_item_toggle'] = rbds_data.rt_plus_item_toggle
                            metadata['rbds_rt_plus_tags'] = rbds_data.rt_plus_tags
                            metadata['rbds_radio_text_ab'] = rbds_data.radio_text_ab
                            metadata['rbds_pi_country_code'] = rbds_data.pi_country_code
                            metadata['rbds_pi_area_code'] = rbds_data.pi_area_code
                            metadata['rbds_pi_program_ref'] = rbds_data.pi_program_ref
                            metadata['rbds_oda_assignments'] = rbds_data.oda_assignments
                            metadata['rbds_oda_payloads'] = rbds_data.oda_payloads
                            metadata['rbds_af_method_a_count'] = rbds_data.af_method_a_count
                            metadata['rbds_af_follow_on_indicator'] = rbds_data.af_follow_on_indicator
                            metadata['rbds_af_method_b'] = rbds_data.af_method_b
                            metadata['rbds_af_tuning_frequency'] = rbds_data.af_tuning_frequency
                            metadata['rbds_paging_messages'] = rbds_data.paging_messages
                            metadata['rbds_enhanced_paging_messages'] = rbds_data.enhanced_paging_messages
                            metadata['rbds_paging_tmc_id'] = rbds_data.paging_tmc_id
                            metadata['rbds_paging_operator_code'] = rbds_data.paging_operator_code
                            metadata['rbds_ews_channel_identifier'] = rbds_data.ews_channel_identifier
                            metadata['rbds_slow_labelling_raw'] = (
                                {str(k): v for k, v in rbds_data.slow_labelling_raw.items()}
                                if rbds_data.slow_labelling_raw else None
                            )
                            metadata['rbds_tdc_channels'] = (
                                {str(ch): buf.hex() for ch, buf in rbds_data.tdc_channels.items()}
                                if rbds_data.tdc_channels else None
                            )
                            metadata['rbds_program_type_name'] = (
                                RBDS_PROGRAM_TYPES.get(int(rbds_data.pty))
                                if rbds_data.pty is not None
                                else None
                            )
                            metadata['rbds_last_updated'] = time.time()
                        elif self._rbds_data:
                            # Use last known RBDS data if no new data this cycle
                            metadata['rbds_ps_name'] = self._rbds_data.ps_name
                            metadata['rbds_radio_text'] = self._rbds_data.radio_text
                            metadata['rbds_pty'] = self._rbds_data.pty
                            metadata['rbds_pty_name'] = self._rbds_data.pty_name
                            metadata['rbds_pi_code'] = self._rbds_data.pi_code
                            metadata['rbds_call_sign'] = self._rbds_data.call_sign
                            metadata['rbds_tp'] = self._rbds_data.tp
                            metadata['rbds_ta'] = self._rbds_data.ta
                            metadata['rbds_ms'] = self._rbds_data.ms
                            metadata['rbds_di_stereo'] = self._rbds_data.di_stereo
                            metadata['rbds_di_artificial_head'] = self._rbds_data.di_artificial_head
                            metadata['rbds_di_compressed'] = self._rbds_data.di_compressed
                            metadata['rbds_di_dynamic_pty'] = self._rbds_data.di_dynamic_pty
                            metadata['rbds_clock_time_utc'] = self._rbds_data.clock_time_utc
                            metadata['rbds_clock_time_local'] = self._rbds_data.clock_time_local
                            metadata['rbds_af_list'] = self._rbds_data.af_list
                            metadata['rbds_pin_day'] = self._rbds_data.pin_day
                            metadata['rbds_pin_hour'] = self._rbds_data.pin_hour
                            metadata['rbds_pin_minute'] = self._rbds_data.pin_minute
                            metadata['rbds_ecc'] = self._rbds_data.ecc
                            metadata['rbds_language_code'] = self._rbds_data.language_code
                            metadata['rbds_language_name'] = self._rbds_data.language_name
                            metadata['rbds_linkage_set_number'] = self._rbds_data.linkage_set_number
                            metadata['rbds_linkage_actuator'] = self._rbds_data.linkage_actuator
                            metadata['rbds_linkage_soft_coupling'] = self._rbds_data.linkage_soft_coupling
                            metadata['rbds_oda_apps'] = self._rbds_data.oda_apps
                            metadata['rbds_tdc_data'] = (
                                self._rbds_data.tdc_data.hex()
                                if self._rbds_data.tdc_data else None
                            )
                            metadata['rbds_in_house_data'] = self._rbds_data.in_house_data
                            metadata['rbds_tmc_present'] = self._rbds_data.tmc_present
                            metadata['rbds_ews_channel'] = self._rbds_data.ews_channel
                            metadata['rbds_ews_message_c'] = self._rbds_data.ews_message_c
                            metadata['rbds_ews_message_d'] = self._rbds_data.ews_message_d
                            metadata['rbds_eon_list'] = self._rbds_data.eon_list
                            metadata['rbds_fast_tp'] = self._rbds_data.fast_tp
                            metadata['rbds_fast_ta'] = self._rbds_data.fast_ta
                            metadata['rbds_fast_ms'] = self._rbds_data.fast_ms
                            metadata['rbds_fast_di_bits'] = self._rbds_data.fast_di_bits
                            metadata['rbds_rt_plus_item_running'] = self._rbds_data.rt_plus_item_running
                            metadata['rbds_rt_plus_item_toggle'] = self._rbds_data.rt_plus_item_toggle
                            metadata['rbds_rt_plus_tags'] = self._rbds_data.rt_plus_tags
                            metadata['rbds_radio_text_ab'] = self._rbds_data.radio_text_ab
                            metadata['rbds_pi_country_code'] = self._rbds_data.pi_country_code
                            metadata['rbds_pi_area_code'] = self._rbds_data.pi_area_code
                            metadata['rbds_pi_program_ref'] = self._rbds_data.pi_program_ref
                            metadata['rbds_oda_assignments'] = self._rbds_data.oda_assignments
                            metadata['rbds_oda_payloads'] = self._rbds_data.oda_payloads
                            metadata['rbds_af_method_a_count'] = self._rbds_data.af_method_a_count
                            metadata['rbds_af_follow_on_indicator'] = self._rbds_data.af_follow_on_indicator
                            metadata['rbds_af_method_b'] = self._rbds_data.af_method_b
                            metadata['rbds_af_tuning_frequency'] = self._rbds_data.af_tuning_frequency
                            metadata['rbds_paging_messages'] = self._rbds_data.paging_messages
                            metadata['rbds_enhanced_paging_messages'] = self._rbds_data.enhanced_paging_messages
                            metadata['rbds_paging_tmc_id'] = self._rbds_data.paging_tmc_id
                            metadata['rbds_paging_operator_code'] = self._rbds_data.paging_operator_code
                            metadata['rbds_ews_channel_identifier'] = self._rbds_data.ews_channel_identifier
                            metadata['rbds_slow_labelling_raw'] = (
                                {str(k): v for k, v in self._rbds_data.slow_labelling_raw.items()}
                                if self._rbds_data.slow_labelling_raw else None
                            )
                            metadata['rbds_tdc_channels'] = (
                                {str(ch): buf.hex() for ch, buf in self._rbds_data.tdc_channels.items()}
                                if self._rbds_data.tdc_channels else None
                            )
                            metadata['rbds_program_type_name'] = (
                                RBDS_PROGRAM_TYPES.get(int(self._rbds_data.pty))
                                if self._rbds_data.pty is not None
                                else None
                            )

                        self.metrics.metadata = metadata

                    return self._apply_squelch(audio_array)

                else:
                    # No demodulation - handle raw IQ samples
                    # When no demodulator is configured, we still get IQ samples from the SDR
                    # Convert them to mono audio by taking the magnitude (envelope detection)
                    if isinstance(audio_data, bytes):
                        # Assume interleaved I/Q as float32 or int16
                        try:
                            iq_array = np.frombuffer(audio_data, dtype=np.float32)
                        except (ValueError, TypeError):
                            try:
                                raw = np.frombuffer(audio_data, dtype=np.int16)
                                iq_array = raw.astype(np.float32) / 32768.0
                            except (ValueError, TypeError) as exc:
                                logger.error(f"Failed to convert IQ data: {exc}")
                                return None
                        
                        # Convert interleaved I/Q to complex
                        iq_complex = iq_array[0::2] + 1j * iq_array[1::2]
                        # Simple envelope detection for raw IQ
                        audio_array = np.abs(iq_complex).astype(np.float32)
                    else:
                        # Numpy array (complex64)
                        iq_complex = np.array(audio_data, dtype=np.complex64)
                        # Simple envelope detection for raw IQ
                        audio_array = np.abs(iq_complex).astype(np.float32)

                    return self._apply_squelch(audio_array)

        except Exception as e:
            logger.error(f"Error reading SDR audio: {e}", exc_info=True)

        return None


class ALSASourceAdapter(AudioSourceAdapter):
    """Audio source adapter for ALSA devices."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._alsa_device: Optional[alsaaudio.PCM] = None
        self._device_name = self.config.device_params.get('device_name', 'default')

    def _start_capture(self) -> None:
        """Start ALSA audio capture."""
        if not ALSA_AVAILABLE:
            raise RuntimeError("ALSA not available")

        try:
            # Create ALSA PCM capture device
            self._alsa_device = alsaaudio.PCM(
                alsaaudio.PCM_CAPTURE,
                alsaaudio.PCM_NORMAL,
                device=self._device_name
            )

            # Configure format
            self._alsa_device.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            self._alsa_device.setrate(self.config.sample_rate)
            self._alsa_device.setchannels(self.config.channels)
            self._alsa_device.setperiodsize(self.config.buffer_size // 4)

            self.status = AudioSourceStatus.RUNNING
            logger.info(f"Started ALSA audio capture from device: {self._device_name}")

        except Exception as e:
            raise RuntimeError(f"Failed to start ALSA capture: {e}")

    def _stop_capture(self) -> None:
        """Stop ALSA audio capture."""
        if self._alsa_device:
            self._alsa_device.close()
            self._alsa_device = None

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from ALSA device."""
        # If device is not connected, attempt reconnection
        if not self._alsa_device:
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                logger.info(f"ALSA device disconnected, attempting to reconnect (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
                time.sleep(0.5)  # Reduced from 2s to 0.5s for faster recovery
                try:
                    self._start_capture()
                    self._reconnect_attempts = 0  # Reset on successful reconnect
                    return None
                except Exception as e:
                    logger.error(f"ALSA reconnection failed: {e}")
                    self.status = AudioSourceStatus.DISCONNECTED
                    return None
            else:
                # Max reconnection attempts reached
                self.status = AudioSourceStatus.ERROR
                self.error_message = f"Max reconnection attempts ({self._max_reconnect_attempts}) reached"
                return None

        try:
            # Read data from ALSA
            length, data = self._alsa_device.read()

            if length > 0 and data:
                # Reset reconnect attempts on successful read
                self._reconnect_attempts = 0
                # Convert bytes to numpy array
                audio_array = np.frombuffer(data, dtype=np.int16)
                # Convert to float32 normalized to [-1, 1]
                audio_array = audio_array.astype(np.float32) / 32768.0
                return audio_array

        except Exception as e:
            logger.error(f"Error reading ALSA audio: {e}")
            # Close the device to trigger reconnection
            if self._alsa_device:
                try:
                    self._alsa_device.close()
                except Exception:
                    pass
                self._alsa_device = None
            # Attempt reconnection on next call
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self.status = AudioSourceStatus.DISCONNECTED

        return None


class PulseSourceAdapter(AudioSourceAdapter):
    """Audio source adapter for PulseAudio via PyAudio."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._pyaudio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._device_index = self.config.device_params.get('device_index', None)

    def _start_capture(self) -> None:
        """Start PulseAudio audio capture."""
        if not PULSE_AVAILABLE:
            raise RuntimeError("PyAudio not available")

        try:
            self._pyaudio = pyaudio.PyAudio()

            # Get device info if index specified
            if self._device_index is not None:
                device_info = self._pyaudio.get_device_info_by_index(self._device_index)
                logger.info(f"Using PulseAudio device: {device_info['name']}")

            # Create audio stream
            self._stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                input_device_index=self._device_index,
                frames_per_buffer=self.config.buffer_size
            )

            self.status = AudioSourceStatus.RUNNING
            logger.info("Started PulseAudio audio capture")

        except Exception as e:
            raise RuntimeError(f"Failed to start PulseAudio capture: {e}")

    def _stop_capture(self) -> None:
        """Stop PulseAudio audio capture."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        
        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from PulseAudio stream."""
        # If stream is not connected, attempt reconnection
        if not self._stream or not self._pyaudio:
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                logger.info(f"PulseAudio stream disconnected, attempting to reconnect (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
                time.sleep(0.5)  # Reduced from 2s to 0.5s for faster recovery
                try:
                    # Clean up old resources first
                    if self._stream:
                        try:
                            self._stream.stop_stream()
                            self._stream.close()
                        except Exception:
                            pass
                        self._stream = None
                    if self._pyaudio:
                        try:
                            self._pyaudio.terminate()
                        except Exception:
                            pass
                        self._pyaudio = None

                    # Attempt to restart
                    self._start_capture()
                    self._reconnect_attempts = 0  # Reset on successful reconnect
                    return None
                except Exception as e:
                    logger.error(f"PulseAudio reconnection failed: {e}")
                    self.status = AudioSourceStatus.DISCONNECTED
                    return None
            else:
                # Max reconnection attempts reached
                self.status = AudioSourceStatus.ERROR
                self.error_message = f"Max reconnection attempts ({self._max_reconnect_attempts}) reached"
                return None

        try:
            # Read data from stream
            data = self._stream.read(self.config.buffer_size, exception_on_overflow=False)

            if data:
                # Reset reconnect attempts on successful read
                self._reconnect_attempts = 0
                # Convert bytes to numpy array
                audio_array = np.frombuffer(data, dtype=np.int16)
                # Convert to float32 normalized to [-1, 1]
                audio_array = audio_array.astype(np.float32) / 32768.0
                return audio_array

        except Exception as e:
            logger.error(f"Error reading PulseAudio audio: {e}")
            # Close the stream to trigger reconnection
            if self._stream:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self._pyaudio:
                try:
                    self._pyaudio.terminate()
                except Exception:
                    pass
                self._pyaudio = None
            # Attempt reconnection on next call
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self.status = AudioSourceStatus.DISCONNECTED

        return None


class FileSourceAdapter(AudioSourceAdapter):
    """Audio source adapter for audio files (useful for testing)."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._file_path = Path(self.config.device_params.get('file_path', ''))
        self._audio_data: Optional[np.ndarray] = None
        self._current_position = 0
        self._loop = self.config.device_params.get('loop', False)

    def _start_capture(self) -> None:
        """Start file audio capture."""
        if not self._file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {self._file_path}")

        try:
            # Load audio file
            if self._file_path.suffix.lower() in ['.wav', '.wave']:
                self._audio_data = self._load_wav_file()
            elif self._file_path.suffix.lower() in ['.mp3']:
                self._audio_data = self._load_mp3_file()
            else:
                raise ValueError(f"Unsupported audio format: {self._file_path.suffix}")

            self._current_position = 0
            self.status = AudioSourceStatus.RUNNING
            logger.info(f"Started file audio capture: {self._file_path}")

        except Exception as e:
            raise RuntimeError(f"Failed to start file capture: {e}")

    def _stop_capture(self) -> None:
        """Stop file audio capture."""
        self._audio_data = None
        self._current_position = 0

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from file."""
        if self._audio_data is None:
            return None

        try:
            # Calculate chunk end position
            end_pos = self._current_position + self.config.buffer_size
            
            if end_pos >= len(self._audio_data):
                if self._loop:
                    # Loop back to beginning
                    end_pos = end_pos % len(self._audio_data)
                    chunk = np.concatenate([
                        self._audio_data[self._current_position:],
                        self._audio_data[:end_pos]
                    ])
                    self._current_position = end_pos
                else:
                    # Return remaining data and mark as finished
                    chunk = self._audio_data[self._current_position:]
                    self._current_position = len(self._audio_data)
                    # Pad with zeros if needed
                    if len(chunk) < self.config.buffer_size:
                        padding = np.zeros(self.config.buffer_size - len(chunk), dtype=np.float32)
                        chunk = np.concatenate([chunk, padding])
            else:
                chunk = self._audio_data[self._current_position:end_pos]
                self._current_position = end_pos

            # Ensure mono if needed
            if len(chunk.shape) > 1 and chunk.shape[1] > 1:
                chunk = np.mean(chunk, axis=1)

            return chunk.astype(np.float32)

        except Exception as e:
            logger.error(f"Error reading file audio: {e}")
            return None

    def _load_wav_file(self) -> np.ndarray:
        """Load WAV file using wave module."""
        import wave
        
        with wave.open(str(self._file_path), 'rb') as wav_file:
            # Get audio properties
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            
            # Read all data
            frames = wav_file.readframes(-1)
            
            # Convert to numpy array
            if sample_width == 2:
                dtype = np.int16
            elif sample_width == 4:
                dtype = np.int32
            else:
                raise ValueError(f"Unsupported sample width: {sample_width}")
            
            audio_array = np.frombuffer(frames, dtype=dtype)
            
            # Convert to float32 and normalize
            max_val = float(np.iinfo(dtype).max)
            audio_array = audio_array.astype(np.float32) / max_val
            
            # Reshape if stereo
            if channels > 1:
                audio_array = audio_array.reshape(-1, channels)
            
            return audio_array

    def _load_mp3_file(self) -> np.ndarray:
        """Load MP3 file using pydub (if available)."""
        try:
            from pydub import AudioSegment
            
            audio = AudioSegment.from_mp3(str(self._file_path))
            
            # Convert to numpy array
            samples = np.array(audio.get_array_of_samples())
            
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
            
            # Convert to float32 and normalize
            max_val = float(2 ** (audio.sample_width * 8 - 1))
            samples = samples.astype(np.float32) / max_val
            
            return samples
            
        except ImportError:
            raise RuntimeError("pydub not available for MP3 playback - install with: pip install pydub")


class StreamSourceAdapter(AudioSourceAdapter):
    """Audio source adapter that delegates streaming + decoding to FFmpeg.
    
    24/7/365 RELIABILITY FEATURES:
    - Automatic reconnection with exponential backoff
    - Robust error handling for network interruptions
    - Non-blocking I/O prevents thread stalls
    - Independent threads per stream (no resource contention)
    - Continuous metadata monitoring
    - Preserves native stream sample rate (no unnecessary resampling)
    """

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        # Support both 'url' (new) and 'stream_url' (legacy) parameter names
        self._stream_url = self.config.device_params.get('url') or self.config.device_params.get('stream_url', '')
        self._resolved_stream_url: Optional[str] = None
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._pcm_backlog = bytearray()
        self._stream_metadata: Dict[str, Any] = {}
        self._last_restart = 0.0
        # 24/7 RELIABILITY: Reduced restart delay for faster recovery
        self._restart_delay_seconds = 2.0  # Reduced from 3.0 for faster failover
        self._metadata_thread: Optional[threading.Thread] = None
        self._metadata_stop_event = threading.Event()
        self._metadata_lock = threading.Lock()
        self._last_icy_metadata: Optional[str] = None
        
        # 24/7 RELIABILITY: Track connection health for monitoring
        self._connection_attempts = 0
        self._successful_connections = 0
        self._last_connection_time: Optional[float] = None

    def _resolve_stream_url(self, url: str) -> str:
        """Validate the configured URL and resolve playlists when needed."""
        # Strip leading/trailing whitespace from URL
        url = url.strip() if url else ''

        if not url:
            raise ValueError("stream_url must be configured for stream sources")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported stream URL scheme '{parsed.scheme}'")
        if not parsed.netloc:
            raise ValueError("Invalid stream URL: missing hostname")

        lower_path = parsed.path.lower()
        if lower_path.endswith('.m3u') or lower_path.endswith('.m3u8'):
            if not REQUESTS_AVAILABLE:
                raise RuntimeError("Requests library not available to resolve playlist URLs")

            try:
                # Disable proxy to allow direct connections to external streams
                response = requests.get(url, timeout=10, proxies={'http': None, 'https': None})
                response.raise_for_status()
            except Exception as exc:
                raise RuntimeError(f"Failed to fetch playlist {url}: {exc}") from exc

            for line in response.text.splitlines():
                entry = line.strip()
                if not entry or entry.startswith('#'):
                    continue

                candidate = urljoin(url, entry)
                candidate_parsed = urlparse(candidate)
                if candidate_parsed.scheme in ("http", "https") and candidate_parsed.netloc:
                    logger.info(f"Resolved M3U entry to stream URL: {candidate}")
                    return candidate

            raise RuntimeError(f"Playlist {url} did not contain a playable stream URL")

        return url

    def _build_ffmpeg_command(self, stream_url: str) -> List[str]:
        """Construct the FFmpeg command used for streaming + decoding.
        
        IMPORTANT: For HTTP/HTTPS streams, we let FFmpeg preserve the stream's native
        sample rate instead of resampling. This ensures the stream plays at the correct
        bitrate and prevents quality degradation from unnecessary resampling.
        
        24/7/365 RELIABILITY FEATURES:
        - Automatic reconnection on network errors
        - Longer timeout for initial connection (handles slow servers)
        - Aggressive buffering to handle network jitter
        - Preserves native sample rate (prevents resampling artifacts)
        
        The stream's actual sample rate will be detected by FFmpeg from the stream metadata.
        """
        # Check if we should preserve stream's native sample rate (default for HTTP streams)
        preserve_native_rate = self.config.device_params.get('preserve_native_rate', True)
        
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'info',  # Need 'info' level to detect stream sample rate from metadata
            '-nostdin',
            '-user_agent', 'EAS-Station/2.0',  # Updated user agent
            '-headers', 'Icy-MetaData:1\r\n',
            # 24/7 RELIABILITY: Enhanced reconnection parameters for network resilience
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_on_network_error', '1',
            '-reconnect_on_http_error', '4xx,5xx',  # Retry on HTTP errors
            '-reconnect_delay_max', '10',  # Increased from 5 for better backoff
            '-timeout', '30000000',  # 30 seconds in microseconds (FFmpeg expects microseconds: 30 × 1,000,000 = 30,000,000 µs)
            '-fflags', '+genpts+discardcorrupt',  # Generate PTS and discard corrupt packets
            '-analyzeduration', '2000000',  # 2 seconds to analyze stream (5s caused false stall detections)
            '-probesize', '2000000',  # 2MB probe size for stream detection
            '-i', stream_url,
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # 16-bit PCM output
        ]
        
        # Only add sample rate conversion if explicitly requested (not default)
        if not preserve_native_rate:
            output_sample_rate = self.config.sample_rate
            if output_sample_rate < 32000:
                logger.warning(
                    f"StreamSourceAdapter {self.config.name}: sample_rate is {output_sample_rate} Hz "
                    f"which is below normal audio range. Using 48000 Hz instead. "
                    f"(If configured for EAS decoder, that should be applied downstream, not to source)"
                )
                output_sample_rate = 48000
            cmd.extend(['-ar', str(output_sample_rate)])
            logger.info(f"{self.config.name}: Forcing stream resample to {output_sample_rate} Hz")
        else:
            logger.info(f"{self.config.name}: Preserving stream's native sample rate (no resampling)")
        
        # Always specify output channels and format
        cmd.extend([
            '-ac', str(self.config.channels),
            '-f', 's16le',
            'pipe:1',
        ])
        
        return cmd

    def _launch_ffmpeg_process(self) -> None:
        """Start a fresh FFmpeg process that reads from the resolved stream URL.
        
        24/7 RELIABILITY: Tracks connection attempts and success rate for monitoring.
        """
        if not self._resolved_stream_url:
            raise RuntimeError("Stream URL has not been resolved yet")

        self._stop_ffmpeg_process()
        command = self._build_ffmpeg_command(self._resolved_stream_url)
        
        # Track connection attempt for reliability monitoring
        self._connection_attempts += 1
        logger.info(
            f"{self.config.name}: launching FFmpeg decoder "
            f"(attempt #{self._connection_attempts}, success rate: "
            f"{self._successful_connections}/{self._connection_attempts})"
        )

        # CRITICAL: Create clean environment for FFmpeg without proxy settings
        # Bare metal deployments may inherit HTTP_PROXY from environment (e.g., Claude Code)
        # which prevents FFmpeg from connecting to actual radio station streams
        ffmpeg_env = os.environ.copy()
        ffmpeg_env['http_proxy'] = ''
        ffmpeg_env['https_proxy'] = ''
        ffmpeg_env['HTTP_PROXY'] = ''
        ffmpeg_env['HTTPS_PROXY'] = ''

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=131072,  # 128KB buffer for better performance with network streams
                env=ffmpeg_env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("FFmpeg executable not found in PATH") from exc
        except Exception as exc:
            raise RuntimeError(f"Failed to start FFmpeg: {exc}") from exc

        if process.stdout is None:
            process.kill()
            raise RuntimeError("FFmpeg stdout pipe was not created")

        # Make stdout non-blocking so the capture loop can poll without hanging
        os.set_blocking(process.stdout.fileno(), False)

        # Drain stderr in a background thread to avoid the pipe filling up
        if process.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._stderr_pump,
                args=(process,),
                name=f"ffmpeg-stderr-{self.config.name}",
                daemon=True,
            )
            self._stderr_thread.start()
        else:
            self._stderr_thread = None

        self._ffmpeg_process = process
        self._pcm_backlog.clear()
        self._last_restart = time.time()
        
        # Track successful launch (actual connection verified when we receive first audio)
        logger.info(f"{self.config.name}: FFmpeg process started (PID: {process.pid})")

    def _stop_ffmpeg_process(self) -> None:
        """Terminate any running FFmpeg process and clean up resources."""
        process = self._ffmpeg_process
        self._ffmpeg_process = None

        if process is None:
            return

        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()  # Reap the zombie process after kill
        finally:
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except Exception:
                    pass
            if process.stderr is not None:
                try:
                    process.stderr.close()
                except Exception:
                    pass

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1)
        self._stderr_thread = None

    def _restart_ffmpeg_process(self, reason: str) -> None:
        """Restart FFmpeg with a small backoff to avoid tight crash loops.
        
        24/7 RELIABILITY: Implements exponential backoff and tracks restart patterns.
        """
        now = time.time()
        if now - self._last_restart < self._restart_delay_seconds:
            return
        
        # Reset connection tracking for new attempt
        self._last_connection_time = None

        logger.warning(f"{self.config.name}: restarting FFmpeg decoder ({reason})")
        try:
            self._launch_ffmpeg_process()
        except Exception as exc:
            # Update _last_restart even on failure so the backoff delay applies
            # before the next attempt.  Without this, _last_restart stays at 0
            # and every _read_audio_chunk() call immediately retries, creating a
            # tight crash loop that burns CPU and floods logs.
            self._last_restart = time.time()
            self.status = AudioSourceStatus.ERROR
            self.error_message = str(exc)
            logger.error(f"{self.config.name}: failed to restart FFmpeg: {exc}")
        else:
            # Successful restart - clear error state and refresh metadata
            self.status = AudioSourceStatus.RUNNING
            self.error_message = None

            metadata_updates: Dict[str, Any] = {
                'connection_timestamp': time.time(),
                'last_error': None,
                'restart_reason': reason,
                'connection_attempts': self._connection_attempts,
                'successful_connections': self._successful_connections,
            }

            icy_state = self._stream_metadata.get('icy')
            if isinstance(icy_state, dict):
                metadata_updates['icy'] = {
                    'last_error': None,
                    'last_check': time.time(),
                    'supported': icy_state.get('supported', False),
                    'metaint': icy_state.get('metaint'),
                }

            self._apply_metadata_update(metadata_updates)
            logger.info(f"{self.config.name}: FFmpeg decoder restarted successfully")

    def _stderr_pump(self, process: subprocess.Popen) -> None:
        """Continuously drain FFmpeg stderr and detect actual stream sample rate.
        
        CRITICAL: When preserve_native_rate=True, FFmpeg outputs audio at the stream's
        native sample rate. We must detect this from stderr to ensure WAV headers match.
        """
        stderr = process.stderr
        if stderr is None:
            return

        detected_sample_rate = None
        preserve_native = self.config.device_params.get('preserve_native_rate', True)
        
        try:
            for raw_line in iter(stderr.readline, b''):
                if not raw_line:
                    break
                text = raw_line.decode('utf-8', errors='replace').strip()
                if not text:
                    continue
                    
                # Parse FFmpeg output to detect actual stream sample rate
                # Example: "Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp, 128 kb/s"
                # Example: "Stream #0:0: Audio: aac, 48000 Hz, stereo, fltp"
                if preserve_native and detected_sample_rate is None and 'Audio:' in text and 'Hz' in text:
                    import re
                    # Match sample rate in Hz (e.g., "44100 Hz", "48000 Hz")
                    match = re.search(r'(\d+)\s*Hz', text)
                    if match:
                        rate = int(match.group(1))
                        if 8000 <= rate <= 192000:  # Sanity check
                            detected_sample_rate = rate
                            logger.info(
                                f"{self.config.name}: Detected stream native sample rate: {rate} Hz "
                                f"(config was {self.config.sample_rate} Hz)"
                            )
                            # Update config to match FFmpeg's actual output
                            if self.config.sample_rate != rate:
                                logger.warning(
                                    f"{self.config.name}: Updating config.sample_rate from {self.config.sample_rate} "
                                    f"to detected {rate} Hz to match FFmpeg output"
                                )
                                self.config.sample_rate = rate
                                # Update metrics to reflect actual sample rate
                                self.metrics.sample_rate = rate
                
                # Log errors and warnings, but debug for normal info
                if 'error' in text.lower() or 'warning' in text.lower():
                    logger.warning(f"{self.config.name}: FFmpeg: {text}")
                else:
                    logger.debug(f"{self.config.name}: FFmpeg: {text}")
        except Exception as exc:
            logger.debug(f"{self.config.name}: stderr pump stopped: {exc}")

    def _start_capture(self) -> None:
        """Resolve the stream URL and start FFmpeg decoding."""
        resolved = self._resolve_stream_url(self._stream_url)
        self._resolved_stream_url = resolved

        self._stream_metadata = {
            'stream_url': self._stream_url,
            'resolved_url': resolved,
            'connection_timestamp': time.time(),
            'decoder': 'ffmpeg',
            'icy': {
                'supported': False,
            },
        }
        with self._metadata_lock:
            self.metrics.metadata = copy.deepcopy(self._stream_metadata)
        self._last_icy_metadata = None

        logger.info(f"{self.config.name}: resolved stream to {resolved}")
        self._launch_ffmpeg_process()
        self.status = AudioSourceStatus.RUNNING
        self._start_metadata_listener()

    def _stop_capture(self) -> None:
        """Stop FFmpeg decoding for the stream source."""
        self._stop_metadata_listener()
        self._stop_ffmpeg_process()
        self._pcm_backlog.clear()

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read decoded PCM samples from FFmpeg stdout.
        
        RELIABILITY FIX: For network streams, FFmpeg may need several seconds to establish
        the HTTP connection before audio data starts flowing. Setting _had_data_activity=True
        prevents the capture loop from excessive sleeping during connection establishment.
        """
        # CRITICAL: Set this True for stream sources to prevent capture loop from sleeping
        # while FFmpeg is connecting to the network stream. FFmpeg needs time to:
        # 1. Resolve DNS
        # 2. Establish TCP connection
        # 3. Send HTTP request
        # 4. Receive response headers
        # 5. Begin receiving audio stream
        # This can take 5-10 seconds for remote streams. During this time, we want the
        # capture loop to keep polling frequently rather than sleeping 50ms between attempts.
        self._had_data_activity = True  # Stream sources are always "active" even when connecting

        process = self._ffmpeg_process
        if process is None or process.poll() is not None:
            self._restart_ffmpeg_process("decoder not running")
            return None

        stdout = process.stdout
        if stdout is None:
            self._restart_ffmpeg_process("stdout pipe missing")
            return None

        bytes_per_sample = 2 * self.config.channels
        target_bytes = self.config.buffer_size * bytes_per_sample

        try:
            while len(self._pcm_backlog) < target_bytes:
                try:
                    chunk = stdout.read(target_bytes - len(self._pcm_backlog))
                except BlockingIOError:
                    # Non-blocking read - no data available yet, try again next time
                    break

                if not chunk:
                    # Empty read - check if process died, otherwise it means FFmpeg is still
                    # connecting to the stream and hasn't started producing audio yet
                    if process.poll() is not None:
                        self._restart_ffmpeg_process("decoder exited")
                    # DON'T break here - FFmpeg might still be connecting to network stream
                    # Keep the backlog at its current size and return None to let capture loop
                    # poll again. This is normal for streams that are starting up.
                    break

                self._pcm_backlog.extend(chunk)
                # Actual data received - this confirms FFmpeg is producing audio
                
                # 24/7 RELIABILITY: Track successful connection on first audio data
                if self._last_connection_time is None:
                    self._successful_connections += 1
                    self._last_connection_time = time.time()
                    logger.info(
                        f"{self.config.name}: ✅ Stream connected successfully! "
                        f"(success rate: {self._successful_connections}/{self._connection_attempts})"
                    )
        except Exception as exc:
            logger.error(f"{self.config.name}: error reading from FFmpeg stdout: {exc}")
            self._restart_ffmpeg_process("stdout read error")
            return None

        if len(self._pcm_backlog) < target_bytes:
            # Not enough data buffered yet - this is normal during:
            # 1. Initial stream connection (can take 5-10 seconds)
            # 2. Network hiccups or buffering
            # 3. Stream reconnection after temporary failure
            # The capture loop will call us again shortly
            return None

        raw = bytes(self._pcm_backlog[:target_bytes])
        del self._pcm_backlog[:target_bytes]

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples

    def _start_metadata_listener(self) -> None:
        """Start a background thread that harvests ICY metadata from the stream."""
        if not REQUESTS_AVAILABLE:
            return

        if self._metadata_thread and self._metadata_thread.is_alive():
            return

        self._metadata_stop_event.clear()
        self._metadata_thread = threading.Thread(
            target=self._metadata_loop,
            name=f"metadata-{self.config.name}",
            daemon=True,
        )
        self._metadata_thread.start()

    def _stop_metadata_listener(self) -> None:
        """Stop the ICY metadata harvesting thread."""
        self._metadata_stop_event.set()
        if self._metadata_thread and self._metadata_thread.is_alive():
            self._metadata_thread.join(timeout=2.0)
        self._metadata_thread = None

    def _metadata_loop(self) -> None:
        """Continuously poll the stream for ICY metadata updates."""
        if not REQUESTS_AVAILABLE:
            return

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'EAS-Station/1.0',
            'Icy-MetaData': '1',
        })
        # CRITICAL: Disable proxy to allow direct connections to external streams
        # Bare metal deployments may inherit HTTP_PROXY from environment (e.g., Claude Code)
        # which prevents connection to actual radio station streams
        session.proxies = {'http': None, 'https': None}

        try:
            while not self._metadata_stop_event.is_set():
                stream_url = self._resolved_stream_url or self._stream_url
                if not stream_url:
                    break

                try:
                    response = session.get(
                        stream_url,
                        stream=True,
                        timeout=(5.0, 15.0),
                    )
                    response.raise_for_status()
                except Exception as exc:
                    logger.debug(
                        "%s: metadata request failed: %s",
                        self.config.name,
                        exc,
                    )
                    if self._metadata_stop_event.wait(5.0):
                        break
                    continue

                metaint_header = response.headers.get('icy-metaint')
                try:
                    metaint = int(metaint_header)
                except (TypeError, ValueError):
                    metaint = 0

                if metaint <= 0:
                    logger.debug(
                        "%s: stream does not advertise ICY metadata (icy-metaint=%s)",
                        self.config.name,
                        metaint_header,
                    )
                    self._apply_metadata_update({
                        'icy': {
                            'supported': False,
                            'last_error': 'ICY metadata not available',
                            'last_check': time.time(),
                        }
                    })
                    response.close()
                    if self._metadata_stop_event.wait(30.0):
                        break
                    continue

                self._apply_metadata_update({
                    'icy': {
                        'supported': True,
                        'metaint': metaint,
                        'last_error': None,
                        'last_check': time.time(),
                    }
                })

                raw = response.raw
                raw.decode_content = False

                try:
                    while not self._metadata_stop_event.is_set():
                        if not raw.read(metaint):
                            break

                        length_byte = raw.read(1)
                        if not length_byte:
                            break

                        block_length = length_byte[0] * 16
                        if block_length == 0:
                            continue

                        metadata_block = raw.read(block_length) or b''
                        metadata_text = metadata_block.rstrip(b'\x00').decode(
                            'utf-8', errors='replace'
                        ).strip()

                        if metadata_text:
                            self._handle_icy_metadata(metadata_text)

                except Exception as exc:
                    logger.debug(
                        "%s: error while reading ICY metadata: %s",
                        self.config.name,
                        exc,
                    )
                    self._apply_metadata_update({
                        'icy': {
                            'last_error': str(exc),
                            'last_check': time.time(),
                        }
                    })
                finally:
                    response.close()

                if self._metadata_stop_event.wait(3.0):
                    break
        finally:
            session.close()

    def _handle_icy_metadata(self, metadata_text: str) -> None:
        """Parse raw ICY metadata and update the source metadata cache."""
        if metadata_text == self._last_icy_metadata:
            return

        self._last_icy_metadata = metadata_text

        def _strip_wrapping_quotes(value: str) -> str:
            """Remove a single layer of matching quotes from the ends of a string."""

            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                return value[1:-1]
            return value

        # ICY outer metadata format: KEY='VALUE';KEY='VALUE';
        # Values can contain ';' and '"', so we MUST NOT split naively on ';'.
        # Use a regex that matches single-quoted ICY values correctly.
        fields: Dict[str, Any] = {}
        for m in _re.finditer(r"(\w+)='([^']*)'", metadata_text):
            fields[m.group(1)] = m.group(2)
        # Fallback: some stations emit unquoted or double-quoted fields; handle them
        # only for keys we haven't already seen from the regex pass.
        for part in metadata_text.split(';'):
            part = part.strip()
            if not part or '=' not in part:
                continue
            key, value = part.split('=', 1)
            key = key.strip()
            if key and key not in fields:
                value = _strip_wrapping_quotes(value.strip())
                fields[key] = value

        updates: Dict[str, Any] = {
            'icy': {
                'supported': True,
                'fields': fields,
                'raw': metadata_text,
                'last_update': time.time(),
            }
        }

        stream_title = fields.get('StreamTitle')
        if stream_title:
            updates['song_raw'] = stream_title

            # Parse rich metadata from StreamTitle (e.g., iHeartRadio format)
            # Example: text="Golden" song_spot="M" MediaBaseId="3136003" ... amgArtworkURL="..." length="00:03:11"
            import re

            title = stream_title.strip()
            artist = None

            # --- Step 1: extract title from an explicit attribute ---
            # Different stream formats use different keys:
            #   iHeartRadio primary:  text="Golden"
            #   iHeartRadio alt:      title="Without You"   <-- this stream!
            #   some automation:      song="..."
            text_match       = re.search(r'\btext="([^"]+)"',   stream_title)
            title_attr_match = re.search(r'\btitle="([^"]+)"',  stream_title)
            song_attr_match  = re.search(r'\bsong="([^"]+)"',   stream_title)

            # Pick the first match in preference order
            explicit_match = text_match or title_attr_match or song_attr_match
            if explicit_match:
                title = unquote(explicit_match.group(1)).strip()
                updates['song_title'] = title
                updates['title'] = title

            # --- Step 2: extract artist ---
            artist_match = re.search(r'\bartist="([^"]+)"', stream_title)
            if artist_match:
                artist = unquote(artist_match.group(1)).strip()
                updates['artist'] = artist
                updates['song_artist'] = artist
            elif explicit_match:
                # Look for "ArtistName - <attr>=\"...\"" prefix before the attribute
                attr_key = 'text' if text_match else ('title' if title_attr_match else 'song')
                prefix_match = re.match(rf'(?P<artist>.+?)\s+-\s+{attr_key}="', stream_title)
                if prefix_match:
                    artist_candidate = unquote(prefix_match.group('artist')).strip()
                    if artist_candidate:
                        artist = artist_candidate
                        updates['artist'] = artist
                        updates['song_artist'] = artist

            # --- Step 3: artwork, length, album ---
            artwork_match = re.search(r'(?:amgArtworkURL|artworkURL|artwork_url)="([^"]+)"', stream_title)
            if artwork_match:
                updates['artwork_url'] = artwork_match.group(1).strip()

            length_match = re.search(r'(?:length|duration)="([^"]+)"', stream_title)
            if length_match:
                updates['length'] = length_match.group(1).strip()

            album_match = re.search(r'\balbum="([^"]+)"', stream_title)
            if album_match:
                updates['album'] = unquote(album_match.group(1)).strip()

            # --- Step 4: traditional "Artist - Title" fallback ---
            # Only used when no explicit title attribute was found.
            if not explicit_match and ' - ' in stream_title:
                clean_title = re.sub(r'[\s;]\w+="[^"]*"', '', stream_title)
                clean_title = re.sub(r'\s+\w+=\S+', '', clean_title)
                clean_title = ' '.join(clean_title.split()).strip()
                clean_title = unquote(clean_title)

                if ' - ' in clean_title:
                    artist_candidate, title_candidate = clean_title.split(' - ', 1)
                    extracted_artist = artist_candidate.strip()
                    extracted_title  = title_candidate.strip()

                    if extracted_title:
                        title = extracted_title
                        updates['song_title'] = title
                        updates['title'] = title
                    if extracted_artist and not artist_match:
                        artist = extracted_artist
                        updates['artist'] = artist
                        updates.setdefault('song_artist', artist)

            # --- Step 5: stream URL from url="" attribute ---
            url_match = _re.search(r'\burl="(https?://[^"]{8,})"', stream_title)
            if url_match:
                updates.setdefault('stream_url', url_match.group(1).strip())

            # --- Step 6: build display_song now that all fields are settled ---
            # Guard against the case where title was never updated (stays as the raw
            # stream_title string) — don't use it as a display value in that case.
            title_is_clean = title and title != stream_title.strip()
            if artist and title_is_clean:
                display_song = f"{artist} - {title}"
            elif title_is_clean:
                display_song = title
            elif artist:
                display_song = artist
            else:
                display_song = None

            if display_song:
                updates['song'] = display_song
            elif _looks_like_base64_blob(stream_title):
                # Try to decode the base64 blob as a playable URL (e.g. a VAST ad tag).
                decoded_url = _decode_base64_url(stream_title)
                if decoded_url:
                    updates['stream_url'] = decoded_url
                # Do not store the raw base64 blob as the song display value.
            else:
                updates['song'] = stream_title

            # Log metadata change at INFO level so stream activity is visible in logs
            logger.info(
                "%s: now playing — %s",
                self.config.name,
                display_song or stream_title,
            )

            now_playing: Dict[str, Any] = {'raw': stream_title}
            if title:
                now_playing['title'] = title
            if artist:
                now_playing['artist'] = artist

            updates['now_playing'] = now_playing

            # Expose the parsed fields for UI fallbacks without clobbering the raw data
            if title:
                fields.setdefault('text', title)
                fields.setdefault('title', title)
                fields.setdefault('song', display_song or title)
            if artist:
                fields.setdefault('artist', artist)
            if updates.get('artwork_url'):
                fields.setdefault('artwork_url', updates['artwork_url'])
            if updates.get('length'):
                fields.setdefault('length', updates['length'])
            if updates.get('album'):
                fields.setdefault('album', updates['album'])

        stream_url = fields.get('StreamUrl')
        if stream_url:
            updates['resolved_url'] = stream_url

        self._apply_metadata_update(updates)

    def _apply_metadata_update(self, updates: Dict[str, Any]) -> None:
        """Merge metadata updates into the shared cache and sync metrics."""

        def _merge_dict(base: Dict[str, Any], new_data: Dict[str, Any]) -> bool:
            changed = False
            for key, value in new_data.items():
                if isinstance(value, dict):
                    existing = base.get(key)
                    if isinstance(existing, dict):
                        if _merge_dict(existing, value):
                            changed = True
                    else:
                        base[key] = copy.deepcopy(value)
                        changed = True
                else:
                    if base.get(key) != value:
                        base[key] = value
                        changed = True
            return changed

        with self._metadata_lock:
            changed = _merge_dict(self._stream_metadata, updates)
            if changed:
                self.metrics.metadata = copy.deepcopy(self._stream_metadata)

        if changed and self.on_metadata_change and 'now_playing' in updates:
            try:
                self.on_metadata_change(self.config.name, updates)
            except Exception as exc:
                logger.warning("on_metadata_change callback error: %s", exc)

# Factory function for creating sources
def create_audio_source(config: AudioSourceConfig) -> AudioSourceAdapter:
    """Factory function to create the appropriate audio source adapter."""
    
    if config.source_type.value == "sdr":
        if not RADIO_AVAILABLE:
            raise RuntimeError("SDR source not available - radio manager missing")
        return SDRSourceAdapter(config)
    
    elif config.source_type.value == "alsa":
        if not ALSA_AVAILABLE:
            raise RuntimeError("ALSA source not available - install python3-alsaaudio")
        return ALSASourceAdapter(config)
    
    elif config.source_type.value == "pulse":
        if not PULSE_AVAILABLE:
            raise RuntimeError("PulseAudio source not available - install pyaudio")
        return PulseSourceAdapter(config)
    
    elif config.source_type.value == "file":
        return FileSourceAdapter(config)

    elif config.source_type.value == "stream":
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("Stream source not available - install requests library")
        return StreamSourceAdapter(config)

    else:
        raise ValueError(f"Unsupported audio source type: {config.source_type}")
