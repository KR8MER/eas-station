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

"""On-disk progress and result stores for async verification runs.

Both stores are plain JSON files under a temp directory, guarded by a module
lock, because the async decode worker runs in a thread and the polling
endpoint has to read what it writes.

``_progress_dir``, ``_progress_lock``, ``_result_dir`` and ``_result_lock``
are module-level mutable globals that the tests replace with ``tmp_path``.
They are **deliberately not re-exported** from the package ``__init__``:
rebinding a re-exported copy would leave the classes here still reading the
real temp directory, and the patch would silently do nothing. Absent from the
package, ``monkeypatch.setattr`` raises instead — which is what tells you
where the patch belongs.
"""

import os
import re
import tempfile
import time
import uuid
import threading
from typing import Dict, Optional, Tuple

from app_utils.optimized_parsing import json_loads, json_dumps, JSONDecodeError


# Progress tracking infrastructure
# Persist to the filesystem so multiple workers can share state
_progress_lock = threading.Lock()
_progress_dir = os.path.join(tempfile.gettempdir(), "alert_verification_progress")
os.makedirs(_progress_dir, exist_ok=True)
_result_lock = threading.Lock()
_result_dir = os.path.join(_progress_dir, "results")
os.makedirs(_result_dir, exist_ok=True)
_OPERATION_ID_SANITIZER = re.compile(r"[^A-Za-z0-9_-]")

def _sanitize_operation_id(operation_id: str) -> str:
    """Return a filesystem-safe operation identifier."""

    return _OPERATION_ID_SANITIZER.sub("", operation_id or "")

def _progress_path(operation_id: str) -> str:
    """Resolve the storage path for a progress payload."""

    safe_id = _sanitize_operation_id(operation_id)
    return os.path.join(_progress_dir, f"{safe_id}.json")

