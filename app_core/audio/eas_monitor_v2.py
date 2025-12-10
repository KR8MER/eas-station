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
EAS Continuous Monitor V2 - Complete Rewrite

This is a complete rewrite that fixes fundamental architecture issues:
- Robust audio reading with timeout detection
- Consistent status reporting
- Clear health metrics
- Proper error recovery
- No silent failures
"""

import logging
import threading
import time
import queue
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass, field
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MonitorHealth:
    """Health tracking for EAS monitor."""
    last_audio_time: float = 0.0
    consecutive_empty_reads: int = 0
    consecutive_errors: int = 0
    total_errors: int = 0
    audio_flowing: bool = False
    health_score: float = 1.0  # 0.0 to 1.0


class EASMonitorV2:
    """
    Completely rewritten EAS continuous monitor.
    
    Key improvements:
    - Robust audio pipeline with health tracking
    - Clear, consistent status reporting
    - Proper timeout detection
    - Graceful error recovery
    - Real-time health metrics
    """

    def __init__(
        self,
        audio_source,
        sample_rate: int = 16000,
        alert_callback: Optional[Callable] = None,
        source_name: str = "unknown"
    ):
        """
        Initialize monitor.

        Args:
            audio_source: Object with read_audio(num_samples) method
            sample_rate: Target sample rate for decoder (16kHz for SAME)
            alert_callback: Function to call when alert detected
            source_name: Human-readable name for this source
        """
        self.audio_source = audio_source
        self.sample_rate = sample_rate
        self.alert_callback = alert_callback
        self.source_name = source_name

        # Get source sample rate if available
        self.source_sample_rate = getattr(audio_source, 'sample_rate', sample_rate)

        # Initialize streaming decoder
        from .streaming_same_decoder import StreamingSAMEDecoder
        self._decoder = StreamingSAMEDecoder(
            sample_rate=sample_rate,
            alert_callback=self._handle_alert
        )

        # State management
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: Optional[float] = None
        self._alerts_detected = 0
        self._samples_processed = 0

        # Health tracking
        self._health = MonitorHealth()
        self._health_lock = threading.Lock()

        # Configuration
        self._chunk_duration_ms = 100  # 100ms chunks
        self._chunk_size = int(self.sample_rate * self._chunk_duration_ms / 1000)
        self._audio_timeout_seconds = 10.0  # Declare audio dead after 10s no data (increased from 5s)
        self._max_empty_reads = 50  # Max consecutive empty reads before warning
        self._max_errors = 100  # Max consecutive errors before stopping
        self._min_samples_for_flow = self.sample_rate * 2  # Require 2s of audio before declaring "flowing"

        logger.info(
            f"EASMonitorV2 initialized for '{source_name}': "
            f"{self.source_sample_rate}Hz -> {sample_rate}Hz, "
            f"chunk={self._chunk_duration_ms}ms ({self._chunk_size} samples)"
        )

    def start(self) -> bool:
        """Start monitoring."""
        if self._running:
            logger.warning(f"Monitor '{self.source_name}' already running")
            return False

        self._running = True
        self._start_time = time.time()
        self._samples_processed = 0
        self._alerts_detected = 0

        # Reset health
        with self._health_lock:
            self._health = MonitorHealth()

        self._thread = threading.Thread(
            target=self._monitor_loop,
            name=f"eas-monitor-{self.source_name}",
            daemon=True
        )
        self._thread.start()

        logger.info(f"✅ EAS monitor '{self.source_name}' started")
        return True

    def stop(self) -> None:
        """Stop monitoring."""
        if not self._running:
            return

        logger.info(f"Stopping EAS monitor '{self.source_name}'...")
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning(f"Monitor thread '{self.source_name}' did not stop cleanly")

        logger.info(
            f"EAS monitor '{self.source_name}' stopped. "
            f"Processed {self._samples_processed:,} samples, "
            f"detected {self._alerts_detected} alerts, "
            f"{self._health.total_errors} errors"
        )

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive, consistent status."""
        decoder_stats = self._decoder.get_stats()
        
        with self._health_lock:
            health = self._health

        # Calculate runtime metrics
        if self._running and self._start_time:
            wall_clock_runtime = time.time() - self._start_time
            
            if self._samples_processed > 0:
                audio_runtime = self._samples_processed / self.sample_rate
                samples_per_second = self._samples_processed / max(wall_clock_runtime, 0.1)
                
                # Calculate health percentage based on processing rate
                expected_rate = self.sample_rate
                health_percentage = min(1.0, samples_per_second / expected_rate)
            else:
                audio_runtime = 0
                samples_per_second = 0
                health_percentage = 0.0
        else:
            wall_clock_runtime = 0
            audio_runtime = 0
            samples_per_second = 0
            health_percentage = 0.0

        # Determine if audio is actually flowing with improved logic
        # Require minimum samples before declaring "flowing" to prevent false positives during startup
        # Also check if we've received data recently (within timeout window)
        time_since_audio = time.time() - health.last_audio_time if health.last_audio_time > 0 else 999999
        audio_flowing = (
            self._running and
            self._samples_processed >= self._min_samples_for_flow and  # Require minimum samples (2s)
            time_since_audio < self._audio_timeout_seconds  # Recent data (within 10s)
        )

        # Get audio adapter stats if available
        adapter_stats = {}
        if hasattr(self.audio_source, 'get_stats'):
            try:
                adapter_stats = self.audio_source.get_stats()
            except Exception:
                pass

        return {
            # Core status
            "running": self._running,
            "mode": "streaming",
            "source_name": self.source_name,
            "audio_flowing": audio_flowing,

            # Decoder metrics
            "samples_processed": self._samples_processed,
            "samples_per_second": int(samples_per_second),
            "wall_clock_runtime_seconds": wall_clock_runtime,
            "runtime_seconds": audio_runtime,

            # Health metrics
            "health_percentage": health_percentage,
            "time_since_last_audio": time_since_audio,
            "consecutive_empty_reads": health.consecutive_empty_reads,
            "consecutive_errors": health.consecutive_errors,
            "total_errors": health.total_errors,

            # Decoder state
            "decoder_synced": decoder_stats.get('synced', False),
            "decoder_in_message": decoder_stats.get('in_message', False),
            "decoder_bytes_decoded": decoder_stats.get('bytes_decoded', 0),

            # Alert tracking
            "alerts_detected": self._alerts_detected,

            # Sample rate info
            "sample_rate": self.sample_rate,
            "source_sample_rate": self.source_sample_rate,

            # Audio adapter health
            "audio_buffer_samples": adapter_stats.get("buffer_samples", 0),
            "audio_queue_depth": adapter_stats.get("queue_size", 0),
            "audio_underruns": adapter_stats.get("underrun_count", 0),
            "audio_subscriber_id": adapter_stats.get("subscriber_id", ""),
        }

    def _handle_alert(self, alert_data: dict) -> None:
        """Handle detected alert."""
        self._alerts_detected += 1
        alert_data['source_name'] = self.source_name
        
        logger.info(
            f"🚨 EAS Alert detected on '{self.source_name}': "
            f"{alert_data.get('event_code', 'UNKNOWN')}"
        )

        if self.alert_callback:
            try:
                self.alert_callback(alert_data)
            except Exception as e:
                logger.error(f"Error in alert callback: {e}", exc_info=True)

    def _resample_linear(self, samples: np.ndarray) -> np.ndarray:
        """Fast linear resampling with robust error handling."""
        if self.source_sample_rate == self.sample_rate:
            return samples

        try:
            # Handle multi-dimensional arrays
            if samples.ndim == 2:
                # Stereo to mono
                samples = samples.mean(axis=1)
            elif samples.ndim > 2:
                # Flatten any higher dimensions
                samples = samples.flatten()

            # Ensure float32
            if samples.dtype != np.float32:
                samples = samples.astype(np.float32)

            # Calculate resampling ratio
            ratio = self.sample_rate / float(self.source_sample_rate)
            new_length = max(1, int(len(samples) * ratio))

            # Perform linear interpolation
            old_indices = np.arange(len(samples))
            new_indices = np.linspace(0, len(samples) - 1, new_length)
            resampled = np.interp(new_indices, old_indices, samples)

            return resampled.astype(np.float32)

        except Exception as e:
            logger.error(f"Resampling error on '{self.source_name}': {e}")
            with self._health_lock:
                self._health.total_errors += 1
            return samples

    def _update_health(self, got_audio: bool, error: bool = False) -> None:
        """Update health tracking."""
        with self._health_lock:
            prev_flowing = self._health.audio_flowing
            
            if error:
                self._health.consecutive_errors += 1
                self._health.total_errors += 1
                self._health.consecutive_empty_reads = 0
            elif got_audio:
                # Got audio successfully
                self._health.last_audio_time = time.time()
                self._health.consecutive_empty_reads = 0
                self._health.consecutive_errors = 0
                self._health.audio_flowing = True
            else:
                # Empty read (no audio available)
                self._health.consecutive_empty_reads += 1
                self._health.consecutive_errors = 0
                
                # If no audio for too long, mark as not flowing
                time_since_audio = time.time() - self._health.last_audio_time if self._health.last_audio_time > 0 else 999999
                if time_since_audio > self._audio_timeout_seconds:
                    if self._health.audio_flowing:
                        # State transition: flowing -> not flowing
                        logger.warning(
                            f"'{self.source_name}': Audio flow stopped - "
                            f"no data for {time_since_audio:.1f}s (timeout: {self._audio_timeout_seconds}s)"
                        )
                    self._health.audio_flowing = False
            
            # Log state transitions for debugging
            if prev_flowing != self._health.audio_flowing:
                if self._health.audio_flowing:
                    logger.info(
                        f"'{self.source_name}': Audio flow started - "
                        f"processed {self._samples_processed:,} samples so far"
                    )

            # Calculate health score
            health_factors = [
                1.0 - min(1.0, self._health.consecutive_errors / 100),
                1.0 - min(1.0, self._health.consecutive_empty_reads / 100),
                1.0 if self._health.audio_flowing else 0.5,
            ]
            self._health.health_score = sum(health_factors) / len(health_factors)

    def _monitor_loop(self) -> None:
        """Main monitoring loop - completely rewritten for robustness."""
        logger.info(f"Monitor loop starting for '{self.source_name}'...")

        while self._running:
            try:
                # Read audio from source
                samples = self.audio_source.read_audio(self._chunk_size)

                if samples is None or len(samples) == 0:
                    # No audio available
                    self._update_health(got_audio=False)
                    
                    # Log warnings at intervals
                    with self._health_lock:
                        empty_reads = self._health.consecutive_empty_reads
                    
                    if empty_reads == self._max_empty_reads:
                        logger.warning(
                            f"'{self.source_name}': No audio for {empty_reads} reads "
                            f"({empty_reads * self._chunk_duration_ms}ms)"
                        )
                    elif empty_reads > self._max_empty_reads and empty_reads % 100 == 0:
                        logger.warning(
                            f"'{self.source_name}': Still no audio after {empty_reads} reads "
                            f"({empty_reads * self._chunk_duration_ms / 1000:.1f}s)"
                        )
                    
                    # Adaptive backoff to avoid busy-waiting and reduce CPU load
                    # First 10 empty reads: 50ms (fast recovery)
                    # 11-50 empty reads: 100ms (moderate backoff)
                    # 51+ empty reads: 200ms (aggressive backoff for sustained gaps)
                    if empty_reads <= 10:
                        time.sleep(0.05)
                    elif empty_reads <= 50:
                        time.sleep(0.1)
                    else:
                        time.sleep(0.2)
                    continue

                # Got audio!
                self._update_health(got_audio=True)

                # Resample if needed
                if self.source_sample_rate != self.sample_rate:
                    samples = self._resample_linear(samples)

                # Feed to decoder
                self._decoder.process_samples(samples)
                self._samples_processed += len(samples)

            except Exception as e:
                logger.error(f"Error in monitor loop for '{self.source_name}': {e}", exc_info=True)
                self._update_health(got_audio=False, error=True)
                
                # Check if we've hit error limit
                with self._health_lock:
                    if self._health.consecutive_errors >= self._max_errors:
                        logger.error(
                            f"'{self.source_name}': Too many consecutive errors "
                            f"({self._health.consecutive_errors}), stopping monitor"
                        )
                        self._running = False
                        break
                
                # Back off on errors
                time.sleep(0.1)

        logger.info(f"Monitor loop exited for '{self.source_name}'")
