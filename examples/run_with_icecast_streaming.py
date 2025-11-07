#!/usr/bin/env python3
"""
Example: Run EAS Monitoring with Icecast Streaming

Demonstrates how to integrate the professional audio subsystem with
both EAS monitoring and Icecast network streaming for audio rebroadcast.

This shows the complete pipeline:
  Audio Sources → Source Manager → EAS Monitor → Alert Detection
                              ↓
                    Icecast Streamer → Network Clients

Features:
- Multiple audio sources with automatic failover
- Continuous EAS/SAME alert monitoring
- Live audio streaming to Icecast server
- Real-time health monitoring and statistics
"""

import logging
import signal
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.source_manager import AudioSourceManager, AudioSourceConfig
from app_core.audio.eas_monitor import ContinuousEASMonitor, EASAlert
from app_core.audio.icecast_output import IcecastStreamer, IcecastConfig, StreamFormat

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def on_alert_detected(alert: EASAlert):
    """Callback when EAS alert is detected."""
    print("=" * 70)
    print("🚨 EAS ALERT DETECTED!")
    print("=" * 70)
    print(f"Time: {alert.timestamp}")
    print(f"Source: {alert.source_name}")
    print(f"Raw Text: {alert.raw_text}")
    print(f"Confidence: {alert.confidence:.1%}")
    print(f"Duration: {alert.duration_seconds:.1f}s")

    if alert.headers:
        for i, header in enumerate(alert.headers, 1):
            print(f"\nHeader {i}:")
            if 'fields' in header:
                fields = header['fields']
                print(f"  Originator: {fields.get('originator', 'Unknown')}")
                print(f"  Event: {fields.get('event_code', 'Unknown')}")
                print(f"  Locations: {fields.get('locations', [])}")

    if alert.audio_file_path:
        print(f"\nAudio saved to: {alert.audio_file_path}")

    print("=" * 70)


def on_failover(event):
    """Callback when audio source failover occurs."""
    logger.warning(
        f"🔄 FAILOVER: {event.from_source or 'none'} → {event.to_source} "
        f"({event.reason.value})"
    )


def main():
    """Run EAS monitoring with Icecast streaming."""
    print("=" * 70)
    print("EAS Monitoring + Icecast Streaming System")
    print("Professional Audio Subsystem Integration")
    print("=" * 70)

    # ========================================================================
    # STEP 1: Create and Configure Audio Source Manager
    # ========================================================================
    logger.info("Creating audio source manager...")
    manager = AudioSourceManager(
        sample_rate=22050,
        master_buffer_seconds=5.0,
        failover_callback=on_failover
    )

    # Add audio sources (configure these for your environment)
    logger.info("Adding audio sources...")

    # Primary: HTTP Stream
    manager.add_source(AudioSourceConfig(
        name="primary-stream",
        source_url="http://stream.example.com/noaa.mp3",  # Replace with actual stream
        priority=10,  # Highest priority
        enabled=True,
        sample_rate=22050,
        silence_threshold_db=-50.0,
        silence_duration_seconds=10.0
    ))

    # Backup: Different HTTP Stream
    manager.add_source(AudioSourceConfig(
        name="backup-stream",
        source_url="http://backup.example.com/noaa.mp3",  # Replace with actual stream
        priority=20,  # Lower priority (backup)
        enabled=True,
        sample_rate=22050
    ))

    # Start audio manager
    logger.info("Starting audio source manager...")
    if not manager.start():
        logger.error("Failed to start audio manager!")
        return 1

    # ========================================================================
    # STEP 2: Create and Start EAS Monitor
    # ========================================================================
    logger.info("Creating EAS monitor...")
    eas_monitor = ContinuousEASMonitor(
        audio_manager=manager,
        buffer_duration=120.0,  # 2 minute rolling buffer
        scan_interval=2.0,  # Scan every 2 seconds
        sample_rate=22050,
        alert_callback=on_alert_detected,
        save_audio_files=True,
        audio_archive_dir="/tmp/eas-alerts"
    )

    logger.info("Starting continuous EAS monitoring...")
    if not eas_monitor.start():
        logger.error("Failed to start EAS monitor!")
        manager.stop()
        return 1

    # ========================================================================
    # STEP 3: Create and Start Icecast Streaming
    # ========================================================================
    logger.info("Creating Icecast streamer...")

    # Configure Icecast connection
    # IMPORTANT: Replace these with your actual Icecast server settings
    icecast_config = IcecastConfig(
        server="localhost",  # Icecast server hostname/IP
        port=8000,          # Icecast server port
        password="hackme",  # Source password (change this!)
        mount="eas-monitor.mp3",  # Mount point name
        name="EAS Monitor Station",
        description="Live EAS/SAME Alert Monitoring",
        genre="Emergency",
        bitrate=128,        # 128 kbps MP3
        format=StreamFormat.MP3,
        public=False        # Don't list in directory
    )

    # Create streamer connected to the same audio source manager
    icecast_streamer = IcecastStreamer(
        config=icecast_config,
        audio_source=manager  # Share the same audio manager
    )

    logger.info("Starting Icecast streaming...")
    if not icecast_streamer.start():
        logger.warning("Failed to start Icecast streaming (continuing without it)")
        icecast_streamer = None
    else:
        logger.info(f"Icecast stream available at: http://{icecast_config.server}:{icecast_config.port}/{icecast_config.mount}")

    # ========================================================================
    # STEP 4: Run Main Loop with Status Monitoring
    # ========================================================================
    print("\n✅ System running!")
    print(f"Active source: {manager.get_active_source()}")
    print(f"EAS buffer: 120s, scan interval: 2s")
    if icecast_streamer:
        print(f"Icecast stream: http://{icecast_config.server}:{icecast_config.port}/{icecast_config.mount}")
    print("\nMonitoring for EAS alerts... (Press Ctrl+C to stop)\n")

    # Setup signal handler for graceful shutdown
    def signal_handler(sig, frame):
        print("\n\nShutting down...")
        if icecast_streamer:
            icecast_streamer.stop()
        eas_monitor.stop()
        manager.stop()
        print("Stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Main loop - print stats periodically
    try:
        while True:
            time.sleep(30)  # Print stats every 30 seconds

            # Get stats
            eas_stats = eas_monitor.get_stats()
            source_metrics = manager.get_all_metrics()

            print("\n" + "=" * 70)
            print("STATUS REPORT")
            print("=" * 70)
            print(f"Active Source: {eas_stats['active_source']}")
            print(f"EAS Scans: {eas_stats['scans_performed']}")
            print(f"Alerts Detected: {eas_stats['alerts_detected']}")

            if icecast_streamer:
                icecast_stats = icecast_streamer.get_stats()
                print(f"\nIcecast Streaming:")
                print(f"  Status: {'Running' if icecast_stats['running'] else 'Stopped'}")
                print(f"  Uptime: {icecast_stats['uptime_seconds']:.0f}s")
                print(f"  Bitrate: {icecast_stats['bitrate_kbps']:.1f} kbps")
                print(f"  Reconnects: {icecast_stats['reconnect_count']}")

            print("\nSource Health:")
            for name, metrics in source_metrics.items():
                print(f"  {name}: {metrics.health.value} "
                      f"(restarts: {metrics.restart_count}, "
                      f"uptime: {metrics.uptime_seconds:.0f}s, "
                      f"buffer: {metrics.buffer_fill_percentage:.1f}%)")

            print("=" * 70)

    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
