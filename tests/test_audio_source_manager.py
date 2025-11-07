"""
Integration tests for AudioSourceManager

Tests multi-source management, failover logic, and end-to-end audio pipeline.
"""

import pytest
import numpy as np
import time
import threading
from unittest.mock import Mock, patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.source_manager import (
    AudioSourceManager,
    AudioSourceConfig,
    FailoverReason,
    FailoverEvent
)
from app_core.audio.ffmpeg_source import FFmpegAudioSource, SourceHealth


class MockFFmpegSource:
    """Mock FFmpeg source for testing."""

    def __init__(self, name: str, health: SourceHealth = SourceHealth.HEALTHY):
        self.name = name
        self._health = health
        self._running = False
        self._read_count = 0
        self._restart_count = 0
        self._uptime = 0.0

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self):
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def read_audio(self, num_samples: int, timeout: float = 0.1):
        """Return mock audio samples."""
        if not self._running or self._health == SourceHealth.FAILED:
            return None

        self._read_count += 1

        # Return silence or tone based on health
        if self._health == SourceHealth.HEALTHY:
            # Return a simple tone
            t = np.linspace(0, num_samples / 22050, num_samples)
            samples = 0.1 * np.sin(2 * np.pi * 440 * t)
            return samples.astype(np.float32)
        elif self._health == SourceHealth.DEGRADED:
            # Return some audio but inconsistent
            if self._read_count % 3 == 0:
                return None
            t = np.linspace(0, num_samples / 22050, num_samples)
            samples = 0.05 * np.sin(2 * np.pi * 440 * t)
            return samples.astype(np.float32)
        else:
            return None

    def get_metrics(self):
        """Return mock metrics."""
        return MagicMock(
            health=self._health,
            is_running=self._running,
            samples_read=self._read_count * 2205,
            restart_count=self._restart_count,
            uptime_seconds=self._uptime,
            buffer_fill_percentage=50.0,
            last_error=None if self._health != SourceHealth.FAILED else "Mock failure"
        )

    def set_health(self, health: SourceHealth):
        """Change health status for testing."""
        self._health = health


