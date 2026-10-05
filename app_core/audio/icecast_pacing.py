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

from __future__ import annotations

"""Real-time release of buffered PCM to the Icecast encoder.

``IcecastStreamer._feed_loop`` used to hand FFmpeg exactly one buffered
chunk per chunk it read from the source -- one in, one out. That keeps
real time only while every chunk is the same length. Injected EAS audio
is cut into 50 ms chunks, but a stream source's live chunks are 4096
frames (85 ms at 48 kHz), so an alert reached listeners at ~59% of real
time, stretched over ~30 s with gaps.

Counting bytes read instead of chunks fixed alerts but not bursty
sources: an HTTP stream delivers several chunks at once, the feed loop
reads one and drains the rest, and only the first earned output -- WNCI
ran at ~70% of real time and listeners' players kept dropping out.

``RealTimePacer`` releases by the wall clock instead: each second that
passes releases one second of audio, whatever the chunk sizes, bursts or
injections on the input side. The local buffer is the jitter cushion.
When the cushion grows past ``high_water_s`` (an injected alert banks its
whole length at once) release runs ``catch_up`` faster so latency drains
back down; listeners' players absorb a 2% faster feed without any audible
change.
"""

import time
from collections import deque
from typing import Callable, Optional


class RealTimePacer:
    """Release buffered PCM chunks at the stream's real-time byte rate."""

    def __init__(
        self,
        bytes_per_second: Callable[[], float],
        high_water_s: float = 20.0,
        catch_up: float = 1.02,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bytes_per_second = bytes_per_second
        self._high_water_s = high_water_s
        self._catch_up = catch_up
        self._clock = clock
        self._last: Optional[float] = None
        self._credit = 0.0

    def release(self, buffer: deque) -> list:
        """Pop and return the chunks the elapsed time pays for.

        Credit never accumulates while the buffer is empty, so a starved
        period cannot later turn into a burst.
        """
        now = self._clock()
        rate = max(1.0, float(self._bytes_per_second()))
        if self._last is not None:
            elapsed = max(0.0, now - self._last)
            if buffer and sum(map(len, buffer)) > self._high_water_s * rate:
                rate *= self._catch_up
            self._credit += elapsed * rate
        self._last = now

        out = []
        while buffer and self._credit > 0:
            chunk = buffer.popleft()
            self._credit -= len(chunk)
            out.append(chunk)
        if not buffer and self._credit > 0:
            self._credit = 0.0
        return out


__all__ = ["RealTimePacer"]
