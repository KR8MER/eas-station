"""On-demand memory diagnostic hooks for long-running Python services.

This module exists because the ``python_hardware_service`` process has been
observed growing to ~13 GB RES in production while static inspection of the
code (bounded ring buffers, transient PIL images, short-TTL Redis writes)
turns up no obvious culprit.  Without a heap snapshot from the actually
leaking process, any "fix" is a guess.  The previous attempt (PR #2062)
explicitly punted on the leak and recommended adding a SIGUSR1 heap-dump
hook so an operator can grab a real snapshot from the live host.

This module provides exactly that:

* :func:`install_memdiag_handlers` arms ``SIGUSR1`` and ``SIGUSR2`` on the
  current process.  Both signal handlers write to a file under
  ``MEMDIAG_DUMP_DIR`` (default ``/tmp``) and to ``stderr`` so the dump is
  visible in the systemd journal too.
* ``SIGUSR1`` produces a memory snapshot — process RSS, ``gc`` summary,
  and (if tracemalloc is enabled) the top allocators by file:line and by
  full traceback.
* ``SIGUSR2`` produces an all-threads Python traceback via
  :mod:`faulthandler`, so the operator can correlate "what allocated this"
  with "what was running at dump time".

Tracemalloc adds non-trivial overhead (every allocation is captured), so
it is **off by default**.  Enable it on a service that is suspected of
leaking by setting ``MEMDIAG_TRACEMALLOC=1`` in that service's
environment.  The number of captured frames per allocation is controlled
by ``MEMDIAG_TRACEMALLOC_FRAMES`` (default 10).

Operator workflow
-----------------
On the host where the leak is occurring::

    # find the pid
    systemctl status eas-hardware.service | grep PID
    # or: pgrep -af hardware_service.py

    # snapshot top allocators
    kill -USR1 <pid>
    ls -lt /tmp/eas-memdiag-*.txt | head

    # snapshot all-thread Python stacks
    kill -USR2 <pid>

The snapshot file is plain text and safe to attach to an issue (no
secrets are captured beyond what already appears in tracemalloc tracebacks
— file paths and line numbers).
"""

from __future__ import annotations

import faulthandler
import gc
import logging
import os
import signal
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# How many top tracemalloc entries to dump.  20 is enough to surface the
# dominant allocator in nearly every real leak we've seen.
_TRACEMALLOC_TOP_N = 20

# Default location for dump files.  /tmp is tmpfs on the production hosts
# so writes are fast and we won't fill the SD card if an operator forgets
# to clean them up — a reboot wipes them.
_DEFAULT_DUMP_DIR = "/tmp"

# Module-level state so the handlers can find what they need.  Kept tiny
# so a SIGUSR1 storm can't blow memory while we're trying to debug a
# memory leak.
_dump_dir: str = _DEFAULT_DUMP_DIR
_service_name: str = "service"
_tracemalloc_enabled: bool = False


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean-ish env var.  Accepts 1/true/yes/on (case-insensitive)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _process_rss_bytes() -> Optional[int]:
    """Return current process RSS in bytes, or ``None`` if it cannot be read.

    Uses ``/proc/self/status`` (Linux) so we don't pull in ``psutil`` just
    for diagnostics — the production hosts are all Linux/Pi.
    """
    try:
        with open("/proc/self/status", "r") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    # parts looks like ["VmRSS:", "12345", "kB"]
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except Exception:
        return None
    return None


def _format_bytes(num: Optional[int]) -> str:
    """Pretty-print a byte count, tolerating ``None`` for unknown values."""
    if num is None:
        return "unknown"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    n = float(num)
    for unit in units:
        if abs(n) < 1024.0 or unit == units[-1]:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{num} B"


