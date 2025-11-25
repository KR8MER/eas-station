"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

Streaming SAME/EAS Decoder

This module implements a real-time streaming decoder for SAME (Specific Area Message Encoding)
headers, processing audio samples continuously as they arrive - similar to how commercial
EAS decoders like DASDEC and multimon-ng operate.

CRITICAL: This is a life-safety system. The decoder MUST process every audio sample
with zero dropouts or gaps. Commercial EAS decoders operate this way.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Callable, Tuple

import numpy as np

from app_utils.eas_fsk import SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ
from app_utils import utc_now

logger = logging.getLogger(__name__)


@dataclass
class StreamingSAMEAlert:
    """Detected SAME alert from streaming decoder."""
    message: str
    confidence: float
    timestamp: datetime
    raw_bits: List[int]


class StreamingSAMEDecoder:
    """
    Real-time streaming SAME decoder.
    
    Processes audio samples continuously as they arrive, maintaining decoder state
    across calls. This mimics commercial EAS decoder behavior (DASDEC, multimon-ng).
    
    Based on multimon-ng correlation+DLL algorithm but refactored for streaming operation.
    
    Usage:
        decoder = StreamingSAMEDecoder(sample_rate=16000, callback=handle_alert)
        
        # In audio loop:
        while audio_streaming:
            samples = get_audio_chunk()  # Get new samples
            decoder.process_samples(samples)  # Process immediately
            
        # Callback is invoked when alert is detected
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        alert_callback: Optional[Callable[[StreamingSAMEAlert], None]] = None
    ):
        """
        Initialize streaming SAME decoder.
        
        Args:
            sample_rate: Audio sample rate in Hz
            alert_callback: Function called when alert detected
        """
        self.sample_rate = sample_rate
        self.alert_callback = alert_callback
        
        # SAME FSK parameters
        self.baud_rate = float(SAME_BAUD)  # 520.83 baud
        self.mark_freq = SAME_MARK_FREQ     # 2083.3 Hz (logic 1)
        self.space_freq = SAME_SPACE_FREQ   # 1562.5 Hz (logic 0)
        
        # Correlation parameters
        self.SUBSAMP = 2  # Downsampling factor
        self.corr_len = int(sample_rate / self.baud_rate)  # Samples per bit
        
        # Generate correlation tables (precomputed for efficiency)
        self.mark_i, self.mark_q, self.space_i, self.space_q = self._generate_correlation_tables()
        
        # Decoder state variables (persistent across process_samples calls)
        self._reset_decoder_state()
        
        # Statistics
        self.samples_processed = 0
        self.alerts_detected = 0
        self.bytes_decoded = 0
        
        logger.info(
            f"Initialized StreamingSAMEDecoder: sample_rate={sample_rate}Hz, "
            f"baud_rate={self.baud_rate:.2f}, corr_len={self.corr_len} samples/bit"
        )
    
    def _reset_decoder_state(self) -> None:
        """Reset decoder state variables."""
        # DLL (Delay-Locked Loop) state
        self.dcd_shreg = 0  # Shift register for bit history
        self.dcd_integrator = 0  # Integrator for noise immunity
        self.sphase = 1  # Sampling phase (16-bit fixed point)
        self.lasts = 0  # Last 8 bits received
        self.byte_counter = 0  # Bits received in current byte
        self.synced = False  # Whether we've found preamble
        
        # Message assembly state
        self.current_msg = []
        self.in_message = False
        
        # Confidence tracking
        self.bit_confidences = []
        
        # Sample buffer (holds corr_len samples for correlation)
        self.sample_buffer = np.zeros(self.corr_len, dtype=np.float32)
        self.buffer_pos = 0
        
        # Pre-allocated correlation window to avoid repeated allocation
        self._correlation_window = np.zeros(self.corr_len, dtype=np.float32)
        
        # Constants
        self.PREAMBLE_BYTE = 0xAB
        self.DLL_GAIN = 0.4
        self.INTEGRATOR_MAX = 12
        self.MAX_MSG_LEN = 268
        self.sphaseinc = int(0x10000 * self.baud_rate * self.SUBSAMP / self.sample_rate)
    
    def reset(self) -> None:
        """
        Reset decoder to initial state.
        
        Call this when the monitor thread restarts to ensure consistent
        statistics and state. This resets all counters including samples_processed.
        """
        self._reset_decoder_state()
        self.samples_processed = 0
        self.alerts_detected = 0
        self.bytes_decoded = 0
        logger.debug("StreamingSAMEDecoder reset to initial state")
    
    def _generate_correlation_tables(self) -> Tuple[List[float], List[float], List[float], List[float]]:
        """Generate correlation tables for mark and space frequencies (multimon-ng style)."""
        mark_i = []
        mark_q = []
        space_i = []
        space_q = []
        
        for i in range(self.corr_len):
            t = 2.0 * math.pi * i / self.sample_rate
            mark_i.append(math.cos(self.mark_freq * t))
            mark_q.append(math.sin(self.mark_freq * t))
            space_i.append(math.cos(self.space_freq * t))
            space_q.append(math.sin(self.space_freq * t))
        
        return mark_i, mark_q, space_i, space_q
    
    def process_samples(self, samples: np.ndarray) -> None:
        """
        Process audio samples in real-time.
        
        This is the main entry point for streaming operation. Feed audio samples
        as they arrive and the decoder will maintain state and emit alerts via callback.
        
        Args:
            samples: Audio samples as numpy array (float32, normalized to [-1.0, 1.0])
        """
        if len(samples) == 0:
            return
        
        self.samples_processed += len(samples)
        
        # OPTIMIZATION: Process samples in batches using vectorized operations
        # instead of iterating one sample at a time in Python.
        # This significantly reduces CPU overhead on Raspberry Pi.
        
        num_samples = len(samples)
        sample_idx = 0
        
        while sample_idx < num_samples:
            # Calculate how many samples we can add to the buffer in one go.
            # This handles the circular buffer by only copying up to the end,
            # then wrapping on the next iteration if needed.
            space_in_buffer = self.corr_len - self.buffer_pos
            samples_to_add = min(space_in_buffer, num_samples - sample_idx)
            
            # Batch copy samples into the circular buffer.
            # Since we limited samples_to_add to space_in_buffer, this slice
            # is guaranteed to fit within bounds [buffer_pos, corr_len).
            self.sample_buffer[self.buffer_pos:self.buffer_pos + samples_to_add] = \
                samples[sample_idx:sample_idx + samples_to_add]
            
            # Process each sample position (still need to track state per sample)
            old_buffer_pos = self.buffer_pos
            self.buffer_pos = (self.buffer_pos + samples_to_add) % self.corr_len
            
            # Only start processing once buffer is initially filled
            if self.samples_processed >= self.corr_len:
                # Process each sample in this batch
                for i in range(samples_to_add):
                    # logical_pos represents where the correlation window ENDS in the buffer.
                    # We add +1 because after writing sample i, the next valid window ends
                    # at position (old_buffer_pos + i + 1). The correlation window spans
                    # [logical_pos - corr_len + 1, logical_pos] in the circular buffer.
                    logical_pos = (old_buffer_pos + i + 1) % self.corr_len
                    self._process_one_sample_at(logical_pos)
            
            sample_idx += samples_to_add
    
    def _process_one_sample_at(self, logical_buffer_pos: int) -> None:
        """
        Process one correlation window ending at the specified buffer position.
        
        Args:
            logical_buffer_pos: The position in the circular buffer where the
                              correlation window ends (0 to corr_len-1).
        
        The correlation window contains the most recent corr_len samples,
        starting from logical_buffer_pos and wrapping around if needed.
        """
        # Get samples in correct order (accounting for circular buffer)
        # OPTIMIZATION: Use pre-allocated array and np.roll-style indexing
        if logical_buffer_pos == 0:
            # Special case: window aligns with buffer start, no reordering needed
            correlation_window = self.sample_buffer
        else:
            # Reorder samples to get contiguous window:
            # [logical_buffer_pos:] contains older samples (start of window)
            # [:logical_buffer_pos] contains newer samples (end of window)
            tail_len = self.corr_len - logical_buffer_pos
            self._correlation_window[:tail_len] = self.sample_buffer[logical_buffer_pos:]
            self._correlation_window[tail_len:] = self.sample_buffer[:logical_buffer_pos]
            correlation_window = self._correlation_window
        
        # Compute correlation (mark - space)
        mark_i_corr = np.dot(correlation_window, self.mark_i)
        mark_q_corr = np.dot(correlation_window, self.mark_q)
        space_i_corr = np.dot(correlation_window, self.space_i)
        space_q_corr = np.dot(correlation_window, self.space_q)
        
        mark_power = mark_i_corr**2 + mark_q_corr**2
        space_power = space_i_corr**2 + space_q_corr**2
        correlation = mark_power - space_power
        total_power = mark_power + space_power
        
        # Update DCD shift register
        self.dcd_shreg = (self.dcd_shreg << 1) & 0xFFFFFFFF
        if correlation > 0:
            self.dcd_shreg |= 1
        
        # Update integrator
        if correlation > 0 and self.dcd_integrator < self.INTEGRATOR_MAX:
            self.dcd_integrator += 1
        elif correlation < 0 and self.dcd_integrator > -self.INTEGRATOR_MAX:
            self.dcd_integrator -= 1
        
        # DLL: Check for bit transitions and adjust timing
        if (self.dcd_shreg ^ (self.dcd_shreg >> 1)) & 1:
            if self.sphase < 0x8000:
                if self.sphase > self.sphaseinc // 2:
                    adjustment = min(int(self.sphase * self.DLL_GAIN), 8192)
                    self.sphase -= adjustment
            else:
                if self.sphase < 0x10000 - self.sphaseinc // 2:
                    adjustment = min(int((0x10000 - self.sphase) * self.DLL_GAIN), 8192)
                    self.sphase += adjustment
        
        # Advance sampling phase
        self.sphase += self.sphaseinc
        
        # End of bit period?
        if self.sphase >= 0x10000:
            self.sphase = 1
            self.lasts = (self.lasts >> 1) & 0x7F
            
            # Make bit decision based on integrator
            if self.dcd_integrator >= 0:
                self.lasts |= 0x80
            
            curbit = (self.lasts >> 7) & 1
            
            # Estimate confidence for this bit
            if self.synced or self.in_message:
                if total_power > 0:
                    bit_confidence = min(abs(correlation) / total_power, 1.0)
                else:
                    bit_confidence = 0.0
                self.bit_confidences.append(bit_confidence)
            
            # Check for preamble sync
            if (self.lasts & 0xFF) == self.PREAMBLE_BYTE and not self.in_message:
                self.synced = True
                self.byte_counter = 0
            elif self.synced:
                self.byte_counter += 1
                if self.byte_counter == 8:
                    # Got a complete byte
                    byte_val = self.lasts & 0xFF
                    self.bytes_decoded += 1
                    
                    # Check if it's a valid ASCII character
                    if 32 <= byte_val <= 126 or byte_val in (10, 13):
                        char = chr(byte_val)
                        
                        if not self.in_message and char == 'Z':
                            # Possible start of ZCZC
                            self.in_message = True
                            self.current_msg = [char]
                        elif self.in_message:
                            self.current_msg.append(char)
                            
                            # Check for end of message
                            msg_text = ''.join(self.current_msg)
                            
                            # Check if message is complete
                            if self._is_message_complete(msg_text, char):
                                self._emit_alert(msg_text)
                                self._reset_message_state()
                    else:
                        # Invalid character, lost sync
                        self.synced = False
                        if self.in_message:
                            self._reset_message_state()
                    
                    self.byte_counter = 0
    
    def _is_message_complete(self, msg_text: str, last_char: str) -> bool:
        """Check if SAME message is complete."""
        # Carriage return or line feed terminates message
        if last_char in ('\r', '\n'):
            return 'ZCZC' in msg_text or 'NNNN' in msg_text
        
        # Check for proper SAME format completion
        if last_char == '-' and len(self.current_msg) > 40:
            dash_count = msg_text.count('-')
            location_count = 0
            has_time_section = '+' in msg_text
            
            if has_time_section:
                try:
                    pre_expiration, _ = msg_text.split('+', 1)
                    location_segments = pre_expiration.split('-')[3:]
                    for segment in location_segments:
                        cleaned = segment.strip()
                        if len(cleaned) == 6 and cleaned.isdigit():
                            location_count += 1
                    
                    if location_count <= 0:
                        min_dashes = 6
                    else:
                        min_dashes = 6 + max(location_count - 1, 0)
                    
                    if dash_count >= min_dashes:
                        return 'ZCZC' in msg_text or 'NNNN' in msg_text
                except:
                    pass
        
        # Safety: prevent runaway messages
        if len(self.current_msg) > self.MAX_MSG_LEN:
            return 'ZCZC' in msg_text or 'NNNN' in msg_text
        
        return False
    
    def _reset_message_state(self) -> None:
        """Reset message assembly state."""
        self.current_msg = []
        self.in_message = False
        self.synced = False
        self.bit_confidences = []
    
    def _emit_alert(self, msg_text: str) -> None:
        """Emit decoded alert via callback."""
        msg_text = msg_text.strip()
        
        # Calculate average confidence
        if self.bit_confidences:
            confidence = sum(self.bit_confidences) / len(self.bit_confidences)
        else:
            confidence = 0.0
        
        # Create alert object
        alert = StreamingSAMEAlert(
            message=msg_text,
            confidence=confidence,
            timestamp=utc_now(),
            raw_bits=list(self.bit_confidences)
        )
        
        self.alerts_detected += 1
        
        logger.info(
            f"🔔 SAME Alert Detected: {msg_text[:50]}... "
            f"(confidence: {confidence:.1%}, alert #{self.alerts_detected})"
        )
        
        # Invoke callback
        if self.alert_callback:
            try:
                self.alert_callback(alert)
            except Exception as e:
                logger.error(f"Error in alert callback: {e}", exc_info=True)
    
    def get_stats(self) -> dict:
        """Get decoder statistics."""
        return {
            'samples_processed': self.samples_processed,
            'alerts_detected': self.alerts_detected,
            'bytes_decoded': self.bytes_decoded,
            'synced': self.synced,
            'in_message': self.in_message,
            'current_message_length': len(self.current_msg)
        }


__all__ = ['StreamingSAMEDecoder', 'StreamingSAMEAlert']