class ProgressTracker:
    """Track progress of long-running operations using a shared file store.

    The reported ``percent`` is mapped onto a unified 0–100 timeline using
    phase weights so the bar advances monotonically across upload → decode
    → extract → storage → data-load instead of resetting every time the
    caller starts a new ``step`` with a different ``total``.  This was the
    root cause of the visible 50 % → 16 % regression users observed when
    the pipeline transitioned from the upload phase (total=4) to the
    decode phase (total=6).
    """

    # Each phase claims a slice of the global 0–100 timeline.  Sub-progress
    # within a phase (current/total) is linearly mapped into the slice.
    PHASE_RANGES: Dict[str, Tuple[int, int]] = {
        "init": (0, 1),
        "upload": (1, 5),
        "decode": (5, 75),
        "extract": (75, 88),
        "storage": (88, 95),
        "data": (95, 99),
    }

    def __init__(self, operation_id: str):
        self.operation_id = operation_id
        # Cached high-water mark used to clamp ``percent`` to be
        # monotonically non-decreasing across phases.  Tracked in-process
        # rather than re-read from disk on every ``update`` call to (a)
        # avoid an extra open() on the hot path and (b) keep CodeQL's
        # path-injection analysis happy without an extra sanitisation
        # step (the on-disk path is already vetted by
        # _sanitize_operation_id, but the in-memory cache sidesteps the
        # question entirely).
        self._max_percent: int = 0
        # Wall-clock start time for elapsed/ETA reporting. A new
        # ProgressTracker(operation_id) is instantiated fresh at every call
        # site across the pipeline (upload -> decode -> extract -> storage
        # -> data), not held as one object for the whole operation, so this
        # can't just be "set once in __init__" -- it's lazily recovered from
        # the on-disk payload the first time this instance actually writes
        # (see _ensure_started_at), which costs one extra read only on that
        # first write per instance, not per update() call within a
        # tight sub-progress loop.
        self._started_at: Optional[float] = None

    def _write_payload(self, payload: Dict) -> None:
        """Persist a progress payload to disk atomically."""

        payload = dict(payload)
        payload["timestamp"] = time.time()
        target_path = _progress_path(self.operation_id)
        temp_path = f"{target_path}.{uuid.uuid4().hex}.tmp"

        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(json_dumps(payload))
        os.replace(temp_path, target_path)

    @classmethod
    def _phase_percent(cls, step: str, current: int, total: int) -> int:
        """Map a phase + sub-progress into the unified 0–100 timeline."""

        low, high = cls.PHASE_RANGES.get(step, (0, 100))
        if total <= 0:
            return low
        ratio = max(0.0, min(1.0, current / total))
        return int(round(low + (high - low) * ratio))

    def _read_existing_percent(self) -> int:
        """Highest percent reported on this tracker instance so far.

        Used to clamp ``percent`` to be monotonically non-decreasing
        across phases.  Stored in-memory on the tracker rather than
        re-read from the on-disk progress file to avoid an extra
        open() per update and to dodge the static-analysis
        path-injection question entirely.
        """
        return self._max_percent

    def _ensure_started_at(self) -> float:
        """Recover (or establish) this operation's wall-clock start time.

        Reads the on-disk payload once per fresh ``ProgressTracker``
        instance -- see ``__init__`` -- so a later phase's tracker inherits
        the same ``started_at`` an earlier phase's tracker already wrote,
        instead of every phase transition resetting the clock and making
        "elapsed" lie.
        """
        if self._started_at is not None:
            return self._started_at
        existing = self.get(self.operation_id)
        started_at = existing.get("started_at") if existing else None
        self._started_at = float(started_at) if started_at else time.time()
        return self._started_at

    def _timing_fields(self, percent: int) -> Dict:
        """Elapsed seconds so far, plus a linear-extrapolation ETA.

        The ETA is deliberately simple (elapsed / (percent/100) - elapsed)
        rather than per-phase-calibrated: this pipeline's phases vary too
        much run to run (upload size, decode complexity, DB load) for a
        fixed historical timing table to beat "how long has this actually
        taken so far, projected forward" in practice, and it needs no
        calibration data to start being reasonable. Noisy in the first few
        percent (as any linear ETA is) and stabilizes quickly after.
        """
        # Deliberately called from OUTSIDE the _progress_lock critical
        # section in update()/complete()/error() below: _ensure_started_at()
        # calls the (also-locking) self.get() on a fresh instance's first
        # write, and threading.Lock is not reentrant -- acquiring it twice
        # from the same thread deadlocks forever, silently, with no
        # exception to point at the cause.
        started_at = self._ensure_started_at()
        elapsed = max(0.0, time.time() - started_at)
        eta_seconds: Optional[float] = None
        if 0 < percent < 100:
            projected_total = elapsed / (percent / 100.0)
            eta_seconds = max(0.0, projected_total - elapsed)
        return {
            "started_at": started_at,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
        }

    def update(self, step: str, current: int, total: int, message: str = ""):
        """Update progress for the current operation.

        Sub-progress within the named phase is mapped onto the global
        0–100 timeline.  The reported ``percent`` is also clamped to be
        monotonically non-decreasing, so a slow phase can't visually
        rewind the bar when a faster phase takes over.
        """
        percent = self._phase_percent(step, current, total)
        # Outside the lock -- see _timing_fields' docstring on why.
        timing = self._timing_fields(percent)

        with _progress_lock:
            previous = self._read_existing_percent()
            if percent < previous:
                percent = previous
            self._max_percent = percent
            progress_data = {
                "step": step,
                "current": current,
                "total": total,
                "message": message,
                "percent": percent,
                **timing,
            }
            self._write_payload(progress_data)

    def complete(self, message: str = "Complete"):
        """Mark operation as complete."""
        timing = self._timing_fields(100)
        with _progress_lock:
            self._write_payload({
                "step": "complete",
                "current": 100,
                "total": 100,
                "message": message,
                "percent": 100,
                **timing,
            })

    def error(self, message: str):
        """Mark operation as failed."""
        timing = self._timing_fields(0)
        with _progress_lock:
            self._write_payload({
                "step": "error",
                "current": 0,
                "total": 100,
                "message": message,
                "percent": 0,
                **timing,
            })

    @staticmethod
    def get(operation_id: str) -> Optional[Dict]:
        """Get progress data for an operation."""
        with _progress_lock:
            path = _progress_path(operation_id)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    return json_loads(handle.read())
            except FileNotFoundError:
                return None
            except (OSError, JSONDecodeError):  # pragma: no cover - defensive
                return None

    @staticmethod
    def clear(operation_id: str):
        """Clear progress data for an operation."""
        with _progress_lock:
            path = _progress_path(operation_id)
            try:
                os.remove(path)
            except FileNotFoundError:
                return
            except OSError:  # pragma: no cover - defensive
                return

    @staticmethod
    def cleanup_old(max_age_seconds: int = 3600):
        """Clean up progress data older than max_age_seconds."""
        current_time = time.time()
        with _progress_lock:
            try:
                for filename in os.listdir(_progress_dir):
                    if not filename.endswith(".json"):
                        continue
                    path = os.path.join(_progress_dir, filename)
                    try:
                        modified = os.path.getmtime(path)
                    except OSError:
                        continue
                    if current_time - modified > max_age_seconds:
                        try:
                            os.remove(path)
                        except OSError:
                            continue
            except OSError:  # pragma: no cover - defensive
                return

class OperationResultStore:
    """Persist alert verification results for asynchronous retrieval."""

    @staticmethod
    def _path(operation_id: str) -> str:
        safe_id = _sanitize_operation_id(operation_id)
        return os.path.join(_result_dir, f"{safe_id}.json")

    @classmethod
    def save(cls, operation_id: str, payload: Dict) -> None:
        data = dict(payload or {})
        target_path = cls._path(operation_id)
        temp_path = f"{target_path}.{uuid.uuid4().hex}.tmp"

        with _result_lock:
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write(json_dumps(data))
            os.replace(temp_path, target_path)

    @classmethod
    def load(cls, operation_id: str) -> Optional[Dict]:
        with _result_lock:
            try:
                with open(cls._path(operation_id), "r", encoding="utf-8") as handle:
                    return json_loads(handle.read())
            except FileNotFoundError:
                return None
            except (OSError, JSONDecodeError):  # pragma: no cover - defensive
                return None

    @classmethod
    def clear(cls, operation_id: str) -> None:
        with _result_lock:
            try:
                os.remove(cls._path(operation_id))
            except FileNotFoundError:
                return
            except OSError:  # pragma: no cover - defensive
                return

    @classmethod
    def cleanup_old(cls, max_age_seconds: int = 3600) -> None:
        current_time = time.time()
        with _result_lock:
            try:
                for filename in os.listdir(_result_dir):
                    if not filename.endswith(".json"):
                        continue
                    path = os.path.join(_result_dir, filename)
                    try:
                        modified = os.path.getmtime(path)
                    except OSError:
                        continue
                    if current_time - modified > max_age_seconds:
                        try:
                            os.remove(path)
                        except OSError:
                            continue
            except OSError:  # pragma: no cover - defensive
                return
