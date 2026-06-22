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
Resampling Broadcast Audio Adapter

Wraps a BroadcastAudioAdapter and resamples audio from source sample rate
to target sample rate. This is critical for the EAS decoder which expects
audio at exactly 16kHz.

The adapter handles buffering and resampling efficiently to minimize CPU overhead.
"""

import logging
import numpy as np
from typing import Optional
from .broadcast_adapter import BroadcastAudioAdapter
from .broadcast_queue import BroadcastQueue

logger = logging.getLogger(__name__)


class ResamplingBroadcastAdapter:
    """
    Resampling wrapper for BroadcastAudioAdapter.

    Subscribes to broadcast queue at source sample rate, resamples to target
    sample rate, and serves audio via read_audio() interface.

    This ensures the EAS decoder always receives audio at exactly 16kHz,
    regardless of the source sample rate (44.1kHz, 48kHz, etc.).
    """

    def __init__(
        self,
        broadcast_queue: BroadcastQueue,
        subscriber_id: str,
        source_sample_rate: int,
        target_sample_rate: int = 16000,
        read_timeout: float = 0.5
    ):
        """
        Initialize resampling adapter.

        Args:
            broadcast_queue: BroadcastQueue to subscribe to
            subscriber_id: Unique subscriber ID
            source_sample_rate: Sample rate of source audio (e.g., 48000)
            target_sample_rate: Target sample rate for output (e.g., 16000)
            read_timeout: Timeout for queue reads
        """
        self.source_sample_rate = source_sample_rate
        self.target_sample_rate = target_sample_rate
        self.sample_rate = target_sample_rate  # For compatibility with EASMonitor

        # Create underlying broadcast adapter at source rate
        self._adapter = BroadcastAudioAdapter(
            broadcast_queue=broadcast_queue,
            subscriber_id=subscriber_id,
            sample_rate=source_sample_rate,
            read_timeout=read_timeout
        )

        # Calculate resampling ratio
        self._needs_resample = (source_sample_rate != target_sample_rate)
        self._resample_ratio = target_sample_rate / source_sample_rate

        logger.info(
            f"ResamplingBroadcastAdapter '{subscriber_id}': "
            f"{source_sample_rate}Hz -> {target_sample_rate}Hz "
            f"(ratio: {self._resample_ratio:.4f}, resample: {self._needs_resample})"
        )

    def read_audio(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Read specified number of samples at target sample rate.

        Args:
            num_samples: Number of samples requested at target rate (e.g., 16kHz)

        Returns:
            NumPy array of num_samples at target rate, or None if insufficient data
        """
        if not self._needs_resample:
            # No resampling needed, pass through directly
            return self._adapter.read_audio(num_samples)

        # Calculate how many source samples we need to produce num_samples output
        # Add extra samples to ensure we have enough after resampling
        source_samples_needed = int(num_samples / self._resample_ratio) + 2

        # Read from underlying adapter at source rate
        source_audio = self._adapter.read_audio(source_samples_needed)

        if source_audio is None or len(source_audio) == 0:
            return None

        # Resample to target rate using linear interpolation
        try:
            # Convert to mono if stereo
            if source_audio.ndim == 2:
                source_audio = source_audio.mean(axis=1)
            elif source_audio.ndim > 2:
                source_audio = source_audio.flatten()

            # Ensure float32 for interpolation
            if source_audio.dtype != np.float32:
                source_audio = source_audio.astype(np.float32)

            # Resample using linear interpolation
            old_indices = np.arange(len(source_audio))
            new_length = max(1, int(len(source_audio) * self._resample_ratio))
            new_indices = np.linspace(0, len(source_audio) - 1, new_length)
            resampled = np.interp(new_indices, old_indices, source_audio).astype(np.float32)

            # Return exactly num_samples (trim if we got more due to rounding)
            if len(resampled) >= num_samples:
                return resampled[:num_samples]
            else:
                # Pad with zeros if we got fewer samples than requested
                padded = np.zeros(num_samples, dtype=np.float32)
                padded[:len(resampled)] = resampled
                return padded

        except Exception as e:
            logger.error(f"Resampling error: {e}")
            return None

    def close(self):
        """Clean up resources."""
        if hasattr(self._adapter, 'close'):
            self._adapter.close()
