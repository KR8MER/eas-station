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

"""
Keep-alive silence policy for live audio streaming endpoints.

The live listen streams (web WAV stream, EAS decoder MP3 feeds) read audio
chunks from a broadcast-queue subscription with a timeout.  The old code
wrote a block of zeros into the stream on EVERY timeout.  Because chunks
arrive at ~100 ms cadence and the timeouts were 100-200 ms, any scheduling
or network jitter made the read race its own producer: a chunk arriving a
few milliseconds late became an injected 50-100 ms silence block spliced
into the middle of continuous audio, with the real chunk playing AFTER the
gap.  That is audible stuttering, it happens several times per second under
load, and every injection pushes the stream further behind real time until
the subscription queue overflows and real audio is dropped as well.

The correct behaviour, implemented by :class:`KeepAliveGate`:

  * Transient jitter (queue momentarily empty): emit NOTHING.  The browser
    or ffmpeg simply waits a few ms for the late chunk; playback continuity
    is preserved and the stream never drifts.
  * Source genuinely quiet (no audio for ``quiet_seconds``, e.g. the source
    stopped): emit paced keep-alive silence so the HTTP connection, ffmpeg
    pipeline, and browser element stay alive until audio returns.
"""

import time
from typing import Callable, Optional


class KeepAliveGate:
    """Decides when a streaming endpoint may emit keep-alive silence.

    Args:
        quiet_seconds: How long a source must be continuously silent before
            keep-alive silence is emitted.  Must be comfortably larger than
            the chunk cadence (~0.1 s) so jitter never qualifies.
        clock: Injectable monotonic clock (for tests).
    """

    def __init__(self, quiet_seconds: float = 1.5, clock: Optional[Callable[[], float]] = None):
        self.quiet_seconds = float(quiet_seconds)
        self._clock = clock or time.monotonic
        # Treat stream start as "just heard audio" so a slow first chunk
        # doesn't open with injected silence.
        self._last_audio = self._clock()

    def audio_received(self) -> None:
        """Record that a real audio chunk was just delivered."""
        self._last_audio = self._clock()

    def should_emit_silence(self) -> bool:
        """True only when the source has been quiet for ``quiet_seconds``.

        A momentary queue-empty (late chunk) returns False — the caller
        must simply wait instead of splicing zeros into the stream.
        """
        return (self._clock() - self._last_audio) >= self.quiet_seconds

    def seconds_since_audio(self) -> float:
        """Elapsed seconds since the last real audio chunk."""
        return self._clock() - self._last_audio
