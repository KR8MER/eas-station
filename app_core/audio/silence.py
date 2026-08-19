from __future__ import annotations
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

"""Dead-air detection for monitored audio sources.

Every other health check in this system watches *process* liveness --
service up, Redis reachable, SDR locked, buffers healthy. All of those can
be green while the audio itself is dead: the station went off the air, the
antenna dropped, ffmpeg wedged, the USB audio device vanished. For an EAS
monitoring station that gap matters, because a silently dead assigned
source means you have stopped monitoring it and nothing says so.

Why a level threshold alone is not enough
-----------------------------------------
The obvious detector -- ``rms_dbfs < -60`` -- works for a stopped file or a
dead stream, where the samples really are near zero. It fails completely on
the case that matters most here, an SDR tuned to an FM station that has
gone off the air: the receiver then outputs *unsquelched noise*, full-scale
hiss sitting tens of dB above any sane silence threshold. A level-only
detector happily reports "audio present" while the operator hears static.

So this module classifies on two independent axes:

``level``
    RMS below a threshold. Catches true digital silence -- a stopped
    source, a muted feed, a dead stream.

``flatness``
    Spectral flatness (Wiener entropy): the geometric mean of the power
    spectrum divided by its arithmetic mean. Noise spreads its energy
    evenly across the band and scores near 1.0; speech and music
    concentrate energy into harmonics and formants and score orders of
    magnitude lower. Measured on synthetic references: FM hiss 0.40-0.57,
    speech-like 0.001, music-like and steady tones < 0.001. That is a
    two-to-three order of magnitude separation, so the threshold between
    them is not delicate.

A chunk is silent when *either* fires. Both are configurable, and the
flatness axis can be switched off for sources where it does not apply.

Timing lives in :class:`app_core.audio.metering.SilenceDetector`, which
already implements duration debouncing, recovery ("signal restored")
detection and an alert-callback fan-out. This module supplies the verdict
and lets that class own the state machine, rather than adding yet another
parallel implementation of the same timing logic.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

#: Station-wide criteria, installed once by the monitoring service from
#: HardwareSettings and picked up by every source adapter as it is built.
#: Dead-air thresholds are a station policy, not a per-source knob, and
#: audio sources are constructed from eight different call sites -- a
#: module-level default keeps them all consistent without threading the
#: settings through every one of them, and without giving app_core.audio
#: a dependency on Flask or the database.
_DEFAULT_CRITERIA_LOCK = threading.Lock()
_DEFAULT_CRITERIA: "SilenceCriteria" = None  # type: ignore[assignment]


def set_default_criteria(criteria: "SilenceCriteria") -> None:
    """Install the station-wide dead-air criteria.

    Applies to sources built after this call. Existing monitors are
    updated by their owner via :meth:`SilenceMonitor.update_criteria`.
    """
    global _DEFAULT_CRITERIA
    with _DEFAULT_CRITERIA_LOCK:
        _DEFAULT_CRITERIA = criteria.sanitized()


def get_default_criteria() -> "SilenceCriteria":
    """Return the station-wide criteria (monitoring off until configured)."""
    with _DEFAULT_CRITERIA_LOCK:
        if _DEFAULT_CRITERIA is None:
            return SilenceCriteria(enabled=False)
        return _DEFAULT_CRITERIA


__all__ = [
    "set_default_criteria",
    "get_default_criteria",
    "criteria_from_source_config",
    "SilenceCriteria",
    "SilenceVerdict",
    "SilenceMonitor",
    "spectral_flatness",
    "DEFAULT_LEVEL_THRESHOLD_DB",
    "DEFAULT_FLATNESS_THRESHOLD",
    "DEFAULT_DURATION_SECONDS",
]

#: RMS below this reads as silence regardless of spectrum. Deliberately
#: deep: a soft passage of real programme audio can sit near -55 dBFS, and
#: alarming on that would be a false positive. True digital silence is far
#: below (a muted-but-dithered source lands around -90 dBFS, a stopped one
#: at the float floor), so -65 separates them with room to spare. The
#: flatness axis -- not this one -- is what catches a dead FM carrier.
DEFAULT_LEVEL_THRESHOLD_DB = -65.0

#: Spectral flatness above this reads as structureless noise (dead carrier
#: hiss). Measured references sit at 0.40+ for hiss and below 0.01 for
#: programme material, so 0.25 is comfortably inside the gap.
DEFAULT_FLATNESS_THRESHOLD = 0.25

#: How long the silent condition must hold before it is reported. Broadcast
#: silence sensors conventionally use 10-30 s; short enough to catch a real
#: outage, long enough to ride over pauses between programme elements.
DEFAULT_DURATION_SECONDS = 20.0

#: FFT size for the flatness estimate. 1024 bins is plenty to tell noise
#: from voice and costs microseconds at the 10 Hz metrics cadence.
_FLATNESS_NFFT = 1024

#: Below this RMS the spectrum is numerically meaningless (dither and
#: rounding noise look perfectly flat), so flatness is not consulted --
#: the level axis has already decided such a chunk is silent anyway.
_FLATNESS_FLOOR_DBFS = -80.0


def spectral_flatness(samples, nfft: int = _FLATNESS_NFFT) -> Optional[float]:
    """Return the spectral flatness (Wiener entropy) of ``samples``.

    Flatness is ``geometric_mean(P) / arithmetic_mean(P)`` over the power
    spectrum ``P``. It is scale-invariant, so it does not care how loud the
    signal is -- only how evenly its energy is spread. That is exactly the
    property needed to tell full-scale FM hiss from actual programme audio.

    Args:
        samples: 1-D array of mono float samples.
        nfft: FFT size. Chunks shorter than this return ``None``.

    Returns:
        Float in ``(0.0, 1.0]`` -- near 1.0 for white noise, orders of
        magnitude lower for speech, music or tones -- or ``None`` when the
        chunk is too short to measure.
    """
    try:
        import numpy as np
    except ImportError:      # pragma: no cover - numpy is a hard dependency
        return None

    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if x.size < nfft:
        return None

    window = np.hanning(nfft)
    values = []
    # Median over several frames so one transient cannot swing the verdict.
    for start in range(0, x.size - nfft + 1, nfft // 2):
        frame = x[start:start + nfft] * window
        power = np.abs(np.fft.rfft(frame)) ** 2
        power = power[1:]                      # drop DC
        if power.size == 0:
            continue
        power = np.maximum(power, 1e-20)
        geometric = np.exp(np.mean(np.log(power)))
        arithmetic = np.mean(power)
        if arithmetic <= 0:
            continue
        values.append(geometric / arithmetic)

    if not values:
        return None
    return float(np.median(values))


@dataclass
class SilenceCriteria:
    """Thresholds deciding whether a chunk of audio counts as silence."""

    enabled: bool = True
    level_threshold_db: float = DEFAULT_LEVEL_THRESHOLD_DB
    #: Detect an open carrier / off-air hiss via spectral flatness. Leave
    #: on for SDR sources; it is the only axis that catches a dead FM
    #: station, whose noise sits far above any level threshold.
    detect_open_carrier: bool = True
    flatness_threshold: float = DEFAULT_FLATNESS_THRESHOLD
    duration_seconds: float = DEFAULT_DURATION_SECONDS

    def sanitized(self) -> "SilenceCriteria":
        """Return a copy with values clamped into sane ranges."""
        return SilenceCriteria(
            enabled=bool(self.enabled),
            level_threshold_db=float(
                min(0.0, max(-120.0, self.level_threshold_db))
            ),
            detect_open_carrier=bool(self.detect_open_carrier),
            flatness_threshold=float(
                min(1.0, max(0.0, self.flatness_threshold))
            ),
            duration_seconds=float(max(1.0, self.duration_seconds)),
        )


def criteria_from_source_config(config) -> "SilenceCriteria":
    """Build one source's dead-air criteria from its own config.

    Dead-air is a per-source policy (see the module docstring's "not a
    per-source knob" note above -- that was true until a station-wide
    policy proved unworkable for a source that's supposed to be silent
    except when relaying an actual alert, like a state relay or
    alert-only feed). ``config`` is anything carrying the ``dead_air_*``
    attributes -- normally an ``AudioSourceConfig``
    (``app_core/audio/ingest.py``), but any object or dict-like shim with
    the same attribute names works, which is what lets both the
    integrated-mode write routes and the separated-architecture Redis
    command handlers share this one implementation instead of drifting
    apart the way ``silence_threshold_db`` handling nearly did across its
    eight call sites.
    """
    return SilenceCriteria(
        enabled=bool(getattr(config, "dead_air_enabled", False)),
        level_threshold_db=float(
            getattr(config, "dead_air_level_threshold_db", -65.0) or -65.0
        ),
        detect_open_carrier=bool(
            getattr(config, "dead_air_detect_open_carrier", True)
        ),
        # Stored as whole percent on the config object; the monitor wants
        # a 0-1 ratio.
        flatness_threshold=float(
            getattr(config, "dead_air_flatness_threshold_pct", 25) or 25
        ) / 100.0,
        duration_seconds=float(
            getattr(config, "dead_air_duration_seconds", 20.0) or 20.0
        ),
    )


@dataclass
class SilenceVerdict:
    """The result of classifying one chunk of audio."""

    is_silent: bool
    #: ``'level'``, ``'open_carrier'``, ``'audio'`` or ``'disabled'``.
    reason: str
    level_db: float
    flatness: Optional[float] = None

    def describe(self) -> str:
        """Human-readable one-liner for logs and the UI."""
        if self.reason == "level":
            return f"no audio ({self.level_db:.1f} dBFS)"
        if self.reason == "open_carrier":
            flat = f"{self.flatness:.2f}" if self.flatness is not None else "?"
            return (
                f"open carrier / no modulation "
                f"({self.level_db:.1f} dBFS, flatness {flat})"
            )
        if self.reason == "disabled":
            return "silence monitoring disabled"
        return f"audio present ({self.level_db:.1f} dBFS)"


def classify(
    samples,
    level_db: float,
    criteria: SilenceCriteria,
) -> SilenceVerdict:
    """Classify one chunk as silence or audio.

    Args:
        samples: Mono float samples for the chunk (may be ``None`` to skip
            the spectral axis and decide on level alone).
        level_db: RMS level of the chunk in dBFS.
        criteria: Thresholds to apply.

    Returns:
        A :class:`SilenceVerdict`.
    """
    if not criteria.enabled:
        return SilenceVerdict(False, "disabled", level_db, None)

    # Axis 1 -- true digital silence.
    if level_db < criteria.level_threshold_db:
        return SilenceVerdict(True, "level", level_db, None)

    # Axis 2 -- structureless noise at any level (the off-air FM case).
    flatness: Optional[float] = None
    if criteria.detect_open_carrier and samples is not None:
        if level_db > _FLATNESS_FLOOR_DBFS:
            flatness = spectral_flatness(samples)
        if flatness is not None and flatness >= criteria.flatness_threshold:
            return SilenceVerdict(True, "open_carrier", level_db, flatness)

    return SilenceVerdict(False, "audio", level_db, flatness)


class SilenceMonitor:
    """Debounced dead-air monitor for a single audio source.

    Classifies each chunk with :func:`classify`, then defers the timing to
    :class:`app_core.audio.metering.SilenceDetector` so the duration
    debounce, the recovery edge and the alert fan-out all come from the
    one implementation that already had them.

    Thread-safe: ``process`` may be called from the ingest thread while
    ``snapshot`` is read by the metrics publisher.
    """

    def __init__(
        self,
        source_name: str,
        criteria: Optional[SilenceCriteria] = None,
        on_change: Optional[Callable[[str, bool, SilenceVerdict], None]] = None,
    ) -> None:
        from .metering import SilenceDetector

        self.source_name = source_name
        self._criteria = (
            criteria.sanitized() if criteria is not None
            else get_default_criteria()
        )
        self._on_change = on_change
        self._lock = threading.Lock()
        self._last_verdict = SilenceVerdict(False, "audio", 0.0, None)
        self._detector = SilenceDetector(
            silence_threshold_db=self._criteria.level_threshold_db,
            silence_duration_seconds=self._criteria.duration_seconds,
            # Always debounce, including the very first chunk: a service
            # restart where the source has not yet produced audio must not
            # fire the rack buzzer before the duration has elapsed.
            assume_prior_signal=True,
        )
        self._was_silent = False
        self._silent_since: Optional[float] = None

    def update_criteria(self, criteria: SilenceCriteria) -> None:
        """Apply new thresholds without losing the current state."""
        clean = criteria.sanitized()
        with self._lock:
            self._criteria = clean
            self._detector.silence_threshold_db = clean.level_threshold_db
            self._detector.silence_duration_seconds = clean.duration_seconds

    @property
    def criteria(self) -> SilenceCriteria:
        with self._lock:
            return self._criteria

    def process(self, samples, level_db: float) -> SilenceVerdict:
        """Feed one chunk in and return its verdict.

        The returned verdict is the *instantaneous* classification. Use
        :meth:`is_silent` for the debounced state that alarms should act
        on -- an instantaneous verdict flips on every pause between words
        and is not something to wire a buzzer to.
        """
        with self._lock:
            criteria = self._criteria

        verdict = classify(samples, level_db, criteria)

        # Hand the detector a verdict rather than a level, so the same
        # duration/recovery machinery covers the open-carrier axis too.
        self._detector.process_audio_level(
            level_db,
            source_name=self.source_name,
            is_silent_override=verdict.is_silent if criteria.enabled else False,
            detail=verdict.describe(),
        )

        now_silent = self._detector.is_silent()
        with self._lock:
            self._last_verdict = verdict
            changed = now_silent != self._was_silent
            self._was_silent = now_silent
            if changed:
                self._silent_since = time.time() if now_silent else None
            callback = self._on_change

        if changed and callback is not None:
            try:
                callback(self.source_name, now_silent, verdict)
            except Exception as exc:
                logger.error(
                    "Silence monitor callback failed for %s: %s",
                    self.source_name, exc,
                )
        return verdict

    def is_silent(self) -> bool:
        """Debounced state: True once silence has held for the duration."""
        return self._detector.is_silent()

    def silence_duration(self) -> float:
        """Seconds the debounced silence state has been active (0 if not)."""
        if not self._detector.is_silent():
            return 0.0
        with self._lock:
            started = self._silent_since
        return time.time() - started if started else 0.0

    def reset(self) -> None:
        """Clear all state (e.g. after a source restart)."""
        self._detector.reset()
        with self._lock:
            self._was_silent = False
            self._silent_since = None

    def snapshot(self) -> Dict[str, Any]:
        """JSON-safe view for Redis publication and the UI."""
        with self._lock:
            verdict = self._last_verdict
            criteria = self._criteria
        silent = self._detector.is_silent()
        return {
            "enabled": criteria.enabled,
            "silent": silent,
            "reason": verdict.reason,
            "detail": verdict.describe(),
            "level_db": round(float(verdict.level_db), 1),
            "flatness": (
                round(float(verdict.flatness), 4)
                if verdict.flatness is not None else None
            ),
            "silence_duration_seconds": round(self.silence_duration(), 1),
            "level_threshold_db": criteria.level_threshold_db,
            "flatness_threshold": criteria.flatness_threshold,
            "duration_seconds": criteria.duration_seconds,
            "detect_open_carrier": criteria.detect_open_carrier,
        }
