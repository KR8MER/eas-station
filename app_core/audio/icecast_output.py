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
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

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
                '-ar', '22050',  # Sample rate
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

            # Add metadata
            cmd.extend([
                '-metadata', f'title={self.config.name}',
                '-metadata', f'artist=EAS Station',
                '-metadata', f'album={self.config.description}',
                '-metadata', f'genre={self.config.genre}',
            ])

            # Output to Icecast
            cmd.extend([
                '-content_type', 'audio/mpeg' if self.config.format == StreamFormat.MP3 else 'audio/ogg',
                '-ice_name', self.config.name,
                '-ice_description', self.config.description,
                '-ice_genre', self.config.genre,
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

        chunk_samples = int(22050 * 0.1)  # 100ms chunks at 22050 Hz

        while not self._stop_event.is_set():
            if not self._ffmpeg_process or self._ffmpeg_process.poll() is not None:
                # FFmpeg died, try to restart
                logger.warning("FFmpeg process died, restarting...")
                self._reconnect_count += 1

                if self._start_ffmpeg():
                    logger.info("FFmpeg restarted successfully")
                else:
                    logger.error("Failed to restart FFmpeg")
                    time.sleep(5.0)
                    continue

            try:
                # Read audio from source
                samples = self.audio_source.read_audio(chunk_samples)

                if samples is not None:
                    # Convert float32 [-1, 1] to int16 PCM
                    pcm_data = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)

                    # Write to FFmpeg stdin
                    if self._ffmpeg_process and self._ffmpeg_process.stdin:
                        self._ffmpeg_process.stdin.write(pcm_data.tobytes())
                        self._ffmpeg_process.stdin.flush()
                        self._bytes_sent += len(pcm_data.tobytes())
                else:
                    # No audio available, sleep briefly
                    time.sleep(0.01)

            except Exception as e:
                logger.error(f"Error feeding Icecast stream: {e}")
                time.sleep(1.0)

        logger.debug("Icecast feed loop stopped")

    def update_metadata(self, title: str, artist: str = "EAS Station") -> None:
        """
        Update stream metadata (requires Icecast admin API).

        Args:
            title: Stream title
            artist: Artist name
        """
        # TODO: Implement Icecast metadata update via admin API
        logger.info(f"Metadata update requested: {title} - {artist}")

    def get_stats(self) -> dict:
        """Get streaming statistics."""
        uptime = time.time() - self._start_time if self._start_time > 0 else 0

        return {
            'running': not self._stop_event.is_set(),
            'uptime_seconds': uptime,
            'bytes_sent': self._bytes_sent,
            'bitrate_kbps': (self._bytes_sent * 8 / 1000 / max(uptime, 1)),
            'reconnect_count': self._reconnect_count,
            'last_error': self._last_error,
            'server': self.config.server,
            'port': self.config.port,
            'mount': self.config.mount,
        }


__all__ = ['IcecastStreamer', 'IcecastConfig', 'StreamFormat']
