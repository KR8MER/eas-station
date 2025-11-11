"""
Continuous EAS Monitoring Service

Integrates professional audio subsystem with EAS decoder for 24/7 alert monitoring.
Continuously buffers audio from AudioSourceManager and runs SAME decoder to detect alerts.

This is the bridge between the audio subsystem and the alert detection logic.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, List

import numpy as np

from app_utils.eas_decode import decode_same_audio, SAMEAudioDecodeResult
from app_utils import utc_now
from .source_manager import AudioSourceManager

logger = logging.getLogger(__name__)


@dataclass
class EASAlert:
    """Detected EAS alert with metadata."""
    timestamp: datetime
    raw_text: str
    headers: List[dict]
    confidence: float
    duration_seconds: float
    source_name: str
    audio_file_path: Optional[str] = None


def create_fips_filtering_callback(
    configured_fips_codes: List[str],
    forward_callback: Callable[[EASAlert], None],
    logger_instance: Optional[logging.Logger] = None
) -> Callable[[EASAlert], None]:
    """
    Create an alert callback wrapper that filters by FIPS codes and logs results.

    This helper function creates a callback that:
    1. Extracts FIPS codes from the alert
    2. Compares them against configured FIPS codes
    3. Logs the matching result
    4. Only forwards alerts that match configured FIPS codes

    Args:
        configured_fips_codes: List of FIPS codes to match (e.g., ['039137', '039051'])
        forward_callback: Function to call when alert matches FIPS codes
        logger_instance: Optional logger (defaults to module logger)

    Returns:
        Callback function that can be passed to ContinuousEASMonitor

    Example:
        >>> configured_fips = ['039137', '039051']  # Putnam County, OH + Others
        >>> def my_forward_handler(alert):
        ...     print(f"Forwarding alert: {alert.raw_text}")
        >>>
        >>> callback = create_fips_filtering_callback(
        ...     configured_fips,
        ...     my_forward_handler,
        ...     logger
        ... )
        >>> monitor = ContinuousEASMonitor(
        ...     audio_manager=manager,
        ...     alert_callback=callback
        ... )
    """
    log = logger_instance or logger

    def fips_filtering_callback(alert: EASAlert) -> None:
        """Callback that filters alerts by FIPS codes with logging."""
        # Extract FIPS codes from alert
        alert_fips_codes = []
        event_code = "UNKNOWN"
        originator = "UNKNOWN"

        if alert.headers and len(alert.headers) > 0:
            first_header = alert.headers[0]
            if 'fields' in first_header:
                fields = first_header['fields']
                event_code = fields.get('event_code', 'UNKNOWN')
                originator = fields.get('originator', 'UNKNOWN')

                locations = fields.get('locations', [])
                if isinstance(locations, list):
                    for loc in locations:
                        if isinstance(loc, dict):
                            code = loc.get('code', '')
                            if code:
                                alert_fips_codes.append(code)

        # Check for FIPS code match
        matches = set(alert_fips_codes) & set(configured_fips_codes)

        if matches:
            # Alert matches configured FIPS codes - FORWARD IT
            log.warning(
                f"✓ FIPS MATCH - FORWARDING ALERT: "
                f"Event={event_code} | "
                f"Originator={originator} | "
                f"Alert FIPS={','.join(alert_fips_codes)} | "
                f"Configured FIPS={','.join(configured_fips_codes)} | "
                f"Matched={','.join(sorted(matches))}"
            )

            try:
                forward_callback(alert)
                log.info(f"Alert forwarding completed successfully")
            except Exception as e:
                log.error(f"Error forwarding alert: {e}", exc_info=True)

        else:
            # Alert does NOT match configured FIPS codes - IGNORE IT
            log.info(
                f"✗ NO FIPS MATCH - IGNORING ALERT: "
                f"Event={event_code} | "
                f"Originator={originator} | "
                f"Alert FIPS={','.join(alert_fips_codes) if alert_fips_codes else 'NONE'} | "
                f"Configured FIPS={','.join(configured_fips_codes)}"
            )

    return fips_filtering_callback


class ContinuousEASMonitor:
    """
    Continuously monitors audio sources for EAS/SAME alerts.

    Buffers audio from AudioSourceManager and periodically analyzes it
    for SAME headers. When alerts are detected, triggers callbacks and
    stores to database.
    """

    def __init__(
        self,
        audio_manager: AudioSourceManager,
        buffer_duration: float = 120.0,
        scan_interval: float = 2.0,
        sample_rate: int = 22050,
        alert_callback: Optional[Callable[[EASAlert], None]] = None,
        save_audio_files: bool = True,
        audio_archive_dir: str = "/tmp/eas-audio"
    ):
        """
        Initialize continuous EAS monitor.

        Args:
            audio_manager: AudioSourceManager instance providing audio
            buffer_duration: Seconds of audio to buffer for analysis (default: 120s)
            scan_interval: Seconds between decode attempts (default: 2s)
            sample_rate: Audio sample rate in Hz (default: 22050)
            alert_callback: Optional callback function called when alert detected
            save_audio_files: Whether to save audio files of detected alerts
            audio_archive_dir: Directory to save alert audio files
        """
        self.audio_manager = audio_manager
        self.buffer_duration = buffer_duration
        self.scan_interval = scan_interval
        self.sample_rate = sample_rate
        self.alert_callback = alert_callback
        self.save_audio_files = save_audio_files
        self.audio_archive_dir = audio_archive_dir

        # Create audio archive directory
        if save_audio_files:
            os.makedirs(audio_archive_dir, exist_ok=True)

        # Circular buffer for audio (ring buffer for analysis)
        buffer_samples = int(sample_rate * buffer_duration)
        self._audio_buffer = np.zeros(buffer_samples, dtype=np.float32)
        self._buffer_pos = 0
        self._buffer_lock = threading.Lock()

        # Monitoring state
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._alerts_detected = 0
        self._scans_performed = 0
        self._last_alert_time: Optional[float] = None

        logger.info(
            f"Initialized ContinuousEASMonitor: buffer={buffer_duration}s, "
            f"scan_interval={scan_interval}s, sample_rate={sample_rate}Hz"
        )

    def start(self) -> bool:
        """
        Start continuous monitoring.

        Returns:
            True if started successfully
        """
        if not self._stop_event.is_set():
            logger.warning("ContinuousEASMonitor already running")
            return False

        self._stop_event.clear()

        # Start monitoring thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="eas-monitor",
            daemon=True
        )
        self._monitor_thread.start()

        logger.info("Started continuous EAS monitoring")
        return True

    def stop(self) -> None:
        """Stop continuous monitoring."""
        logger.info("Stopping continuous EAS monitoring")
        self._stop_event.set()

        if self._monitor_thread:
            self._monitor_thread.join(timeout=10.0)

        logger.info(
            f"Stopped EAS monitoring. Stats: {self._scans_performed} scans, "
            f"{self._alerts_detected} alerts detected"
        )

    def _monitor_loop(self) -> None:
        """Main monitoring loop - runs continuously."""
        logger.debug("EAS monitor loop started")

        # Buffer for reading audio chunks
        chunk_samples = int(self.sample_rate * 0.1)  # 100ms chunks
        last_scan_time = 0.0

        while not self._stop_event.is_set():
            try:
                # Read audio from manager
                samples = self.audio_manager.read_audio(chunk_samples)

                if samples is not None:
                    # Add to circular buffer
                    self._add_to_buffer(samples)

                # Check if it's time to scan for alerts
                current_time = time.time()
                if current_time - last_scan_time >= self.scan_interval:
                    self._scan_for_alerts()
                    last_scan_time = current_time
                else:
                    # Brief sleep to avoid busy-waiting
                    time.sleep(0.01)

            except Exception as e:
                logger.error(f"Error in EAS monitor loop: {e}", exc_info=True)
                time.sleep(1.0)  # Back off on error

        logger.debug("EAS monitor loop stopped")

    def _add_to_buffer(self, samples: np.ndarray) -> None:
        """Add samples to circular buffer."""
        with self._buffer_lock:
            num_samples = len(samples)
            buffer_len = len(self._audio_buffer)

            # Handle wraparound
            if self._buffer_pos + num_samples <= buffer_len:
                # Fits without wraparound
                self._audio_buffer[self._buffer_pos:self._buffer_pos + num_samples] = samples
                self._buffer_pos = (self._buffer_pos + num_samples) % buffer_len
            else:
                # Needs wraparound
                first_chunk = buffer_len - self._buffer_pos
                self._audio_buffer[self._buffer_pos:] = samples[:first_chunk]
                remaining = num_samples - first_chunk
                self._audio_buffer[:remaining] = samples[first_chunk:]
                self._buffer_pos = remaining

    def _get_buffer_contents(self) -> np.ndarray:
        """Get current buffer contents in correct order."""
        with self._buffer_lock:
            # Return buffer starting from current position (oldest data first)
            return np.concatenate([
                self._audio_buffer[self._buffer_pos:],
                self._audio_buffer[:self._buffer_pos]
            ])

    def _scan_for_alerts(self) -> None:
        """Scan buffered audio for EAS alerts."""
        try:
            self._scans_performed += 1

            # Get audio buffer
            audio_samples = self._get_buffer_contents()

            # Save to temporary WAV file for decoder
            temp_wav = self._save_to_temp_wav(audio_samples)

            try:
                # Run decoder
                result = decode_same_audio(temp_wav, sample_rate=self.sample_rate)

                # Check if we found an alert
                if result.headers and len(result.headers) > 0:
                    # Alert detected!
                    self._handle_alert_detected(result, audio_samples, temp_wav)

            finally:
                # Clean up temp file if we're not saving it
                if not self.save_audio_files and os.path.exists(temp_wav):
                    try:
                        os.unlink(temp_wav)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Error scanning for alerts: {e}", exc_info=True)

    def _save_to_temp_wav(self, samples: np.ndarray) -> str:
        """Save samples to temporary WAV file."""
        # Create temp file
        fd, temp_path = tempfile.mkstemp(suffix=".wav", prefix="eas_scan_")
        os.close(fd)

        # Write WAV file
        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)

            # Convert float32 [-1, 1] to int16 PCM
            pcm_data = (samples * 32767).astype(np.int16)
            wf.writeframes(pcm_data.tobytes())

        return temp_path

    def _handle_alert_detected(
        self,
        result: SAMEAudioDecodeResult,
        audio_samples: np.ndarray,
        temp_wav_path: str
    ) -> None:
        """Handle detected EAS alert."""
        current_time = time.time()

        # Get active source name
        source_name = self.audio_manager.get_active_source() or "unknown"

        # Create alert object for logging
        alert = EASAlert(
            timestamp=utc_now(),
            raw_text=result.raw_text,
            headers=[h.to_dict() for h in result.headers],
            confidence=result.bit_confidence,
            duration_seconds=result.duration_seconds,
            source_name=source_name
        )

        # === COMPREHENSIVE LOGGING FOR ALL ALERTS (BEFORE FILTERING) ===
        # This logs EVERY alert detected, regardless of FIPS codes or forwarding criteria
        # Useful for auditing and troubleshooting
        try:
            # Extract key alert details
            event_code = "UNKNOWN"
            originator = "UNKNOWN"
            location_codes = []

            if alert.headers and len(alert.headers) > 0:
                first_header = alert.headers[0]
                if 'fields' in first_header:
                    fields = first_header['fields']
                    event_code = fields.get('event_code', 'UNKNOWN')
                    originator = fields.get('originator', 'UNKNOWN')

                    # Extract location codes (FIPS codes)
                    locations = fields.get('locations', [])
                    if isinstance(locations, list):
                        for loc in locations:
                            if isinstance(loc, dict):
                                code = loc.get('code', '')
                                if code:
                                    location_codes.append(code)

            # Log comprehensive alert information (always logged for auditing)
            logger.warning(
                f"🔔 AUDIO ALERT RECEIVED: "
                f"Event={event_code} | "
                f"Originator={originator} | "
                f"FIPS Codes={','.join(location_codes) if location_codes else 'NONE'} | "
                f"Source={source_name} | "
                f"Confidence={alert.confidence:.1%} | "
                f"Raw={alert.raw_text}"
            )

            # Also log as structured data for easier parsing
            logger.info(
                f"Audio alert details: event_code={event_code}, "
                f"originator={originator}, "
                f"location_codes={location_codes}, "
                f"source={source_name}, "
                f"confidence={alert.confidence}, "
                f"timestamp={alert.timestamp.isoformat()}"
            )

        except Exception as e:
            logger.error(f"Error logging alert details: {e}", exc_info=True)
        # === END COMPREHENSIVE LOGGING ===

        # === SAVE AUDIO FOR ALL ALERTS (BEFORE COOLDOWN CHECK) ===
        # This ensures complete audit trail - every alert gets audio saved
        if self.save_audio_files:
            alert_filename = self._create_alert_filename(alert)
            alert_file_path = os.path.join(self.audio_archive_dir, alert_filename)

            try:
                # Move temp file to permanent location
                os.rename(temp_wav_path, alert_file_path)
                alert.audio_file_path = alert_file_path
                logger.info(f"Saved alert audio to {alert_file_path}")
            except Exception as e:
                logger.error(f"Failed to save alert audio: {e}")
        # === END AUDIO SAVING ===

        # Check if this is a duplicate (within cooldown period)
        # Note: Duplicates are still LOGGED and AUDIO SAVED above, but not processed further
        if self._last_alert_time:
            time_since_last = current_time - self._last_alert_time
            if time_since_last < 30.0:  # 30 second cooldown
                logger.info(
                    f"Alert within cooldown period ({time_since_last:.1f}s) - "
                    f"logged and audio saved, but not activating"
                )
                return

        self._last_alert_time = current_time
        self._alerts_detected += 1

        # Log alert activation (this means the alert passed cooldown and will be processed/forwarded)
        logger.warning(
            f"🚨 EAS ALERT ACTIVATING: {alert.raw_text} "
            f"(source: {source_name}, confidence: {alert.confidence:.1%})"
        )

        # Trigger callback (this will apply FIPS filtering and forward if matching)
        if self.alert_callback:
            try:
                # Extract location codes for logging
                callback_location_codes = []
                if alert.headers and len(alert.headers) > 0:
                    first_header = alert.headers[0]
                    if 'fields' in first_header:
                        fields = first_header['fields']
                        locations = fields.get('locations', [])
                        if isinstance(locations, list):
                            for loc in locations:
                                if isinstance(loc, dict):
                                    code = loc.get('code', '')
                                    if code:
                                        callback_location_codes.append(code)

                logger.info(
                    f"Invoking alert callback for processing/FIPS filtering: "
                    f"alert_fips_codes={callback_location_codes}"
                )

                self.alert_callback(alert)

                # Log successful callback completion
                logger.info(
                    f"✓ Alert callback completed successfully for {alert.raw_text[:50]}... "
                    f"(Note: Check callback implementation for FIPS filtering results)"
                )

            except Exception as e:
                logger.error(
                    f"✗ Error in alert callback: {e} "
                    f"(Alert may not have been forwarded/broadcast)",
                    exc_info=True
                )

    def _create_alert_filename(self, alert: EASAlert) -> str:
        """Create filename for alert audio file."""
        # Format: YYYYMMDD_HHMMSS_ORIGINATOR-EVENT.wav
        timestamp_str = alert.timestamp.strftime("%Y%m%d_%H%M%S")

        # Extract originator and event code from first header
        originator = "UNK"
        event_code = "UNK"

        if alert.headers and len(alert.headers) > 0:
            first_header = alert.headers[0]
            if 'fields' in first_header:
                fields = first_header['fields']
                originator = fields.get('originator', 'UNK')
                event_code = fields.get('event_code', 'UNK')

        return f"{timestamp_str}_{originator}-{event_code}.wav"

    def get_stats(self) -> dict:
        """Get monitoring statistics."""
        return {
            'running': not self._stop_event.is_set(),
            'scans_performed': self._scans_performed,
            'alerts_detected': self._alerts_detected,
            'buffer_duration_seconds': self.buffer_duration,
            'scan_interval_seconds': self.scan_interval,
            'active_source': self.audio_manager.get_active_source(),
            'last_alert_time': self._last_alert_time
        }


__all__ = ['ContinuousEASMonitor', 'EASAlert', 'create_fips_filtering_callback']
