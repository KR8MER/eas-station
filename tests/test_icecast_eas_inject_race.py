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

"""An injected alert must survive being drained in a single feed-loop pass.

The injector bumps ``_eas_inject_seq`` and then queues the whole alert in
a few milliseconds. ``_feed_loop`` drains everything queued into its local
buffer, and used to check the sequence only at the top of the next
iteration -- where it cleared the buffer, alert included. On the 32 ms
``sdr-wbks`` mount a 12 s injected test tone vanished completely; on the
85 ms WNCI mount its first ~140 ms was cut.
"""

import inspect
import sys
from collections import deque
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.icecast_output import IcecastConfig, IcecastStreamer


def _streamer():
    source = mock.MagicMock()
    source._eas_inject_seq = 0
    config = IcecastConfig(server="localhost", port=8000, password="x", mount="t",
                           name="t", description="t")
    streamer = IcecastStreamer(config, source)
    streamer._last_eas_inject_seq = 0  # normally set by start()
    return streamer, source


def test_alert_drained_in_one_pass_is_not_cleared():
    streamer, source = _streamer()
    buffer = deque(maxlen=600)
    for _ in range(150):
        streamer._bank_pcm(buffer, b"live")

    source._eas_inject_seq += 1               # injector: bump, then publish
    for _ in range(260):                      # drain pulls the whole alert at once
        streamer._bank_pcm(buffer, b"eas")
    streamer._bank_pcm(buffer, b"live-after")  # next iteration's read

    assert list(buffer) == [b"eas"] * 260 + [b"live-after"]


def test_live_audio_banked_before_the_injection_is_flushed_once():
    streamer, source = _streamer()
    buffer = deque([b"old"] * 5, maxlen=600)
    source._eas_inject_seq += 1
    streamer._bank_pcm(buffer, b"eas-1")
    streamer._bank_pcm(buffer, b"eas-2")
    assert list(buffer) == [b"eas-1", b"eas-2"]


def test_feed_loop_checks_the_sequence_only_when_banking():
    source = inspect.getsource(IcecastStreamer._feed_loop)
    assert "_eas_inject_seq" not in source
    assert source.count("self._bank_pcm(buffer,") == 2


def test_small_live_chunks_behind_an_alert_never_drop_alert_audio():
    """SDR mount: ~79 live chunks/s queue behind a 280-chunk alert.

    The old deque(maxlen=600) hit its cap ~5 s in and silently dropped the
    oldest chunks -- the alert -- so the rest played at ~3.5x speed.
    """
    from app_core.audio.icecast_pacing import RealTimePacer

    streamer, source = _streamer()
    streamer.config.sample_rate, streamer.config.channels = 48000, 2
    now = [0.0]
    pacer = RealTimePacer(lambda: 48000 * 4, clock=lambda: now[0])
    buffer = deque()
    source._eas_inject_seq += 1
    eas = [b"E" * 9600] * 280                      # 50 ms stereo int16 chunks
    for chunk in eas:
        streamer._bank_pcm(buffer, chunk)
    pacer.release(buffer)
    released = []
    for _ in range(int(15 * 79)):                  # 15 s of 12.6 ms live chunks
        now[0] += 2420 / (48000 * 4)
        streamer._bank_pcm(buffer, b"L" * 2420)
        released.extend(pacer.release(buffer))
    assert released[:280] == eas


def test_duration_cap_still_bounds_a_stalled_encoder():
    streamer, _ = _streamer()
    streamer.config.sample_rate, streamer.config.channels = 8000, 1
    buffer = deque()
    for _ in range(20000):                          # 2000 s of 100 ms chunks, never drained
        streamer._bank_pcm(buffer, b"x" * 1600)
    assert sum(map(len, buffer)) <= 361 * 8000 * 2


def test_streamer_buffers_are_not_chunk_capped():
    for method in (IcecastStreamer._feed_loop, IcecastStreamer._prebuffer_audio):
        assert "maxlen" not in inspect.getsource(method)
