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

"""Tests for the GPIO-triggered "Dump / Abort Broadcast" input action and
the _run_command() PID-tracking refactor it depends on.

_run_command() is on every broadcast path (RWT, resend, live alerts), so
its regression coverage here is deliberately the heaviest of the four GPIO
input action phases -- see the plan's own framing of this as the
highest-risk change.
"""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeRedis:
    def __init__(self, kv=None):
        self.kv = dict(kv or {})
        self.deleted = []

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def setex(self, key, ttl, value):
        self.kv[key] = value

    def delete(self, key):
        self.deleted.append(key)
        self.kv.pop(key, None)


@pytest.fixture
def redis_client_factory(monkeypatch):
    def _install(client):
        import app_core.redis_client as redis_client_module
        monkeypatch.setattr(redis_client_module, "get_redis_client", lambda: client)
    return _install


class _FakeProcess:
    """Stand-in for subprocess.Popen's return value."""

    def __init__(self, pid=4242, wait_exception=None):
        self.pid = pid
        self._wait_exception = wait_exception
        self.wait_called = False

    def wait(self):
        self.wait_called = True
        if self._wait_exception:
            raise self._wait_exception


# ---------------------------------------------------------------------------
# _run_command() refactor regression
# ---------------------------------------------------------------------------


def test_run_command_still_blocks_until_exit(monkeypatch, redis_client_factory):
    from app_utils import eas as eas_module

    redis_client_factory(_FakeRedis())
    process = _FakeProcess(pid=1234)
    monkeypatch.setattr(eas_module.subprocess, "Popen", lambda *a, **k: process)

    eas_module._run_command(["aplay", "test.wav"], logger=None)

    assert process.wait_called is True


def test_run_command_publishes_and_clears_pid_on_success(monkeypatch, redis_client_factory):
    from app_utils import eas as eas_module

    client = _FakeRedis()
    redis_client_factory(client)
    process = _FakeProcess(pid=5555)
    monkeypatch.setattr(eas_module.subprocess, "Popen", lambda *a, **k: process)

    eas_module._run_command(["aplay", "test.wav"], logger=None)

    # Cleared after the command completes -- no stale PID left behind.
    assert eas_module._BROADCAST_PID_KEY in client.deleted
    assert eas_module._BROADCAST_PID_KEY not in client.kv


def test_run_command_clears_pid_even_if_wait_raises(monkeypatch, redis_client_factory):
    from app_utils import eas as eas_module

    client = _FakeRedis()
    redis_client_factory(client)
    process = _FakeProcess(pid=6666, wait_exception=OSError("boom"))
    monkeypatch.setattr(eas_module.subprocess, "Popen", lambda *a, **k: process)

    logged = []
    fake_logger = type("L", (), {"warning": lambda self, msg: logged.append(msg)})()

    # Original behavior: exception is swallowed and logged, never raised.
    eas_module._run_command(["aplay", "test.wav"], logger=fake_logger)

    assert len(logged) == 1
    assert eas_module._BROADCAST_PID_KEY not in client.kv


def test_run_command_swallows_launch_failure_like_before(monkeypatch, redis_client_factory):
    from app_utils import eas as eas_module

    redis_client_factory(_FakeRedis())

    def _raise(*a, **k):
        raise FileNotFoundError("no such player")

    monkeypatch.setattr(eas_module.subprocess, "Popen", _raise)

    logged = []
    fake_logger = type("L", (), {"warning": lambda self, msg: logged.append(msg)})()

    # Must not raise -- matches subprocess.run(check=False)'s original
    # swallow-and-log behavior for a launch failure.
    eas_module._run_command(["nonexistent-player", "test.wav"], logger=fake_logger)

    assert len(logged) == 1


def test_get_broadcast_pid_reads_published_value(redis_client_factory):
    from app_utils.eas import _BROADCAST_PID_KEY, get_broadcast_pid

    redis_client_factory(_FakeRedis({_BROADCAST_PID_KEY: "9999"}))

    assert get_broadcast_pid() == 9999


def test_get_broadcast_pid_none_when_not_set(redis_client_factory):
    from app_utils.eas import get_broadcast_pid

    redis_client_factory(_FakeRedis())

    assert get_broadcast_pid() is None


# ---------------------------------------------------------------------------
# abort_current_broadcast()
# ---------------------------------------------------------------------------


