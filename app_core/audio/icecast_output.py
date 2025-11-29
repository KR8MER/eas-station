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

from __future__ import annotations

"""
Icecast Output for Audio Rebroadcast

Streams audio from AudioSourceManager to an Icecast server for network distribution.
Allows multiple clients to listen to the monitored audio stream.

Key Features:
- Streams to Icecast/Shoutcast servers
- Automatic reconnection on failure
- Multiple format support (MP3, OGG)
- Metadata updates (stream title, description)
- Health monitoring
"""

import base64
import errno
import logging
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, unquote

import numpy as np
import requests
from requests import exceptions as requests_exceptions

logger = logging.getLogger(__name__)

# Delay before restarting FFmpeg after a failure (seconds)
ICECAST_RESTART_DELAY = 5.0

# Metadata update retry configuration
METADATA_UPDATE_MAX_RETRIES = 3  # Maximum number of retry attempts for metadata updates
METADATA_UPDATE_RETRY_DELAY = 2.0  # Initial delay between retries in seconds (with exponential backoff)


class StreamFormat(Enum):
    """Supported streaming formats."""
    MP3 = "mp3"
    OGG = "ogg"


@dataclass
class IcecastConfig:
    """Configuration for Icecast streaming."""
    server: str
    port: int
    password: str
    mount: str
    name: str
    description: str
    genre: str = "Emergency"
    bitrate: int = 128
    format: StreamFormat = StreamFormat.MP3
    public: bool = False
    sample_rate: int = 44100  # Audio sample rate in Hz
    channels: int = 1  # Audio channels (1 = mono, 2 = stereo)
    admin_user: Optional[str] = None
    admin_password: Optional[str] = None
    metadata_poll_interval: float = 1.0
    source_timeout: float = 30.0  # Seconds without writes before forcing a restart


