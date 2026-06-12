"""Tests for the GPS serial NMEA-silence watchdog.

A receiver (or USB-serial adapter) can wedge in a way that leaves the
port "open" while emitting no bytes; ``read(1)`` then just times out
forever and the reader loop spins without anyone noticing. The watchdog
detects a configurable stretch of silence and closes/reopens the port,
retrying until the receiver comes back. gpsd mode is unaffected — it has
its own socket reconnect logic.
"""

import threading
import time

import pytest

import app_core.gps.gps_manager as gps_manager_module
from app_core.gps.gps_manager import GPSManager


class FakeSerial:
    """Stand-in for serial.Serial that never produces data."""

    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.closed = False
        self.in_waiting = 0

    def read(self, _n=1):
        return b""

    def write(self, _data):
        return None

    def flush(self):
        return None

    def close(self):
        self.closed = True
        self.is_open = False


def _manager(config=None):
    # __init__ does not open the serial port or start threads, so this is
    # safe to construct in a unit test.
    return GPSManager(config=config or {}, redis_client=None)


def test_watchdog_defaults_to_30s():
    mgr = _manager()
    assert mgr._serial_watchdog_s == 30.0


def test_watchdog_config_overrides_default():
    mgr = _manager({"serial_watchdog_s": 12})
    assert mgr._serial_watchdog_s == 12.0


def test_watchdog_env_override(monkeypatch):
    monkeypatch.setenv("GPS_SERIAL_WATCHDOG_S", "45")
    mgr = _manager()
    assert mgr._serial_watchdog_s == 45.0


def test_watchdog_zero_disables():
    mgr = _manager({"serial_watchdog_s": 0})
    assert mgr._serial_watchdog_s == 0.0


def test_watchdog_garbage_value_falls_back():
    mgr = _manager({"serial_watchdog_s": "not-a-number"})
    assert mgr._serial_watchdog_s == 30.0


def test_reader_loop_fires_watchdog_on_silence():
    """A silent port trips the watchdog after the configured timeout."""
    mgr = _manager({"serial_watchdog_s": 0.05})
    mgr._ser = FakeSerial()
    mgr._running = True

    fired = threading.Event()

    def fake_reopen():
        fired.set()
        mgr._running = False  # stop the loop after the first trip

    mgr._watchdog_reopen_serial = fake_reopen

    loop = threading.Thread(target=mgr._reader_loop, daemon=True)
    loop.start()
    loop.join(timeout=5.0)

    assert fired.is_set(), "watchdog did not fire on a silent serial port"
    assert not loop.is_alive()


def test_reader_loop_does_not_fire_when_disabled():
    """With the watchdog disabled, silence never triggers a reopen."""
    mgr = _manager({"serial_watchdog_s": 0})
    mgr._ser = FakeSerial()
    mgr._running = True

    fired = threading.Event()
    mgr._watchdog_reopen_serial = lambda: fired.set()

    loop = threading.Thread(target=mgr._reader_loop, daemon=True)
    loop.start()
    time.sleep(0.3)
    mgr._running = False
    loop.join(timeout=5.0)

    assert not fired.is_set()


def test_reopen_replaces_port_and_counts(monkeypatch):
    import serial

    monkeypatch.setattr(serial, "Serial", FakeSerial)

    mgr = _manager({"serial_watchdog_s": 1})
    old_port = FakeSerial()
    mgr._ser = old_port
    mgr._running = True

    mgr._watchdog_reopen_serial()

    assert old_port.closed
    assert isinstance(mgr._ser, FakeSerial)
    assert mgr._ser is not old_port
    assert mgr._watchdog_restarts == 1
    assert mgr.get_status()["watchdog_restarts"] == 1
    assert mgr._fix["status"] == "reading"


def test_reopen_retries_until_port_returns(monkeypatch):
    """Open failures (e.g. unplugged USB adapter) retry instead of dying."""
    import serial

    attempts = {"n": 0}

    def flaky_serial(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("device not present")
        return FakeSerial(*args, **kwargs)

    monkeypatch.setattr(serial, "Serial", flaky_serial)
    monkeypatch.setattr(gps_manager_module.time, "sleep", lambda _s: None)

    mgr = _manager({"serial_watchdog_s": 1})
    mgr._ser = FakeSerial()
    mgr._running = True

    mgr._watchdog_reopen_serial()

    assert attempts["n"] == 3
    assert isinstance(mgr._ser, FakeSerial)
    assert mgr._fix["status"] == "reading"


def test_reopen_gives_up_when_manager_stopped(monkeypatch):
    """If the manager is stopped mid-retry, the watchdog exits quietly."""
    import serial

    def always_fail(*args, **kwargs):
        mgr._running = False  # simulate stop() arriving during the retry loop
        raise OSError("device not present")

    monkeypatch.setattr(serial, "Serial", always_fail)
    monkeypatch.setattr(gps_manager_module.time, "sleep", lambda _s: None)

    mgr = _manager({"serial_watchdog_s": 1})
    mgr._ser = FakeSerial()
    mgr._running = True

    mgr._watchdog_reopen_serial()  # must return rather than loop forever

    assert mgr._watchdog_restarts == 1
