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

"""Duration-based release of buffered PCM to the Icecast encoder.

``IcecastStreamer._feed_loop`` used to hand FFmpeg exactly one buffered
chunk per chunk it read from the source -- one in, one out. That keeps
real time only while every chunk is the same length. Injected EAS audio
is always cut into 50 ms chunks (``eas_stream_injector``), but a stream
source's live chunks are ``buffer_size`` frames: 4096 frames at 48 kHz
is 85 ms. During an alert each 85 ms of live input therefore released
only 50 ms of alert audio, so the alert reached listeners at ~59% of real
time -- stretched over ~30 s with gaps that sounded like buffer
underruns -- until the backlog drained.

``ByteCreditPacer`` releases buffered audio by *duration* instead: every
byte of PCM read in earns one byte of PCM out, whatever the chunk sizes
on either side. The cushion of banked audio stays constant in time
rather than in chunk count.
"""

from collections import deque


class ByteCreditPacer:
    """Track how many PCM bytes may be written for what has been read."""

    def __init__(self) -> None:
        self._credit = 0

    def earn(self, n_bytes: int) -> None:
        """Credit *n_bytes* of PCM that just arrived from the source."""
        self._credit += max(0, int(n_bytes))

    def earn_one_chunk(self, buffer: deque) -> None:
        """Credit the next buffered chunk -- used when a read timed out.

        Matches the old one-in/one-out behaviour on a starved source: a
        timeout still lets one banked chunk through, so the cushion drains
        gradually instead of the encoder stalling outright.
        """
        if buffer:
            self._credit = max(self._credit, len(buffer[0]))

    def release(self, buffer: deque) -> list:
        """Pop and return the buffered chunks the current credit pays for.

        A chunk is released whenever any credit remains, so a partial
        credit is carried as a (bounded) debt into the next read rather
        than holding a chunk back. Credit never accumulates while the
        buffer is empty, so an idle period cannot later turn into a burst.
        """
        out = []
        while buffer and self._credit > 0:
            chunk = buffer.popleft()
            self._credit -= len(chunk)
            out.append(chunk)
        if not buffer and self._credit > 0:
            self._credit = 0
        return out


__all__ = ["ByteCreditPacer"]
