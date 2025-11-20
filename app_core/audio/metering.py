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
Audio Metering and Silence Detection

Provides real-time audio level monitoring, silence detection,
and alerting for audio pipeline health monitoring.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AudioAlert:
    """Audio pipeline alert."""
    timestamp: float
    level: AlertLevel
    source: str
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None


class AudioMeter:
    """Real-time audio level meter with peak and RMS monitoring."""

    def __init__(self, window_size: int = 1024, peak_hold_time: float = 2.0):
        self.window_size = window_size
        self.peak_hold_time = peak_hold_time
        
        # Audio buffers
        self._buffer = np.zeros(window_size, dtype=np.float32)
        self._buffer_pos = 0
        
        # Peak tracking
        self._current_peak = -np.inf
        self._peak_hold_start = 0.0
        
        # RMS calculation
        self._rms_sum = 0.0
        self._rms_count = 0
        
        self._lock = threading.Lock()

    def process_samples(self, samples: np.ndarray) -> Dict[str, float]:
        """Process new audio samples and return meter readings."""
        with self._lock:
            metrics = {}
            
            # Update buffer and calculate peak
            current_time = time.time()
            peak_updated = False
            
            for sample in samples:
                # Update circular buffer
                self._buffer[self._buffer_pos] = sample
                self._buffer_pos = (self._buffer_pos + 1) % self.window_size
                
                # Track peak
                abs_sample = abs(sample)
                if abs_sample > self._current_peak:
                    self._current_peak = abs_sample
                    self._peak_hold_start = current_time
                    peak_updated = True
            
            # Release peak hold if expired
            if current_time - self._peak_hold_start > self.peak_hold_time:
                # Find new peak from buffer
                self._current_peak = np.max(np.abs(self._buffer))
                self._peak_hold_start = current_time
            
            # Calculate RMS from buffer
            rms = np.sqrt(np.mean(self._buffer ** 2))
            
            # Calculate current peak from latest samples
            instant_peak = np.max(np.abs(samples))
            
            # Convert to dBFS
            metrics['peak_dbfs'] = 20 * np.log10(max(self._current_peak, 1e-10))
            metrics['rms_dbfs'] = 20 * np.log10(max(rms, 1e-10))
            metrics['instant_peak_dbfs'] = 20 * np.log10(max(instant_peak, 1e-10))
            metrics['peak_linear'] = self._current_peak
            metrics['rms_linear'] = rms
            
            return metrics

    def get_levels(self) -> Dict[str, float]:
        """Get current meter levels without processing new samples."""
        with self._lock:
            # Calculate current RMS from buffer
            rms = np.sqrt(np.mean(self._buffer ** 2))
            
            return {
                'peak_dbfs': 20 * np.log10(max(self._current_peak, 1e-10)),
                'rms_dbfs': 20 * np.log10(max(rms, 1e-10)),
                'peak_linear': self._current_peak,
                'rms_linear': rms
            }

    def reset(self) -> None:
        """Reset meter state."""
        with self._lock:
            self._buffer.fill(0)
            self._buffer_pos = 0
            self._current_peak = -np.inf
            self._peak_hold_start = 0.0
            self._rms_sum = 0.0
            self._rms_count = 0


