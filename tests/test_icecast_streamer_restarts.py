"""Tests for IcecastStreamer restart handling."""

import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.icecast_output import IcecastConfig, IcecastStreamer


class _DummyAudioSource:
    def get_audio_chunk(self, timeout=0.1):  # pragma: no cover - stub
        return None

    metrics = mock.MagicMock(metadata={})


def test_restart_ffmpeg_resets_encoder(monkeypatch):
    """Restarting the FFmpeg pipeline should replace the process and track reconnects."""

    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='hackme',
        mount='test',
        name='Test Stream',
        description='Testing restart logic',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())
    streamer._stop_event.clear()

    class DummyProcess:
        def __init__(self):
            self.terminated = False
            self.killed = False
            self.pid = 12345

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd='ffmpeg', timeout=timeout)

        def kill(self):
            self.killed = True

    dummy_process = DummyProcess()
    streamer._ffmpeg_process = dummy_process

    new_process = object()

    def fake_start_ffmpeg():
        streamer._ffmpeg_process = new_process
        return True

    # Mock time.sleep to avoid waiting during tests
    sleep_calls = []
    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(streamer, "_start_ffmpeg", fake_start_ffmpeg)
    monkeypatch.setattr(time, "sleep", fake_sleep)

    previous_restarts = streamer._reconnect_count
    result = streamer._restart_ffmpeg("test reason")

    assert result is True
    assert dummy_process.terminated is True
    assert dummy_process.killed is True
    assert streamer._ffmpeg_process is new_process
    assert streamer._reconnect_count == previous_restarts + 1
    assert streamer._last_error == "test reason"
    assert streamer._last_write_time <= time.time()
    # Verify that the restart delay was called
    assert 5.0 in sleep_calls, f"Expected ICECAST_RESTART_DELAY (5.0s) in sleep calls, got {sleep_calls}"
