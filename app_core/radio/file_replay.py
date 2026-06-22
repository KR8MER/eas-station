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

IQ file replay receiver driver.

This driver streams a previously-captured ``complex64`` ``.npy`` file
into the existing radio pipeline so SDR Diagnostics, the RBDS Decoder
Health card, and the audio source enumerator see it exactly like a live
SDR.  The intended use is regression-testing decoder changes (e.g. the
early-decimation bug captured in ``bugs/iq_sdr_*.npy``) without needing
real RTL-SDR / Airspy hardware.

Design notes
------------
* The file path is stored in the existing ``ReceiverConfig.serial``
  field as a basename and resolved against ``RADIO_REPLAY_DIR`` so we
  don't need a database migration.  The replay directory defaults to
  ``RADIO_CAPTURE_DIR`` (where ``capture_iq`` writes its outputs), so a
  capture-then-replay round trip is one click in the UI.

* A worker thread emits fixed-size chunks (~50 ms) at wall-clock pace
  matching ``config.sample_rate``, using the same ``_capture_tap_append``
  publisher tap as the live SoapySDR drivers.  This means the existing
  ``capture_iq`` action works on a replay receiver too, which is useful
  for verifying that a fix observed in the UI also lands bit-identical
  on disk.

* Sample data is memory-mapped (``np.load(..., mmap_mode='r')``) so
  multi-hundred-MB captures don't blow up RAM.

* EOF policy is "loop" by default, so the dashboard keeps decoding
  forever.  This matches operator expectations from offline-DSP tools
  like ``gqrx`` / ``inspectrum``.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .manager import (
    ReceiverConfig,
    ReceiverInterface,
    ReceiverStatus,
    RadioManager,
)


# Default replay directory.  Mirrors the capture directory used by the
# capture_iq command so files written by capture_iq are immediately
# eligible for replay.  Operators can override via the ``RADIO_REPLAY_DIR``
# environment variable when they keep curated fixtures elsewhere.
DEFAULT_REPLAY_DIR = "/var/log/eas-station/captures"


def get_replay_dir() -> str:
    """Return the directory replay files must live under.

    Lookup order matches the rest of the radio stack:
    1. ``RADIO_REPLAY_DIR`` env var (explicit override).
    2. ``RADIO_CAPTURE_DIR`` env var (so captures replay without copy).
    3. ``DEFAULT_REPLAY_DIR``.
    """
    return os.environ.get(
        "RADIO_REPLAY_DIR",
        os.environ.get("RADIO_CAPTURE_DIR", DEFAULT_REPLAY_DIR),
    )


def resolve_replay_path(name: Optional[str]) -> Path:
    """Resolve ``name`` to an absolute path under the replay directory.

    The argument is treated as a path *relative to* ``get_replay_dir()``.
    Absolute paths, ``..`` segments, or anything that resolves outside
    the replay directory are rejected to prevent arbitrary filesystem
    reads via the receiver config.

    Raises
    ------
    ValueError
        If ``name`` is empty or escapes the replay directory.
    FileNotFoundError
        If the resolved path does not exist.
    """
    if not name:
        raise ValueError(
            "File replay receiver requires a file path (set the device "
            "serial field to a .npy file name under RADIO_REPLAY_DIR)."
        )

    replay_dir = Path(get_replay_dir()).resolve()
    # Strip an optional ``file:`` prefix so operators can prefix paths
    # explicitly to disambiguate from real serial numbers.
    raw = name[5:] if name.lower().startswith("file:") else name
    raw = raw.strip()
    if not raw:
        raise ValueError("File replay path is empty.")

    candidate = (replay_dir / raw).resolve()
    try:
        candidate.relative_to(replay_dir)
    except ValueError as exc:
        raise ValueError(
            f"File replay path {raw!r} is outside the replay directory "
            f"{replay_dir!s}."
        ) from exc

    if not candidate.is_file():
        raise FileNotFoundError(f"File replay path does not exist: {candidate}")

    return candidate