class SilenceDetector:
    """Silence detection with configurable thresholds and timing."""

    def __init__(
        self,
        silence_threshold_db: float = -60.0,
        silence_duration_seconds: float = 5.0,
        check_interval_seconds: float = 0.1
    ):
        self.silence_threshold_db = silence_threshold_db
        self.silence_duration_seconds = silence_duration_seconds
        self.check_interval_seconds = check_interval_seconds
        
        # State tracking
        self._is_silent = False
        self._silence_start_time: Optional[float] = None
        self._last_signal_time = time.time()
        self._ever_had_signal = False
        
        # Alerting
        self._alerts: List[AudioAlert] = []
        self._alert_callbacks: List[Callable[[AudioAlert], None]] = []
        
        self._lock = threading.Lock()

    def add_alert_callback(self, callback: Callable[[AudioAlert], None]) -> None:
        """Add a callback to receive silence alerts."""
        with self._lock:
            self._alert_callbacks.append(callback)

    def remove_alert_callback(self, callback: Callable[[AudioAlert], None]) -> None:
        """Remove an alert callback."""
        with self._lock:
            if callback in self._alert_callbacks:
                self._alert_callbacks.remove(callback)

    def process_audio_level(self, level_db: float, source_name: str = "unknown") -> None:
        """Process audio level and detect silence."""
        with self._lock:
            current_time = time.time()

            # Check if audio is above silence threshold
            if level_db > self.silence_threshold_db:
                # We have signal
                self._last_signal_time = current_time
                self._ever_had_signal = True

                # If we were in silence, alert that signal restored
                if self._is_silent:
                    self._is_silent = False
                    self._create_alert(
                        AlertLevel.INFO,
                        source_name,
                        f"Signal restored ({level_db:.1f} dBFS)",
                        level_db,
                        self.silence_threshold_db
                    )
                    
                # Clear silence start time
                self._silence_start_time = None

            else:
                # Audio is below threshold
                if not self._ever_had_signal and not self._is_silent:
                    self._silence_start_time = self._last_signal_time
                    self._is_silent = True
                    self._create_alert(
                        AlertLevel.WARNING,
                        source_name,
                        f"Silence detected (no prior signal) ({level_db:.1f} dBFS)",
                        level_db,
                        self.silence_threshold_db
                    )
                    return

                if not self._is_silent and self._silence_start_time is None:
                    # Start timing silence from the last time we had a signal
                    self._silence_start_time = self._last_signal_time

                elif self._silence_start_time is not None:
                    # Check if silence duration exceeded
                    silence_start = self._silence_start_time or self._last_signal_time
                    silence_duration = current_time - silence_start

                    if silence_duration >= self.silence_duration_seconds and not self._is_silent:
                        # Silence detected
                        self._is_silent = True
                        self._create_alert(
                            AlertLevel.WARNING,
                            source_name,
                            f"Silence detected for {silence_duration:.1f}s ({level_db:.1f} dBFS)",
                            level_db,
                            self.silence_threshold_db
                        )

    def is_silent(self) -> bool:
        """Check if silence is currently detected."""
        with self._lock:
            return self._is_silent

    def get_silence_duration(self) -> float:
        """Get current silence duration in seconds."""
        with self._lock:
            if self._silence_start_time is None:
                return 0.0
            return time.time() - self._silence_start_time

    def get_time_since_last_signal(self) -> float:
        """Get time since last detected signal."""
        with self._lock:
            return time.time() - self._last_signal_time

    def get_recent_alerts(self, max_count: int = 10) -> List[AudioAlert]:
        """Get recent silence alerts."""
        with self._lock:
            return self._alerts[-max_count:] if self._alerts else []

    def clear_alerts(self) -> None:
        """Clear all stored alerts."""
        with self._lock:
            self._alerts.clear()

    def _create_alert(
        self,
        level: AlertLevel,
        source: str,
        message: str,
        value: Optional[float] = None,
        threshold: Optional[float] = None
    ) -> None:
        """Create and dispatch an alert."""
        alert = AudioAlert(
            timestamp=time.time(),
            level=level,
            source=source,
            message=message,
            value=value,
            threshold=threshold
        )
        
        # Store alert
        self._alerts.append(alert)
        
        # Limit stored alerts
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-50:]  # Keep last 50
        
        # Dispatch to callbacks
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Error in silence alert callback: {e}")

    def reset(self) -> None:
        """Reset silence detector state."""
        with self._lock:
            self._is_silent = False
            self._silence_start_time = None
            self._last_signal_time = time.time()
            self._alerts.clear()


