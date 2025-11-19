"""
Tests for the Audio Ingest Pipeline

Unit tests for audio source adapters, ingest controller,
and metering components.
"""

import logging
import pytest
import numpy as np
import time
from flask import Flask
from typing import Optional
from unittest.mock import Mock, patch

from app_core.audio.ingest import (
    AudioIngestController, AudioSourceAdapter, AudioSourceConfig,
    AudioSourceType, AudioSourceStatus
)
from app_core.audio.sources import create_audio_source
from app_core.audio.metering import AudioMeter, SilenceDetector, AudioHealthMonitor
from webapp.admin import audio_ingest as audio_admin


class DummyCaptureAdapter(AudioSourceAdapter):
    """Simple adapter used to exercise restart and controller logic."""

    def __init__(self, name: str = "dummy", *, fail_after: Optional[int] = None):
        config = AudioSourceConfig(
            source_type=AudioSourceType.FILE,
            name=name,
            buffer_size=256,
        )
        super().__init__(config)
        self._fail_after = fail_after
        self._chunks_read = 0

    def _start_capture(self) -> None:
        self._chunks_read = 0

    def _stop_capture(self) -> None:
        pass

    def _read_audio_chunk(self):
        if self._stop_event.is_set():
            return None
        self._chunks_read += 1
        if self._fail_after is not None and self._chunks_read > self._fail_after:
            raise RuntimeError("simulated capture failure")
        time.sleep(0.005)
        return np.zeros(self.config.buffer_size, dtype=np.float32)


class TestAudioSourceConfig:
    """Test audio source configuration."""

    def test_minimal_config(self):
        """Test creating a minimal configuration."""
        config = AudioSourceConfig(
            source_type=AudioSourceType.FILE,
            name="test_file"
        )
        
        assert config.source_type == AudioSourceType.FILE
        assert config.name == "test_file"
        assert config.enabled is True
        assert config.priority == 100
        assert config.sample_rate == 44100
        assert config.channels == 1

    def test_full_config(self):
        """Test creating a full configuration."""
        config = AudioSourceConfig(
            source_type=AudioSourceType.ALSA,
            name="test_alsa",
            enabled=False,
            priority=50,
            sample_rate=48000,
            channels=2,
            buffer_size=8192,
            silence_threshold_db=-50.0,
            device_params={"device_name": "hw:0"}
        )
        
        assert config.source_type == AudioSourceType.ALSA
        assert config.name == "test_alsa"
        assert config.enabled is False
        assert config.priority == 50
        assert config.sample_rate == 48000
        assert config.channels == 2
        assert config.buffer_size == 8192
        assert config.silence_threshold_db == -50.0
        assert config.device_params["device_name"] == "hw:0"


class TestAudioMeter:
    """Test audio level metering."""

    def test_meter_creation(self):
        """Test creating an audio meter."""
        meter = AudioMeter(window_size=512, peak_hold_time=1.0)
        
        assert meter.window_size == 512
        assert meter.peak_hold_time == 1.0
        assert meter._buffer.shape == (512,)
        assert meter._current_peak == -np.inf

    def test_silent_audio(self):
        """Test processing silent audio."""
        meter = AudioMeter(window_size=1024)
        
        # Process silent audio
        silent_samples = np.zeros(1024, dtype=np.float32)
        metrics = meter.process_samples(silent_samples)
        
        # Should show very low levels
        assert metrics['rms_dbfs'] < -90.0
        assert metrics['peak_dbfs'] < -90.0
        assert metrics['rms_linear'] == 0.0
        assert metrics['peak_linear'] == 0.0

    def test_tone_audio(self):
        """Test processing a tone signal."""
        meter = AudioMeter(window_size=1024)
        
        # Generate 440Hz tone at -20 dBFS
        sample_rate = 44100
        duration = 1.0
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        amplitude = 10 ** (-20 / 20)  # -20 dBFS
        tone_samples = amplitude * np.sin(2 * np.pi * 440 * t)
        
        metrics = meter.process_samples(tone_samples)
        
        # Should show levels around -20 dBFS
        assert -25.0 < metrics['rms_dbfs'] < -15.0
        assert -23.0 < metrics['peak_dbfs'] < -17.0
        assert metrics['rms_linear'] > 0.0
        assert metrics['peak_linear'] > 0.0

    def test_peak_hold(self):
        """Test peak hold functionality."""
        meter = AudioMeter(window_size=512, peak_hold_time=0.1)
        
        # Process high peak followed by lower levels
        high_peak = np.array([0.9] + [0.0] * 511, dtype=np.float32)
        low_level = np.array([0.1] * 512, dtype=np.float32)
        
        # Process high peak
        metrics1 = meter.process_samples(high_peak)
        peak1 = metrics1['peak_dbfs']
        
        # Process low level immediately (should still hold the peak)
        metrics2 = meter.process_samples(low_level)
        peak2 = metrics2['peak_dbfs']
        
        assert peak2 == pytest.approx(peak1, rel=1e-3)
        
        # Wait for hold to expire
        time.sleep(0.15)
        
        # Process low level again (peak should drop)
        metrics3 = meter.process_samples(low_level)
        peak3 = metrics3['peak_dbfs']
        
        assert peak3 < peak2

    def test_meter_reset(self):
        """Test resetting the meter."""
        meter = AudioMeter(window_size=512)
        
        # Process some audio
        samples = np.random.randn(512).astype(np.float32) * 0.1
        meter.process_samples(samples)
        
        # Reset
        meter.reset()
        
        # Should be back to initial state
        assert meter._current_peak == -np.inf
        assert meter._peak_hold_start == 0.0
        assert np.all(meter._buffer == 0)


