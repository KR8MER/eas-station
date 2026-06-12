"""Tests for the two-stage gpsd watchdog.

Stage 1 (event silence): gpsd emits TPV/SKY at ~1 Hz while a WATCH is
active, fix or no fix — so prolonged silence on an open socket means gpsd
is wedged, and the reader forces a reconnect.

Stage 2 (stuck acquiring): events keep flowing but TPV never reaches
mode 2/3. gpsd is known to wedge in this state after serial/USB hiccups
(historically cleared only by a reboot); the watchdog restarts the gpsd
daemon, rate-limited by a cooldown so a genuinely poor sky view cannot
cause a restart loop.
"""

import time

import pytest

import app_core.gps.gps_manager as gps_manager_module
from app_core.gps.gps_manager import GPSManager


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _manager(config=None):
    return GPSManager(config=config or {}, redis_client=None)


class TestConfig:
    def test_defaults(self):
        mgr = _manager()
        assert mgr._gpsd_watchdog_s == 60.0
        assert mgr._gpsd_stuck_acquiring_s == 900.0

    def test_config_overrides(self):
        mgr = _manager({"gpsd_watchdog_s": 120, "gpsd_stuck_acquiring_s": 300})
        assert mgr._gpsd_watchdog_s == 120.0
        assert mgr._gpsd_stuck_acquiring_s == 300.0

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("GPS_GPSD_WATCHDOG_S", "90")
        monkeypatch.setenv("GPS_GPSD_STUCK_ACQUIRING_S", "600")
        mgr = _manager()
        assert mgr._gpsd_watchdog_s == 90.0
        assert mgr._gpsd_stuck_acquiring_s == 600.0

    def test_zero_disables(self):
        mgr = _manager({"gpsd_watchdog_s": 0, "gpsd_stuck_acquiring_s": 0})
        assert mgr._gpsd_watchdog_s == 0.0
        assert mgr._gpsd_stuck_acquiring_s == 0.0


class TestStageOneSilence:
    def test_silence_forces_reconnect(self):
        mgr = _manager()
        sock = FakeSocket()
        mgr._gpsd_sock = sock
        mgr._gpsd_last_event_monotonic = time.monotonic() - 61
        mgr._gpsd_last_fix_monotonic = time.monotonic()  # keep stage 2 quiet

        assert mgr._gpsd_watchdog_check() is True
        assert sock.closed
        assert mgr._gpsd_sock is None
        assert mgr._gpsd_watchdog_reconnects == 1
        assert mgr.get_status()["gpsd_watchdog_reconnects"] == 1

    def test_recent_events_do_not_fire(self):
        mgr = _manager()
        mgr._gpsd_sock = FakeSocket()
        now = time.monotonic()
        mgr._gpsd_last_event_monotonic = now
        mgr._gpsd_last_fix_monotonic = now

        assert mgr._gpsd_watchdog_check() is False
        assert mgr._gpsd_watchdog_reconnects == 0

    def test_disabled_stage_one_never_fires(self):
        mgr = _manager({"gpsd_watchdog_s": 0})
        mgr._gpsd_sock = FakeSocket()
        now = time.monotonic()
        mgr._gpsd_last_event_monotonic = now - 3600
        mgr._gpsd_last_fix_monotonic = now

        assert mgr._gpsd_watchdog_check() is False