class AudioHealthMonitor:
    """Comprehensive audio health monitoring with multiple detectors."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        
        # Components
        self.meter = AudioMeter()
        self.silence_detector = SilenceDetector()
        
        # Clipping detection
        self._clipping_threshold = 0.95  # 95% of full scale
        self._clipping_count = 0
        self._clipping_window = 100  # samples to check
        self._clipping_alert_threshold = 10  # alerts per window
        
        # Level history for trend analysis
        self._level_history: List[Dict[str, float]] = []
        self._max_history_size = 1000
        
        # Health status
        self._health_score = 100.0
        self._last_update = time.time()
        
        self._lock = threading.Lock()

    def process_samples(self, samples: np.ndarray) -> Dict[str, any]:
        """Process audio samples and return health metrics."""
        with self._lock:
            current_time = time.time()
            
            # Get meter readings
            meter_levels = self.meter.process_samples(samples)
            
            # Detect clipping
            clipping_detected = self._detect_clipping(samples)
            
            # Process silence detection
            self.silence_detector.process_audio_level(
                meter_levels['rms_dbfs'],
                self.source_name
            )
            
            # Store level history
            history_entry = {
                'timestamp': current_time,
                **meter_levels,
                'clipping': clipping_detected
            }
            self._level_history.append(history_entry)
            
            # Limit history size
            if len(self._level_history) > self._max_history_size:
                self._level_history = self._level_history[-self._max_history_size // 2:]
            
            # Calculate health score
            self._calculate_health_score(meter_levels, clipping_detected)
            
            return {
                'meter_levels': meter_levels,
                'clipping_detected': clipping_detected,
                'health_score': self._health_score,
                'silence_detected': self.silence_detector.is_silent(),
                'silence_duration': self.silence_detector.get_silence_duration()
            }

    def get_health_status(self) -> Dict[str, any]:
        """Get current health status."""
        with self._lock:
            return {
                'source_name': self.source_name,
                'health_score': self._health_score,
                'last_update': self._last_update,
                'meter_levels': self.meter.get_levels(),
                'silence_detected': self.silence_detector.is_silent(),
                'silence_duration': self.silence_detector.get_silence_duration(),
                'time_since_signal': self.silence_detector.get_time_since_last_signal(),
                'recent_alerts': self.silence_detector.get_recent_alerts(5),
                'level_trend': self._get_level_trend()
            }

    def add_alert_callback(self, callback: Callable[[AudioAlert], None]) -> None:
        """Add alert callback to silence detector."""
        self.silence_detector.add_alert_callback(callback)

    def _detect_clipping(self, samples: np.ndarray) -> bool:
        """Detect if samples are clipping."""
        # Count samples above clipping threshold
        clipping_samples = np.sum(np.abs(samples) > self._clipping_threshold)
        
        # Update clipping counter
        self._clipping_count += clipping_samples
        
        # Check if we should alert
        if self._clipping_count >= self._clipping_alert_threshold:
            self._clipping_count = 0  # Reset counter
            return True
        
        return False

    def _calculate_health_score(self, meter_levels: Dict[str, float], clipping: bool) -> None:
        """Calculate overall health score (0-100)."""
        score = 100.0
        
        # Penalize clipping
        if clipping:
            score -= 20.0
        
        # Penalize very low levels (potential dead air)
        if meter_levels['rms_dbfs'] < -50:
            score -= 10.0
        
        # Penalize very high levels (potential distortion)
        if meter_levels['rms_dbfs'] > -3:
            score -= 10.0
        
        # Penalize silence
        if self.silence_detector.is_silent():
            silence_duration = self.silence_detector.get_silence_duration()
            score -= min(30.0, silence_duration * 2.0)  # Lose 2 points per second of silence
        
        # Ensure score is within bounds
        self._health_score = max(0.0, min(100.0, score))
        self._last_update = time.time()

    def _get_level_trend(self) -> Dict[str, float]:
        """Calculate level trend over recent history."""
        if len(self._level_history) < 10:
            return {'trend': 0.0, 'direction': 'stable'}
        
        # Get last 10 entries
        recent = self._level_history[-10:]
        
        # Calculate RMS trend
        rms_values = [entry['rms_dbfs'] for entry in recent]
        if len(rms_values) >= 2:
            trend = rms_values[-1] - rms_values[0]
            
            if trend > 3.0:
                direction = 'rising'
            elif trend < -3.0:
                direction = 'falling'
            else:
                direction = 'stable'
                
            return {'trend': trend, 'direction': direction}
        
        return {'trend': 0.0, 'direction': 'stable'}

    def reset(self) -> None:
        """Reset all monitoring state."""
        with self._lock:
            self.meter.reset()
            self.silence_detector.reset()
            self._clipping_count = 0
            self._level_history.clear()
            self._health_score = 100.0
            self._last_update = time.time()