class IcecastStreamer:
    """
    Streams audio to Icecast server using FFmpeg.

    Reads audio from AudioSourceManager and encodes/streams to Icecast
    for network distribution to multiple clients.
    """

    def __init__(self, config: IcecastConfig, audio_source):
        """
        Initialize Icecast streamer.

        Args:
            config: Icecast configuration
            audio_source: Audio source (AudioSourceAdapter or similar) with get_broadcast_queue() method
        """
        self.config = config
        self.audio_source = audio_source
        
        # Subscribe to source's broadcast queue for non-destructive audio access
        # This allows multiple consumers (Icecast, web streaming, EAS monitor) to
        # receive independent copies of audio without competing for chunks.
        # CRITICAL FIX: Previously we called audio_source.get_audio_chunk() which
        # destructively removed from a shared queue - now we subscribe independently.
        self._subscriber_id = f"icecast-{config.mount}"
        self._audio_queue = None  # Will be set in start() after source is running
        
        # Pre-sanitize stream metadata fields to avoid runtime encoding errors.
        self._stream_name = self._sanitize_metadata_value(
            getattr(self.config, 'name', None),
            "EAS Station",
        )
        self._stream_description = self._sanitize_metadata_value(
            getattr(self.config, 'description', None),
            self._stream_name,
        )
        self._stream_genre = self._sanitize_metadata_value(
            getattr(self.config, 'genre', None),
            "Emergency",
        )

        # FFmpeg process
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._feeder_thread: Optional[threading.Thread] = None
        self._stderr_reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stop_event.set()  # Start in stopped state

        # Statistics
        self._start_time = 0.0
        self._bytes_sent = 0
        self._reconnect_count = 0
        self._last_error: Optional[str] = None
        self._last_metadata_payload: Optional[Tuple[str, Optional[str]]] = None
        self._last_metadata_song: Optional[str] = None
        self._last_metadata_check = 0.0
        self._metadata_poll_interval = max(self.config.metadata_poll_interval, 0.5)
        self._source_timeout = max(getattr(self.config, 'source_timeout', 30.0) or 0.0, 0.0)
        self._last_write_time = 0.0
        self._last_buffer_warning = 0.0  # Throttle buffer warnings to avoid log spam
        self._consecutive_empty_reads = 0  # Track consecutive failed reads from audio source

        # Extended metadata (album art, song length, etc.)
        self._last_artwork_url: Optional[str] = None
        self._last_song_length: Optional[str] = None
        self._last_album: Optional[str] = None

        # Metadata update coordination
        self._metadata_update_lock = threading.Lock()
        self._metadata_update_thread: Optional[threading.Thread] = None
        self._pending_metadata: Optional[
            Tuple[Tuple[str, Optional[str]], str, Optional[str]]
        ] = None

        # Connection health tracking
        self._connection_health = {
            'last_connect_time': 0.0,
            'reconnect_attempts': 0,
            'backoff_time': 1.0,  # Start 1 second
            'max_backoff': 60.0,   # Cap at 60 seconds
        }

        logger.info(
            f"Initialized IcecastStreamer: {config.server}:{config.port}/{config.mount}"
        )

    def start(self) -> bool:
        """
        Start streaming to Icecast.

        Returns:
            True if started successfully
        """
        if not self._stop_event.is_set():
            logger.warning("IcecastStreamer already running")
            return False

        self._stop_event.clear()
        self._start_time = time.time()
        self._last_write_time = self._start_time

        # Subscribe to source's broadcast queue for non-destructive audio access
        # Each Icecast stream gets its own independent subscription
        if hasattr(self.audio_source, 'get_broadcast_queue'):
            source_broadcast = self.audio_source.get_broadcast_queue()
            self._audio_queue = source_broadcast.subscribe(self._subscriber_id)
            logger.info(
                f"Icecast streamer '{self._subscriber_id}' subscribed to source broadcast queue"
            )
        else:
            # Fallback for legacy sources without broadcast queue
            logger.warning(
                f"Audio source for mount {self.config.mount} does not support broadcast queue, "
                "falling back to direct access (may cause audio contention)"
            )
            self._audio_queue = None

        # Start FFmpeg encoder
        if not self._start_ffmpeg():
            return False

        self._last_write_time = time.time()

        # Start feeder thread
        self._feeder_thread = threading.Thread(
            target=self._feed_loop,
            name="icecast-feeder",
            daemon=True
        )
        self._feeder_thread.start()

        logger.info(f"Started Icecast streaming to {self.config.server}:{self.config.port}")
        return True

    def stop(self) -> None:
        """Stop streaming."""
        logger.info(f"Stopping Icecast streamer for mount {self.config.mount}")
        self._stop_event.set()

        # Unsubscribe from broadcast queue
        if hasattr(self.audio_source, 'get_broadcast_queue') and self._audio_queue is not None:
            try:
                source_broadcast = self.audio_source.get_broadcast_queue()
                source_broadcast.unsubscribe(self._subscriber_id)
                logger.info(f"Icecast streamer '{self._subscriber_id}' unsubscribed from source")
            except Exception as e:
                logger.warning(f"Error unsubscribing Icecast streamer: {e}")
            self._audio_queue = None

        # Stop FFmpeg
        if self._ffmpeg_process:
            try:
                logger.debug(f"Terminating FFmpeg process for mount {self.config.mount}")
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=5.0)
                logger.info(f"FFmpeg process terminated successfully for mount {self.config.mount}")
            except Exception:
                try:
                    logger.warning(f"Force-killing FFmpeg process for mount {self.config.mount}")
                    self._ffmpeg_process.kill()
                except Exception:
                    pass
            self._ffmpeg_process = None

        # Wait for stderr reader thread
        if self._stderr_reader_thread:
            self._stderr_reader_thread.join(timeout=2.0)
            self._stderr_reader_thread = None

        # Wait for feeder thread
        if self._feeder_thread:
            self._feeder_thread.join(timeout=5.0)

        # Wait for any in-flight metadata updates
        with self._metadata_update_lock:
            pending_thread = self._metadata_update_thread
            self._metadata_update_thread = None
            self._pending_metadata = None

        if pending_thread and pending_thread.is_alive():
            pending_thread.join(timeout=2.0)

        logger.info(f"Stopped Icecast streamer for mount {self.config.mount}")

    def _read_ffmpeg_stderr(self) -> None:
        """Read and log FFmpeg stderr output to prevent buffer blocking."""
        if not self._ffmpeg_process or not self._ffmpeg_process.stderr:
            return

        try:
            # Read stderr line by line and log it
            for line in iter(self._ffmpeg_process.stderr.readline, b''):
                if self._stop_event.is_set():
                    break

                decoded_line = line.decode('utf-8', errors='replace').strip()
                if decoded_line:
                    # Only log important messages (errors/warnings) to avoid log spam
                    # FFmpeg is very verbose with version info and config
                    lower_line = decoded_line.lower()
                    if any(keyword in lower_line for keyword in
                           ['error', 'failed', 'invalid', 'unable', 'not found',
                            'warning', 'deprecated', 'refused', 'timeout']):
                        logger.warning(f"FFmpeg [{self.config.mount}]: {decoded_line}")
                    else:
                        logger.debug(f"FFmpeg [{self.config.mount}]: {decoded_line}")
        except Exception as e:
            logger.debug(f"FFmpeg stderr reader stopped: {e}")

    def _start_ffmpeg(self) -> bool:
        """Start FFmpeg encoder and Icecast streamer."""
        try:
            # Build Icecast URL with properly encoded credentials
            # URL-encode the password to handle special characters like @, :, /, etc.
            from urllib.parse import quote
            encoded_password = quote(self.config.password, safe='')

            # Strip leading slash from mount point to prevent double slash in URL
            # Mount points internally have leading slash (/stream.mp3) but icecast:// URL
            # format doesn't want it: icecast://user:pass@host:port/stream.mp3 (not //stream.mp3)
            mount_path = self.config.mount.lstrip('/')

            # Note: The 10-minute timeout fix is SERVER-SIDE in Icecast config (source-timeout=0)
            # The icecast:// protocol (libshout) doesn't support HTTP timeout options
            icecast_url = (
                f"icecast://source:{encoded_password}@"
                f"{self.config.server}:{self.config.port}/{mount_path}"
            )

            # FFmpeg command to encode and stream
            cmd = [
                'ffmpeg',
                '-f', 's16le',  # Input: 16-bit PCM
                '-ar', str(self.config.sample_rate),  # Sample rate
                '-ac', str(max(1, int(self.config.channels))),
                '-i', 'pipe:0',  # Read from stdin
            ]

            # Add format-specific encoding options
            if self.config.format == StreamFormat.MP3:
                cmd.extend([
                    '-acodec', 'libmp3lame',
                    '-b:a', f'{self.config.bitrate}k',
                    '-f', 'mp3',
                ])
            elif self.config.format == StreamFormat.OGG:
                cmd.extend([
                    '-acodec', 'libvorbis',
                    '-b:a', f'{self.config.bitrate}k',
                    '-f', 'ogg',
                ])

            stream_name = self._stream_name or "EAS Station"
            stream_description = self._stream_description or stream_name
            stream_genre = self._stream_genre or "Emergency"

            # Add metadata
            cmd.extend([
                '-metadata', f'title={stream_name}',
                '-metadata', f'artist=EAS Station',
                '-metadata', f'album={stream_description}',
                '-metadata', f'genre={stream_genre}',
            ])

            # Output to Icecast with keep-alive options
            cmd.extend([
                '-content_type', 'audio/mpeg' if self.config.format == StreamFormat.MP3 else 'audio/ogg',
                '-ice_name', stream_name,
                '-ice_description', stream_description,
                '-ice_genre', stream_genre,
                '-ice_public', '0',  # Disable directory listing
                icecast_url
            ])

            logger.info(f"Starting FFmpeg Icecast streamer for mount {self.config.mount}: {' '.join(cmd[:10])}...")

            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=8192
            )

            # Start stderr reader thread to prevent buffer blocking
            self._stderr_reader_thread = threading.Thread(
                target=self._read_ffmpeg_stderr,
                name=f"ffmpeg-stderr-{self.config.mount}",
                daemon=True
            )
            self._stderr_reader_thread.start()

            logger.info(f"FFmpeg process started successfully for mount {self.config.mount} (PID: {self._ffmpeg_process.pid})")
            return True

        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Failed to start FFmpeg Icecast streamer: {e}")
            return False

    def _start_ffmpeg_with_adaptive_backoff(self) -> bool:
        """Start FFmpeg with exponential backoff on repeated failures."""
        health = self._connection_health
        now = time.time()
        
        # If last connection failed recently, apply backoff
        if health['last_connect_time'] > 0 and now - health['last_connect_time'] < 30:
            # Connection is failing repeatedly
            wait_time = min(health['backoff_time'], health['max_backoff'])
            logger.warning(
                f"Icecast backoff: waiting {wait_time:.1f}s "
                f"(attempt {health['reconnect_attempts']})"
            )
            time.sleep(wait_time)
            
            # Exponential backoff: 1s, 2s, 4s, 8s, ... up to 60s
            health['backoff_time'] *= 2
            health['reconnect_attempts'] += 1
        else:
            # Connection healthy - reset backoff
            health['backoff_time'] = 1.0
            health['reconnect_attempts'] = 0
            
        health['last_connect_time'] = now
        
        # Attempt connection
        try:
            return self._start_ffmpeg()
        except Exception as e:
            logger.error(f"FFmpeg start failed: {e}")
            return False

    def _get_audio_from_subscription(self, timeout: float = 1.0):
        """
        Get audio chunk from broadcast subscription queue.
        
        Uses the subscription queue if available (preferred), otherwise
        falls back to direct source access for legacy compatibility.
        """
        import queue as queue_module
        
        if self._audio_queue is not None:
            # Use broadcast subscription (non-destructive)
            try:
                return self._audio_queue.get(timeout=timeout)
            except queue_module.Empty:
                return None
        else:
            # Fallback to direct source access (legacy, may cause contention)
            return self.audio_source.get_audio_chunk(timeout=timeout)

    def _prebuffer_audio(self, target_chunks=150, timeout_seconds=30.0):
        """
        Pre-buffer audio with relaxed constraints.
        Prioritize getting some audio over waiting for perfect buffer.
        """
        from collections import deque
        buffer = deque(maxlen=600)
        
        start_time = time.time()
        min_acceptable_chunks = 50  # Accept buffer with 50 chunks (2.5s) minimum
        
        while len(buffer) < target_chunks:
            elapsed = time.time() - start_time
            
            if elapsed > timeout_seconds:
                # Timeout reached
                if len(buffer) >= min_acceptable_chunks:
                    logger.warning(
                        f"Icecast prebuffer timeout with {len(buffer)}/{target_chunks} "
                        f"chunks ({len(buffer)*50}ms) - starting with partial buffer"
                    )
                    return buffer  # Return partial buffer instead of failing
                else:
                    logger.error(
                        f"Icecast prebuffer failed: only {len(buffer)} chunks "
                        f"after {timeout_seconds}s - audio source may be unavailable"
                    )
                    return None
            
            # Gradually relax timeout as we approach hard limit
            time_remaining = timeout_seconds - elapsed
            read_timeout = min(1.0, max(0.1, time_remaining / 10))
            
            try:
                # Use subscription-based read (non-destructive)
                samples = self._get_audio_from_subscription(timeout=read_timeout)
                if samples is not None:
                    buffer.append(self._samples_to_pcm_bytes(samples))
                    
                    # Progress feedback
                    if len(buffer) % 50 == 0:
                        logger.info(
                            f"Icecast prebuffering: {len(buffer)}/{target_chunks} chunks "
                            f"({len(buffer)*50}ms of audio)"
                        )
            except Exception as e:
                logger.debug(f"Prebuffer read error: {e}")
                time.sleep(0.05)
        
        return buffer

    def _get_chunk_timeout(self):
        """
        Calculate read timeout based on source type and buffer health.
        HTTP/Icecast sources need longer timeouts than local SDR.
        """
        source_type = type(self.audio_source).__name__
        buffer_health = getattr(self.audio_source, 'buffer_health', 0.5)
        
        # Base timeouts by source type
        base_timeouts = {
            'IcecastIngestSource': 2.0,    # Network sources: 2s (handles buffering)
            'HTTPIngestSource': 2.0,       # HTTP streams: 2s
            'AudioSourceManager': 0.5,    # Local SDR: 0.5s
            'default': 1.0
        }
        
        base = base_timeouts.get(source_type, base_timeouts['default'])
        
        # If buffer is low, increase timeout to give source time to recover
        if buffer_health < 0.25:
            return base * 2.0
        elif buffer_health < 0.5:
            return base * 1.5
            
        return base

    def _feed_loop(self) -> None:
        """Feed audio to FFmpeg for encoding and streaming."""
        logger.debug("Icecast feed loop started")

        # CRITICAL: Pre-buffer audio to prevent stuttering/clipping
        # Use the helper method which handles timeouts and partial buffers gracefully
        from collections import deque
        buffer = self._prebuffer_audio(target_chunks=150)
        
        if buffer is None:
             # If prebuffering failed completely, start with empty buffer but warn
             buffer = deque(maxlen=600)
             logger.warning("Starting Icecast stream with empty buffer due to prebuffer failure")

        buffer_low_watermark = 150  # Warn if buffer drops below 7.5 seconds (25% of max)

        # Diagnostic: Check audio source type and status
        source_type = type(self.audio_source).__name__
        source_status = getattr(self.audio_source, 'status', 'unknown')
        subscription_mode = "broadcast subscription" if self._audio_queue is not None else "direct access (legacy)"
        logger.info(f"Audio source for {self.config.mount}: {source_type}, Status: {source_status}, Mode: {subscription_mode}")

        while not self._stop_event.is_set():
            if not self._ffmpeg_process or self._ffmpeg_process.poll() is not None:
                reason = "encoder not running" if not self._ffmpeg_process else "encoder exited"
                # Use adaptive backoff for restarts
                if not self._restart_ffmpeg(reason):
                    time.sleep(1.0)
                continue

            try:
                wrote_chunk = False
                # Read audio from subscription queue (non-destructive) using adaptive timeout
                read_timeout = self._get_chunk_timeout()
                samples = self._get_audio_from_subscription(timeout=read_timeout)

                if samples is not None:
                    pcm_bytes = self._samples_to_pcm_bytes(samples)
                    buffer.append(pcm_bytes)
                    self._consecutive_empty_reads = 0  # Reset counter on successful read
                else:
                    # Track consecutive empty reads to diagnose source issues
                    self._consecutive_empty_reads += 1
                    if self._consecutive_empty_reads == 20: 
                        logger.error(
                            f"Audio source for mount {self.config.mount} has not provided data for ~20 reads. "
                            f"Buffer: {len(buffer)}/{buffer.maxlen} chunks. "
                            "Check if audio source is running and configured correctly."
                        )
                    elif self._consecutive_empty_reads == 100:
                        logger.critical(
                            f"Audio source for mount {self.config.mount} starved for 100+ reads! "
                            f"This indicates a serious issue with the audio source."
                        )

                # Feed FFmpeg from buffer
                if buffer and self._ffmpeg_process and self._ffmpeg_process.stdin:
                    chunk = buffer.popleft()
                    self._ffmpeg_process.stdin.write(chunk)
                    self._ffmpeg_process.stdin.flush()
                    self._bytes_sent += len(chunk)
                    wrote_chunk = True

                    # Monitor buffer health
                    buffer_level = len(buffer)
                    if buffer_level < buffer_low_watermark:
                        now_warn = time.time()
                        if now_warn - self._last_buffer_warning > 30.0:
                            logger.warning(
                                f"Icecast buffer running low for mount {self.config.mount}: "
                                f"{buffer_level}/{buffer.maxlen} chunks. "
                                "Audio source may be blocking or too slow."
                            )
                            self._last_buffer_warning = now_warn
                elif not buffer:
                    # Buffer empty
                    now_error = time.time()
                    if now_error - self._last_buffer_warning > 30.0:
                        logger.error(
                            f"Icecast buffer completely empty for mount {self.config.mount}! "
                            "Audio source starved."
                        )
                        self._last_buffer_warning = now_error
                    time.sleep(0.05)

                if wrote_chunk:
                    self._last_write_time = time.time()

                now = time.time()
                if now - self._last_metadata_check >= self._metadata_poll_interval:
                    self._last_metadata_check = now
                    self._maybe_update_metadata()

                if (
                    self._source_timeout
                    and buffer
                    and self._last_write_time > 0.0
                    and now - self._last_write_time > self._source_timeout
                ):
                    idle_duration = now - self._last_write_time
                    logger.warning(
                        "No audio written to Icecast for %.1f seconds; forcing encoder restart",
                        idle_duration,
                    )
                    if not self._restart_ffmpeg(f"idle writer timeout ({idle_duration:.1f}s)"):
                        time.sleep(1.0)
                    continue

            except BrokenPipeError as exc:
                logger.error(f"Icecast FFmpeg pipe closed for mount {self.config.mount}: {exc}")
                if not self._restart_ffmpeg("ffmpeg pipe closed"):
                    time.sleep(1.0)
            except OSError as exc:
                if exc.errno == errno.EPIPE:
                    logger.error(f"Icecast FFmpeg write EPIPE for mount {self.config.mount}: {exc}")
                    if not self._restart_ffmpeg("ffmpeg EPIPE"):
                        time.sleep(1.0)
                else:
                    logger.error(f"Error feeding Icecast stream for mount {self.config.mount}: {exc}")
                    time.sleep(1.0)
            except Exception as e:
                logger.error(f"Error feeding Icecast stream: {e}")
                time.sleep(1.0)

        logger.debug("Icecast feed loop stopped")

    def _restart_ffmpeg(self, reason: str) -> bool:
        """Tear down and re-launch the FFmpeg encoder pipeline."""

        if self._stop_event.is_set():
            return False

        process = self._ffmpeg_process
        stderr_thread = self._stderr_reader_thread

        logger.warning(f"FFmpeg process restart triggered for mount {self.config.mount}: {reason}")

        if process:
            try:
                logger.debug(f"Terminating FFmpeg process for mount {self.config.mount} (PID: {process.pid})")
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                    logger.debug(f"FFmpeg process terminated gracefully for mount {self.config.mount}")
                except subprocess.TimeoutExpired:
                    logger.debug(f"FFmpeg did not terminate gracefully for mount {self.config.mount}; killing process")
                    process.kill()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug(f"Error waiting for FFmpeg termination for mount {self.config.mount}: {exc}")
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug(f"Error terminating FFmpeg for mount {self.config.mount}: {exc}")

        # Wait for stderr reader thread to finish
        if stderr_thread and stderr_thread.is_alive():
            stderr_thread.join(timeout=1.0)

        self._ffmpeg_process = None
        self._stderr_reader_thread = None
        self._reconnect_count += 1
        self._last_error = reason

        if self._stop_event.is_set():
            return False

        # Use adaptive backoff instead of fixed delay
        if self._start_ffmpeg_with_adaptive_backoff():
            self._last_write_time = time.time()
            logger.info(f"FFmpeg restarted successfully for mount {self.config.mount}")
            return True

        logger.error(f"Failed to restart FFmpeg for mount {self.config.mount} ({reason})")
        return False

    def _samples_to_pcm_bytes(self, samples: np.ndarray) -> bytes:
        """Convert audio samples into interleaved int16 PCM bytes."""

        array = np.asarray(samples, dtype=np.float32)
        channels = max(1, int(self.config.channels))

        if array.ndim == 1:
            if channels > 1:
                array = np.repeat(array[:, np.newaxis], channels, axis=1)
            else:
                array = array[:, np.newaxis]
        elif array.shape[1] != channels:
            if array.shape[1] > channels:
                array = array[:, :channels]
            else:
                pad = np.zeros((array.shape[0], channels - array.shape[1]), dtype=np.float32)
                array = np.concatenate((array, pad), axis=1)

        clipped = np.clip(array, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype(np.int16, copy=False)
        return pcm.tobytes()

    def _maybe_update_metadata(self) -> None:
        """Push updated now-playing metadata to Icecast when it changes."""
        if not (self.config.admin_user and self.config.admin_password):
            return

        metrics = getattr(self.audio_source, 'metrics', None)
        metadata = getattr(metrics, 'metadata', None)
        if not isinstance(metadata, dict):
            return

        payload = self._extract_metadata_fields(metadata)
        if payload is None:
            return

        # Extract title and artist for Icecast update
        raw_title = payload.get('title')
        raw_artist = payload.get('artist')

        # Sanitize metadata before queuing for async update
        safe_title = self._sanitize_metadata_value(
            raw_title,
            self.config.name or self.config.mount or "EAS Station",
        )
        if not safe_title:
            safe_title = self.config.name or self.config.mount or "EAS Station"
        safe_title = safe_title.strip()
        safe_artist = self._sanitize_metadata_value(raw_artist, "")
        if safe_artist:
            safe_artist = safe_artist.strip()
        if not safe_artist:
            safe_artist = None

        # Store extended metadata (gracefully)
        try:
            self._last_artwork_url = payload.get('artwork_url')
            self._last_song_length = payload.get('length')
            self._last_album = payload.get('album')
        except Exception as e:
            logger.debug(f"Error storing extended metadata: {e}")

        cache_key = (
            safe_title.strip() if safe_title else "",
            safe_artist.strip() if safe_artist else None,
        )
        if self._last_metadata_payload == cache_key:
            return

        self._queue_metadata_update(cache_key, safe_title, safe_artist)

    def _extract_metadata_fields(
        self,
        metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Optional[str]]]:
        """
        Derive title/artist and extended metadata from source metadata.

        Returns a dict with keys: title, artist, artwork_url, length, album
        Returns None if no useful metadata found.
        """

        def _normalize(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, dict):
                for key in ('title', 'song', 'text', 'value', 'name'):
                    if key in value:
                        return _normalize(value.get(key))
                return None
            if isinstance(value, (list, tuple)):
                for item in value:
                    normalized = _normalize(item)
                    if normalized:
                        return normalized
                return None

            text = str(value).strip()
            if not text:
                return None

            # Clean up metadata that contains XML/JSON attributes
            # Example: text="Everybody Talks" song_spot="M" MediaBaseId="1842682" ...
            # Extract just the text="" value
            import re
            text_match = re.search(r'text="([^"]+)"', text)
            if text_match:
                text = text_match.group(1)

            # Also try title="" attribute
            elif 'title="' in text:
                title_match = re.search(r'title="([^"]+)"', text)
                if title_match:
                    text = title_match.group(1)

            # Also try song="" attribute
            elif 'song="' in text:
                song_match = re.search(r'song="([^"]+)"', text)
                if song_match:
                    text = song_match.group(1)

            # Remove any remaining XML-like attributes
            # Remove key="value" patterns
            text = re.sub(r'\s+\w+="[^"]*"', '', text)
            # Remove key='value' patterns
            text = re.sub(r"\s+\w+='[^']*'", '', text)
            # Remove standalone key=value patterns (no quotes)
            text = re.sub(r'\s+\w+=\S+', '', text)

            # Decode URL-encoded characters (e.g., %20 -> space)
            # This handles metadata from sources like iHeartMedia that include URL encoding
            try:
                text = unquote(text)
            except Exception:
                # If unquote fails for any reason, keep the original text
                pass
            
            # Collapse extraneous whitespace (including newlines)
            # This must happen AFTER URL decoding to handle decoded spaces properly
            text = ' '.join(text.split())
            
            return text or None

        now_playing = metadata.get('now_playing')
        nested_title = None
        nested_artist = None
        if isinstance(now_playing, dict):
            nested_title = _normalize(now_playing.get('title') or now_playing.get('song'))
            nested_artist = _normalize(now_playing.get('artist'))
        elif now_playing is not None:
            nested_title = _normalize(now_playing)

        title_candidates = [
            nested_title,
            _normalize(metadata.get('song_title')),
            _normalize(metadata.get('song')),
            _normalize(metadata.get('title')),
            _normalize(metadata.get('program_title')),
            _normalize(metadata.get('rbds_radio_text')),
        ]

        artist_candidates = [
            nested_artist,
            _normalize(metadata.get('artist')),
            _normalize(metadata.get('song_artist')),
            _normalize(metadata.get('performer')),
            _normalize(metadata.get('rbds_ps_name')),
            _normalize(metadata.get('station_name')),
            _normalize(metadata.get('station_callsign')),
        ]

        title = next((candidate for candidate in title_candidates if candidate), None)
        artist = next((candidate for candidate in artist_candidates if candidate), None)

        if not title and not artist:
            return None

        # Extract additional metadata fields with graceful error handling
        result = {
            'title': title,
            'artist': artist,
            'artwork_url': None,
            'length': None,
            'album': None,
        }

        # Try to extract album art URL (various field names)
        try:
            artwork_candidates = [
                _normalize(metadata.get('amgArtworkURL')),
                _normalize(metadata.get('artwork_url')),
                _normalize(metadata.get('artworkURL')),
                _normalize(metadata.get('album_art')),
                _normalize(metadata.get('cover_art')),
            ]
            if isinstance(now_playing, dict):
                artwork_candidates.extend([
                    _normalize(now_playing.get('artwork_url')),
                    _normalize(now_playing.get('album_art')),
                ])

            # Find first valid URL (should contain http/https)
            for candidate in artwork_candidates:
                if candidate and ('http://' in candidate or 'https://' in candidate):
                    result['artwork_url'] = candidate
                    break
        except Exception as e:
            logger.debug(f"Error extracting artwork URL from metadata: {e}")

        # Try to extract song length/duration
        try:
            length_candidates = [
                _normalize(metadata.get('length')),
                _normalize(metadata.get('duration')),
                _normalize(metadata.get('song_length')),
            ]
            if isinstance(now_playing, dict):
                length_candidates.extend([
                    _normalize(now_playing.get('length')),
                    _normalize(now_playing.get('duration')),
                ])

            result['length'] = next((candidate for candidate in length_candidates if candidate), None)
        except Exception as e:
            logger.debug(f"Error extracting length from metadata: {e}")

        # Try to extract album name
        try:
            album_candidates = [
                _normalize(metadata.get('album')),
                _normalize(metadata.get('album_name')),
            ]
            if isinstance(now_playing, dict):
                album_candidates.append(_normalize(now_playing.get('album')))

            result['album'] = next((candidate for candidate in album_candidates if candidate), None)
        except Exception as e:
            logger.debug(f"Error extracting album from metadata: {e}")

        return result

    @staticmethod
    def _sanitize_metadata_value(value: Optional[str], fallback: str = "") -> str:
        """Return a clean metadata string, supporting UTF-8/Unicode characters."""

        def _prepare(text: Optional[str]) -> str:
            if not text:
                return ""
            cleaned = str(text).strip()
            if not cleaned:
                return ""
            # Collapse extraneous whitespace (including newlines) and return
            cleaned = ' '.join(cleaned.split())
            return cleaned

        sanitized_fallback = _prepare(fallback)
        sanitized_value = _prepare(value)

        if sanitized_value:
            return sanitized_value

        return sanitized_fallback or ""

    def _queue_metadata_update(
        self,
        cache_key: Tuple[str, Optional[str]],
        title: str,
        artist: Optional[str]
    ) -> None:
        """Schedule metadata update on a background thread."""

        if self._stop_event.is_set():
            return

        with self._metadata_update_lock:
            # If an update is already running, store the latest metadata and exit.
            if self._metadata_update_thread and self._metadata_update_thread.is_alive():
                self._pending_metadata = (cache_key, title, artist)
                return

            # No update running; start a new thread.
            self._pending_metadata = None
            self._metadata_update_thread = threading.Thread(
                target=self._run_metadata_update,
                name=f"icecast-metadata-{self.config.mount}",
                args=(cache_key, title, artist),
                daemon=True,
            )
            self._metadata_update_thread.start()

    def _run_metadata_update(
        self,
        cache_key: Tuple[str, Optional[str]],
        title: str,
        artist: Optional[str]
    ) -> None:
        """Perform metadata updates sequentially without blocking audio."""

        pending: Optional[Tuple[Tuple[str, Optional[str]], str, Optional[str]]] = (
            cache_key,
            title,
            artist,
        )

        while pending and not self._stop_event.is_set():
            cache_key, current_title, current_artist = pending

            try:
                sent_value = self._send_metadata_update(current_title, current_artist)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "Unable to update Icecast metadata for %s: %s\nTraceback:\n%s",
                    self.config.mount,
                    exc,
                    ''.join(traceback.format_tb(exc.__traceback__)),
                )
                self._last_error = str(exc)
                sent_value = None

            if sent_value:
                self._last_metadata_payload = cache_key
                self._last_metadata_song = sent_value
                if self._last_artwork_url or self._last_song_length or self._last_album:
                    logger.debug(
                        "Extended metadata for %s: artwork=%s, length=%s, album=%s",
                        self.config.mount,
                        self._last_artwork_url or 'N/A',
                        self._last_song_length or 'N/A',
                        self._last_album or 'N/A',
                    )

            with self._metadata_update_lock:
                if self._stop_event.is_set():
                    self._pending_metadata = None
                    self._metadata_update_thread = None
                    return

                next_pending = self._pending_metadata
                self._pending_metadata = None

                if next_pending:
                    next_cache_key, next_title, next_artist = next_pending
                    pending = (next_cache_key, next_title, next_artist)
                else:
                    pending = None
                    self._metadata_update_thread = None


    def _send_metadata_update(self, title: str, artist: Optional[str]) -> Optional[str]:
        """Submit metadata to Icecast and return the formatted payload on success."""
        if not (self.config.admin_user and self.config.admin_password):
            logger.debug(
                "Metadata update skipped for %s: credentials not configured (user=%s, pass=%s)",
                self.config.mount,
                "SET" if self.config.admin_user else "NOT SET",
                "SET" if self.config.admin_password else "NOT SET",
            )
            return None

        safe_stream_name = self._stream_name or "EAS Station"

        title_text = self._sanitize_metadata_value(title, safe_stream_name)
        artist_text = self._sanitize_metadata_value(artist, "")

        if artist_text and title_text and artist_text.lower() not in title_text.lower():
            song_value = f"{artist_text} - {title_text}"
        else:
            song_value = title_text

        song_value = self._sanitize_metadata_value(song_value, safe_stream_name)

        # Ensure mount path has leading slash for metadata API endpoint
        mount_path = self.config.mount
        if not mount_path.startswith('/'):
            mount_path = f"/{mount_path}"

        # Manually build URL with UTF-8 encoded parameters to avoid latin-1 encoding issues
        # Ensure values are proper Unicode strings before percent-encoding
        mount_str = str(mount_path) if mount_path else ''
        song_str = str(song_value) if song_value else ''

        # quote() with safe='' ensures proper UTF-8 percent-encoding for all special characters
        # Explicitly specify encoding='utf-8' to be absolutely clear
        encoded_mount = quote(mount_str, safe='/', encoding='utf-8', errors='replace')
        encoded_song = quote(song_str, safe='', encoding='utf-8', errors='replace')

        # Build the URL manually to avoid requests' internal parameter encoding
        base_url = f"http://{self.config.server}:{self.config.port}/admin/metadata"
        url = f"{base_url}?mode=updinfo&mount={encoded_mount}&song={encoded_song}"

        # Try auth with standard requests first (latin-1), fall back to UTF-8 if needed
        auth_user = str(self.config.admin_user or '')
        auth_pass = str(self.config.admin_password or '')

        # Log credentials info for debugging (mask password) - use INFO to ensure it shows
        logger.info(
            "Icecast auth for %s: user=%r pass=***%s (total_len=%d)",
            self.config.mount,
            auth_user,
            auth_pass[-2:] if len(auth_pass) >= 2 else "**",
            len(f"{auth_user}:{auth_pass}"),
        )

        # Try to use requests' built-in auth first (latin-1 encoding)
        # This is the standard that most servers expect
        try:
            # Test if credentials can be latin-1 encoded
            auth_user.encode('latin-1')
            auth_pass.encode('latin-1')
            # If successful, use requests' built-in auth
            auth_tuple = (auth_user, auth_pass)
            headers = {}
            logger.debug("Using latin-1 auth encoding (standard)")
        except UnicodeEncodeError:
            # Falls back to UTF-8 for Unicode passwords (RFC 7617)
            credentials = f"{auth_user}:{auth_pass}".encode('utf-8')
            encoded_credentials = base64.b64encode(credentials).decode('ascii')
            auth_tuple = None
            headers = {'Authorization': f'Basic {encoded_credentials}'}
            logger.info("Using UTF-8 auth encoding (RFC 7617) for Unicode password")

        # Retry logic for handling race conditions with Icecast mount initialization
        # If we get a 400 "Source does not exist" error, the mount may not be fully ready
        max_retries = METADATA_UPDATE_MAX_RETRIES
        retry_delay = METADATA_UPDATE_RETRY_DELAY
        
        for attempt in range(max_retries + 1):  # +1 because we count initial attempt as 0
            try:
                # Make the HTTP GET request
                if auth_tuple:
                    response = requests.get(url, auth=auth_tuple, timeout=5.0)
                else:
                    response = requests.get(url, headers=headers, timeout=5.0)
            except requests_exceptions.RequestException as exc:
                logger.warning(
                    "Failed to update Icecast metadata for %s (attempt %d/%d): %s",
                    self.config.mount,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                self._last_error = str(exc)
                
                # Don't retry on connection errors, they're unlikely to resolve quickly
                return None

            if response.status_code == 200:
                logger.info(
                    "Updated Icecast metadata for %s: %s",
                    self.config.mount,
                    song_value,
                )
                return song_value
            
            # Handle 400 errors with retry logic (likely "Source does not exist" race condition)
            if response.status_code == 400:
                if attempt < max_retries:
                    # Calculate exponential backoff delay
                    current_delay = retry_delay * (2 ** attempt)
                    # Use DEBUG level for early attempts since this is expected during mount initialization
                    logger.debug(
                        "Icecast metadata update returned 400 for %s (attempt %d/%d): %s. "
                        "Retrying in %.1f seconds...",
                        self.config.mount,
                        attempt + 1,
                        max_retries + 1,
                        response.text.strip()[:200],
                        current_delay,
                    )
                    time.sleep(current_delay)
                    continue  # Retry the request
                else:
                    # Final attempt failed - use DEBUG since this is common during startup
                    logger.debug(
                        "Icecast metadata update returned 400 for %s after %d attempts: %s. "
                        "This is normal during mount initialization.",
                        self.config.mount,
                        max_retries + 1,
                        response.text.strip()[:200],
                    )
                    self._last_error = f"metadata update failed ({response.status_code}) after {max_retries + 1} attempts"
                    return None
            
            # For other non-200 status codes, log and return without retry
            logger.warning(
                "Icecast metadata update returned %s for %s: %s",
                response.status_code,
                self.config.mount,
                response.text.strip()[:200],
            )
            self._last_error = f"metadata update failed ({response.status_code})"
            return None
        
        # Should not reach here, but just in case
        return None

    def update_metadata(self, title: str, artist: str = "EAS Station") -> bool:
        """Manually update stream metadata via the Icecast admin API."""
        sent_value = self._send_metadata_update(title, artist)
        if sent_value:
            cache_key = (title.strip() if title else "", artist.strip() if artist else None)
            self._last_metadata_payload = cache_key
            self._last_metadata_song = sent_value
            return True

        return False

    def get_stats(self) -> dict:
        """Get streaming statistics."""
        uptime = time.time() - self._start_time if self._start_time > 0 else 0

        # Guard against division by zero when calculating bitrate
        if uptime <= 0:
            bitrate = 0.0
        else:
            bitrate = (self._bytes_sent * 8 / 1000) / uptime

        return {
            'running': not self._stop_event.is_set(),
            'uptime_seconds': uptime,
            'bytes_sent': self._bytes_sent,
            'bitrate_kbps': bitrate,
            'reconnect_count': self._reconnect_count,
            'last_error': self._last_error,
            'server': self.config.server,
            'port': self.config.port,
            'mount': self.config.mount,
            'name': self.config.name,
            'description': self.config.description,
            'genre': self.config.genre,
            'format': self.config.format.value,
            'public': self.config.public,
            'last_metadata': self._last_metadata_song,
            'metadata_enabled': bool(self.config.admin_user and self.config.admin_password),
            'source_timeout': self._source_timeout,
            # Extended metadata
            'artwork_url': self._last_artwork_url,
            'song_length': self._last_song_length,
            'album': self._last_album,
        }


__all__ = ['IcecastStreamer', 'IcecastConfig', 'StreamFormat']