class TestStageTwoStuckAcquiring:
    def _stuck_manager(self, **config):
        mgr = _manager(config or None)
        mgr._gpsd_sock = FakeSocket()
        now = time.monotonic()
        mgr._gpsd_last_event_monotonic = now  # events flowing
        mgr._gpsd_last_fix_monotonic = now - 901  # but no fix for >15 min
        return mgr

    def test_stuck_acquiring_restarts_gpsd(self):
        mgr = self._stuck_manager()
        calls = []
        mgr._restart_gpsd_daemon = lambda: calls.append(1) or True

        assert mgr._gpsd_watchdog_check() is True
        assert calls == [1]
        assert mgr._gpsd_sock is None
        assert mgr._gpsd_last_daemon_restart_monotonic is not None

    def test_cooldown_blocks_back_to_back_restarts(self):
        mgr = self._stuck_manager()
        mgr._restart_gpsd_daemon = lambda: True
        assert mgr._gpsd_watchdog_check() is True

        # Immediately stuck again — cooldown must hold the second attempt.
        mgr._gpsd_sock = FakeSocket()
        mgr._gpsd_last_fix_monotonic = time.monotonic() - 901
        assert mgr._gpsd_watchdog_check() is False

    def test_fires_again_after_cooldown_and_window(self):
        mgr = self._stuck_manager()
        calls = []
        mgr._restart_gpsd_daemon = lambda: calls.append(1) or True
        # Last restart long enough ago that both the cooldown (1800s) and a
        # fresh stuck window (900s) measured from it have elapsed.
        mgr._gpsd_last_daemon_restart_monotonic = time.monotonic() - 1801
        mgr._gpsd_last_fix_monotonic = time.monotonic() - 5000

        assert mgr._gpsd_watchdog_check() is True
        assert calls == [1]

    def test_recent_fix_keeps_stage_two_quiet(self):
        mgr = self._stuck_manager()
        mgr._gpsd_last_fix_monotonic = time.monotonic()
        assert mgr._gpsd_watchdog_check() is False

    def test_disabled_stage_two_never_fires(self):
        mgr = self._stuck_manager(gpsd_stuck_acquiring_s=0)
        fired = []
        mgr._restart_gpsd_daemon = lambda: fired.append(1)
        assert mgr._gpsd_watchdog_check() is False
        assert not fired


class TestDaemonRestart:
    class _Result:
        def __init__(self, rc):
            self.returncode = rc
            self.stderr = ""

    def test_successful_restart_counts_and_stamps(self, monkeypatch):
        runs = []

        def fake_run(cmd, **kwargs):
            runs.append(cmd)
            return TestDaemonRestart._Result(0)

        monkeypatch.setattr(gps_manager_module.subprocess, "run", fake_run)
        mgr = _manager()

        assert mgr._restart_gpsd_daemon() is True
        assert mgr._gpsd_daemon_restarts == 1
        status = mgr.get_status()
        assert status["gpsd_daemon_restarts"] == 1
        assert status["gpsd_last_daemon_restart_at"] is not None
        # sudo -n succeeded for both units; no plain-systemctl fallback runs.
        assert len(runs) == 2
        assert all(cmd[0] == "sudo" for cmd in runs)

    def test_falls_back_to_plain_systemctl(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            # sudo path fails (no sudoers rule); plain systemctl works.
            rc = 1 if cmd[0] == "sudo" else 0
            return TestDaemonRestart._Result(rc)

        monkeypatch.setattr(gps_manager_module.subprocess, "run", fake_run)
        mgr = _manager()
        assert mgr._restart_gpsd_daemon() is True

    def test_total_failure_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            gps_manager_module.subprocess,
            "run",
            lambda cmd, **kw: TestDaemonRestart._Result(1),
        )
        mgr = _manager()
        assert mgr._restart_gpsd_daemon() is False
        assert mgr._gpsd_daemon_restarts == 1


class TestTPVFixStamp:
    def test_mode2_stamps_fix_time(self):
        mgr = _manager()
        mgr._gpsd_last_fix_monotonic = None
        mgr._handle_gpsd_tpv({"class": "TPV", "mode": 2})
        assert mgr._gpsd_last_fix_monotonic is not None

    def test_mode1_does_not_stamp(self):
        mgr = _manager()
        mgr._gpsd_last_fix_monotonic = None
        mgr._handle_gpsd_tpv({"class": "TPV", "mode": 1})
        assert mgr._gpsd_last_fix_monotonic is None
