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

Tests for the live-stream keep-alive silence policy.

Covers the listen-stream stutter fix: the web WAV stream and the EAS
decoder MP3 feeds used to write a 50-100 ms block of zeros on EVERY queue
timeout, with timeouts that raced the ~100 ms producer cadence — so any
scheduling jitter spliced silence into continuous audio (audible stutter)
and pushed the stream permanently behind real time.  KeepAliveGate must
report "emit nothing" for transient jitter and permit keep-alive silence
only after sustained source quiet.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.audio.stream_keepalive import KeepAliveGate


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_transient_jitter_never_emits_silence():
    clock = FakeClock()
    gate = KeepAliveGate(quiet_seconds=1.5, clock=clock)

    # Chunks arriving with up to 400 ms of jitter — far past the old
    # 100-200 ms timeouts that used to inject silence — must never
    # qualify for keep-alive silence.
    for jitter in (0.05, 0.15, 0.25, 0.40, 0.10, 0.35):
        clock.advance(jitter)
        assert gate.should_emit_silence() is False, f"jitter {jitter}s wrongly emitted silence"
        gate.audio_received()


def test_sustained_quiet_emits_silence():
    clock = FakeClock()
    gate = KeepAliveGate(quiet_seconds=1.5, clock=clock)
    gate.audio_received()

    clock.advance(1.49)
    assert gate.should_emit_silence() is False

    clock.advance(0.02)
    assert gate.should_emit_silence() is True
    # Stays true until audio returns
    clock.advance(5.0)
    assert gate.should_emit_silence() is True


def test_audio_return_resets_quiet_timer():
    clock = FakeClock()
    gate = KeepAliveGate(quiet_seconds=1.5, clock=clock)

    clock.advance(10.0)
    assert gate.should_emit_silence() is True

    gate.audio_received()
    assert gate.should_emit_silence() is False
    clock.advance(0.3)
    assert gate.should_emit_silence() is False


def test_stream_start_counts_as_recent_audio():
    # A freshly opened stream must not open with injected silence while the
    # first chunk is in flight.
    clock = FakeClock()
    gate = KeepAliveGate(quiet_seconds=1.5, clock=clock)
    clock.advance(0.4)
    assert gate.should_emit_silence() is False


def test_seconds_since_audio_tracks_clock():
    clock = FakeClock()
    gate = KeepAliveGate(quiet_seconds=1.5, clock=clock)
    gate.audio_received()
    clock.advance(0.75)
    assert abs(gate.seconds_since_audio() - 0.75) < 1e-9