class TestSilenceDetector:
    """Test silence detection."""

    def test_detector_creation(self):
        """Test creating a silence detector."""
        detector = SilenceDetector(
            silence_threshold_db=-50.0,
            silence_duration_seconds=2.0
        )
        
        assert detector.silence_threshold_db == -50.0
        assert detector.silence_duration_seconds == 2.0
        assert not detector.is_silent()
        assert detector.get_silence_duration() == 0.0

    def test_signal_detection(self):
        """Test detecting normal signal levels."""
        detector = SilenceDetector(silence_threshold_db=-60.0)
        
        # Process signal above threshold
        detector.process_audio_level(-30.0, "test_source")
        
        assert not detector.is_silent()
        assert detector.get_silence_duration() == 0.0

    def test_silence_detection(self):
        """Test detecting silence."""
        detector = SilenceDetector(
            silence_threshold_db=-60.0,
            silence_duration_seconds=0.1  # Short for testing
        )
        
        # Start with signal
        detector.process_audio_level(-30.0, "test_source")
        assert not detector.is_silent()
        
        # Process silence
        time.sleep(0.05)
        detector.process_audio_level(-70.0, "test_source")
        assert not detector.is_silent()  # Not yet reached duration
        
        # Wait for duration to pass
        time.sleep(0.06)
        detector.process_audio_level(-70.0, "test_source")
        assert detector.is_silent()  # Should now detect silence

    def test_signal_recovery(self):
        """Test recovery from silence."""
        detector = SilenceDetector(
            silence_threshold_db=-60.0,
            silence_duration_seconds=0.1
        )
        
        # Detect silence
        detector.process_audio_level(-70.0, "test_source")
        time.sleep(0.11)
        detector.process_audio_level(-70.0, "test_source")
        assert detector.is_silent()
        
        # Recover with signal
        detector.process_audio_level(-30.0, "test_source")
        assert not detector.is_silent()
        assert detector.get_silence_duration() == 0.0

    def test_alert_callbacks(self):
        """Test alert callback functionality."""
        alerts = []
        
        def test_callback(alert):
            alerts.append(alert)
        
        detector = SilenceDetector(
            silence_threshold_db=-60.0,
            silence_duration_seconds=0.1
        )
        detector.add_alert_callback(test_callback)
        
        # Trigger silence
        detector.process_audio_level(-70.0, "test_source")
        time.sleep(0.11)
        detector.process_audio_level(-70.0, "test_source")
        
        # Should have generated alerts
        assert len(alerts) >= 1
        assert "silence detected" in alerts[-1].message.lower()

    def test_detector_reset(self):
        """Test resetting the detector."""
        detector = SilenceDetector(silence_threshold_db=-60.0)
        
        # Set some state
        detector.process_audio_level(-70.0, "test_source")
        time.sleep(0.1)
        
        # Reset
        detector.reset()
        
        # Should be back to initial state
        assert not detector.is_silent()
        assert detector.get_silence_duration() == 0.0
        assert len(detector.get_recent_alerts()) == 0


