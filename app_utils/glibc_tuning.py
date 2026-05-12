"""Runtime glibc malloc tuning for long-running Python services.

The previous hardware-service memory leak (commit eb48eea — "MALLOC_ARENA_MAX=2
already cut RSS from 9.68 GB to ~320 MB") was fixed by setting environment
variables in the systemd unit::

    Environment="MALLOC_ARENA_MAX=2"
    Environment="MALLOC_TRIM_THRESHOLD_=131072"

Those only take effect at process startup and only when the unit file on
the live host actually carries them.  On hosts where the unit drifted
(operator override, missed ``daemon-reload`` after an update, container
image that didn't pick up the new unit, etc.) the leak resurfaces — and
because the recently-added GPS code (PPS deque grown 1024 → 16 384,
ADEV τ=1000 s) does ~17× more allocation per ``get_status()`` than it
used to, the unchecked arenas now grow at ~1 GB/min instead of the
~3 MB/min residual we saw before.

This module applies the same tuning *from inside the process* via
``mallopt(3)`` so the fix is robust to systemd-unit drift, and runs a
periodic :py:func:`malloc_trim` to actively return free top-of-heap
memory to the kernel.  It's a no-op on non-glibc platforms (the symbols
just won't resolve), so it's safe to call unconditionally.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


M_TRIM_THRESHOLD = -1
M_ARENA_MAX = -8

_libc: Optional[ctypes.CDLL] = None


def _get_libc() -> Optional[ctypes.CDLL]:
    global _libc
    if _libc is not None:
        return _libc
    try:
        name = ctypes.util.find_library("c") or "libc.so.6"
        _libc = ctypes.CDLL(name, use_errno=True)
    except OSError as exc:
        logger.debug("glibc_tuning: libc not loadable (%s); tuning disabled", exc)
        _libc = None
    return _libc


def apply_glibc_tuning(arena_max: int = 2, trim_threshold: int = 131072) -> bool:
    """Apply ``MALLOC_ARENA_MAX`` / ``MALLOC_TRIM_THRESHOLD_`` at runtime.

    Multi-threaded Python on glibc defaults to one malloc arena per CPU,
    none of which return memory to the kernel.  With the hardware service
    spawning NMEA / gpsd / PPS / screen / Flask / health-check threads,
    that grows RSS to multiples of the live working set.  Capping the
    arena count and lowering the trim threshold keeps RSS honest.

    ``mallopt()`` returns 1 on success and 0 on failure.  This function
    logs the outcome and returns True iff both settings stuck.  Best
    called from the main thread before any worker threads are spawned —
    arena count changes only affect *new* arenas, so applying it after
    threads have already pinned their own arena is a no-op for those.
    """
    libc = _get_libc()
    if libc is None:
        return False
    try:
        libc.mallopt.argtypes = [ctypes.c_int, ctypes.c_int]
        libc.mallopt.restype = ctypes.c_int
    except Exception as exc:
        logger.debug("glibc_tuning: mallopt binding failed (%s)", exc)
        return False

    ok = True
    try:
        rc = libc.mallopt(M_ARENA_MAX, int(arena_max))
        if rc != 1:
            logger.warning(
                "glibc_tuning: mallopt(M_ARENA_MAX, %d) returned %d", arena_max, rc
            )
            ok = False
        else:
            logger.info("glibc_tuning: arena cap = %d", arena_max)
    except Exception as exc:
        logger.warning("glibc_tuning: mallopt(M_ARENA_MAX) failed: %s", exc)
        ok = False

    try:
        rc = libc.mallopt(M_TRIM_THRESHOLD, int(trim_threshold))
        if rc != 1:
            logger.warning(
                "glibc_tuning: mallopt(M_TRIM_THRESHOLD, %d) returned %d",
                trim_threshold, rc,
            )
            ok = False
        else:
            logger.info("glibc_tuning: trim threshold = %d", trim_threshold)
    except Exception as exc:
        logger.warning("glibc_tuning: mallopt(M_TRIM_THRESHOLD) failed: %s", exc)
        ok = False

    return ok


def malloc_trim(pad: int = 0) -> bool:
    """Ask glibc to return free top-of-heap memory to the kernel now.

    Returns True if any memory was actually released.  The arenas hold
    onto small free blocks that ``MALLOC_TRIM_THRESHOLD_`` won't reach
    on its own once they get fragmented under sustained allocation;
    calling this periodically is what keeps RSS bounded for services
    that allocate in tight loops.
    """
    libc = _get_libc()
    if libc is None:
        return False
    try:
        libc.malloc_trim.argtypes = [ctypes.c_size_t]
        libc.malloc_trim.restype = ctypes.c_int
        return bool(libc.malloc_trim(int(pad)))
    except Exception as exc:
        logger.debug("glibc_tuning: malloc_trim failed: %s", exc)
        return False


def start_malloc_trim_thread(
    interval_s: float = 60.0,
    pad: int = 0,
    stop_event: Optional[threading.Event] = None,
) -> threading.Thread:
    """Start a daemon thread that calls :py:func:`malloc_trim` every
    ``interval_s`` seconds.

    Returns the thread (already started).  Pass ``stop_event`` to halt
    it from the caller's shutdown path; otherwise the daemon flag means
    it'll die with the interpreter.
    """
    # Use a private event when the caller didn't supply one so we can
    # still wait()-with-timeout (responsive to interpreter shutdown via
    # daemon=True) instead of a bare ``time.sleep`` that ignores the
    # stop signal until the next tick.
    waiter = stop_event if stop_event is not None else threading.Event()

    def _loop() -> None:
        while not waiter.wait(timeout=interval_s):
            try:
                malloc_trim(pad)
            except Exception:
                pass

    thread = threading.Thread(target=_loop, name="glibc-malloc-trim", daemon=True)
    thread.start()
    return thread
