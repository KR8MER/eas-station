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
Redis Audio Adapter for EAS Monitor

Subscribes to Redis pub/sub channels to receive audio samples from audio-service.
Provides the audio_manager interface expected by ContinuousEASMonitor.

This is the bridge between audio-service (audio demodulation) and
eas-service (EAS monitoring) in 3-tier separated architecture.
"""

import base64
import json
import logging
import queue
import struct
import threading
import time
from typing import Optional, Any

import numpy as np

logger = logging.getLogger(__name__)


class RedisAudioAdapter:
    """
    Audio adapter that receives audio samples from Redis pub/sub.

    Subscribes to audio:samples:* channels published by audio-service,
    and provides audio via the read_audio() interface expected by ContinuousEASMonitor.

    This enables 3-tier separated architecture where:
    - sdr-service: SDR hardware access + IQ sample publishing
    - audio-service: IQ demodulation + audio publishing
    - eas-service: EAS monitoring + alert storage
    """

    def __init__(
        self,
        subscriber_id: str,
        sample_rate: int = 16000,
        read_timeout: float = 0.5
    ):
        """
        Initialize Redis audio adapter.

        Args:
            subscriber_id: Unique ID for this subscription (e.g., "eas-monitor")
            sample_rate: Expected sample rate (should match audio-service output)
            read_timeout: Timeout for queue reads in seconds
        """
        self.subscriber_id = subscriber_id
        self.sample_rate = sample_rate
        self._read_timeout = max(0.1, float(read_timeout))

        self._redis_client: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._subscriber_thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue = queue.Queue(maxsize=100)
        self._running = threading.Event()
        self._last_audio_time: Optional[float] = None
        self._total_samples_received: int = 0
        self._underrun_count: int = 0
        self._total_reads: int = 0
        self._active_source: Optional[str] = None

        # Buffer management
        self._chunk_list: list = []
        self._chunk_total_samples: int = 0
        self._buffer_lock = threading.Lock()
        self._max_buffer_samples = sample_rate * 5  # 5 seconds

        self._initialize()

    def _initialize(self) -> None:
        """Initialize Redis connection and subscription."""
        import redis as redis_lib
        from app_core.config.redis_config import (
            get_redis_host,
            get_redis_port,
            get_redis_db,
            get_redis_password,
            RedisTimeouts,
        )

        try:
            # Audio frames published on audio:samples:* are raw binary
            # (magic + struct header + float32 samples), not UTF-8 text.
            # The shared app-wide client from get_redis_client() is
            # decode_responses=True, which makes redis-py try to UTF-8
            # decode every pub/sub payload before it reaches our code --
            # raw audio bytes are routinely not valid UTF-8, so that client
            # raises UnicodeDecodeError out of pubsub.listen() itself and
            # permanently kills this subscriber thread (no reconnect) on
            # the first real audio chunk. Use a dedicated raw-bytes
            # connection for this subscription instead.
            self._redis_client = redis_lib.Redis(
                host=get_redis_host(),
                port=get_redis_port(),
                db=get_redis_db(),
                password=get_redis_password(),
                decode_responses=False,
                socket_connect_timeout=RedisTimeouts.CONNECT_TIMEOUT,
                socket_timeout=RedisTimeouts.SOCKET_TIMEOUT,
                socket_keepalive=True,
                health_check_interval=RedisTimeouts.HEALTH_CHECK_INTERVAL,
                retry_on_timeout=True,
            )
            self._redis_client.ping()
            logger.info(f"Redis audio adapter '{self.subscriber_id}' connected to Redis")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Redis: {e}") from e

        # Subscribe to all audio channels (audio:samples:*)
        self._pubsub = self._redis_client.pubsub(ignore_subscribe_messages=True)
        self._pubsub.psubscribe("audio:samples:*")  # Pattern subscription
        logger.info("Subscribed to Redis pattern: audio:samples:*")

        # Start subscriber thread
        self._running.set()
        self._subscriber_thread = threading.Thread(
            target=self._redis_subscriber_loop,
            name=f"redis-audio-{self.subscriber_id}",
            daemon=True
        )
        self._subscriber_thread.start()
        logger.info("Started Redis audio subscriber thread")

    def _redis_subscriber_loop(self) -> None:
        """Redis pub/sub subscriber loop - receives audio samples."""
        logger.info("Redis audio subscriber loop started")

        try:
            for message in self._pubsub.listen():
                if not self._running.is_set():
                    break

                msg_type = message.get('type')
                if msg_type not in ('pmessage', 'message'):
                    continue

                try:
                    raw = message['data']
                    if isinstance(raw, str):
                        raw = raw.encode('latin-1')

                    # Detect binary frame (magic b'EAS1') vs legacy JSON
                    if raw[:4] == b'EAS1':
                        # Binary format: 4 magic + 4 name_len + name + 8 ts + 4 count + 4 rate + samples
                        offset = 4
                        name_len = struct.unpack('>I', raw[offset:offset + 4])[0]
                        offset += 4
                        source_name = raw[offset:offset + name_len].decode('utf-8')
                        offset += name_len
                        _ts, _count, _rate = struct.unpack('>dII', raw[offset:offset + 16])
                        offset += 16
                        audio_samples = np.frombuffer(raw[offset:], dtype=np.float32).copy()
                    else:
                        # Legacy JSON+base64 fallback
                        data = json.loads(raw)
                        encoded_samples = data.get('samples', '')
                        if not encoded_samples:
                            continue
                        source_name = data.get('source_name', 'unknown')
                        sample_bytes = base64.b64decode(encoded_samples)
                        audio_samples = np.frombuffer(sample_bytes, dtype=np.float32)

                    self._active_source = source_name

                    # Add to buffer
                    with self._buffer_lock:
                        self._chunk_list.append(audio_samples)
                        self._chunk_total_samples += len(audio_samples)
                        self._last_audio_time = time.time()
                        self._total_samples_received += len(audio_samples)

                        # Trim buffer if too large
                        if self._chunk_total_samples > self._max_buffer_samples:
                            buffer = self._consolidate_chunks()
                            trimmed = buffer[-self._max_buffer_samples:]
                            self._chunk_list = [trimmed]
                            self._chunk_total_samples = len(trimmed)

                except Exception as e:
                    logger.error(f"Error processing Redis audio sample: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Redis audio subscriber loop error: {e}", exc_info=True)
        finally:
            logger.info("Redis audio subscriber loop exited")

    def _consolidate_chunks(self) -> np.ndarray:
        """Consolidate chunk list into a single contiguous array."""
        if not self._chunk_list:
            return np.array([], dtype=np.float32)
        if len(self._chunk_list) == 1:
            return self._chunk_list[0]
        result = np.concatenate(self._chunk_list)
        self._chunk_list = [result]
        self._chunk_total_samples = len(result)
        return result

    def read_audio(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Read specified number of audio samples.

        Compatible with ContinuousEASMonitor interface.

        Args:
            num_samples: Number of samples to read

        Returns:
            NumPy array of samples, or None if insufficient data
        """
        with self._buffer_lock:
            self._total_reads += 1

            # Wait briefly for samples to arrive if buffer is empty
            max_wait_time = self._read_timeout
            wait_start = time.time()

            while self._chunk_total_samples < num_samples and (time.time() - wait_start) < max_wait_time:
                # Release lock while waiting
                self._buffer_lock.release()
                time.sleep(0.01)
                self._buffer_lock.acquire()

            # Check if we have enough samples now
            if self._chunk_total_samples < num_samples:
                self._underrun_count += 1
                # Log with exponential backoff: at 10, 50, 100, 200, 500, 1000, etc.
                # This reduces log spam while still showing the problem severity
                # Using set for O(1) lookup performance
                if (self._underrun_count in {10, 50, 100, 200, 500, 1000, 2000, 5000, 10000} or
                    (self._underrun_count > 10000 and self._underrun_count % 10000 == 0)):
                    logger.warning(
                        f"Audio underrun #{self._underrun_count}: "
                        f"buffer={self._chunk_total_samples}/{num_samples} samples"
                    )
                return None

            # Extract requested samples
            buffer = self._consolidate_chunks()
            samples = buffer[:num_samples].copy()

            # Keep remaining samples
            remaining = buffer[num_samples:]
            if len(remaining) > 0:
                self._chunk_list = [remaining]
                self._chunk_total_samples = len(remaining)
            else:
                self._chunk_list = []
                self._chunk_total_samples = 0

            return samples

    def get_active_source(self) -> Optional[str]:
        """Get name of currently active audio source."""
        return self._active_source

    def get_stats(self) -> dict:
        """Get adapter statistics for monitoring."""
        with self._buffer_lock:
            buffer_samples = self._chunk_total_samples
            buffer_seconds = buffer_samples / self.sample_rate if self.sample_rate > 0 else 0
            underrun_rate = (self._underrun_count / self._total_reads * 100) if self._total_reads > 0 else 0

            return {
                "subscriber_id": self.subscriber_id,
                "buffer_samples": buffer_samples,
                "buffer_seconds": buffer_seconds,
                "sample_rate": self.sample_rate,
                "total_reads": self._total_reads,
                "total_samples_received": self._total_samples_received,
                "underrun_count": self._underrun_count,
                "underrun_rate_percent": underrun_rate,
                "last_audio_time": self._last_audio_time,
                "active_source": self._active_source,
                "health": "good" if underrun_rate < 1.0 else "degraded" if underrun_rate < 5.0 else "poor"
            }

    def stop(self) -> None:
        """Stop Redis subscription."""
        self._running.clear()

        if self._pubsub:
            try:
                self._pubsub.punsubscribe()
                self._pubsub.close()
            except Exception as e:
                logger.error(f"Error closing Redis pub/sub: {e}")

        if self._subscriber_thread and self._subscriber_thread.is_alive():
            self._subscriber_thread.join(timeout=5.0)

        logger.info(f"Redis audio adapter '{self.subscriber_id}' stopped")

    def __repr__(self) -> str:
        return f"<RedisAudioAdapter '{self.subscriber_id}'>"
