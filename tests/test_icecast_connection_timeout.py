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

"""Tests for Icecast connection timeout prevention.

The 10-minute timeout issue is fixed server-side in Icecast configuration
by setting source-timeout to 0 (infinite). This test verifies that FFmpeg
commands are generated correctly without invalid protocol options.
"""

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


def test_ffmpeg_command_valid_for_icecast_protocol():
    """Ensure FFmpeg command is valid and doesn't include HTTP-only options."""

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

    # Verify no invalid HTTP-only options for icecast:// protocol
    invalid_options = ['-timeout', '-tcp_nodelay', '-send_expect_100', '-rw_timeout']
    for opt in invalid_options:
        assert opt not in captured_cmd, (
            f"FFmpeg command includes {opt} which is not valid for icecast:// protocol. "
            f"This causes immediate connection failures."
        )

    # Verify the command includes valid icecast options
    assert '-ice_public' in captured_cmd, "Missing valid Icecast option -ice_public"
    assert 'icecast://' in ' '.join(captured_cmd), "Missing icecast:// URL"


def test_icecast_config_includes_ice_public():
    """Ensure ice_public option is set to disable directory listing."""

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

    # Verify ice_public option is present
    assert '-ice_public' in captured_cmd, "FFmpeg command missing -ice_public option"

    # Find the value
    public_index = captured_cmd.index('-ice_public')
    public_value = captured_cmd[public_index + 1]

    assert public_value == '0', (
        f"Expected ice_public value of 0, got {public_value}"
    )


if __name__ == '__main__':
    # Run tests
    test_ffmpeg_command_valid_for_icecast_protocol()
    print("✓ FFmpeg command is valid for icecast:// protocol")

    test_icecast_config_includes_ice_public()
    print("✓ FFmpeg includes -ice_public 0")

    print("\n✅ All Icecast connection tests passed!")
    print("Note: 10-minute timeout fix is in Icecast server config (source-timeout=0)")
