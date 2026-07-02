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
Stateful streaming resamplers for the EAS ingest path.

The capture loop hands `_resample_for_eas()` one ~100 ms chunk at a time.
Resampling each chunk independently is subtly wrong in two ways:

  1. Polyphase path (44.1 kHz → 16 kHz etc.): `scipy.signal.resample_poly`
     assumes zeros outside the block, so every chunk boundary carries a
     filter edge transient — measured at up to ~13 % of signal amplitude,
     ~10 events/second.  That is a continuous low-level crackle in the audio
     the SAME decoder and the alert recorder consume, and it erodes FSK
     decode margin.

  2. Integer-decimation path (48 kHz → 16 kHz): trimming ``len % factor``
     samples per chunk silently drops audio whenever the chunk length is not
     divisible by the factor (e.g. 4096-sample chunks at factor 3 lose one
     sample per chunk — a click and ~10 samples/second of clock drift).

Both classes below carry their state across chunks so the concatenated
output is identical to resampling the whole stream at once (verified to
below -60 dB in tests/test_eas_resampler.py).

``StreamingPolyphaseResampler`` uses overlap-save: input is consumed in
blocks that are multiples of ``down`` (so the polyphase phase is identical
at every block start), with ``context`` history samples re-filtered on each
side of the emitted region so no filter edge ever lands in the output.
"""

import logging
from math import gcd
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class StreamingPolyphaseResampler:
    """Chunk-streaming wrapper around scipy's polyphase resampler.

    Feed arbitrary-length chunks via :meth:`process`; the concatenated output
    matches a single whole-signal ``resample_poly`` call except for the first
    ``context`` input samples of pure latency (a few milliseconds).
    """

    def __init__(self, source_rate: int, target_rate: int):
        from scipy.signal import firwin

        self.source_rate = int(source_rate)
        self.target_rate = int(target_rate)
        g = gcd(self.source_rate, self.target_rate)
        self.up = self.target_rate // g
        self.down = self.source_rate // g

        # Same FIR design scipy uses internally for resample_poly defaults.
        max_rate = max(self.up, self.down)
        half_len = 10 * max_rate
        self._taps = firwin(2 * half_len + 1, 1.0 / max_rate, window=('kaiser', 5.0))

        # Filter half-span in input samples, rounded up to a multiple of
        # ``down`` so both the emitted region offset and every block start
        # stay phase-aligned (input index ≡ 0 mod down).
        half_span_in = int(np.ceil((half_len + 1) / self.up))
        self.context = int(np.ceil(half_span_in / self.down)) * self.down
        # Output samples produced per ``context`` input samples (exact:
        # context is a multiple of down).
        self._context_out = self.context * self.up // self.down

        # Pending input.  Seeded with ``context`` zeros so the very first
        # emitted sample has the same zero history a whole-signal
        # resample_poly call assumes.
        self._pending = np.zeros(self.context, dtype=np.float32)

    def process(self, chunk: np.ndarray) -> np.ndarray:
        """Resample the next chunk of the stream.

        Args:
            chunk: 1-D float array of samples at ``source_rate``.

        Returns:
            1-D float32 array at ``target_rate`` (possibly empty while the
            initial context fills).
        """
        from scipy.signal import resample_poly

        if chunk is not None and len(chunk) > 0:
            self._pending = np.concatenate(
                [self._pending, np.asarray(chunk, dtype=np.float32).flatten()]
            )

        # Emit for input region [context, context + block); keep ``context``
        # samples after the block as right-hand filter support.
        available = len(self._pending) - 2 * self.context
        block = (available // self.down) * self.down
        if block <= 0:
            return np.empty(0, dtype=np.float32)

        segment = self._pending[: block + 2 * self.context]
        resampled = resample_poly(
            segment, self.up, self.down, window=self._taps.copy()
        )
        out = resampled[self._context_out: self._context_out + block * self.up // self.down]

        # Drop the emitted input; what remains (context + unaligned tail)
        # becomes the left context of the next block.  ``block`` is a
        # multiple of ``down`` so the next block starts phase-aligned.
        self._pending = self._pending[block:]
        return np.asarray(out, dtype=np.float32)


class StreamingIntegerDecimator:
    """Box-average decimation that carries remainder samples across chunks.

    Replaces the per-chunk ``trimmed = chunk[:n - (n % factor)]`` pattern,
    which silently dropped up to ``factor - 1`` samples on every chunk whose
    length was not a multiple of the factor.
    """

    def __init__(self, factor: int):
        self.factor = int(factor)
        self._remainder = np.empty(0, dtype=np.float32)

    def process(self, chunk: np.ndarray) -> np.ndarray:
        x = np.concatenate(
            [self._remainder, np.asarray(chunk, dtype=np.float32).flatten()]
        )
        usable = (len(x) // self.factor) * self.factor
        self._remainder = x[usable:]
        if usable == 0:
            return np.empty(0, dtype=np.float32)
        return x[:usable].reshape(-1, self.factor).mean(axis=1).astype(np.float32)


def make_eas_resampler(source_rate: int, target_rate: int = 16000):
    """Return the appropriate stateful resampler for a source rate.

    Integer ratios get the cheap box decimator (adequate anti-aliasing for
    SAME tones, ~5-10x faster); everything else gets the streaming polyphase.
    Returns ``None`` when no resampling is needed.
    """
    source_rate = int(source_rate)
    target_rate = int(target_rate)
    if source_rate == target_rate:
        return None
    if source_rate % target_rate == 0:
        return StreamingIntegerDecimator(source_rate // target_rate)
    return StreamingPolyphaseResampler(source_rate, target_rate)
