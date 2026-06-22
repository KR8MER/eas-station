"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

Streaming SAME/EAS Decoder

This module implements a real-time streaming decoder for SAME (Specific Area Message Encoding)
headers, processing audio samples continuously as they arrive - similar to how commercial
EAS decoders like DASDEC and multimon-ng operate.

CRITICAL: This is a life-safety system. The decoder MUST process every audio sample
with zero dropouts or gaps. Commercial EAS decoders operate this way.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Callable, Tuple

import numpy as np

from app_utils import utc_now
from app_utils.eas_demod import (
    SAMEDemodulatorCore,
    ENDEC_MODE_UNKNOWN,
)

logger = logging.getLogger(__name__)


@dataclass
class StreamingSAMEAlert:
    """Detected SAME alert from streaming decoder."""
    message: str
    confidence: float
    timestamp: datetime
    raw_bits: List[int]
    endec_mode: str = ENDEC_MODE_UNKNOWN
    burst_timing_gaps_ms: List[float] = field(default_factory=list)


class StreamingSAMEDecoder:
    """
    Real-time streaming SAME decoder.

    Processes audio samples continuously as they arrive, maintaining decoder state
    across calls. This mimics commercial EAS decoder behavior (DASDEC, multimon-ng).

    Delegates all DSP (bandpass filter, BLAS correlation, DLL state machine, ENDEC
    fingerprinting) to SAMEDemodulatorCore — the single shared FSK/DLL engine.

    Usage:
        decoder = StreamingSAMEDecoder(sample_rate=16000, callback=handle_alert)

        # In audio loop:
        while audio_streaming:
            samples = get_audio_chunk()  # Get new samples
            decoder.process_samples(samples)  # Process immediately

        # Callback is invoked when alert is detected
    """

    # Minimum average bit confidence to accept a decoded message.
    # Confidence = |mark_power - space_power| / total_power per bit, averaged
    # over the whole burst.  Real EAS transmitters produce clean FSK (> 0.5).
    # Music or noise that accidentally triggers the DLL produces mixed tone
    # energy and scores much lower.  0.25 rejects the worst false positives
    # while still passing weak or marginal real alerts.
    MIN_CONFIDENCE = 0.25

    def __init__(
        self,
        sample_rate: int = 16000,
        alert_callback: Optional[Callable[['StreamingSAMEAlert'], None]] = None
    ):
        """
        Initialize streaming SAME decoder.

        Args:
            sample_rate: Audio sample rate in Hz
            alert_callback: Function called when alert detected
        """
        self.sample_rate = sample_rate
        self.alert_callback = alert_callback
        self.alerts_detected = 0

        # Create the shared demodulation core
        self._core = SAMEDemodulatorCore(
            sample_rate=sample_rate,
            message_callback=self._on_message_decoded,
            apply_bandpass=True,
        )

        logger.info(
            "Initialized StreamingSAMEDecoder: sample_rate=%dHz, "
            "baud_rate=%.2f, corr_len=%d samples/bit",
            sample_rate, self._core.baud_rate, self._core.corr_len,
        )

    # ------------------------------------------------------------------
    # Core bridge: receives decoded messages from SAMEDemodulatorCore
    # ------------------------------------------------------------------

    def _on_message_decoded(
        self,
        msg_text: str,
        confidence: float,
        burst_sample_ranges: List[Tuple[int, int]],
    ) -> None:
        """Bridge from SAMEDemodulatorCore callback to StreamingSAMEAlert."""
        if confidence < self.MIN_CONFIDENCE:
            logger.warning(
                "Low-confidence SAME decode (%.1f%% < %.0f%% threshold) — logging but not forwarding to air: %s",
                confidence * 100, self.MIN_CONFIDENCE * 100, msg_text[:60],
            )
            # Do NOT return — still fire the callback so the alert is logged to the
            # received-alerts table.  The forwarding decision is made downstream in
            # create_fips_filtering_callback, which will mark these as
            # 'ignored / low_confidence' without passing them to the air chain.

        self.alerts_detected += 1

        alert = StreamingSAMEAlert(
            message=msg_text,
            confidence=confidence,
            timestamp=utc_now(),
            raw_bits=list(self._core.bit_confidences),
            endec_mode=self._core.endec_mode,
            burst_timing_gaps_ms=list(self._core.burst_timing_gaps_ms),
        )

        logger.info(
            "SAME Alert Detected: %s... (confidence: %.1f%%, endec=%s, alert #%d)",
            msg_text[:50], confidence * 100, self._core.endec_mode, self.alerts_detected,
        )

        if self.alert_callback:
            try:
                self.alert_callback(alert)
            except Exception as e:
                logger.error("Error in alert callback: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Public API — forwarded to core
    # ------------------------------------------------------------------

    def process_samples(self, samples: np.ndarray) -> None:
        """Process audio samples in real-time.

        Args:
            samples: Audio samples as numpy array (float32, normalized to [-1.0, 1.0])
        """
        self._core.process_samples(samples)

    def reset(self) -> None:
        """Reset decoder to initial state, including all counters."""
        self._core.reset()
        self.alerts_detected = 0
        logger.debug("StreamingSAMEDecoder reset to initial state")

    def get_stats(self) -> dict:
        """Get decoder statistics."""
        return {
            'samples_processed': self._core.samples_processed,
            'alerts_detected': self.alerts_detected,
            'bytes_decoded': self._core.bytes_decoded,
            'synced': self._core.synced,
            'in_message': self._core.in_message,
            'current_message_length': len(self._core.current_msg),
            'endec_mode': self._core.endec_mode,
            'burst_timing_gaps_ms': list(self._core.burst_timing_gaps_ms),
            'bandpass_filter_active': self._core._bandpass_available,
        }

    # ------------------------------------------------------------------
    # Attribute forwarding — keeps all existing test assertions passing
    # ------------------------------------------------------------------

    @property
    def samples_processed(self) -> int:
        return self._core.samples_processed

    @samples_processed.setter
    def samples_processed(self, value: int) -> None:
        self._core.samples_processed = value

    @property
    def bytes_decoded(self) -> int:
        return self._core.bytes_decoded

    @property
    def synced(self) -> bool:
        return self._core.synced

    @property
    def in_message(self) -> bool:
        return self._core.in_message

    @in_message.setter
    def in_message(self, value: bool) -> None:
        self._core.in_message = value

    @property
    def current_msg(self) -> List[str]:
        return self._core.current_msg

    @current_msg.setter
    def current_msg(self, value: List[str]) -> None:
        self._core.current_msg = value

    @property
    def bit_confidences(self) -> List[float]:
        return self._core.bit_confidences

    @property
    def corr_len(self) -> int:
        return self._core.corr_len

    @property
    def _correlation_window(self) -> np.ndarray:
        """Legacy compatibility attribute — returns a zero array of corr_len."""
        return np.zeros(self._core.corr_len, dtype=np.float32)

    @property
    def endec_mode(self) -> str:
        return self._core.endec_mode

    @property
    def burst_timing_gaps_ms(self) -> List[float]:
        return self._core.burst_timing_gaps_ms

    @property
    def _bandpass_available(self) -> bool:
        return self._core._bandpass_available


__all__ = ['StreamingSAMEDecoder', 'StreamingSAMEAlert', 'ENDEC_MODE_UNKNOWN']
