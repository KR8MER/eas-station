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

"""Tests for stream authentication and HTTP-status error reporting.

Covers:
- HTTP Basic auth header generation and raw Authorization header passthrough.
- FFmpeg command embedding the auth headers.
- The stderr pump translating an HTTP 403 into a clear, fatal error message.
- The preflight status-code -> user-message mapping.
- Redaction of stored stream passwords from API responses.
"""

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.ingest import AudioSourceConfig, AudioSourceStatus, AudioSourceType
from app_core.audio.sources import StreamSourceAdapter


def _make_adapter(**device_params):
    config = AudioSourceConfig(
        source_type=AudioSourceType.STREAM,
        name="Test Stream",
        device_params={'url': 'https://example.com/stream.aac', **device_params},
    )
    return StreamSourceAdapter(config)


def test_basic_auth_header_generated():
    adapter = _make_adapter(auth_username='alice', auth_password='secret')
    ffmpeg_header, headers = adapter._build_http_headers()
    expected = 'Basic ' + base64.b64encode(b'alice:secret').decode('ascii')
    assert headers['Authorization'] == expected
    assert 'Authorization: ' + expected in ffmpeg_header
    assert headers['Icy-MetaData'] == '1'


def test_raw_auth_header_takes_precedence():
    adapter = _make_adapter(auth_username='alice', auth_password='secret',
                            auth_header='Bearer abc123')
    _, headers = adapter._build_http_headers()
    assert headers['Authorization'] == 'Bearer abc123'


def test_named_auth_header_split():
    adapter = _make_adapter(auth_header='X-Token: zzz')
    _, headers = adapter._build_http_headers()
    assert headers['X-Token'] == 'zzz'
    assert 'Authorization' not in headers


def test_no_auth_means_no_authorization_header():
    adapter = _make_adapter()
    _, headers = adapter._build_http_headers()
    assert 'Authorization' not in headers


def test_ffmpeg_command_includes_auth_and_no_4xx_retry():
    adapter = _make_adapter(auth_username='bob', auth_password='pw')
    cmd = adapter._build_ffmpeg_command('https://example.com/stream.aac')
    # Headers passed to FFmpeg include the Authorization line.
    headers_idx = cmd.index('-headers')
    assert 'Authorization: Basic' in cmd[headers_idx + 1]
    # 4xx errors must NOT be retried (only transient 5xx).
    retry_idx = cmd.index('-reconnect_on_http_error')
    assert cmd[retry_idx + 1] == '5xx'


def test_describe_http_error_messages():
    assert '403' in StreamSourceAdapter._describe_http_error(403)
    assert 'authentication' in StreamSourceAdapter._describe_http_error(403).lower()
    assert '401' in StreamSourceAdapter._describe_http_error(401)
    assert '404' in StreamSourceAdapter._describe_http_error(404)


def test_stderr_pump_marks_403_fatal():
    """A 403 in FFmpeg stderr should surface as a fatal ERROR with a clear message."""
    adapter = _make_adapter()

    class _FakeStderr:
        def __init__(self, lines):
            self._lines = list(lines)

        def readline(self):
            return self._lines.pop(0) if self._lines else b''

    class _FakeProcess:
        def __init__(self, lines):
            self.stderr = _FakeStderr(lines)

    proc = _FakeProcess([
        b"[http @ 0x55] HTTP error 403 Forbidden\n",
        b'',
    ])
    adapter._stderr_pump(proc)

    assert adapter._fatal_auth_error is True
    assert adapter.status == AudioSourceStatus.ERROR
    assert '403' in (adapter.error_message or '')


def test_restart_skipped_when_auth_fatal():
    adapter = _make_adapter()
    adapter._fatal_auth_error = True
    adapter._last_http_error = '403 Forbidden — stream requires authentication.'
    # Should short-circuit without attempting to launch FFmpeg.
    adapter._restart_ffmpeg_process('decoder exited')
    assert adapter.status == AudioSourceStatus.ERROR
    assert '403' in adapter.error_message


def test_stderr_pump_marks_404_as_error_but_not_fatal():
    """A 404 must surface as an ERROR status (so it's visible in the UI) but
    NOT set _fatal_auth_error -- unlike bad credentials, a mount that
    doesn't exist yet is a normal, recoverable condition for a Stream
    source relaying another Icecast source client (e.g. SDRTrunk), and the
    restart loop must keep retrying instead of giving up permanently."""
    adapter = _make_adapter()

    class _FakeStderr:
        def __init__(self, lines):
            self._lines = list(lines)

        def readline(self):
            return self._lines.pop(0) if self._lines else b''

    class _FakeProcess:
        def __init__(self, lines):
            self.stderr = _FakeStderr(lines)

    proc = _FakeProcess([
        b"[http @ 0x55] HTTP error 404 Not Found\n",
        b'',
    ])
    adapter._stderr_pump(proc)

    assert adapter._fatal_auth_error is False
    assert adapter.status == AudioSourceStatus.ERROR
    assert '404' in (adapter.error_message or '')


def test_restart_retries_on_404_instead_of_stopping():
    adapter = _make_adapter()
    adapter._last_http_error = '404 Not Found — stream URL does not exist (yet); will keep retrying.'
    adapter.error_message = adapter._last_http_error
    adapter._fatal_auth_error = False
    adapter._last_restart = 0.0

    launched = []
    adapter._launch_ffmpeg_process = lambda: launched.append(True)

    adapter._restart_ffmpeg_process('decoder exited')

    assert launched == [True], "a 404 must not short-circuit the restart loop"


def test_probe_status_mapping():
    from webapp.admin.audio_ingest import _describe_stream_status
    ok, msg = _describe_stream_status(200)
    assert ok and '200' in msg
    ok, msg = _describe_stream_status(403)
    assert not ok and '403' in msg and 'authentication' in msg.lower()
    ok, msg = _describe_stream_status(401)
    assert not ok and '401' in msg
    ok, msg = _describe_stream_status(503, 'Service Unavailable')
    assert not ok and '503' in msg


def test_redact_device_params_hides_password():
    from webapp.admin.audio_ingest import _redact_device_params
    redacted = _redact_device_params({
        'url': 'https://example.com/s.aac',
        'auth_username': 'alice',
        'auth_password': 'secret',
    })
    assert 'auth_password' not in redacted
    assert redacted['auth_password_set'] is True
    assert redacted['auth_username'] == 'alice'

    # No password stored -> no indicator leakage of a secret.
    plain = _redact_device_params({'url': 'https://example.com/s.aac'})
    assert 'auth_password' not in plain
    assert 'auth_password_set' not in plain
