"""Tests for SDR discovery augmentation with in-use receivers.

librtlsdr claims the USB interface exclusively while a receiver is
streaming, so a busy RTL-SDR disappears from SoapySDR enumeration —
"Discover USB Devices" on a healthy single-dongle system reported
"No SDR devices found".  The sdr-service now synthesizes device entries
for hardware held by loaded receivers so the setup UI reflects reality.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sdr_hardware_service as svc  # noqa: E402


class _FakeConfig:
    def __init__(self, driver, serial):
        self.driver = driver
        self.serial = serial


class _FakeReceiver:
    def __init__(self, driver, serial, running=True):
        self.config = _FakeConfig(driver, serial)
        self._running = running

    def is_running(self):
        return self._running


class _FakeManager:
    def __init__(self, receivers):
        self._receivers = receivers


def _with_manager(receivers):
    svc._state.radio_manager = _FakeManager(receivers)


def teardown_function(_fn):
    svc._state.radio_manager = None


def test_busy_receiver_hardware_reported_when_enumeration_empty():
    _with_manager({"sdr": _FakeReceiver("rtlsdr", "00000001")})

    devices = svc._augment_discovery_with_active_receivers([])

    assert len(devices) == 1
    dev = devices[0]
    assert dev["driver"] == "rtlsdr"
    assert dev["serial"] == "00000001"
    assert dev["in_use"] is True
    assert dev["receiver_identifier"] == "sdr"
    assert "in use by receiver 'sdr'" in dev["label"]


def test_enumerated_device_not_duplicated():
    """If enumeration already sees the dongle, no synthetic entry is added."""
    _with_manager({"sdr": _FakeReceiver("rtlsdr", "00000001")})
    enumerated = [{"driver": "rtlsdr", "serial": "00000001", "label": "Generic RTL"}]

    devices = svc._augment_discovery_with_active_receivers(list(enumerated))

    assert devices == enumerated


def test_serialless_config_skipped_when_same_driver_enumerated():
    """A serial-less receiver can't be matched exactly; don't double-report
    the dongle when enumeration already found one with that driver."""
    _with_manager({"sdr": _FakeReceiver("rtlsdr", "")})
    enumerated = [{"driver": "rtlsdr", "serial": "00000001", "label": "Generic RTL"}]

    devices = svc._augment_discovery_with_active_receivers(list(enumerated))

    assert devices == enumerated


def test_serialless_config_reported_when_nothing_enumerated():
    _with_manager({"sdr": _FakeReceiver("rtlsdr", "")})

    devices = svc._augment_discovery_with_active_receivers([])

    assert len(devices) == 1
    assert devices[0]["driver"] == "rtlsdr"
    assert devices[0]["in_use"] is True


def test_stopped_receiver_labelled_assigned_not_in_use():
    _with_manager({"sdr": _FakeReceiver("rtlsdr", "00000001", running=False)})

    devices = svc._augment_discovery_with_active_receivers([])

    assert len(devices) == 1
    assert devices[0]["in_use"] is False
    assert "assigned to receiver 'sdr'" in devices[0]["label"]


def test_no_manager_is_a_noop():
    svc._state.radio_manager = None
    enumerated = [{"driver": "airspy", "serial": "X1"}]

    devices = svc._augment_discovery_with_active_receivers(list(enumerated))

    assert devices == enumerated
