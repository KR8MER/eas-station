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

from __future__ import annotations

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
from urllib.parse import quote

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
            audio_source: Audio source (AudioSourceManager or similar) with read_audio() method
        """
        self.config = config
        self.audio_source = audio_source

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

            # Note: The 10-minute timeout fix is SERVER-SIDE in Icecast config (source-timeout=0)
            # The icecast:// protocol (libshout) doesn't support HTTP timeout options
            icecast_url = (
                f"icecast://source:{encoded_password}@"
                f"{self.config.server}:{self.config.port}/{self.config.mount}"
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

    def _feed_loop(self) -> None:
        """Feed audio to FFmpeg for encoding and streaming."""
        logger.debug("Icecast feed loop started")

        chunk_samples = int(self.config.sample_rate * 0.1)  # 100ms chunks

        # CRITICAL: Pre-buffer audio to prevent stuttering/clipping
        # Build up a buffer before starting to feed FFmpeg
        from collections import deque
        buffer = deque(maxlen=600)  # Up to 30 seconds of audio (600 * 50ms chunks) - increased from 500
        prebuffer_target = 150  # Pre-fill with 7.5 seconds before starting - increased from 100 to prevent buffer empty errors
        buffer_low_watermark = 150  # Warn if buffer drops below 7.5 seconds (25% of max) - increased from 100

        logger.info(f"Pre-buffering {prebuffer_target} chunks (~{prebuffer_target*50}ms) for smooth Icecast streaming")

        # Diagnostic: Check audio source type and status
        source_type = type(self.audio_source).__name__
        source_status = getattr(self.audio_source, 'status', 'unknown')
        logger.info(f"Audio source: {source_type}, Status: {source_status}")

        prebuffer_timeout = time.time() + 15.0  # 15 seconds max to prebuffer
        prebuffer_attempts = 0

        while len(buffer) < prebuffer_target and time.time() < prebuffer_timeout:
            samples = self.audio_source.get_audio_chunk(timeout=1.0)  # Increased from 0.5s to 1.0s
            prebuffer_attempts += 1
            if samples is not None:
                pcm_bytes = self._samples_to_pcm_bytes(samples)
                buffer.append(pcm_bytes)

        if len(buffer) < prebuffer_target:
            logger.error(
                f"Pre-buffer timeout: only filled {len(buffer)}/{prebuffer_target} chunks "
                f"(~{len(buffer)*50}ms of audio) after {prebuffer_attempts} attempts. "
                f"Audio source {source_type} may not be providing data. Check source status!"
            )
        else:
            logger.info(f"Pre-buffer complete: {len(buffer)} chunks (~{len(buffer)*50}ms of audio)")

        while not self._stop_event.is_set():
            if not self._ffmpeg_process or self._ffmpeg_process.poll() is not None:
                reason = "encoder not running" if not self._ffmpeg_process else "encoder exited"
                if not self._restart_ffmpeg(reason):
                    time.sleep(5.0)
                continue

            try:
                wrote_chunk = False
                # Read audio from source and add to buffer
                samples = self.audio_source.get_audio_chunk(timeout=0.5)  # Increased from 0.1s to 0.5s

                if samples is not None:
                    pcm_bytes = self._samples_to_pcm_bytes(samples)
                    buffer.append(pcm_bytes)
                    self._consecutive_empty_reads = 0  # Reset counter on successful read
                else:
                    # Track consecutive empty reads to diagnose source issues
                    self._consecutive_empty_reads += 1
                    if self._consecutive_empty_reads == 100:  # After 10 seconds of no data (100 * 0.1s timeout)
                        logger.error(
                            f"Audio source has not provided data for 10+ seconds. "
                            f"Buffer: {len(buffer)}/{buffer.maxlen} chunks. "
                            "Check if audio source is running and configured correctly."
                        )
                    elif self._consecutive_empty_reads == 500:  # After 50 seconds
                        logger.critical(
                            f"Audio source completely starved for 50+ seconds! "
                            f"This indicates a serious issue with the audio source. "
                            f"Buffer exhausted. Check logs for audio source errors."
                        )

                # Feed FFmpeg from buffer (always try to send, even if we just got None)
                # This keeps FFmpeg fed even when source is temporarily slow
                if buffer and self._ffmpeg_process and self._ffmpeg_process.stdin:
                    chunk = buffer.popleft()
                    self._ffmpeg_process.stdin.write(chunk)
                    self._ffmpeg_process.stdin.flush()
                    self._bytes_sent += len(chunk)
                    wrote_chunk = True

                    # Monitor buffer health and warn if running low (throttled to avoid spam)
                    buffer_level = len(buffer)
                    if buffer_level < buffer_low_watermark:
                        now_warn = time.time()
                        if now_warn - self._last_buffer_warning > 30.0:  # Max one warning per 30s
                            logger.warning(
                                f"Icecast buffer running low: {buffer_level}/{buffer.maxlen} chunks "
                                f"({buffer_level*50}ms / {buffer.maxlen*50}ms). "
                                "Audio source may be blocking or too slow."
                            )
                            self._last_buffer_warning = now_warn
                elif not buffer:
                    # Buffer empty - slow down to avoid busy loop
                    # Throttle error logging to avoid spam (max 1 per 30 seconds)
                    now_error = time.time()
                    if now_error - self._last_buffer_warning > 30.0:  # Increased from 10s to 30s
                        logger.error("Icecast buffer completely empty! Audio source starved.")
                        self._last_buffer_warning = now_error
                    time.sleep(0.05)  # Increased from 0.01s to 0.05s to reduce CPU usage

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
                        time.sleep(5.0)
                    continue

            except BrokenPipeError as exc:
                logger.error(f"Icecast FFmpeg pipe closed for mount {self.config.mount}: {exc}")
                logger.info(f"Waiting {ICECAST_RESTART_DELAY} seconds before restarting FFmpeg...")
                if not self._restart_ffmpeg("ffmpeg pipe closed"):
                    time.sleep(5.0)
            except OSError as exc:
                if exc.errno == errno.EPIPE:
                    logger.error(f"Icecast FFmpeg write EPIPE for mount {self.config.mount}: {exc}")
                    logger.info(f"Waiting {ICECAST_RESTART_DELAY} seconds before restarting FFmpeg...")
                    if not self._restart_ffmpeg("ffmpeg EPIPE"):
                        time.sleep(5.0)
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

        # Add delay before restart to prevent rapid restart cycles
        logger.info(f"Waiting {ICECAST_RESTART_DELAY} seconds before restarting FFmpeg for mount {self.config.mount}...")
        time.sleep(ICECAST_RESTART_DELAY)

        if self._stop_event.is_set():
            return False

        if self._start_ffmpeg():
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

            # Collapse extraneous whitespace (including newlines)
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
