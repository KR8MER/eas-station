"""Tests for app_utils.glibc_tuning.

The module is a thin ctypes wrapper around glibc's mallopt / malloc_trim,
so the tests just verify that the wrappers don't blow up and that the
public surface behaves sensibly on platforms where libc is reachable
(every Linux host this service ships on).  Non-glibc platforms return
False, which is fine — these tests skip themselves when libc can't be
loaded so they don't false-positive on a dev macOS box.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest

# Load directly from file (same trick test_memdiag.py uses) so we don't
# trigger app_utils/__init__.py — glibc_tuning only needs the stdlib.
_MOD_PATH = Path(__file__).resolve().parents[1] / "app_utils" / "glibc_tuning.py"
_spec = importlib.util.spec_from_file_location(
    "app_utils_glibc_tuning_test", _MOD_PATH
)
glibc_tuning = importlib.util.module_from_spec(_spec)
sys.modules["app_utils_glibc_tuning_test"] = glibc_tuning
_spec.loader.exec_module(glibc_tuning)


def _libc_available() -> bool:
    return glibc_tuning._get_libc() is not None


pytestmark = pytest.mark.skipif(
    not _libc_available(), reason="libc not reachable (non-glibc platform)"
)


def test_apply_glibc_tuning_returns_true_on_glibc():
    """Both mallopt() calls succeed on the production target."""
    assert glibc_tuning.apply_glibc_tuning(arena_max=2, trim_threshold=131072) is True


def test_apply_glibc_tuning_is_idempotent():
    """Repeat calls keep returning True — the previous fix recommends
    applying this once at startup but a hot reload (or an opportunistic
    re-arm from a watchdog) shouldn't break."""
    assert glibc_tuning.apply_glibc_tuning(2, 131072) is True
    assert glibc_tuning.apply_glibc_tuning(2, 131072) is True


def test_malloc_trim_does_not_raise():
    """malloc_trim() returns a bool — its truthiness depends on whether
    glibc had anything to release, which we can't force from Python.
    The contract is just "doesn't raise"."""
    result = glibc_tuning.malloc_trim(0)
    assert isinstance(result, bool)


def test_start_malloc_trim_thread_runs_and_stops():
    """The ticker thread should honour the stop event so the service's
    shutdown path can wind it down cleanly."""
    stop = threading.Event()
    # Tiny interval so the thread loops at least once during the test
    # without us having to sleep for a minute.
    thread = glibc_tuning.start_malloc_trim_thread(interval_s=0.05, stop_event=stop)
    assert thread.is_alive()
    time.sleep(0.2)  # let it tick a couple of times
    stop.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive(), "trim thread did not stop after stop_event was set"