def test_abort_is_noop_when_nothing_playing(monkeypatch):
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr(gpio_input_actions, "logger", gpio_input_actions.logger)
    monkeypatch.setattr("app_utils.eas.get_broadcast_pid", lambda: None)

    killed = []
    monkeypatch.setattr("os.kill", lambda pid, sig: killed.append((pid, sig)))

    # Must not raise, must not touch a process that doesn't exist.
    gpio_input_actions.abort_current_broadcast()

    assert killed == []


def test_abort_sends_sigterm_then_clears_marker_and_audits(monkeypatch):
    import signal

    from app_core.audio import gpio_input_actions

    monkeypatch.setattr("app_utils.eas.get_broadcast_pid", lambda: 4321)
    monkeypatch.setattr(
        "app_utils.eas.get_broadcast_state",
        lambda: {"active": True, "label": "Tornado Warning", "identifier": "urn:test-1"},
    )

    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == 0:
            # First liveness check: alive. Every later poll during the
            # grace-period loop: report exited so the loop ends fast.
            if kill_calls.count((pid, 0)) > 1:
                raise ProcessLookupError()

    monkeypatch.setattr("os.kill", fake_kill)
    monkeypatch.setattr("time.sleep", lambda s: None)

    cleared = []
    monkeypatch.setattr("app_utils.eas.clear_broadcast_active", lambda: cleared.append(True))

    audit_calls = []
    import app_core.auth.audit as audit_module
    monkeypatch.setattr(audit_module.AuditLogger, "log", lambda **kwargs: audit_calls.append(kwargs))

    gpio_input_actions.abort_current_broadcast(reason="test abort", operator="tester")

    assert (4321, signal.SIGTERM) in kill_calls
    assert cleared == [True]
    assert len(audit_calls) == 1
    assert audit_calls[0]["resource_id"] == "urn:test-1"
    assert audit_calls[0]["details"]["reason"] == "test abort"
    assert audit_calls[0]["details"]["label"] == "Tornado Warning"
    assert audit_calls[0]["username"] == "tester"


def test_abort_escalates_to_sigkill_after_grace_period(monkeypatch):
    import signal

    from app_core.audio import gpio_input_actions

    monkeypatch.setattr("app_utils.eas.get_broadcast_pid", lambda: 7777)
    monkeypatch.setattr(
        "app_utils.eas.get_broadcast_state", lambda: {"active": True, "label": "RWT"},
    )
    monkeypatch.setattr("app_utils.eas.clear_broadcast_active", lambda: None)
    import app_core.auth.audit as audit_module
    monkeypatch.setattr(audit_module.AuditLogger, "log", lambda **kwargs: None)

    kill_calls = []
    # Process never reports as exited (ProcessLookupError never raised) --
    # forces the grace-period loop to time out and escalate to SIGKILL.
    monkeypatch.setattr("os.kill", lambda pid, sig: kill_calls.append((pid, sig)))

    # Fast-forward the grace-period wait loop instantly.
    times = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr("time.monotonic", lambda: next(times, 100.0))
    monkeypatch.setattr("time.sleep", lambda s: None)

    gpio_input_actions.abort_current_broadcast()

    assert (7777, signal.SIGTERM) in kill_calls
    assert (7777, signal.SIGKILL) in kill_calls


def test_abort_process_already_exited_still_clears_marker(monkeypatch):
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr("app_utils.eas.get_broadcast_pid", lambda: 8888)
    monkeypatch.setattr(
        "app_utils.eas.get_broadcast_state", lambda: {"active": True, "label": "x"},
    )

    def fake_kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr("os.kill", fake_kill)

    cleared = []
    monkeypatch.setattr("app_utils.eas.clear_broadcast_active", lambda: cleared.append(True))

    gpio_input_actions.abort_current_broadcast()

    assert cleared == [True]


# ---------------------------------------------------------------------------
# Dispatch wiring
# ---------------------------------------------------------------------------


def test_dispatch_wiring_calls_abort_action(monkeypatch):
    from app_core import gpio_input_listener

    calls = []
    monkeypatch.setattr(
        "app_core.audio.gpio_input_actions.abort_current_broadcast",
        lambda: calls.append(True),
    )

    gpio_input_listener._dispatch_input_action({"pin": 26, "action": "dump_broadcast"})

    assert calls == [True]