class TestAudioSourceManager:
    """Test suite for AudioSourceManager."""

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_initialization(self, mock_ffmpeg_class):
        """Test manager initialization."""
        manager = AudioSourceManager(sample_rate=22050)

        assert manager.sample_rate == 22050
        assert manager.get_active_source() is None
        assert len(manager.get_all_metrics()) == 0

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_add_source(self, mock_ffmpeg_class):
        """Test adding audio sources."""
        # Setup mock
        mock_source = MockFFmpegSource("test-source")
        mock_ffmpeg_class.return_value = mock_source

        manager = AudioSourceManager(sample_rate=22050)

        # Add source
        config = AudioSourceConfig(
            name="test-source",
            source_url="http://example.com/stream",
            priority=10,
            enabled=True,
            sample_rate=22050
        )

        result = manager.add_source(config)
        assert result is True

        # Verify source was added
        metrics = manager.get_all_metrics()
        assert "test-source" in metrics

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_duplicate_source_rejected(self, mock_ffmpeg_class):
        """Test that duplicate source names are rejected."""
        mock_source = MockFFmpegSource("test-source")
        mock_ffmpeg_class.return_value = mock_source

        manager = AudioSourceManager(sample_rate=22050)

        config = AudioSourceConfig(
            name="test-source",
            source_url="http://example.com/stream",
            priority=10,
            enabled=True
        )

        # First add should succeed
        assert manager.add_source(config) is True

        # Second add with same name should fail
        assert manager.add_source(config) is False

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_start_activates_highest_priority(self, mock_ffmpeg_class):
        """Test that starting manager activates highest priority source."""
        # Create mock sources
        source1 = MockFFmpegSource("source-1", SourceHealth.HEALTHY)
        source2 = MockFFmpegSource("source-2", SourceHealth.HEALTHY)

        def create_mock(config, **kwargs):
            if config.name == "source-1":
                return source1
            return source2

        mock_ffmpeg_class.side_effect = create_mock

        manager = AudioSourceManager(sample_rate=22050)

        # Add sources (lower priority number = higher priority)
        manager.add_source(AudioSourceConfig(
            name="source-1",
            source_url="http://example.com/primary",
            priority=10,  # Higher priority
            enabled=True
        ))

        manager.add_source(AudioSourceConfig(
            name="source-2",
            source_url="http://example.com/backup",
            priority=20,  # Lower priority
            enabled=True
        ))

        # Start manager
        manager.start()
        time.sleep(0.1)  # Give thread time to activate

        # Should activate highest priority (lowest number)
        assert manager.get_active_source() == "source-1"

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_failover_on_source_failure(self, mock_ffmpeg_class):
        """Test automatic failover when active source fails."""
        source1 = MockFFmpegSource("source-1", SourceHealth.HEALTHY)
        source2 = MockFFmpegSource("source-2", SourceHealth.HEALTHY)

        def create_mock(config, **kwargs):
            if config.name == "source-1":
                return source1
            return source2

        mock_ffmpeg_class.side_effect = create_mock

        # Track failover events
        failover_events = []

        def on_failover(event):
            failover_events.append(event)

        manager = AudioSourceManager(
            sample_rate=22050,
            failover_callback=on_failover
        )

        # Add sources
        manager.add_source(AudioSourceConfig(
            name="source-1",
            source_url="http://example.com/primary",
            priority=10,
            enabled=True
        ))

        manager.add_source(AudioSourceConfig(
            name="source-2",
            source_url="http://example.com/backup",
            priority=20,
            enabled=True
        ))

        # Start manager
        manager.start()
        time.sleep(0.2)

        # Verify source-1 is active
        assert manager.get_active_source() == "source-1"

        # Simulate source-1 failure
        source1.set_health(SourceHealth.FAILED)
        time.sleep(0.5)  # Wait for health check to detect failure

        # Should failover to source-2
        assert manager.get_active_source() == "source-2"

        # Should have recorded failover event
        assert len(failover_events) > 0
        assert failover_events[-1].from_source == "source-1"
        assert failover_events[-1].to_source == "source-2"

        manager.stop()

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_read_audio_from_active_source(self, mock_ffmpeg_class):
        """Test reading audio from the active source."""
        source = MockFFmpegSource("test-source", SourceHealth.HEALTHY)
        mock_ffmpeg_class.return_value = source

        manager = AudioSourceManager(sample_rate=22050)

        manager.add_source(AudioSourceConfig(
            name="test-source",
            source_url="http://example.com/stream",
            priority=10,
            enabled=True
        ))

        manager.start()
        time.sleep(0.1)

        # Read audio
        samples = manager.read_audio(2205)  # 100ms at 22050 Hz

        assert samples is not None
        assert len(samples) == 2205
        assert samples.dtype == np.float32

        manager.stop()

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_read_audio_returns_none_when_no_active_source(self, mock_ffmpeg_class):
        """Test read_audio returns None when no source is active."""
        manager = AudioSourceManager(sample_rate=22050)

        # Try to read without any sources
        samples = manager.read_audio(2205)
        assert samples is None

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_remove_source(self, mock_ffmpeg_class):
        """Test removing a source."""
        source = MockFFmpegSource("test-source")
        mock_ffmpeg_class.return_value = source

        manager = AudioSourceManager(sample_rate=22050)

        config = AudioSourceConfig(
            name="test-source",
            source_url="http://example.com/stream",
            priority=10,
            enabled=True
        )

        manager.add_source(config)
        assert "test-source" in manager.get_all_metrics()

        # Remove source
        result = manager.remove_source("test-source")
        assert result is True

        # Verify removed
        assert "test-source" not in manager.get_all_metrics()

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_priority_based_selection(self, mock_ffmpeg_class):
        """Test that sources are selected based on priority."""
        source1 = MockFFmpegSource("low-priority", SourceHealth.HEALTHY)
        source2 = MockFFmpegSource("medium-priority", SourceHealth.HEALTHY)
        source3 = MockFFmpegSource("high-priority", SourceHealth.HEALTHY)

        def create_mock(config, **kwargs):
            if config.name == "low-priority":
                return source1
            elif config.name == "medium-priority":
                return source2
            return source3

        mock_ffmpeg_class.side_effect = create_mock

        manager = AudioSourceManager(sample_rate=22050)

        # Add sources in random order
        manager.add_source(AudioSourceConfig(
            name="medium-priority",
            source_url="http://example.com/medium",
            priority=20,
            enabled=True
        ))

        manager.add_source(AudioSourceConfig(
            name="low-priority",
            source_url="http://example.com/low",
            priority=30,
            enabled=True
        ))

        manager.add_source(AudioSourceConfig(
            name="high-priority",
            source_url="http://example.com/high",
            priority=10,
            enabled=True
        ))

        manager.start()
        time.sleep(0.2)

        # Should select highest priority (lowest number)
        assert manager.get_active_source() == "high-priority"

        manager.stop()

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_disabled_sources_not_activated(self, mock_ffmpeg_class):
        """Test that disabled sources are not activated."""
        source1 = MockFFmpegSource("enabled-source", SourceHealth.HEALTHY)
        source2 = MockFFmpegSource("disabled-source", SourceHealth.HEALTHY)

        def create_mock(config, **kwargs):
            if config.name == "enabled-source":
                return source1
            return source2

        mock_ffmpeg_class.side_effect = create_mock

        manager = AudioSourceManager(sample_rate=22050)

        manager.add_source(AudioSourceConfig(
            name="disabled-source",
            source_url="http://example.com/disabled",
            priority=10,
            enabled=False  # Disabled
        ))

        manager.add_source(AudioSourceConfig(
            name="enabled-source",
            source_url="http://example.com/enabled",
            priority=20,
            enabled=True
        ))

        manager.start()
        time.sleep(0.2)

        # Should activate enabled source even though disabled has higher priority
        assert manager.get_active_source() == "enabled-source"

        manager.stop()

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_concurrent_audio_readers(self, mock_ffmpeg_class):
        """Test multiple threads reading audio simultaneously."""
        source = MockFFmpegSource("test-source", SourceHealth.HEALTHY)
        mock_ffmpeg_class.return_value = source

        manager = AudioSourceManager(sample_rate=22050)

        manager.add_source(AudioSourceConfig(
            name="test-source",
            source_url="http://example.com/stream",
            priority=10,
            enabled=True
        ))

        manager.start()
        time.sleep(0.1)

        # Create multiple reader threads
        results = []
        errors = []

        def reader_thread(thread_id):
            try:
                for _ in range(10):
                    samples = manager.read_audio(2205)
                    if samples is not None:
                        results.append((thread_id, len(samples)))
                    time.sleep(0.01)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader_thread, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # Should have no errors
        assert len(errors) == 0

        # Should have received audio from all threads
        assert len(results) > 0

        manager.stop()

    @patch('app_core.audio.source_manager.FFmpegAudioSource')
    def test_get_all_metrics(self, mock_ffmpeg_class):
        """Test retrieving metrics for all sources."""
        source1 = MockFFmpegSource("source-1", SourceHealth.HEALTHY)
        source2 = MockFFmpegSource("source-2", SourceHealth.DEGRADED)

        def create_mock(config, **kwargs):
            if config.name == "source-1":
                return source1
            return source2

        mock_ffmpeg_class.side_effect = create_mock

        manager = AudioSourceManager(sample_rate=22050)

        manager.add_source(AudioSourceConfig(
            name="source-1",
            source_url="http://example.com/1",
            priority=10,
            enabled=True
        ))

        manager.add_source(AudioSourceConfig(
            name="source-2",
            source_url="http://example.com/2",
            priority=20,
            enabled=True
        ))

        # Get metrics
        metrics = manager.get_all_metrics()

        assert len(metrics) == 2
        assert "source-1" in metrics
        assert "source-2" in metrics

        assert metrics["source-1"].health == SourceHealth.HEALTHY
        assert metrics["source-2"].health == SourceHealth.DEGRADED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
