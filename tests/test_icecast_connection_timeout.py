"""Tests for Icecast connection timeout prevention."""

import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.icecast_output import IcecastConfig, IcecastStreamer


class _DummyAudioSource:
    """Dummy audio source for testing."""

    def get_audio_chunk(self, timeout=0.1):  # pragma: no cover - stub
        return None

    metrics = mock.MagicMock(metadata={})


def test_ffmpeg_command_includes_infinite_timeout():
    """Ensure FFmpeg command includes -timeout -1 to prevent 10-minute disconnect."""

    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test_password',
        mount='test_mount',
        name='Test Stream',
        description='Test stream for timeout verification',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())

    # Mock subprocess.Popen to capture the command
    captured_cmd = []

    def mock_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        mock_process = mock.MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = mock.MagicMock()
        mock_process.stdout = mock.MagicMock()
        mock_process.stderr = mock.MagicMock()
        return mock_process

    with mock.patch('subprocess.Popen', side_effect=mock_popen):
        streamer._start_ffmpeg()

    # Verify timeout option is present
    assert '-timeout' in captured_cmd, "FFmpeg command missing -timeout option"

    # Find the timeout value
    timeout_index = captured_cmd.index('-timeout')
    timeout_value = captured_cmd[timeout_index + 1]

    assert timeout_value == '-1', (
        f"Expected timeout value of -1 (infinite), got {timeout_value}. "
        "This is critical to prevent the 10-minute disconnect bug."
    )


def test_ffmpeg_command_includes_tcp_nodelay():
    """Ensure FFmpeg command includes TCP_NODELAY for lower latency."""

    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test_password',
        mount='test_mount',
        name='Test Stream',
        description='Test stream',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())

    captured_cmd = []

    def mock_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        mock_process = mock.MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = mock.MagicMock()
        mock_process.stdout = mock.MagicMock()
        mock_process.stderr = mock.MagicMock()
        return mock_process

    with mock.patch('subprocess.Popen', side_effect=mock_popen):
        streamer._start_ffmpeg()

    # Verify tcp_nodelay option is present
    assert '-tcp_nodelay' in captured_cmd, "FFmpeg command missing -tcp_nodelay option"

    # Find the value
    nodelay_index = captured_cmd.index('-tcp_nodelay')
    nodelay_value = captured_cmd[nodelay_index + 1]

    assert nodelay_value == '1', (
        f"Expected tcp_nodelay value of 1, got {nodelay_value}"
    )


def test_ffmpeg_command_disables_expect_100():
    """Ensure FFmpeg command disables Expect: 100-continue for better compatibility."""

    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test_password',
        mount='test_mount',
        name='Test Stream',
        description='Test stream',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())

    captured_cmd = []

    def mock_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        mock_process = mock.MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = mock.MagicMock()
        mock_process.stdout = mock.MagicMock()
        mock_process.stderr = mock.MagicMock()
        return mock_process

    with mock.patch('subprocess.Popen', side_effect=mock_popen):
        streamer._start_ffmpeg()

    # Verify send_expect_100 option is present
    assert '-send_expect_100' in captured_cmd, "FFmpeg command missing -send_expect_100 option"

    # Find the value
    expect_index = captured_cmd.index('-send_expect_100')
    expect_value = captured_cmd[expect_index + 1]

    assert expect_value == '0', (
        f"Expected send_expect_100 value of 0, got {expect_value}"
    )


if __name__ == '__main__':
    # Run tests
    test_ffmpeg_command_includes_infinite_timeout()
    print("✓ FFmpeg includes -timeout -1 (infinite)")

    test_ffmpeg_command_includes_tcp_nodelay()
    print("✓ FFmpeg includes -tcp_nodelay 1")

    test_ffmpeg_command_disables_expect_100()
    print("✓ FFmpeg includes -send_expect_100 0")

    print("\n✅ All connection timeout prevention tests passed!")