class FileReplayReceiver(ReceiverInterface):
    """Stream a complex64 ``.npy`` IQ capture through the radio pipeline.

    The class deliberately mimics the surface area of the SoapySDR
    receivers (``get_samples`` / ``get_effective_sample_rate`` /
    ``is_running`` / ``capture_to_file``) so the publisher thread in
    ``sdr_hardware_service.publish_samples_and_metrics`` can consume
    from it without a special case.
    """

    # Worker chunk duration in seconds.  50 ms ≈ the cadence of a live
    # SDR USB read at 250 kHz, which keeps the downstream pipeline's
    # latency profile identical between live and replay sources.
    _CHUNK_SECONDS = 0.05

    # Loop policy at EOF.  Always loop for now; a future enhancement may
    # surface "stop on EOF" through ``ReceiverConfig`` so one-shot replay
    # captures can be A/B-compared end-to-end.
    _LOOP_AT_EOF = True

    def __init__(
        self,
        config: ReceiverConfig,
        *,
        event_logger=None,
    ) -> None:
        super().__init__(config, event_logger=event_logger)

        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status_lock = threading.Lock()
        self._status = ReceiverStatus(identifier=config.identifier, locked=False)

        # Sample buffer + cursor.  Loaded lazily on ``start`` so a
        # configuration error doesn't crash the manager during boot.
        self._samples = None
        self._sample_count = 0
        self._cursor = 0
        self._cursor_lock = threading.Lock()

        # Last delivered chunk, exposed via ``get_samples``.  The
        # publisher reads at the same cadence we produce, so a single
        # latched chunk is sufficient.
        self._latched_lock = threading.Lock()
        self._latched_chunk = None
        self._latched_signal_strength: Optional[float] = None

        # Resolved file path (None until ``start`` validates the config).
        self._resolved_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # ReceiverInterface implementation
    # ------------------------------------------------------------------
    def is_running(self) -> bool:  # noqa: D401 - documented in base class
        return self._running.is_set()

    def start(self) -> None:  # noqa: D401 - documented in base class
        if self._running.is_set():
            return

        try:
            import numpy as np  # noqa: F401 - probed for availability
        except ImportError as exc:
            self._update_status(
                locked=False,
                last_error=f"numpy not available for file replay: {exc}",
            )
            raise

        try:
            self._resolved_path = resolve_replay_path(self.config.serial)
        except (ValueError, FileNotFoundError) as exc:
            self._interface_logger.error(
                "FileReplayReceiver %s: cannot resolve replay path: %s",
                self.config.identifier,
                exc,
            )
            self._update_status(locked=False, last_error=str(exc))
            raise

        try:
            self._load_samples()
        except Exception as exc:
            self._interface_logger.error(
                "FileReplayReceiver %s: failed to load %s: %s",
                self.config.identifier,
                self._resolved_path,
                exc,
            )
            self._update_status(locked=False, last_error=str(exc))
            raise

        self._running.set()
        self._update_status(locked=True, last_error=None)
        self._emit_event(
            "INFO",
            f"File replay started: {self._resolved_path.name}",
            details={
                "path": str(self._resolved_path),
                "sample_count": self._sample_count,
                "sample_rate": self.config.sample_rate,
                "duration_sec": (
                    self._sample_count / self.config.sample_rate
                    if self.config.sample_rate > 0
                    else 0.0
                ),
            },
        )

        thread_name = f"FileReplayReceiver-{self.config.identifier}"
        self._thread = threading.Thread(
            target=self._replay_loop, name=thread_name, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:  # noqa: D401 - documented in base class
        if not self._running.is_set():
            return
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._update_status(locked=False)
        self._emit_event(
            "INFO",
            f"File replay stopped: {self.config.identifier}",
        )

    def get_status(self) -> ReceiverStatus:  # noqa: D401 - documented in base class
        with self._status_lock:
            # Return a copy so external callers can't mutate our state.
            return ReceiverStatus(
                identifier=self._status.identifier,
                locked=self._status.locked,
                signal_strength=self._status.signal_strength,
                last_error=self._status.last_error,
                capture_mode=self._status.capture_mode,
                capture_path=self._status.capture_path,
                reported_at=self._status.reported_at or datetime.now(timezone.utc),
            )

    def capture_to_file(
        self,
        duration_seconds: float,
        output_dir: Path,
        prefix: str,
        *,
        mode: str = "iq",
    ) -> Path:
        """Persist the next ``duration_seconds`` of replayed samples.

        This is a best-effort implementation that snapshots the current
        latched chunk and slices the underlying file to the requested
        duration. It's primarily useful for round-trip tests; the
        ``capture_iq`` Redis action driven by the publisher tap is the
        production path.
        """
        import numpy as np

        if self._samples is None:
            raise RuntimeError(
                "FileReplayReceiver has no loaded samples; call start() first."
            )

        rate = max(1, int(self.config.sample_rate))
        n = min(self._sample_count, int(max(0.0, duration_seconds) * rate))
        if n <= 0:
            raise ValueError("duration_seconds must produce at least one sample")

        with self._cursor_lock:
            start = self._cursor
        end = start + n
        if end <= self._sample_count:
            payload = np.asarray(self._samples[start:end], dtype=np.complex64)
        else:
            wrap = end - self._sample_count
            payload = np.concatenate(
                [
                    np.asarray(self._samples[start:], dtype=np.complex64),
                    np.asarray(self._samples[:wrap], dtype=np.complex64),
                ]
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        suffix = (mode or "iq").lower()
        out_path = output_dir / f"{prefix}_{suffix}_{timestamp}.npy"
        np.save(out_path, payload)

        self._update_status(
            capture_mode=suffix,
            capture_path=str(out_path),
        )
        return out_path

    # ------------------------------------------------------------------
    # Pipeline compatibility shims (mirrors _SoapySDRReceiver)
    # ------------------------------------------------------------------
    def get_samples(self, num_samples: Optional[int] = None):
        """Return the most recently published chunk for the publisher thread.

        ``num_samples`` is accepted for parity with the SoapySDR driver
        but ignored: we always return the whole latched chunk so the
        publisher sees the same chunk cadence we emit.
        """
        if not self._running.is_set():
            return None

        with self._latched_lock:
            chunk = self._latched_chunk
            if chunk is None:
                return None
            # Detach from the latched reference so the publisher can
            # safely mutate / forward the array.
            self._latched_chunk = None
            return chunk

    def get_effective_sample_rate(self) -> int:
        """Replay files are already at ``config.sample_rate`` (no decim)."""
        return int(self.config.sample_rate)

    def get_ring_buffer_stats(self) -> Optional[dict]:
        """Provide a minimal stats payload so the diagnostics UI doesn't 500."""
        if not self._running.is_set() or self._samples is None:
            return None
        return {
            "size": self._sample_count,
            "fill_level": self._sample_count,
            "fill_percentage": 100.0,
            "samples_available": self._sample_count,
            "buffer_type": "file_replay",
            "total_samples_written": self._sample_count,
            "total_samples_read": int(self._cursor),
            "overflow_count": 0,
            "underflow_count": 0,
            "uptime_seconds": 0.0,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _load_samples(self) -> None:
        """Memory-map the configured ``.npy`` and validate its dtype."""
        import numpy as np

        assert self._resolved_path is not None
        try:
            arr = np.load(self._resolved_path, mmap_mode="r")
        except ValueError:
            # Pickle-format npys can't be mmap'd. Fall back to a regular
            # load so any user-provided file still works, just without the
            # mmap benefit.
            arr = np.load(self._resolved_path)

        if arr.ndim != 1:
            arr = arr.reshape(-1)

        if arr.dtype != np.complex64:
            try:
                arr = arr.astype(np.complex64, copy=False)
            except Exception as exc:
                raise ValueError(
                    f"Replay file {self._resolved_path} has unsupported "
                    f"dtype {arr.dtype!s}; expected complex64."
                ) from exc

        if arr.size == 0:
            raise ValueError(
                f"Replay file {self._resolved_path} contains no samples."
            )

        self._samples = arr
        self._sample_count = int(arr.size)
        self._cursor = 0

    def _replay_loop(self) -> None:
        """Worker thread: emit chunks at wall-clock pace."""
        import numpy as np

        rate = max(1, int(self.config.sample_rate))
        chunk_samples = max(1, int(rate * self._CHUNK_SECONDS))
        chunk_duration = chunk_samples / float(rate)
        next_emit = time.monotonic()

        try:
            while self._running.is_set():
                chunk = self._next_chunk(chunk_samples)
                if chunk is None:
                    # End-of-file and looping disabled; idle and let the
                    # operator restart explicitly.
                    self._update_status(locked=False, last_error="end of file")
                    break

                # Synthetic signal strength from chunk RMS magnitude.
                # Matches the convention the dashboard already uses for
                # the live SoapySDR drivers (linear magnitude in [0, 1]).
                try:
                    mag = float(np.sqrt(np.mean(np.abs(chunk) ** 2)))
                except Exception:  # pragma: no cover - defensive
                    mag = None

                with self._latched_lock:
                    self._latched_chunk = chunk
                    self._latched_signal_strength = mag

                self._update_status(locked=True, signal_strength=mag)

                # Sleep until the next chunk boundary.  Drift-free: we
                # advance ``next_emit`` by a fixed interval rather than
                # ``time.sleep(chunk_duration)`` so cumulative scheduler
                # error doesn't slow the stream below the requested rate.
                next_emit += chunk_duration
                delay = next_emit - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    # We fell behind real time.  Reset the schedule so we
                    # don't spin emitting back-to-back chunks forever.
                    next_emit = time.monotonic()
        except Exception as exc:  # pragma: no cover - defensive logging
            self._interface_logger.exception(
                "FileReplayReceiver %s worker crashed: %s",
                self.config.identifier,
                exc,
            )
            self._update_status(locked=False, last_error=str(exc))

    def _next_chunk(self, chunk_samples: int):
        """Return the next chunk of ``chunk_samples`` complex64 samples.

        Returns ``None`` when the file is exhausted and looping is
        disabled.
        """
        import numpy as np

        if self._samples is None or self._sample_count == 0:
            return None

        with self._cursor_lock:
            start = self._cursor
            end = start + chunk_samples

            if end <= self._sample_count:
                view = self._samples[start:end]
                self._cursor = end if end < self._sample_count else 0
                if end == self._sample_count and not self._LOOP_AT_EOF:
                    # Final chunk before stopping.
                    pass
                # Copy so the publisher can hold the chunk past the next
                # wrap. mmap'd arrays read lazily, so a real copy is the
                # safest contract here.
                return np.asarray(view, dtype=np.complex64).copy()

            if not self._LOOP_AT_EOF:
                # Emit what's left and then stop.
                view = self._samples[start:]
                self._cursor = self._sample_count
                if view.size == 0:
                    return None
                return np.asarray(view, dtype=np.complex64).copy()

            # Wrap around EOF.
            tail = np.asarray(self._samples[start:], dtype=np.complex64)
            head_len = chunk_samples - tail.size
            head = np.asarray(self._samples[:head_len], dtype=np.complex64)
            self._cursor = head_len
            return np.concatenate([tail, head]).astype(np.complex64, copy=False)

    def _update_status(self, **fields) -> None:
        with self._status_lock:
            for key, value in fields.items():
                setattr(self._status, key, value)
            self._status.reported_at = datetime.now(timezone.utc)


def register_driver(manager: "RadioManager") -> None:
    """Register the file-replay driver under the canonical ``file`` name."""
    manager.register_driver("file", FileReplayReceiver)
    # Convenience aliases so operators can use either spelling.
    manager.register_driver("file_replay", FileReplayReceiver)
    manager.register_driver("iq_replay", FileReplayReceiver)


__all__ = [
    "DEFAULT_REPLAY_DIR",
    "FileReplayReceiver",
    "get_replay_dir",
    "register_driver",
    "resolve_replay_path",
]
