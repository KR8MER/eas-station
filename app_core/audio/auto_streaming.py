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
from types import SimpleNamespace
from typing import Dict, Optional, TYPE_CHECKING

from .icecast_output import IcecastConfig, IcecastStreamer, StreamFormat
from .mount_points import generate_mount_point, StreamFormat as MountStreamFormat

if TYPE_CHECKING:
    from .ingest import AudioIngestController

logger = logging.getLogger(__name__)

# Prefix used for per-source EAS ingest stream keys inside _streamers.
# A key looks like "_eas-ingest-<source_name>".
_EAS_INGEST_KEY_PREFIX = "_eas-ingest-"


class EASIngestShim:
    """
    Duck-type shim that exposes a source's 16 kHz EAS broadcast queue as
    a plain broadcast queue so IcecastStreamer can stream it without
    modification.

    IcecastStreamer calls ``audio_source.get_broadcast_queue()`` to subscribe
    to audio chunks and reads ``audio_source.config.sample_rate`` /
    ``audio_source.config.channels`` to configure FFmpeg.  This shim maps
    those calls onto the source's EAS-specific queue (pre-resampled 16 kHz
    float32 mono), giving Icecast clients an always-current view of exactly
    what the EAS decoder is processing.
    """

    def __init__(self, source_adapter):
        self._source = source_adapter
        # Expose the same config interface IcecastStreamer expects
        self.config = SimpleNamespace(sample_rate=16000, channels=1)

    def get_broadcast_queue(self):
        """Return the source's EAS (16 kHz) broadcast queue."""
        return self._source.get_eas_broadcast_queue()

    @property
    def status(self):
        """Mirror the underlying source's status for health checks."""
        return getattr(self._source, 'status', None)


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
        audio_controller: Optional['AudioIngestController'] = None,
        flask_app=None,
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
            flask_app: Flask application instance (used to read database settings
                       such as EASDecoderMonitorSettings from background threads)
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
        self._flask_app = flask_app

        # Active streamers: source_name -> IcecastStreamer
        self._streamers: Dict[str, IcecastStreamer] = {}
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

        # Stop all active streamers
        with self._lock:
            for source_name, streamer in list(self._streamers.items()):
                try:
                    streamer.stop()
                except Exception as e:
                    logger.error(f"Error stopping streamer for {source_name}: {e}")

            self._streamers.clear()

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

        # For StreamSourceAdapter with preserve_native_rate=True, FFmpeg detects
        # the actual sample rate asynchronously from its stderr output and updates
        # config.sample_rate only after parsing the stream info line.  That
        # detection happens *before* the first audio packet is delivered, so
        # waiting until _last_connection_time is set guarantees the rate in
        # config.sample_rate is correct.
        #
        # This wait is intentionally placed BEFORE acquiring self._lock so that
        # up to 5 seconds of blocking does not stall other lock holders.
        #
        # Without this wait, add_source() could read config.sample_rate = 44100
        # (the default) for a source that actually streams at 48000 Hz.  The
        # resulting IcecastConfig would tell FFmpeg ("-ar 44100") to interpret
        # 48000 Hz PCM as 44100 Hz, encoding an MP3 that plays at 91.9% speed —
        # making 10 minutes of audio take ~11 minutes.
        if hasattr(audio_source, '_last_connection_time'):  # StreamSourceAdapter
            deadline = time.time() + 5.0
            while time.time() < deadline and audio_source._last_connection_time is None:
                time.sleep(0.05)

        with self._lock:
            if source_name in self._streamers:
                logger.warning(f"Streamer for {source_name} already exists")
                return False

            try:
                # CRITICAL: Each Icecast stream outputs its OWN source's audio
                # at the source's NATIVE sample rate - DO NOT alter the stream!
                # Use the source's native sample rate and channels
                sample_rate = 44100  # Default
                if hasattr(audio_source, 'config') and hasattr(audio_source.config, 'sample_rate'):
                    sample_rate = audio_source.config.sample_rate
                elif hasattr(audio_source, 'sample_rate'):
                    sample_rate = audio_source.sample_rate

                channels = 2 if getattr(audio_source.config, 'channels', 1) > 1 else 1

                # Convert StreamFormat enum to MountStreamFormat enum
                mount_format = MountStreamFormat.MP3 if self.default_format == StreamFormat.MP3 else MountStreamFormat.OGG

                # Generate mount point using centralized logic
                mount_point = generate_mount_point(source_name, format=mount_format)

                config = IcecastConfig(
                    server=self.icecast_server,
                    port=self.icecast_port,
                    password=self.icecast_password,
                    mount=mount_point,
                    name=f"{source_name} - EAS Monitor",
                    description=f"Live stream from {source_name}",
                    genre="Emergency Alert System",
                    bitrate=bitrate or self.default_bitrate,
                    format=self.default_format,
                    public=False,
                    sample_rate=sample_rate,  # Use source's native sample rate
                    channels=channels,
                    admin_user=self.icecast_admin_user,
                    admin_password=self.icecast_admin_password,
                )

                # CRITICAL: Each Icecast stream subscribes to its OWN source's audio
                # via the source's BroadcastQueue. This ensures it gets an independent
                # copy of the audio without starving the EAS monitor or other consumers.
                # This ensures WNCI stream outputs WNCI audio, WIMT outputs WIMT audio, etc.
                logger.info(
                    f"Icecast stream '{source_name}' will subscribe to source "
                    f"at native {sample_rate} Hz (broadcast mode)"
                )

                # Create and start streamer with direct source access
                streamer = IcecastStreamer(config, audio_source)
                if streamer.start():
                    self._streamers[source_name] = streamer
                    logger.info(
                        f"Started Icecast stream for {source_name} at "
                        f"http://{self.icecast_server}:{self.icecast_port}{mount_point}"
                    )
                    return True
                else:
                    logger.error(f"Failed to start Icecast stream for {source_name}")
                    return False

            except Exception as e:
                logger.error(f"Error creating streamer for {source_name}: {e}")
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

            if not streamer:
                logger.warning(f"No streamer found for {source_name}")
                return False

            try:
                streamer.stop()
                logger.info(f"Stopped Icecast stream for {source_name}")
                return True
            except Exception as e:
                logger.error(f"Error stopping streamer for {source_name}: {e}")
                return False

    def get_stream_url(self, source_name: str) -> Optional[str]:
        """
        Get the Icecast stream URL for a source.

        Args:
            source_name: Name of the source

        Returns:
            Stream URL if source is streaming, None otherwise
        """
        with self._lock:
            streamer = self._streamers.get(source_name)
            if streamer:
                mount_point = getattr(streamer.config, 'mount', None)
                if mount_point:
                    return (
                        f"http://{self.icecast_server}:{self.icecast_port}{mount_point}"
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
            eas_ingest_streams = {}
            for key, streamer in self._streamers.items():
                if key.startswith(_EAS_INGEST_KEY_PREFIX):
                    source_name = key[len(_EAS_INGEST_KEY_PREFIX):]
                    eas_ingest_streams[source_name] = streamer.get_stats()
                else:
                    active_streams[key] = streamer.get_stats()

            return {
                "enabled": self.enabled,
                "server": f"{self.icecast_server}:{self.icecast_port}",
                "active_stream_count": len(self._streamers),
                "active_streams": active_streams,
                "eas_ingest_streams": eas_ingest_streams,
            }

    def is_available(self) -> bool:
        """
        Check if Icecast streaming is available.

        Returns:
            True if enabled and configured
        """
        return self.enabled and bool(self.icecast_password)

    def update_alert_metadata(
        self, title: str, artist: Optional[str] = "EAS Alert"
    ) -> int:
        """Override metadata on every active streamer with alert text.

        Returns the number of streamers that accepted the override.
        """
        if not title:
            return 0
        count = 0
        with self._lock:
            for key, streamer in self._streamers.items():
                try:
                    if streamer.update_alert_metadata(title, artist):
                        count += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to set alert metadata on %s: %s", key, exc
                    )
        return count

    def clear_alert_metadata(self) -> None:
        """Release the alert metadata override on every active streamer."""
        with self._lock:
            for key, streamer in self._streamers.items():
                try:
                    streamer.clear_alert_metadata()
                except Exception as exc:
                    logger.warning(
                        "Failed to clear alert metadata on %s: %s", key, exc
                    )

    def _add_eas_ingest_stream(self, source_name: str, source_adapter, mount_name: str = "eas-ingest") -> bool:
        """
        Create an Icecast stream for the EAS decoder input (16 kHz mono).

        The mount point is ``/{mount_name}.mp3`` where ``mount_name`` defaults to
        ``eas-ingest-{source_name}`` when only one argument is provided.  The
        stream carries the same 16 kHz float32 audio the EAS decoder processes,
        so operators can confirm what the decoder is hearing without needing CLI
        access.

        Args:
            source_name: Human-readable name of the underlying source (for logging).
            source_adapter: Running AudioSourceAdapter whose EAS queue to stream.
            mount_name: Mount name without leading slash or extension
                        (e.g. ``"eas-ingest-my-source"``).

        Returns:
            True if the stream started successfully.
        """
        eas_key = f"{_EAS_INGEST_KEY_PREFIX}{source_name}"
        try:
            shim = EASIngestShim(source_adapter)
            mount = f"/{mount_name}.mp3"
            config = IcecastConfig(
                server=self.icecast_server,
                port=self.icecast_port,
                password=self.icecast_password,
                mount=mount,
                name="EAS Decoder Input",
                description=f"16 kHz mono — what the EAS decoder hears (source: {source_name})",
                genre="Emergency Alert System",
                bitrate=48,          # 48 kbps is plenty for a 16 kHz mono diagnostic stream
                format=StreamFormat.MP3,
                public=False,
                sample_rate=16000,
                channels=1,
                admin_user=self.icecast_admin_user,
                admin_password=self.icecast_admin_password,
            )
            streamer = IcecastStreamer(config, shim)
            with self._lock:
                if eas_key in self._streamers:
                    return False  # Created concurrently, skip
                if streamer.start():
                    self._streamers[eas_key] = streamer
                    logger.info(
                        "✅ EAS ingest Icecast stream started: "
                        "http://%s:%s%s (from source '%s')",
                        self.icecast_server, self.icecast_port, mount, source_name,
                    )
                    return True
                else:
                    logger.error("Failed to start EAS ingest Icecast stream for '%s'", source_name)
                    return False
        except Exception as exc:
            logger.error("Error creating EAS ingest Icecast stream for '%s': %s", source_name, exc, exc_info=True)
            return False

    def _get_eas_monitor_settings(self):
        """Read EASDecoderMonitorSettings from the database.

        Returns ``(enabled, stream_name_prefix)`` where *stream_name_prefix* is
        the base name used to build per-source mount points.  Falls back to
        ``(False, "eas-ingest")`` when no Flask app context is available so that
        EAS ingest streams are **not** created by default.  They consume an
        Icecast source slot per audio source, so they must be explicitly enabled
        via the admin UI before they activate.
        """
        if not self._flask_app:
            return False, "eas-ingest"
        try:
            with self._flask_app.app_context():
                from app_core.models import EASDecoderMonitorSettings
                settings = EASDecoderMonitorSettings.query.first()
                if settings is None:
                    return False, "eas-ingest"
                prefix = (settings.stream_name or "eas-ingest").strip().lower().replace(" ", "-")
                return bool(settings.enabled), prefix
        except Exception as exc:
            logger.debug("Could not read EASDecoderMonitorSettings: %s", exc)
            return False, "eas-ingest"

    def _monitor_loop(self) -> None:
        """Monitor active streams, discover new sources, and handle reconnections."""
        logger.debug("Auto-streaming monitor loop started")

        while not self._stop_event.is_set():
            try:
                if self.audio_controller:
                    from .ingest import AudioSourceStatus

                    all_sources = self.audio_controller.get_all_sources()

                    # ── 1. Auto-discover RUNNING sources for native-rate streams ──
                    for source_name, source_adapter in all_sources.items():
                        with self._lock:
                            if source_name in self._streamers:
                                continue
                        if source_adapter.status == AudioSourceStatus.RUNNING:
                            try:
                                if self.add_source(source_name, source_adapter):
                                    logger.info(
                                        "Auto-discovered and added source '%s' "
                                        "to Icecast streaming",
                                        source_name,
                                    )
                            except Exception as exc:
                                logger.debug(
                                    "Failed to add auto-discovered source '%s': %s",
                                    source_name, exc,
                                )

                    # ── 2. Manage per-source EAS ingest streams ───────────────────
                    # Each running source gets its own 16 kHz monitoring mount so
                    # operators can verify what every decoder channel is hearing.
                    eas_enabled, eas_prefix = self._get_eas_monitor_settings()

                    for source_name, source_adapter in all_sources.items():
                        eas_key = f"{_EAS_INGEST_KEY_PREFIX}{source_name}"
                        with self._lock:
                            already_active = eas_key in self._streamers

                        if source_adapter.status == AudioSourceStatus.RUNNING and hasattr(
                            source_adapter, 'get_eas_broadcast_queue'
                        ):
                            if eas_enabled and not already_active:
                                # Sanitise source name for use in a mount path
                                from .mount_points import sanitize_mount_name
                                safe_name = sanitize_mount_name(source_name)
                                mount_name = f"{eas_prefix}-{safe_name}"
                                self._add_eas_ingest_stream(source_name, source_adapter, mount_name)
                            elif not eas_enabled and already_active:
                                # Monitor was disabled while stream was running
                                logger.info(
                                    "EAS decoder monitor disabled — stopping ingest stream for '%s'",
                                    source_name,
                                )
                                self.remove_source(eas_key)

                    # ── 3. Remove EAS ingest streams for stopped/removed sources ──
                    with self._lock:
                        eas_keys = [k for k in self._streamers if k.startswith(_EAS_INGEST_KEY_PREFIX)]
                    for eas_key in eas_keys:
                        src = eas_key[len(_EAS_INGEST_KEY_PREFIX):]
                        source_adapter = all_sources.get(src)
                        if not source_adapter or source_adapter.status != AudioSourceStatus.RUNNING:
                            logger.info(
                                "EAS ingest source '%s' no longer running — "
                                "stopping EAS ingest stream",
                                src,
                            )
                            self.remove_source(eas_key)

                    # ── 4. Health-check all streamers and auto-reconnect dead ones ──
                    with self._lock:
                        for sn, streamer in list(self._streamers.items()):
                            if not streamer.get_stats().get("running", False):
                                logger.warning(
                                    "Streamer for '%s' stopped unexpectedly – will remove "
                                    "so it gets recreated on next cycle", sn
                                )
                                # Remove now; the discovery step above will recreate it
                                # on the next monitor-loop iteration when the source is
                                # still RUNNING.
                                try:
                                    streamer.stop()
                                except Exception:
                                    pass
                                self._streamers.pop(sn, None)

                        # ── 5. Remove native-rate streamers for stopped sources ──
                        # Only collect names here; remove_source() re-acquires
                        # self._lock, which is non-reentrant — calling it while
                        # still inside this `with` block self-deadlocks this
                        # thread (and every other caller of get_status(), which
                        # includes the metrics loop that publishes the Redis
                        # heartbeat the whole web UI's health status depends on).
                        stale_sources = []
                        if self.audio_controller:
                            for source_name in list(self._streamers.keys()):
                                if source_name.startswith(_EAS_INGEST_KEY_PREFIX):
                                    continue  # Lifecycle managed above in steps 2–3
                                source_adapter = all_sources.get(source_name)
                                if (
                                    not source_adapter
                                    or source_adapter.status != AudioSourceStatus.RUNNING
                                ):
                                    stale_sources.append(source_name)

                    # Remove outside the lock — see comment above.
                    for source_name in stale_sources:
                        logger.info(
                            "Removing Icecast stream for '%s' "
                            "(source stopped or removed)",
                            source_name,
                        )
                        self.remove_source(source_name)

                time.sleep(10.0)

            except Exception as exc:
                logger.error("Error in auto-streaming monitor loop: %s", exc)
                time.sleep(5.0)

        logger.debug("Auto-streaming monitor loop stopped")


__all__ = ['AutoStreamingService', 'EASIngestShim', '_EAS_INGEST_KEY_PREFIX']
