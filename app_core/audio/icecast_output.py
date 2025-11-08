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
    admin_user: Optional[str] = None
    admin_password: Optional[str] = None
    metadata_poll_interval: float = 1.0


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

        # Start FFmpeg encoder
        if not self._start_ffmpeg():
            return False

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
        logger.info("Stopping Icecast streamer")
        self._stop_event.set()

        # Stop FFmpeg
        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=5.0)
            except Exception:
                try:
                    self._ffmpeg_process.kill()
                except Exception:
                    pass
            self._ffmpeg_process = None

        # Wait for feeder thread
        if self._feeder_thread:
            self._feeder_thread.join(timeout=5.0)

        logger.info("Stopped Icecast streamer")

    def _start_ffmpeg(self) -> bool:
        """Start FFmpeg encoder and Icecast streamer."""
        try:
            # Build Icecast URL
            icecast_url = (
                f"icecast://source:{self.config.password}@"
                f"{self.config.server}:{self.config.port}/{self.config.mount}"
            )

            # FFmpeg command to encode and stream
            cmd = [
                'ffmpeg',
                '-f', 's16le',  # Input: 16-bit PCM
                '-ar', str(self.config.sample_rate),  # Sample rate
                '-ac', '1',      # Mono
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

            # Output to Icecast
            cmd.extend([
                '-content_type', 'audio/mpeg' if self.config.format == StreamFormat.MP3 else 'audio/ogg',
                '-ice_name', stream_name,
                '-ice_description', stream_description,
                '-ice_genre', stream_genre,
                icecast_url
            ])

            logger.info(f"Starting FFmpeg Icecast streamer: {' '.join(cmd[:10])}...")

            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=8192
            )

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
        buffer = deque(maxlen=200)  # Up to 10 seconds of audio (200 * 50ms chunks)
        prebuffer_target = 20  # Pre-fill with 1 second before starting (reduced for faster startup)

        logger.info(f"Pre-buffering {prebuffer_target} chunks (~1 second) for smooth Icecast streaming")
        prebuffer_timeout = time.time() + 10.0  # 10 seconds max to prebuffer

        while len(buffer) < prebuffer_target and time.time() < prebuffer_timeout:
            samples = self.audio_source.get_audio_chunk(timeout=0.5)
            if samples is not None:
                pcm_data = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
                buffer.append(pcm_data.tobytes())

        if len(buffer) < prebuffer_target:
            logger.warning(f"Pre-buffer timeout: only filled {len(buffer)}/{prebuffer_target} chunks (~{len(buffer)*50}ms of audio)")
        else:
            logger.info(f"Pre-buffer complete: {len(buffer)} chunks (~{len(buffer)*50}ms of audio)")

        while not self._stop_event.is_set():
            if not self._ffmpeg_process or self._ffmpeg_process.poll() is not None:
                # FFmpeg died, try to get error output
                stderr_output = None
                if self._ffmpeg_process and self._ffmpeg_process.stderr:
                    try:
                        stderr_output = self._ffmpeg_process.stderr.read().decode('utf-8', errors='replace')
                    except Exception as e:
                        logger.debug(f"Could not read FFmpeg stderr: {e}")

                if stderr_output:
                    logger.error(f"FFmpeg process died with error:\n{stderr_output}")
                else:
                    logger.warning("FFmpeg process died (no error output available)")

                self._reconnect_count += 1

                if self._start_ffmpeg():
                    logger.info("FFmpeg restarted successfully")
                else:
                    logger.error("Failed to restart FFmpeg")
                    time.sleep(5.0)
                    continue

            try:
                # Read audio from source and add to buffer
                samples = self.audio_source.get_audio_chunk(timeout=0.1)

                if samples is not None:
                    # Convert float32 [-1, 1] to int16 PCM
                    pcm_data = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
                    buffer.append(pcm_data.tobytes())

                # Feed FFmpeg from buffer (always try to send, even if we just got None)
                # This keeps FFmpeg fed even when source is temporarily slow
                if buffer and self._ffmpeg_process and self._ffmpeg_process.stdin:
                    chunk = buffer.popleft()
                    self._ffmpeg_process.stdin.write(chunk)
                    self._ffmpeg_process.stdin.flush()
                    self._bytes_sent += len(chunk)
                elif not buffer:
                    # Buffer empty - slow down to avoid busy loop
                    time.sleep(0.01)

                now = time.time()
                if now - self._last_metadata_check >= self._metadata_poll_interval:
                    self._last_metadata_check = now
                    self._maybe_update_metadata()

            except Exception as e:
                logger.error(f"Error feeding Icecast stream: {e}")
                time.sleep(1.0)

        logger.debug("Icecast feed loop stopped")

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

        title, artist = payload
        cache_key = (title or "", artist)
        if self._last_metadata_payload == cache_key:
            return

        try:
            sent_value = self._send_metadata_update(title or self.config.name, artist)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Unable to update Icecast metadata for %s: %s\nTraceback:\n%s",
                self.config.mount,
                exc,
                ''.join(traceback.format_tb(exc.__traceback__)),
            )
            self._last_error = str(exc)
            return

        if sent_value:
            self._last_metadata_payload = cache_key
            self._last_metadata_song = sent_value

    def _extract_metadata_fields(
        self,
        metadata: Dict[str, Any]
    ) -> Optional[Tuple[Optional[str], Optional[str]]]:
        """Derive title/artist information from source metadata."""

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

        return title, artist

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

    def _send_metadata_update(self, title: str, artist: Optional[str]) -> Optional[str]:
        """Submit metadata to Icecast and return the formatted payload on success."""
        if not (self.config.admin_user and self.config.admin_password):
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

        # HTTP Basic Auth requires ASCII/latin-1 encoding
        # Sanitize credentials to prevent encoding errors
        try:
            auth_user = str(self.config.admin_user or '').encode('latin-1').decode('latin-1')
            auth_pass = str(self.config.admin_password or '').encode('latin-1').decode('latin-1')
        except UnicodeEncodeError:
            # If credentials contain non-latin-1 characters, use ASCII subset
            auth_user = str(self.config.admin_user or '').encode('ascii', 'replace').decode('ascii')
            auth_pass = str(self.config.admin_password or '').encode('ascii', 'replace').decode('ascii')
            logger.warning(
                "Icecast admin credentials contain non-ASCII characters for %s, using fallback encoding",
                self.config.mount,
            )

        try:
            # Make the HTTP GET request with the pre-encoded URL
            response = requests.get(
                url,
                auth=(auth_user, auth_pass),
                timeout=5.0,
            )
        except requests_exceptions.RequestException as exc:
            logger.warning(
                "Failed to update Icecast metadata for %s: %s",
                self.config.mount,
                exc,
            )
            self._last_error = str(exc)
            return None

        if response.status_code == 200:
            logger.info(
                "Updated Icecast metadata for %s: %s",
                self.config.mount,
                song_value,
            )
            return song_value

        logger.warning(
            "Icecast metadata update returned %s for %s: %s",
            response.status_code,
            self.config.mount,
            response.text.strip()[:200],
        )
        self._last_error = f"metadata update failed ({response.status_code})"
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
        }


__all__ = ['IcecastStreamer', 'IcecastConfig', 'StreamFormat']
