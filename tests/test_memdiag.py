"""Tests for the app_utils.memdiag on-demand diagnostic hooks.

These cover the public surface (handler installation, snapshot writing,
tracemalloc gating) without sending real signals — the signal callbacks
are exercised by calling them directly, which is what the runtime would
do via ``signal.signal``.
"""
from __future__ import annotations

import importlib.util
import os
import signal
import sys
import tracemalloc
from pathlib import Path

import pytest

# Load app_utils.memdiag directly from file to avoid triggering
# app_utils/__init__.py (which pulls in sqlalchemy / psutil for the rest
# of the package).  memdiag itself only needs the standard library.
_MEMDIAG_PATH = Path(__file__).resolve().parents[1] / "app_utils" / "memdiag.py"
_spec = importlib.util.spec_from_file_location("app_utils_memdiag_test", _MEMDIAG_PATH)
memdiag = importlib.util.module_from_spec(_spec)
sys.modules["app_utils_memdiag_test"] = memdiag
_spec.loader.exec_module(memdiag)


@pytest.fixture(autouse=True)
def _isolate_memdiag(tmp_path, monkeypatch):
    """Each test gets a fresh dump dir + reset module state."""
    # Point dumps at the per-test tmpdir so we never touch /tmp during
    # CI and so assertions can list the directory cleanly.
    monkeypatch.setenv("MEMDIAG_DUMP_DIR", str(tmp_path))
    monkeypatch.delenv("MEMDIAG_TRACEMALLOC", raising=False)
    monkeypatch.delenv("MEMDIAG_TRACEMALLOC_FRAMES", raising=False)
    memdiag._reset_for_tests()
    yield tmp_path
    memdiag._reset_for_tests()


def test_install_handlers_registers_sigusr1_and_sigusr2(_isolate_memdiag):
    memdiag.install_memdiag_handlers("test")
    # signal.getsignal returns the active handler; should be the
    # module's private callbacks now.
    assert signal.getsignal(signal.SIGUSR1) is memdiag._sigusr1_handler
    assert signal.getsignal(signal.SIGUSR2) is memdiag._sigusr2_handler


def test_install_is_idempotent(_isolate_memdiag):
    memdiag.install_memdiag_handlers("test")
    # Second call should not raise and should leave handlers intact.
    memdiag.install_memdiag_handlers("test")
    assert signal.getsignal(signal.SIGUSR1) is memdiag._sigusr1_handler


def test_tracemalloc_off_by_default(_isolate_memdiag):
    memdiag.install_memdiag_handlers("test")
    assert memdiag._tracemalloc_enabled is False
    # We don't assert tracemalloc.is_tracing() here because the test
    # process may have it on for other reasons; what matters is that we
    # didn't *enable* it ourselves.


def test_tracemalloc_env_var_enables_it(_isolate_memdiag, monkeypatch):
    monkeypatch.setenv("MEMDIAG_TRACEMALLOC", "1")
    memdiag.install_memdiag_handlers("test")
    assert memdiag._tracemalloc_enabled is True
    assert tracemalloc.is_tracing()


def test_write_memory_dump_creates_file_with_header(_isolate_memdiag):
    memdiag.install_memdiag_handlers("hardware")
    path = memdiag.write_memory_dump(reason="unit-test")
    assert path is not None
    assert os.path.exists(path)
    content = open(path).read()
    # Header fields we always emit
    assert "EAS memdiag" in content
    assert "service     : hardware" in content
    assert f"pid         : {os.getpid()}" in content
    assert "gc.get_count" in content
    assert "tracemalloc :" in content


def test_memory_dump_notes_when_tracemalloc_disabled(_isolate_memdiag):
    memdiag.install_memdiag_handlers("test", enable_tracemalloc=False)
    path = memdiag.write_memory_dump(reason="off")
    content = open(path).read()
    assert "tracemalloc is not enabled" in content


def test_memory_dump_includes_tracemalloc_section_when_enabled(_isolate_memdiag):
    memdiag.install_memdiag_handlers("test", enable_tracemalloc=True, tracemalloc_frames=5)
    # Force at least some allocations so the snapshot has content.
    junk = ["x" * 1024 for _ in range(64)]
    path = memdiag.write_memory_dump(reason="on")
    content = open(path).read()
    # We should see both views and at least one entry.
    assert "top 20 allocators by file:line" in content
    assert "top 20 allocators by traceback" in content
    # Both sections use the same right-aligned `#NN` prefix.
    assert "# 1 " in content
    # Reference the captured allocations to keep them alive until the
    # snapshot has been taken.
    assert junk[0] == "x" * 1024


def test_write_threads_dump_creates_file(_isolate_memdiag):
    memdiag.install_memdiag_handlers("test")
    path = memdiag.write_threads_dump(reason="unit-test")
    assert path is not None
    content = open(path).read()
    assert "thread snapshot" in content
    # faulthandler.dump_traceback always emits at least the current
    # thread's stack; the marker line is "Current thread" or "Thread".
    assert "Thread" in content or "thread" in content


def test_sigusr1_handler_writes_dump(_isolate_memdiag):
    memdiag.install_memdiag_handlers("hardware")
    # Drive the handler directly — same code path the kernel would
    # invoke on a real SIGUSR1.
    memdiag._sigusr1_handler(signal.SIGUSR1, None)
    files = list(_isolate_memdiag.glob("eas-memdiag-hardware-*-memory.txt"))
    assert len(files) == 1


def test_sigusr2_handler_writes_threads_dump(_isolate_memdiag):
    memdiag.install_memdiag_handlers("hardware")
    memdiag._sigusr2_handler(signal.SIGUSR2, None)
    files = list(_isolate_memdiag.glob("eas-memdiag-hardware-*-threads.txt"))
    assert len(files) == 1


def test_format_bytes_handles_none_and_units():
    assert memdiag._format_bytes(None) == "unknown"
    assert memdiag._format_bytes(0) == "0.00 B"
    assert memdiag._format_bytes(2048) == "2.00 KiB"
    assert memdiag._format_bytes(5 * 1024 * 1024) == "5.00 MiB"


def test_dump_filenames_include_service_pid_and_kind(_isolate_memdiag):
    memdiag.install_memdiag_handlers("hardware")
    mem_path = memdiag.write_memory_dump()
    thr_path = memdiag.write_threads_dump()
    assert os.path.basename(mem_path).startswith(f"eas-memdiag-hardware-{os.getpid()}-")
    assert os.path.basename(mem_path).endswith("-memory.txt")
    assert os.path.basename(thr_path).endswith("-threads.txt")