def _open_dump_file(suffix: str):
    """Open a timestamped dump file in ``_dump_dir``.

    Returns ``(path, file_handle)`` or ``(None, None)`` on failure.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = f"eas-memdiag-{_service_name}-{os.getpid()}-{ts}-{suffix}.txt"
    path = os.path.join(_dump_dir, fname)
    try:
        # Plain text mode is fine — these dumps are read by humans.  We
        # buffer with line buffering so partial output is still useful if
        # the process dies mid-dump.
        fh = open(path, "w", buffering=1)
        return path, fh
    except Exception as exc:
        logger.error("memdiag: failed to open dump file %s: %s", path, exc)
        return None, None


def _write_header(fh, kind: str) -> None:
    fh.write(f"=== EAS memdiag {kind} ===\n")
    fh.write(f"service     : {_service_name}\n")
    fh.write(f"pid         : {os.getpid()}\n")
    fh.write(f"timestamp   : {datetime.now(timezone.utc).isoformat()}\n")
    fh.write(f"python      : {sys.version.split()[0]}\n")
    fh.write(f"rss         : {_format_bytes(_process_rss_bytes())}\n")
    counts = gc.get_count()
    fh.write(f"gc.get_count: gen0={counts[0]} gen1={counts[1]} gen2={counts[2]}\n")
    try:
        # gc.get_objects() is O(N) but we are explicitly diagnosing a
        # memory issue — knowing the live object count is useful and the
        # caller chose to send the signal.
        n_objects = len(gc.get_objects())
    except Exception:
        n_objects = -1
    fh.write(f"gc.objects  : {n_objects}\n")
    fh.write(f"tracemalloc : {'enabled' if _tracemalloc_enabled and tracemalloc.is_tracing() else 'disabled'}\n")
    fh.write("\n")


def _write_tracemalloc_section(fh) -> None:
    """Append top-allocators output if tracemalloc is on; otherwise note that."""
    if not (_tracemalloc_enabled and tracemalloc.is_tracing()):
        fh.write(
            "tracemalloc is not enabled in this process — set the\n"
            "MEMDIAG_TRACEMALLOC=1 env var on the service unit and\n"
            "restart it to capture allocator-level detail next time.\n"
        )
        return

    try:
        snapshot = tracemalloc.take_snapshot()
    except Exception as exc:
        fh.write(f"tracemalloc.take_snapshot() failed: {exc}\n")
        return

    current, peak = tracemalloc.get_traced_memory()
    fh.write(f"tracemalloc.current: {_format_bytes(current)}\n")
    fh.write(f"tracemalloc.peak   : {_format_bytes(peak)}\n\n")
    # Flush before the (potentially expensive) statistics pass so the
    # header survives even if statistics() runs out of memory or the
    # service is OOM-killed mid-dump (the original bug that produced
    # 367-byte stub dumps).
    try:
        fh.flush()
    except Exception:
        pass

    # 1) Top by file:line — best for spotting hot allocation sites.
    #    Each entry is written + flushed individually so a partial dump
    #    is still useful when the process dies mid-loop.
    fh.write(f"--- top {_TRACEMALLOC_TOP_N} allocators by file:line ---\n")
    try:
        stats = snapshot.statistics("lineno")
    except Exception as exc:
        fh.write(f"  (failed to compute lineno stats: {exc})\n")
        stats = []
    for i, stat in enumerate(stats[:_TRACEMALLOC_TOP_N], 1):
        try:
            fh.write(f"#{i:>2}  {_format_bytes(stat.size)}  count={stat.count}  {stat.traceback}\n")
            fh.flush()
        except Exception as exc:
            fh.write(f"  (entry #{i} write failed: {exc})\n")
            break

    fh.write("\n")
    try:
        fh.flush()
    except Exception:
        pass

    # 2) Top by full traceback — opt-in via MEMDIAG_TRACEMALLOC_TRACEBACKS=1.
    #    With high allocation counts this section is the one that hangs /
    #    OOMs the dump (it walks every captured traceback), so we skip it
    #    by default. Set MEMDIAG_TRACEMALLOC_FRAMES>1 *and* the env var
    #    to opt back in once the by-lineno top has narrowed the suspect.
    if not _env_bool("MEMDIAG_TRACEMALLOC_TRACEBACKS", default=False):
        fh.write(
            "--- top allocators by full traceback (skipped) ---\n"
            "  Set MEMDIAG_TRACEMALLOC_TRACEBACKS=1 (and frames>1) to enable.\n"
        )
        return

    fh.write(f"--- top {_TRACEMALLOC_TOP_N} allocators by traceback ---\n")
    try:
        stats = snapshot.statistics("traceback")
    except Exception as exc:
        fh.write(f"  (failed to compute traceback stats: {exc})\n")
        stats = []
    for i, stat in enumerate(stats[:_TRACEMALLOC_TOP_N], 1):
        try:
            fh.write(f"#{i:>2} {_format_bytes(stat.size)}  count={stat.count}\n")
            for line in stat.traceback.format():
                fh.write(f"    {line}\n")
            fh.write("\n")
            fh.flush()
        except Exception as exc:
            fh.write(f"  (entry #{i} write failed: {exc})\n")
            break


def write_memory_dump(reason: str = "manual") -> Optional[str]:
    """Synchronously write a memory dump file and return its path.

    Exposed for tests and for callers that want to capture a snapshot
    without going through a signal (e.g. on graceful shutdown for
    post-mortem diagnostics).  Safe to call from any thread.
    """
    path, fh = _open_dump_file("memory")
    if not fh:
        return None
    try:
        _write_header(fh, f"memory snapshot ({reason})")
        _write_tracemalloc_section(fh)
    except Exception as exc:
        # Best-effort — we don't want a diagnostic helper to take down
        # the service it's diagnosing.
        try:
            fh.write(f"\n!! memdiag failed mid-dump: {exc}\n")
        except Exception:
            pass
        logger.error("memdiag: error writing memory dump: %s", exc, exc_info=True)
    finally:
        try:
            fh.close()
        except Exception:
            pass
    return path


def write_threads_dump(reason: str = "manual") -> Optional[str]:
    """Synchronously write an all-threads Python traceback to a file."""
    path, fh = _open_dump_file("threads")
    if not fh:
        return None
    try:
        _write_header(fh, f"thread snapshot ({reason})")
        # faulthandler.dump_traceback writes to a file descriptor, which
        # is signal-safe and works even if the GIL is contended.
        try:
            faulthandler.dump_traceback(file=fh, all_threads=True)
        except Exception as exc:
            fh.write(f"\nfaulthandler.dump_traceback failed: {exc}\n")
    finally:
        try:
            fh.close()
        except Exception:
            pass
    return path


def _sigusr1_handler(signum, frame):  # noqa: ARG001 - signal API
    """SIGUSR1 → write a memory snapshot.

    Signal handlers run on the main thread between bytecode instructions,
    so they can use ordinary Python I/O.  We still keep the work small
    and catch everything because dying inside a signal handler is its
    own special hell.
    """
    try:
        path = write_memory_dump(reason="SIGUSR1")
        # Also log so operators see something in the journal even if
        # they forget where /tmp is.
        if path:
            msg = f"memdiag: wrote memory dump to {path}\n"
        else:
            msg = "memdiag: failed to write memory dump (see logs)\n"
        try:
            sys.stderr.write(msg)
            sys.stderr.flush()
        except Exception:
            pass
    except Exception as exc:
        logger.error("memdiag: SIGUSR1 handler failed: %s", exc, exc_info=True)


def _sigusr2_handler(signum, frame):  # noqa: ARG001 - signal API
    """SIGUSR2 → write an all-threads Python traceback."""
    try:
        path = write_threads_dump(reason="SIGUSR2")
        if path:
            msg = f"memdiag: wrote thread dump to {path}\n"
        else:
            msg = "memdiag: failed to write thread dump (see logs)\n"
        try:
            sys.stderr.write(msg)
            sys.stderr.flush()
        except Exception:
            pass
    except Exception as exc:
        logger.error("memdiag: SIGUSR2 handler failed: %s", exc, exc_info=True)


def install_memdiag_handlers(
    service_name: str,
    *,
    dump_dir: Optional[str] = None,
    enable_tracemalloc: Optional[bool] = None,
    tracemalloc_frames: Optional[int] = None,
) -> None:
    """Install SIGUSR1/SIGUSR2 memory-diagnostic handlers.

    Parameters
    ----------
    service_name:
        Short identifier (e.g. ``"hardware"``) embedded in dump filenames
        so operators can tell which service produced a dump.
    dump_dir:
        Directory for dump files.  Defaults to ``MEMDIAG_DUMP_DIR`` env
        var if set, else ``/tmp``.
    enable_tracemalloc:
        Whether to start :mod:`tracemalloc`.  Defaults to the
        ``MEMDIAG_TRACEMALLOC`` env var (off by default — tracemalloc adds
        per-allocation overhead).  Pass ``True`` here only if the caller
        knows it always wants allocator-level detail.
    tracemalloc_frames:
        How many frames of traceback to record per allocation.  Defaults
        to ``MEMDIAG_TRACEMALLOC_FRAMES`` env var, or 10.

    This function is idempotent — calling it twice replaces the previous
    handlers, so unit tests can exercise it without leaking state.

    Signals are not available on every platform / thread (notably,
    ``signal.signal`` only works on the main thread of the main
    interpreter).  If installation fails the function logs a warning and
    returns; callers do not need to special-case that.
    """
    global _dump_dir, _service_name, _tracemalloc_enabled

    _service_name = service_name or "service"
    _dump_dir = dump_dir or os.environ.get("MEMDIAG_DUMP_DIR") or _DEFAULT_DUMP_DIR

    if enable_tracemalloc is None:
        enable_tracemalloc = _env_bool("MEMDIAG_TRACEMALLOC", default=False)

    if tracemalloc_frames is None:
        # Default to 1 frame: just enough to populate the by-lineno top.
        # 10-frame stacks (the previous default) bloated tracemalloc's
        # internal storage to the point where statistics("lineno") could
        # OOM on a leaking process — the very situation the dump is
        # supposed to diagnose.
        try:
            tracemalloc_frames = int(os.environ.get("MEMDIAG_TRACEMALLOC_FRAMES", "1"))
        except ValueError:
            tracemalloc_frames = 1
    tracemalloc_frames = max(1, tracemalloc_frames)

    if enable_tracemalloc:
        try:
            if not tracemalloc.is_tracing():
                tracemalloc.start(tracemalloc_frames)
            _tracemalloc_enabled = True
            logger.info(
                "memdiag: tracemalloc enabled (%d frames per allocation)",
                tracemalloc_frames,
            )
        except Exception as exc:
            logger.warning("memdiag: failed to start tracemalloc: %s", exc)
            _tracemalloc_enabled = False
    else:
        _tracemalloc_enabled = False

    # Make sure the dump directory exists.  We don't try to create
    # arbitrary parents — if the operator overrode it to something silly
    # we'd rather fail loudly.
    try:
        os.makedirs(_dump_dir, exist_ok=True)
    except Exception as exc:
        logger.warning("memdiag: dump dir %s not usable: %s", _dump_dir, exc)

    # Install handlers.  signal.signal raises ValueError if called from
    # a non-main thread; we catch that so a misuse doesn't crash the
    # service.
    installed = []
    for sig, handler, label in (
        (getattr(signal, "SIGUSR1", None), _sigusr1_handler, "SIGUSR1"),
        (getattr(signal, "SIGUSR2", None), _sigusr2_handler, "SIGUSR2"),
    ):
        if sig is None:
            continue  # Windows etc.
        try:
            signal.signal(sig, handler)
            installed.append(label)
        except (ValueError, OSError) as exc:
            logger.warning("memdiag: could not install %s handler: %s", label, exc)

    if installed:
        logger.info(
            "memdiag: installed handlers (%s); pid=%d dump_dir=%s tracemalloc=%s",
            ",".join(installed),
            os.getpid(),
            _dump_dir,
            "on" if _tracemalloc_enabled else "off",
        )


def _reset_for_tests() -> None:
    """Reset module state.  Test helper only."""
    global _dump_dir, _service_name, _tracemalloc_enabled
    _dump_dir = _DEFAULT_DUMP_DIR
    _service_name = "service"
    if tracemalloc.is_tracing():
        try:
            tracemalloc.stop()
        except Exception:
            pass
    _tracemalloc_enabled = False


__all__ = [
    "install_memdiag_handlers",
    "write_memory_dump",
    "write_threads_dump",
]
