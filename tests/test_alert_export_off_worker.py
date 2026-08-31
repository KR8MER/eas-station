"""Regression tests for _run_off_worker (webapp/admin/api/routes_alert_export.py).

Guards against the bug caught during manual testing: db.engine needs an
active Flask application context to resolve (it reads current_app
internally), so it must be looked up on the calling greenlet *before*
spawning the thread, never inside the threaded closure itself -- which has
no app context pushed at all. The first version of this fix looked it up
inside the closure and failed every real request with
"RuntimeError: Working outside of application context."
"""

from __future__ import annotations

from webapp.admin.api.routes_alert_export import _run_off_worker


def test_runs_function_and_returns_result():
    assert _run_off_worker(lambda: 1 + 1) == 2


def test_passes_args_and_kwargs_through():
    def add(a, b, c=0):
        return a + b + c

    assert _run_off_worker(add, 1, 2, c=3) == 6


def test_propagates_exceptions_from_the_worker():
    def boom():
        raise ValueError("rendering failed")

    try:
        _run_off_worker(boom)
        assert False, "expected ValueError to propagate"
    except ValueError as exc:
        assert "rendering failed" in str(exc)


def test_actually_runs_on_a_different_thread_than_the_caller():
    import threading

    caller_thread = threading.current_thread().ident
    worker_thread = _run_off_worker(lambda: threading.current_thread().ident)
    assert worker_thread != caller_thread