class TestAudioHealthMonitor:
    """Test comprehensive audio health monitoring."""

    def test_monitor_creation(self):
        """Test creating a health monitor."""
        monitor = AudioHealthMonitor("test_source")
        
        assert monitor.source_name == "test_source"
        assert monitor.meter is not None
        assert monitor.silence_detector is not None
        assert monitor._health_score == 100.0

    def test_healthy_signal_processing(self):
        """Test processing healthy audio signal."""
        monitor = AudioHealthMonitor("test_source")
        
        # Generate healthy tone at -20 dBFS
        sample_rate = 44100
        t = np.linspace(0, 0.1, int(sample_rate * 0.1), False)
        amplitude = 10 ** (-20 / 20)
        samples = amplitude * np.sin(2 * np.pi * 440 * t)
        
        status = monitor.process_samples(samples)
        
        assert status['health_score'] >= 80.0
        assert not status['silence_detected']
        assert not status['clipping_detected']

    def test_silent_signal_processing(self):
        """Test processing silent signal."""
        monitor = AudioHealthMonitor("test_source")
        
        # Process silent audio
        silent_samples = np.zeros(1024, dtype=np.float32)
        status = monitor.process_samples(silent_samples)
        
        # Health score should be reduced
        assert status['health_score'] < 100.0
        assert status['silence_detected']

    def test_clipping_detection(self):
        """Test clipping detection."""
        monitor = AudioHealthMonitor("test_source")
        
        # Generate clipped signal
        clipped_samples = np.full(1024, 0.98, dtype=np.float32)  # Near full scale
        
        # Process enough to trigger clipping alerts
        for _ in range(20):  # Multiple chunks to trigger threshold
            status = monitor.process_samples(clipped_samples)
            if status['clipping_detected']:
                break
        
        assert status['clipping_detected']
        assert status['health_score'] < 90.0

    def test_health_status_retrieval(self):
        """Test getting health status."""
        monitor = AudioHealthMonitor("test_source")
        
        # Process some audio
        samples = np.random.randn(512).astype(np.float32) * 0.1
        monitor.process_samples(samples)
        
        status = monitor.get_health_status()
        
        assert status['source_name'] == "test_source"
        assert 0.0 <= status['health_score'] <= 100.0
        assert 'meter_levels' in status
        assert 'silence_detected' in status
        assert 'level_trend' in status
        assert isinstance(status['recent_alerts'], list)

    def test_monitor_reset(self):
        """Test resetting the monitor."""
        monitor = AudioHealthMonitor("test_source")
        
        # Process some audio to change state
        samples = np.random.randn(512).astype(np.float32) * 0.1
        monitor.process_samples(samples)
        
        # Reset
        monitor.reset()
        
        # Should be back to initial state
        status = monitor.get_health_status()
        assert status['health_score'] == 100.0
        assert len(monitor._level_history) == 0


class TestAudioSourceAdapter:
    """Test audio source adapter base functionality."""

    def test_adapter_creation(self):
        """Test creating an audio source adapter."""
        config = AudioSourceConfig(
            source_type=AudioSourceType.FILE,
            name="test",
            device_params={"file_path": "/nonexistent.wav"}
        )
        
        # Should be able to create adapter (file source is always available)
        adapter = create_audio_source(config)
        
        assert adapter.config == config
        assert adapter.status == AudioSourceStatus.STOPPED

    def test_unsupported_source_type(self):
        """Test error handling for unsupported source types."""
        config = AudioSourceConfig(
            source_type=AudioSourceType.SDR,
            name="test",
            device_params={"receiver_id": "test"}
        )
        
        # Mock radio manager as unavailable
        with patch('app_core.audio.sources.RADIO_AVAILABLE', False):
            with pytest.raises(RuntimeError, match="SDR source not available"):
                create_audio_source(config)


