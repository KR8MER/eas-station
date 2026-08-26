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

"""Regression test: RWT (weekly test) audio must reach the Icecast air-chain.

app_core.rwt_scheduler._drive_rwt_airchain() drives playout for BOTH the
fully automated weekly RWT and the operator-triggered "Send Test RWT"
button (and, transitively, a GPIO-triggered RWT -- see
app_core/gpio_input_listener.py::_trigger_rwt_from_input, which calls the
same trigger_rwt_broadcast() this eventually reaches). None of those three
trigger sources ever pushed audio into Icecast before this fix -- only
local audio_player_cmd (e.g. aplay) playback did, the same gap found in
webapp/eas/workflow.py's manual Send (see tests/test_manual_send_injection.py).
The weekly compliance test was airing nowhere a stream listener could hear
it.
"""

import struct
import wave
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from app_core.rwt_scheduler import _drive_rwt_airchain


def _make_wav_bytes(duration_s: float = 0.05, sample_rate: int = 8000) -> bytes:
    buf = BytesIO()
    n_frames = int(duration_s * sample_rate)
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack('<%dh' % n_frames, *([0] * n_frames)))
    return buf.getvalue()


def test_drive_rwt_airchain_injects_into_icecast():
    activation = SimpleNamespace(identifier='RWT-AUTO-TEST', event_code='RWT')
    composite_wav = _make_wav_bytes()

    with patch('app_core.rwt_scheduler.set_broadcast_active', return_value=True), \
         patch('app_core.rwt_scheduler.clear_broadcast_active'), \
         patch('app_core.rwt_scheduler.play_broadcast_audio'), \
         patch('app_core.audio.redis_commands.get_audio_command_publisher') as mock_get_pub:
        mock_pub = mock_get_pub.return_value
        mock_pub.inject_raw_eas_audio.return_value = {'success': True, 'data': {'injected': True}}

        result = _drive_rwt_airchain(
            activation_record=activation,
            composite_wav=composite_wav,
            eom_wav=None,
            header_seconds=0.0,
            eom_seconds=0.0,
            eas_config={'audio_player_cmd': None},
            log=SimpleNamespace(
                warning=lambda *a, **k: None, info=lambda *a, **k: None,
            ),
        )

    assert result is True
    mock_pub.inject_raw_eas_audio.assert_called_once()
    injected_audio = mock_pub.inject_raw_eas_audio.call_args[0][0]
    assert injected_audio == composite_wav


def test_drive_rwt_airchain_injection_failure_is_non_fatal():
    """A failed/unavailable injection must never block GPIO keying or local
    playback -- same guard as resend and manual Send."""
    activation = SimpleNamespace(identifier='RWT-AUTO-TEST-2', event_code='RWT')
    composite_wav = _make_wav_bytes()

    with patch('app_core.rwt_scheduler.set_broadcast_active', return_value=True), \
         patch('app_core.rwt_scheduler.clear_broadcast_active'), \
         patch('app_core.rwt_scheduler.play_broadcast_audio') as mock_play, \
         patch(
             'app_core.audio.redis_commands.get_audio_command_publisher',
             side_effect=RuntimeError('audio service unreachable'),
         ):
        result = _drive_rwt_airchain(
            activation_record=activation,
            composite_wav=composite_wav,
            eom_wav=None,
            header_seconds=0.0,
            eom_seconds=0.0,
            eas_config={'audio_player_cmd': ['aplay']},
            log=SimpleNamespace(
                warning=lambda *a, **k: None, info=lambda *a, **k: None,
            ),
        )

    assert result is True
    mock_play.assert_called_once()
