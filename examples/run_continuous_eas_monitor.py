#!/usr/bin/env python3
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

"""
Example: Run Continuous EAS Monitoring

Demonstrates how to integrate the professional audio subsystem with
the EAS decoder for 24/7 alert monitoring.

This shows the complete pipeline:
  Audio Sources → Source Manager → EAS Monitor → Alert Detection
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
    """Run continuous EAS monitoring."""
    print("=" * 70)
    print("Continuous EAS Monitoring System")
    print("Professional Audio Subsystem + EAS Decoder Integration")
    print("=" * 70)

    # Create audio source manager
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

    # Note: You can also add SDR or ALSA sources:
    # manager.add_source(AudioSourceConfig(
    #     name="rtlsdr-162.55",
    #     source_url="/dev/rtlsdr0",
    #     priority=30,
    #     enabled=True,
    #     sample_rate=22050
    # ))

    # Start audio manager
    logger.info("Starting audio source manager...")
    if not manager.start():
        logger.error("Failed to start audio manager!")
        return 1

    # Create EAS monitor
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

    # Start EAS monitoring
    logger.info("Starting continuous EAS monitoring...")
    if not eas_monitor.start():
        logger.error("Failed to start EAS monitor!")
        manager.stop()
        return 1

    print("\n✅ System running!")
    print(f"Active source: {manager.get_active_source()}")
    print(f"Buffer duration: 120s")
    print(f"Scan interval: 2s")
    print("\nMonitoring for EAS alerts... (Press Ctrl+C to stop)\n")

    # Setup signal handler for graceful shutdown
    def signal_handler(sig, frame):
        print("\n\nShutting down...")
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
            print(f"Scans Performed: {eas_stats['scans_performed']}")
            print(f"Alerts Detected: {eas_stats['alerts_detected']}")

            print("\nSource Health:")
            for name, metrics in source_metrics.items():
                print(f"  {name}: {metrics.health.value} "
                      f"(restarts: {metrics.restart_count}, "
                      f"uptime: {metrics.uptime_seconds:.0f}s)")

            print("=" * 70)

    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