class TestAudioIngestController:
    """Test the main ingest controller."""

    def test_controller_creation(self):
        """Test creating an ingest controller."""
        controller = AudioIngestController(enable_monitor=False)
        
        assert len(controller._sources) == 0
        assert controller._active_source is None

    def test_add_source(self):
        """Test adding a source to the controller."""
        controller = AudioIngestController(enable_monitor=False)
        
        config = AudioSourceConfig(
            source_type=AudioSourceType.FILE,
            name="test_file",
            device_params={"file_path": "/nonexistent.wav"}
        )
        
        adapter = create_audio_source(config)
        controller.add_source(adapter)
        
        assert "test_file" in controller._sources
        assert len(controller.list_sources()) == 1

    def test_remove_source(self):
        """Test removing a source from the controller."""
        controller = AudioIngestController(enable_monitor=False)
        
        config = AudioSourceConfig(
            source_type=AudioSourceType.FILE,
            name="test_file",
            device_params={"file_path": "/nonexistent.wav"}
        )
        
        adapter = create_audio_source(config)
        controller.add_source(adapter)
        controller.remove_source("test_file")
        
        assert "test_file" not in controller._sources
        assert len(controller.list_sources()) == 0

    def test_source_priority_selection(self):
        """Test source selection based on priority."""
        controller = AudioIngestController(enable_monitor=False)
        
        # Add sources with different priorities
        config1 = AudioSourceConfig(
            source_type=AudioSourceType.FILE,
            name="low_priority",
            priority=200,
            device_params={"file_path": "/nonexistent.wav"}
        )
        
        config2 = AudioSourceConfig(
            source_type=AudioSourceType.FILE,
            name="high_priority",
            priority=100,
            device_params={"file_path": "/nonexistent.wav"}
        )
        
        adapter1 = create_audio_source(config1)
        adapter2 = create_audio_source(config2)
        
        controller.add_source(adapter1)
        controller.add_source(adapter2)
        
        # Mock sources as running
        adapter1.status = AudioSourceStatus.RUNNING
        adapter2.status = AudioSourceStatus.RUNNING
        
        # Should prefer higher priority (lower number)
        sources = [
            (name, source) for name, source in controller._sources.items()
            if source.status == AudioSourceStatus.RUNNING
        ]
        sources.sort(key=lambda x: x[1].config.priority)
        
        assert sources[0][0] == "high_priority"

    def test_cleanup(self):
        """Test controller cleanup."""
        controller = AudioIngestController(enable_monitor=False)
        
        config = AudioSourceConfig(
            source_type=AudioSourceType.FILE,
            name="test",
            device_params={"file_path": "/nonexistent.wav"}
        )
        
        adapter = create_audio_source(config)
        controller.add_source(adapter)
        
        controller.cleanup()

        assert len(controller._sources) == 0
        assert controller._active_source is None

    def test_adapter_restart_recovers_running_state(self):
        """Verify restart() stops and restarts the capture loop."""
        adapter = DummyCaptureAdapter()
        assert adapter.start()
        time.sleep(0.2)
        assert adapter.status == AudioSourceStatus.RUNNING

        assert adapter.restart("unit-test", delay=0.0)
        time.sleep(0.2)
        assert adapter.status == AudioSourceStatus.RUNNING
        assert adapter._restart_count >= 1
        adapter.stop()

    def test_ensure_source_running_requests_restart(self):
        """Controller should restart unhealthy adapters on demand."""
        controller = AudioIngestController(enable_monitor=False)
        adapter = DummyCaptureAdapter(name="ensure-test")
        controller.add_source(adapter)
        adapter.config.enabled = True
        adapter.status = AudioSourceStatus.ERROR

        def _restart(reason):
            adapter.status = AudioSourceStatus.RUNNING
            return True

        adapter.restart = Mock(side_effect=_restart)

        assert controller.ensure_source_running("ensure-test", reason="unit-test") is True
        adapter.restart.assert_called_once()


# ---------------------------------------------------------------------------
# Icecast control API tests
# ---------------------------------------------------------------------------


@pytest.fixture
def icecast_control_app(monkeypatch):
    """Create a lightweight Flask app with the audio ingest routes registered."""

    app = Flask('icecast-control-test')
    app.config['TESTING'] = True

    monkeypatch.setattr(audio_admin, '_auto_streaming_service', None)
    audio_admin.register_audio_ingest_routes(app, logging.getLogger('icecast-control-test'))

    yield app


def test_api_start_icecast_stream_success(icecast_control_app, monkeypatch):
    service = Mock()
    service.start.return_value = True
    service.is_available.return_value = True
    service.get_status.return_value = {
        'active_stream_count': 0,
        'server': 'localhost:8000'
    }

    monkeypatch.setattr(audio_admin, '_auto_streaming_service', service)

    client = icecast_control_app.test_client()
    response = client.post('/api/audio/icecast/start')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['message']
    assert payload['status']['active_stream_count'] == 0
    service.start.assert_called_once()


def test_api_start_icecast_stream_requires_configuration(icecast_control_app, monkeypatch):
    monkeypatch.setattr(audio_admin, '_auto_streaming_service', None)
    monkeypatch.setattr(audio_admin, '_reload_auto_streaming_from_env', lambda: None)

    client = icecast_control_app.test_client()
    response = client.post('/api/audio/icecast/start')

    assert response.status_code == 400
    payload = response.get_json()
    assert 'configured' in payload['message'].lower()


def test_api_stop_icecast_stream_success(icecast_control_app, monkeypatch):
    service = Mock()
    service.stop.return_value = None
    service.get_status.return_value = {'active_stream_count': 0}

    monkeypatch.setattr(audio_admin, '_auto_streaming_service', service)

    client = icecast_control_app.test_client()
    response = client.post('/api/audio/icecast/stop')

    assert response.status_code == 200
    payload = response.get_json()
    assert 'stopped' in payload['message'].lower()
    service.stop.assert_called_once()


def test_api_stop_icecast_stream_requires_configuration(icecast_control_app, monkeypatch):
    monkeypatch.setattr(audio_admin, '_auto_streaming_service', None)

    client = icecast_control_app.test_client()
    response = client.post('/api/audio/icecast/stop')

    assert response.status_code == 400
    payload = response.get_json()
    assert 'configured' in payload['message'].lower()


if __name__ == '__main__':
    pytest.main([__file__])

