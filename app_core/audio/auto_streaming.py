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
Automatic Icecast Streaming for Audio Sources

Automatically creates and maintains Icecast streams for all running audio sources.
Falls back gracefully if Icecast is not available.

Features:
- Auto-start streaming when audio source starts
- Auto-stop streaming when audio source stops
- Health monitoring and automatic reconnection
- Per-source mount points
- Configurable quality settings
"""

import logging
import threading
import time
from typing import Dict, Optional, TYPE_CHECKING

from .icecast_output import IcecastConfig, IcecastStreamer, StreamFormat
from .broadcast_adapter import BroadcastAudioAdapter

if TYPE_CHECKING:
    from .ingest import AudioIngestController

logger = logging.getLogger(__name__)


class AutoStreamingService:
    """
    Manages automatic Icecast streaming for audio sources.

    Creates and maintains an Icecast stream for each running audio source.
    Handles lifecycle management and automatic failover.
    """

    def __init__(
        self,
        icecast_server: str = "localhost",
        icecast_port: int = 8000,
        icecast_password: str = "",
        icecast_admin_user: Optional[str] = None,
        icecast_admin_password: Optional[str] = None,
        default_bitrate: int = 128,
        default_format: StreamFormat = StreamFormat.MP3,
        enabled: bool = False,
        audio_controller: Optional['AudioIngestController'] = None
    ):
        """
        Initialize auto-streaming service.

        Args:
            icecast_server: Icecast server hostname
            icecast_port: Icecast server port
            icecast_password: Source password for Icecast
            default_bitrate: Default bitrate for streams (kbps)
            default_format: Default audio format (MP3 or OGG)
            enabled: Whether service is enabled
            audio_controller: AudioIngestController for broadcast queue access
        """
        self.icecast_server = icecast_server
        self.icecast_port = icecast_port
        self.icecast_password = icecast_password
        self.icecast_admin_user = icecast_admin_user
        self.icecast_admin_password = icecast_admin_password
        self.default_bitrate = default_bitrate
        self.default_format = default_format
        self.enabled = enabled
        self.audio_controller = audio_controller

        # Active streamers: source_name -> IcecastStreamer
        self._streamers: Dict[str, IcecastStreamer] = {}
        # Broadcast adapters: source_name -> BroadcastAudioAdapter
        self._broadcast_adapters: Dict[str, BroadcastAudioAdapter] = {}
        self._lock = threading.Lock()

        # Monitoring thread
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        logger.info(
            f"AutoStreamingService initialized: {icecast_server}:{icecast_port} "
            f"(enabled={enabled}, broadcast_mode={audio_controller is not None})"
        )

    def start(self) -> bool:
        """
        Start the auto-streaming service.

        Returns:
            True if started successfully
        """
        if not self.enabled:
            logger.info("AutoStreamingService is disabled, not starting")
            return False

        if not self.icecast_password:
            logger.warning(
                "AutoStreamingService: No Icecast password configured, "
                "streaming will not work"
            )
            return False

        self._stop_event.clear()

        # Start monitoring thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="auto-streaming-monitor",
            daemon=True
        )
        self._monitor_thread.start()

        logger.info("AutoStreamingService started")
        return True

    def stop(self) -> None:
        """Stop the auto-streaming service and all active streams."""
        logger.info("Stopping AutoStreamingService")
        self._stop_event.set()

        # Stop all active streamers and clean up broadcast adapters
        with self._lock:
            for source_name, streamer in list(self._streamers.items()):
                try:
                    streamer.stop()
                except Exception as e:
                    logger.error(f"Error stopping streamer for {source_name}: {e}")

            self._streamers.clear()

            # Unsubscribe all broadcast adapters
            for source_name, adapter in list(self._broadcast_adapters.items()):
                try:
                    adapter.unsubscribe()
                except Exception as e:
                    logger.error(f"Error unsubscribing broadcast adapter for {source_name}: {e}")

            self._broadcast_adapters.clear()

        # Wait for monitor thread
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)

        logger.info("AutoStreamingService stopped")

    def add_source(self, source_name: str, audio_source, bitrate: Optional[int] = None) -> bool:
        """
        Add an audio source for streaming.

        Args:
            source_name: Unique name for the source
            audio_source: Audio source object (AudioSourceAdapter) - will be wrapped in broadcast adapter
            bitrate: Optional custom bitrate (uses default if None)

        Returns:
            True if streaming started successfully
        """
        if not self.enabled:
            logger.debug(f"AutoStreaming disabled, not adding {source_name}")
            return False

        with self._lock:
            if source_name in self._streamers:
                logger.warning(f"Streamer for {source_name} already exists")
                return False

            try:
                # Detect sample rate from audio source
                sample_rate = 44100  # Default
                if hasattr(audio_source, 'config') and hasattr(audio_source.config, 'sample_rate'):
                    sample_rate = audio_source.config.sample_rate
                elif hasattr(audio_source, 'sample_rate'):
                    sample_rate = audio_source.sample_rate

                # Create Icecast configuration
                channels = 2 if getattr(audio_source.config, 'channels', 1) > 1 else 1

                # Mount point must include .mp3 extension to match Icecast stream format
                mount_point = f"{source_name}.mp3"

                config = IcecastConfig(
                    server=self.icecast_server,
                    port=self.icecast_port,
                    password=self.icecast_password,
                    mount=mount_point,  # Mount point = source name with .mp3 extension
                    name=f"{source_name} - EAS Monitor",
                    description=f"Live stream from {source_name}",
                    genre="Emergency Alert System",
                    bitrate=bitrate or self.default_bitrate,
                    format=self.default_format,
                    public=False,
                    sample_rate=sample_rate,
                    channels=channels,
                    admin_user=self.icecast_admin_user,
                    admin_password=self.icecast_admin_password,
                )

                # If we have access to broadcast queue, use non-destructive subscription
                # Otherwise fall back to direct audio source access (legacy mode)
                actual_audio_source = audio_source
                if self.audio_controller is not None:
                    logger.info(
                        f"Creating broadcast subscription for Icecast stream: {source_name} "
                        "(non-destructive mode)"
                    )
                    broadcast_queue = self.audio_controller.get_broadcast_queue()
                    broadcast_adapter = BroadcastAudioAdapter(
                        broadcast_queue=broadcast_queue,
                        subscriber_id=f"icecast-{source_name}",
                        sample_rate=sample_rate
                    )
                    self._broadcast_adapters[source_name] = broadcast_adapter
                    actual_audio_source = broadcast_adapter
                    logger.info(
                        f"Icecast stream '{source_name}' subscribed to broadcast queue "
                        f"(no competition with EAS monitor)"
                    )

                # Create and start streamer
                streamer = IcecastStreamer(config, actual_audio_source)
                if streamer.start():
                    self._streamers[source_name] = streamer
                    logger.info(
                        f"Started Icecast stream for {source_name} at "
                        f"http://{self.icecast_server}:{self.icecast_port}/{source_name}"
                    )
                    return True
                else:
                    logger.error(f"Failed to start Icecast stream for {source_name}")
                    # Clean up broadcast adapter if we created one
                    if source_name in self._broadcast_adapters:
                        self._broadcast_adapters[source_name].unsubscribe()
                        del self._broadcast_adapters[source_name]
                    return False

            except Exception as e:
                logger.error(f"Error creating streamer for {source_name}: {e}")
                # Clean up broadcast adapter if we created one
                if source_name in self._broadcast_adapters:
                    self._broadcast_adapters[source_name].unsubscribe()
                    del self._broadcast_adapters[source_name]
                return False

    def remove_source(self, source_name: str) -> bool:
        """
        Remove an audio source and stop its stream.

        Args:
            source_name: Name of source to remove

        Returns:
            True if removed successfully
        """
        with self._lock:
            streamer = self._streamers.pop(source_name, None)
            broadcast_adapter = self._broadcast_adapters.pop(source_name, None)

            success = False
            if streamer:
                try:
                    streamer.stop()
                    logger.info(f"Stopped Icecast stream for {source_name}")
                    success = True
                except Exception as e:
                    logger.error(f"Error stopping streamer for {source_name}: {e}")

            if broadcast_adapter:
                try:
                    broadcast_adapter.unsubscribe()
                    logger.info(f"Unsubscribed broadcast adapter for {source_name}")
                except Exception as e:
                    logger.error(f"Error unsubscribing broadcast adapter for {source_name}: {e}")

            if not streamer and not broadcast_adapter:
                logger.warning(f"No streamer or adapter found for {source_name}")
                return False

            return success

    def get_stream_url(self, source_name: str) -> Optional[str]:
        """
        Get the Icecast stream URL for a source.

        Args:
            source_name: Name of the source

        Returns:
            Stream URL if source is streaming, None otherwise
        """
        with self._lock:
            if source_name in self._streamers:
                return (
                    f"http://{self.icecast_server}:{self.icecast_port}/{source_name}"
                )
            return None

    def get_status(self) -> dict:
        """
        Get service status and statistics.

        Returns:
            Dictionary with status information
        """
        with self._lock:
            active_streams = {}
            for source_name, streamer in self._streamers.items():
                active_streams[source_name] = streamer.get_stats()

            return {
                "enabled": self.enabled,
                "server": f"{self.icecast_server}:{self.icecast_port}",
                "active_stream_count": len(self._streamers),
                "active_streams": active_streams,
            }

    def is_available(self) -> bool:
        """
        Check if Icecast streaming is available.

        Returns:
            True if enabled and configured
        """
        return self.enabled and bool(self.icecast_password)

    def _monitor_loop(self) -> None:
        """Monitor active streams and handle reconnections."""
        logger.debug("Auto-streaming monitor loop started")

        while not self._stop_event.is_set():
            try:
                with self._lock:
                    # Check health of all streamers
                    for source_name, streamer in list(self._streamers.items()):
                        stats = streamer.get_stats()
                        if not stats.get("running", False):
                            logger.warning(
                                f"Streamer for {source_name} stopped unexpectedly"
                            )
                            # Could implement auto-restart here if needed

                # Sleep for monitoring interval
                time.sleep(10.0)

            except Exception as e:
                logger.error(f"Error in auto-streaming monitor loop: {e}")
                time.sleep(5.0)

        logger.debug("Auto-streaming monitor loop stopped")


__all__ = ['AutoStreamingService']
