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
the _run_command()/play_broadcast_audio() PID+EOM-tracking refactor it
depends on.

_run_command() (and its public wrapper play_broadcast_audio(), used by the
three other broadcast-playback call sites: RWT airchain, manual Send
workflow, resend script) is on every broadcast path, so its regression
coverage here is deliberately the heaviest of the four GPIO input action
phases -- see the plan's own framing of this as the highest-risk change.

abort_current_broadcast() must never let a broadcast end without an EOM
burst (47 CFR 11.61(a)) -- that requirement is exercised explicitly below.
"""

from pathlib import Path
import sys
from types import SimpleNamespace

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
        self.wait_timeout = "unset"
        self.killed = False

    def wait(self, timeout=None):
        self.wait_called = True
        self.wait_timeout = timeout
        if self._wait_exception:
            raise self._wait_exception

    def kill(self):
        self.killed = True


class _FakeTimeoutProcess:
    """Popen stand-in whose first wait() times out, second succeeds --
    models a hung player that a timeout has to kill."""

    def __init__(self, pid=9090):
        self.pid = pid
        self.kill_called = False
        self._wait_calls = 0

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls == 1:
            import subprocess
            raise subprocess.TimeoutExpired(cmd="aplay", timeout=timeout)
        return 0

    def kill(self):
        self.kill_called = True


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


def test_run_command_publishes_and_clears_eom_wav(monkeypatch, redis_client_factory):
    from app_utils import eas as eas_module

    client = _FakeRedis()
    redis_client_factory(client)
    process = _FakeProcess(pid=5556)
    monkeypatch.setattr(eas_module.subprocess, "Popen", lambda *a, **k: process)

    published = {}
    original_wait = process.wait

    def _wait_and_snapshot(timeout=None):
        # Snapshot mid-flight, before the finally clause clears it.
        published["pid"] = client.kv.get(eas_module._BROADCAST_PID_KEY)
        published["eom"] = client.kv.get(eas_module._BROADCAST_EOM_KEY)
        return original_wait(timeout=timeout)

    process.wait = _wait_and_snapshot

    eas_module._run_command(["aplay", "test.wav"], logger=None, eom_wav=b"EOMBYTES")

    assert published["pid"] == "5556"
    # Stored base64-encoded: the real Redis client is configured with
    # decode_responses=True (see _publish_broadcast_pid()'s docstring), which
    # UTF-8-decodes every value on read -- raw WAV bytes are not valid UTF-8.
    import base64
    assert published["eom"] == base64.b64encode(b"EOMBYTES").decode('ascii')
    assert eas_module._BROADCAST_EOM_KEY in client.deleted
    assert eas_module._BROADCAST_EOM_KEY not in client.kv


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


def test_run_command_kills_on_timeout(monkeypatch, redis_client_factory):
    """RWT airchain / manual Send / resend all bound playback to their own
    broadcast length via timeout=... -- confirm _run_command() now handles
    that the same way subprocess.run(..., timeout=...) + TimeoutExpired used
    to at each of those call sites."""
    from app_utils import eas as eas_module

    client = _FakeRedis()
    redis_client_factory(client)
    process = _FakeTimeoutProcess()
    monkeypatch.setattr(eas_module.subprocess, "Popen", lambda *a, **k: process)

    logged = []
    fake_logger = type("L", (), {"warning": lambda self, msg: logged.append(msg)})()

    eas_module._run_command(["aplay", "test.wav"], logger=fake_logger, timeout=5.0)

    assert process.kill_called is True
    assert len(logged) == 1
    assert eas_module._BROADCAST_PID_KEY not in client.kv


def test_play_broadcast_audio_delegates_to_run_command(monkeypatch, redis_client_factory):
    from app_utils import eas as eas_module

    client = _FakeRedis()
    redis_client_factory(client)
    process = _FakeProcess(pid=7070)
    monkeypatch.setattr(eas_module.subprocess, "Popen", lambda *a, **k: process)

    eas_module.play_broadcast_audio(
        ["aplay", "test.wav"], logger=None, eom_wav=b"EOM", timeout=12.0,
    )

    assert process.wait_called is True
    assert process.wait_timeout == 12.0


def test_get_broadcast_pid_reads_published_value(redis_client_factory):
    from app_utils.eas import _BROADCAST_PID_KEY, get_broadcast_pid

    redis_client_factory(_FakeRedis({_BROADCAST_PID_KEY: "9999"}))

    assert get_broadcast_pid() == 9999


def test_get_broadcast_pid_none_when_not_set(redis_client_factory):
    from app_utils.eas import get_broadcast_pid

    redis_client_factory(_FakeRedis())

    assert get_broadcast_pid() is None


def test_get_broadcast_eom_audio_reads_published_value(redis_client_factory):
    import base64

    from app_utils.eas import _BROADCAST_EOM_KEY, get_broadcast_eom_audio

    # Seeded base64-encoded, matching what _publish_broadcast_pid() actually
    # writes through the real (decode_responses=True) Redis client.
    encoded = base64.b64encode(b"EOMDATA").decode('ascii')
    redis_client_factory(_FakeRedis({_BROADCAST_EOM_KEY: encoded}))

    assert get_broadcast_eom_audio() == b"EOMDATA"


def test_get_broadcast_eom_audio_none_when_not_set(redis_client_factory):
    from app_utils.eas import get_broadcast_eom_audio

    redis_client_factory(_FakeRedis())

    assert get_broadcast_eom_audio() is None


# ---------------------------------------------------------------------------
# abort_current_broadcast()
# ---------------------------------------------------------------------------


def test_abort_is_noop_when_nothing_playing(monkeypatch):
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr(gpio_input_actions, "logger", gpio_input_actions.logger)
    monkeypatch.setattr("app_utils.eas.get_broadcast_pid", lambda: None)
    # No PID published AND no active marker -- genuinely nothing to abort.
    # Explicitly mocked (rather than relying on the real function's
    # no-Redis-available fallback) so this stays fast and deterministic
    # regardless of what Redis this test happens to run next to.
    monkeypatch.setattr("app_utils.eas.get_broadcast_state", lambda: {"active": False})

    killed = []
    monkeypatch.setattr("os.kill", lambda pid, sig: killed.append((pid, sig)))

    # Must not raise, must not touch a process that doesn't exist.
    gpio_input_actions.abort_current_broadcast()

    assert killed == []


def _install_common_abort_mocks(monkeypatch, pid, label="Tornado Warning", identifier="urn:test-1",
                                 eom_wav=b"EOMBYTES"):
    monkeypatch.setattr("app_utils.eas.get_broadcast_pid", lambda: pid)
    monkeypatch.setattr(
        "app_utils.eas.get_broadcast_state",
        lambda: {"active": True, "label": label, "identifier": identifier},
    )
    monkeypatch.setattr("app_utils.eas.get_broadcast_eom_audio", lambda: eom_wav)

    cleared = []
    monkeypatch.setattr("app_utils.eas.clear_broadcast_active", lambda: cleared.append(True))

    audit_calls = []
    import app_core.auth.audit as audit_module
    monkeypatch.setattr(audit_module.AuditLogger, "log", lambda **kwargs: audit_calls.append(kwargs))

    # abort_current_broadcast() now also purges audio already queued into
    # the live Icecast air-chain via this Redis command -- mock it to a fast
    # canned response so tests don't pay a real (and, with no Redis
    # reachable, slow-retrying) connection attempt just to be swallowed by
    # the caller's own try/except.
    abort_injected_calls = []

    class _FakePublisher:
        def abort_injected_audio(self, eom_wav=None, timeout=10.0):
            abort_injected_calls.append({"eom_wav": eom_wav, "timeout": timeout})
            return {"success": True, "message": "ok", "data": {"cleared": 3}}

    monkeypatch.setattr(
        "app_core.audio.redis_commands.get_audio_command_publisher",
        lambda: _FakePublisher(),
    )

    return cleared, audit_calls, abort_injected_calls


def test_abort_sends_sigterm_plays_eom_then_clears_marker_and_audits(monkeypatch):
    import signal

    from app_core.audio import gpio_input_actions

    cleared, audit_calls, abort_injected_calls = _install_common_abort_mocks(monkeypatch, pid=4321)

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

    eom_calls = []

    def fake_play_eom(eom_wav):
        eom_calls.append(eom_wav)
        # EOM must play before the marker is cleared / audit is written.
        assert cleared == []
        assert audit_calls == []
        return True

    monkeypatch.setattr(gpio_input_actions, "_play_abort_eom_burst", fake_play_eom)

    gpio_input_actions.abort_current_broadcast(reason="test abort", operator="tester")

    assert (4321, signal.SIGTERM) in kill_calls
    assert eom_calls == [b"EOMBYTES"]
    assert cleared == [True]
    assert len(audit_calls) == 1
    assert audit_calls[0]["resource_id"] == "urn:test-1"
    assert audit_calls[0]["details"]["reason"] == "test abort"
    assert audit_calls[0]["details"]["label"] == "Tornado Warning"
    assert audit_calls[0]["details"]["eom_sent"] is True
    assert audit_calls[0]["username"] == "tester"
    # The Icecast air-chain purge must run too, carrying the same EOM audio
    # so stream listeners hear a compliant sign-off rather than dead air.
    assert len(abort_injected_calls) == 1
    assert abort_injected_calls[0]["eom_wav"] == b"EOMBYTES"
    assert audit_calls[0]["details"]["injected_audio_cleared"] == 3


def test_abort_without_eom_audio_still_completes_and_flags_it(monkeypatch):
    """No EOM audio was ever published for this broadcast (e.g. a config
    gap) -- abort must not hang the relay forever waiting for audio that
    will never arrive, but the audit trail must clearly show the EOM was
    NOT sent."""
    from app_core.audio import gpio_input_actions

    cleared, audit_calls, _abort_injected_calls = _install_common_abort_mocks(
        monkeypatch, pid=5432, eom_wav=None,
    )

    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == 0 and kill_calls.count((pid, 0)) > 1:
            raise ProcessLookupError()

    monkeypatch.setattr("os.kill", fake_kill)
    monkeypatch.setattr("time.sleep", lambda s: None)

    play_eom_calls = []
    monkeypatch.setattr(
        gpio_input_actions, "_play_abort_eom_burst",
        lambda eom_wav: play_eom_calls.append(eom_wav) or True,
    )

    gpio_input_actions.abort_current_broadcast()

    # Never invoked -- there was nothing to play.
    assert play_eom_calls == []
    assert cleared == [True]
    assert audit_calls[0]["details"]["eom_sent"] is False


def test_abort_eom_playback_failure_still_completes_and_flags_it(monkeypatch):
    """The EOM burst genuinely fails to play (bad audio device, etc.) --
    abort must still eventually release the relay (a broadcast stuck
    forever is its own violation) but the audit record must say so."""
    from app_core.audio import gpio_input_actions

    cleared, audit_calls, _abort_injected_calls = _install_common_abort_mocks(monkeypatch, pid=6543)

    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == 0 and kill_calls.count((pid, 0)) > 1:
            raise ProcessLookupError()

    monkeypatch.setattr("os.kill", fake_kill)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(gpio_input_actions, "_play_abort_eom_burst", lambda eom_wav: False)

    gpio_input_actions.abort_current_broadcast()

    assert cleared == [True]
    assert audit_calls[0]["details"]["eom_sent"] is False


def test_abort_escalates_to_sigkill_then_settles_before_eom(monkeypatch):
    import signal

    from app_core.audio import gpio_input_actions

    cleared, audit_calls, _abort_injected_calls = _install_common_abort_mocks(
        monkeypatch, pid=7777, label="RWT", identifier=None,
    )

    kill_calls = []
    # Process never reports as exited via SIGTERM-phase polls, but does
    # report exited once SIGKILL "lands" (post-kill settle loop) so the
    # settle loop can exit promptly instead of exhausting its own deadline.
    sigkill_sent = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == signal.SIGKILL:
            sigkill_sent.append(True)
        elif sig == 0 and sigkill_sent:
            raise ProcessLookupError()

    monkeypatch.setattr("os.kill", fake_kill)

    # Fast-forward the grace-period wait loop instantly; the settle loop
    # uses its own monotonic() calls too, so keep returning a large value.
    times = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr("time.monotonic", lambda: next(times, 100.0))
    monkeypatch.setattr("time.sleep", lambda s: None)

    eom_calls = []
    monkeypatch.setattr(
        gpio_input_actions, "_play_abort_eom_burst",
        lambda eom_wav: eom_calls.append(eom_wav) or True,
    )

    gpio_input_actions.abort_current_broadcast()

    assert (7777, signal.SIGTERM) in kill_calls
    assert (7777, signal.SIGKILL) in kill_calls
    assert eom_calls == [b"EOMBYTES"]
    assert cleared == [True]


def test_abort_process_already_exited_still_clears_marker(monkeypatch):
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr("app_utils.eas.get_broadcast_pid", lambda: 8888)
    monkeypatch.setattr(
        "app_utils.eas.get_broadcast_state", lambda: {"active": True, "label": "x"},
    )
    monkeypatch.setattr("app_utils.eas.get_broadcast_eom_audio", lambda: None)
    # The Icecast purge still runs even though the local process was already
    # gone -- mocked to a fast canned response rather than a real (and, with
    # no Redis reachable, slow-retrying) connection attempt.
    monkeypatch.setattr(
        "app_core.audio.redis_commands.get_audio_command_publisher",
        lambda: SimpleNamespace(
            abort_injected_audio=lambda eom_wav=None, timeout=10.0: {
                "success": True, "message": "ok", "data": {"cleared": 0},
            },
        ),
    )
    import app_core.auth.audit as audit_module
    monkeypatch.setattr(audit_module.AuditLogger, "log", lambda **kwargs: None)

    def fake_kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr("os.kill", fake_kill)

    cleared = []
    monkeypatch.setattr("app_utils.eas.clear_broadcast_active", lambda: cleared.append(True))

    gpio_input_actions.abort_current_broadcast()

    assert cleared == [True]


def test_abort_works_with_no_local_pid_but_active_icecast_broadcast(monkeypatch):
    """A station with no local audio player configured at all (Icecast-only,
    a real supported deployment) never has a trackable PID -- before this
    fix, abort_current_broadcast() returned immediately in this case
    ("nothing is currently playing") even while the alert was actively
    streaming to Icecast listeners. It must now still purge the queued
    audio, attempt the EOM burst, release the marker, and audit the abort."""
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr("app_utils.eas.get_broadcast_pid", lambda: None)
    monkeypatch.setattr(
        "app_utils.eas.get_broadcast_state",
        lambda: {"active": True, "label": "Tornado Warning", "identifier": "urn:test-2"},
    )
    monkeypatch.setattr("app_utils.eas.get_broadcast_eom_audio", lambda: b"EOMBYTES")

    cleared = []
    monkeypatch.setattr("app_utils.eas.clear_broadcast_active", lambda: cleared.append(True))

    audit_calls = []
    import app_core.auth.audit as audit_module
    monkeypatch.setattr(audit_module.AuditLogger, "log", lambda **kwargs: audit_calls.append(kwargs))

    abort_injected_calls = []

    class _FakePublisher:
        def abort_injected_audio(self, eom_wav=None, timeout=10.0):
            abort_injected_calls.append(eom_wav)
            return {"success": True, "message": "ok", "data": {"cleared": 12}}

    monkeypatch.setattr(
        "app_core.audio.redis_commands.get_audio_command_publisher",
        lambda: _FakePublisher(),
    )

    killed = []
    monkeypatch.setattr("os.kill", lambda pid, sig: killed.append((pid, sig)))

    eom_calls = []
    monkeypatch.setattr(
        gpio_input_actions, "_play_abort_eom_burst",
        lambda eom_wav: eom_calls.append(eom_wav) or True,
    )

    gpio_input_actions.abort_current_broadcast(reason="test", operator="tester")

    # No local process to touch -- but the Icecast queue and EOM burst
    # still had to be handled, and the broadcast still had to be released.
    assert killed == []
    assert abort_injected_calls == [b"EOMBYTES"]
    assert eom_calls == [b"EOMBYTES"]
    assert cleared == [True]
    assert len(audit_calls) == 1
    assert audit_calls[0]["details"]["injected_audio_cleared"] == 12
    assert audit_calls[0]["details"]["eom_sent"] is True


def test_play_abort_eom_burst_runs_configured_player(monkeypatch):
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr(
        "app_utils.eas.load_eas_config", lambda: {"audio_player_cmd": ["aplay"]},
    )

    run_calls = []

    class _FakeResult:
        returncode = 0

    def fake_run(command, check=False, timeout=None):
        run_calls.append((command, timeout))
        return _FakeResult()

    monkeypatch.setattr(gpio_input_actions.subprocess, "run", fake_run)

    result = gpio_input_actions._play_abort_eom_burst(b"RIFF....fakewav")

    assert result is True
    assert len(run_calls) == 1
    assert run_calls[0][0][0] == "aplay"


def test_play_abort_eom_burst_false_when_no_player_configured(monkeypatch):
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr("app_utils.eas.load_eas_config", lambda: {"audio_player_cmd": None})

    assert gpio_input_actions._play_abort_eom_burst(b"RIFF....fakewav") is False


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
