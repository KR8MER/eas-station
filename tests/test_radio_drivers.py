"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

import pathlib
import sys
import time
import types

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.drivers import RTLSDRReceiver, AirspyReceiver, _SoapySDRReceiver
from app_core.radio.manager import ReceiverConfig


class _Result:
    def __init__(self, ret: int) -> None:
        self.ret = ret


class _FailingDevice:
    def __init__(self) -> None:
        self.stream = object()

    def setSampleRate(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def setFrequency(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def setGain(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def setupStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        return "stream"

    def activateStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def readStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        # Return -2 (STREAM_ERROR) which triggers reconnection,
        # unlike -4 (OVERFLOW) which is treated as transient
        return _Result(-2)

    def deactivateStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def closeStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def unmake(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def close(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass


class _WorkingDevice:
    def __init__(self) -> None:
        self.stream = object()

    def setSampleRate(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def setFrequency(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def setGain(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def setupStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        return "stream"

    def activateStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def readStream(self, stream, buffers, length, **kwargs):  # noqa: N802 - mimic Soapy API
        buffer = buffers[0]
        buffer[:length] = 0.25 + 0.25j
        return _Result(length)

    def deactivateStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def closeStream(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def unmake(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass

    def close(self, *args, **kwargs):  # noqa: N802 - mimic Soapy API
        pass


class _DeviceFactory:
    open_count = 0

    def __new__(cls, args):
        cls.open_count += 1
        if cls.open_count == 1:
            return _FailingDevice()
        return _WorkingDevice()

    @classmethod
    def enumerate(cls):
        return []


class _SoapyModule(types.SimpleNamespace):
    pass


def _install_soapysdr_stub(monkeypatch):
    module = _SoapyModule()
    module.SOAPY_SDR_RX = 1
    module.SOAPY_SDR_CF32 = 2
    module.Device = _DeviceFactory
    monkeypatch.setitem(sys.modules, "SoapySDR", module)
    return module


def test_receiver_recovers_from_stream_error(monkeypatch):
    _DeviceFactory.open_count = 0
    _install_soapysdr_stub(monkeypatch)

    config = ReceiverConfig(
        identifier="test",
        driver="rtlsdr",
        frequency_hz=162_550_000,
        sample_rate=2_400_000,
        gain=10.0,
        auto_start=True,
    )

    receiver = RTLSDRReceiver(config)
    receiver.start()

    try:
        deadline = time.time() + 2.0
        success = False
        while time.time() < deadline:
            status = receiver.get_status()
            samples = receiver.get_samples(512)
            if status.locked and samples is not None and len(samples) == 512:
                # Ensure samples look like complex64 numpy array
                assert isinstance(samples, np.ndarray)
                assert samples.dtype == np.complex64
                success = True
                break
            time.sleep(0.05)

        assert success, "receiver did not recover from initial stream error"
    finally:
        receiver.stop()
        monkeypatch.delitem(sys.modules, "SoapySDR", raising=False)
        _DeviceFactory.open_count = 0


def test_receiver_logs_error_and_recovery(monkeypatch):
    _DeviceFactory.open_count = 0
    _install_soapysdr_stub(monkeypatch)

    events = []

    def recorder(level, message, *, module, details=None):
        events.append((level, message, module, details))

    config = ReceiverConfig(
        identifier="test",
        driver="rtlsdr",
        frequency_hz=162_550_000,
        sample_rate=2_400_000,
        gain=10.0,
        auto_start=True,
    )

    receiver = RTLSDRReceiver(config, event_logger=recorder)
    receiver.start()

    try:
        deadline = time.time() + 2.0
        recovered = False
        while time.time() < deadline:
            if any(event[0] == "INFO" and "recovered" in event[1] for event in events):
                recovered = True
                break
            time.sleep(0.05)

        assert any(
            event[0] == "ERROR" and "SoapySDR readStream error" in event[1]
            for event in events
        ), "expected readStream error to be logged"
        assert recovered, "receiver did not emit recovery log entry"

        assert any(
            (details or {}).get("identifier") == "test" and details.get("driver") == "rtlsdr"
            for _, _, _, details in events
        ), "event details should include receiver metadata"
    finally:
        receiver.stop()
        monkeypatch.delitem(sys.modules, "SoapySDR", raising=False)
        _DeviceFactory.open_count = 0


def test_read_error_description_includes_lock_hint():
    description = _SoapySDRReceiver._describe_soapysdr_error(-7)
    assert "not locked" in description.lower()

    annotated = _SoapySDRReceiver._annotate_lock_hint(description)
    assert "pll" in annotated.lower()
    assert "hint" in annotated.lower()


def test_unknown_error_code_still_formats_message():
    description = _SoapySDRReceiver._describe_soapysdr_error(-99)
    assert "unknown" in description.lower()

    annotated = _SoapySDRReceiver._annotate_lock_hint("generic error")
    assert annotated == "generic error"


class _GainRecordingDevice:
    """Mock SoapySDR device that records gain-related calls."""

    def __init__(self) -> None:
        self.stream = object()
        self.calls: list[tuple] = []

    def setSampleRate(self, *args, **kwargs):  # noqa: N802
        pass

    def setFrequency(self, *args, **kwargs):  # noqa: N802
        pass

    def getFrequency(self, *args, **kwargs):  # noqa: N802
        return 162_550_000.0

    def hasGainMode(self, *args, **kwargs):  # noqa: N802
        return True

    def setGainMode(self, direction, channel, enable):  # noqa: N802
        self.calls.append(("setGainMode", bool(enable)))

    def getGainRange(self, *args, **kwargs):  # noqa: N802
        class _Range:
            def minimum(self_inner):
                return 0.0

            def maximum(self_inner):
                return 49.6

        return _Range()

    def setGain(self, direction, channel, value):  # noqa: N802
        self.calls.append(("setGain", float(value)))

    def setBandwidth(self, *args, **kwargs):  # noqa: N802
        pass

    def listAntennas(self, *args, **kwargs):  # noqa: N802
        return []

    def setupStream(self, *args, **kwargs):  # noqa: N802
        return "stream"

    def activateStream(self, *args, **kwargs):  # noqa: N802
        pass

    def readStream(self, stream, buffers, length, **kwargs):  # noqa: N802
        buffer = buffers[0]
        buffer[:length] = 0.25 + 0.25j
        return _Result(length)

    def deactivateStream(self, *args, **kwargs):  # noqa: N802
        pass

    def closeStream(self, *args, **kwargs):  # noqa: N802
        pass

    def unmake(self, *args, **kwargs):  # noqa: N802
        pass

    def close(self, *args, **kwargs):  # noqa: N802
        pass


def _install_recording_soapysdr_stub(monkeypatch, recorded: list):
    class _Factory:
        def __new__(cls, args):
            device = _GainRecordingDevice()
            recorded.append(device)
            return device

        @classmethod
        def enumerate(cls):
            return []

    module = _SoapyModule()
    module.SOAPY_SDR_RX = 1
    module.SOAPY_SDR_CF32 = 2
    module.Device = _Factory
    monkeypatch.setitem(sys.modules, "SoapySDR", module)


def _wait_for_calls(device, predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate(device.calls):
            return True
        time.sleep(0.02)
    return False


def test_external_lna_disables_agc_and_biases_gain_down(monkeypatch):
    """When external_lna_db is set and gain is None, AGC must be off and the
    manual gain must be reduced by the external LNA's contribution."""

    devices: list = []
    _install_recording_soapysdr_stub(monkeypatch, devices)

    config = ReceiverConfig(
        identifier="lna-test",
        driver="rtlsdr",
        frequency_hz=162_550_000,
        sample_rate=2_400_000,
        gain=None,
        external_lna_db=20.0,
        auto_start=True,
    )

    receiver = RTLSDRReceiver(config)
    receiver.start()
    try:
        assert devices, "device factory never invoked"
        device = devices[0]
        assert _wait_for_calls(
            device, lambda c: any(name == "setGain" for name, *_ in c)
        ), f"no setGain call recorded: {device.calls}"

        gain_mode_calls = [v for n, v in device.calls if n == "setGainMode"]
        set_gain_calls = [v for n, v in device.calls if n == "setGain"]

        # AGC must be disabled when an external LNA is present.
        assert gain_mode_calls and gain_mode_calls[-1] is False, gain_mode_calls
        # Auto target was 0 + 0.4*49.6 = 19.84 dB; minus 20 dB LNA -> clamped to 0.
        assert set_gain_calls, set_gain_calls
        assert set_gain_calls[-1] == 0.0, set_gain_calls
    finally:
        receiver.stop()
        monkeypatch.delitem(sys.modules, "SoapySDR", raising=False)


def test_no_external_lna_keeps_agc_path(monkeypatch):
    """Without an external LNA, the legacy AGC-on path must still run."""

    devices: list = []
    _install_recording_soapysdr_stub(monkeypatch, devices)

    config = ReceiverConfig(
        identifier="no-lna",
        driver="rtlsdr",
        frequency_hz=162_550_000,
        sample_rate=2_400_000,
        gain=None,
        external_lna_db=0.0,
        auto_start=True,
    )

    receiver = RTLSDRReceiver(config)
    receiver.start()
    try:
        assert devices
        device = devices[0]
        assert _wait_for_calls(
            device, lambda c: any(name == "setGainMode" for name, *_ in c)
        ), f"no setGainMode call recorded: {device.calls}"

        gain_mode_calls = [v for n, v in device.calls if n == "setGainMode"]
        # AGC enabled (True) and no manual setGain call.
        assert gain_mode_calls[-1] is True, gain_mode_calls
        assert not any(n == "setGain" for n, *_ in device.calls), device.calls
    finally:
        receiver.stop()
        monkeypatch.delitem(sys.modules, "SoapySDR", raising=False)


def test_airspy_external_lna_biases_gain_down(monkeypatch):
    """Airspy receivers must also disable AGC and back off gain when an
    external LNA is present. Airspy uses its own 0-21 dB linearity range
    rather than the generic getGainRange path."""

    devices: list = []
    _install_recording_soapysdr_stub(monkeypatch, devices)

    config = ReceiverConfig(
        identifier="airspy-lna",
        driver="airspy",
        frequency_hz=162_550_000,
        sample_rate=2_500_000,  # Valid Airspy R2 rate
        gain=None,
        external_lna_db=5.0,
        auto_start=True,
    )

    receiver = AirspyReceiver(config)
    receiver.start()
    try:
        assert devices
        device = devices[0]
        # Airspy override runs after the parent path, so we wait until the
        # parent's setGain has been followed by the Airspy-specific one.
        assert _wait_for_calls(
            device,
            lambda c: sum(1 for n, *_ in c if n == "setGain") >= 2,
            timeout=3.0,
        ), f"Airspy override never ran: {device.calls}"

        gain_mode_calls = [v for n, v in device.calls if n == "setGainMode"]
        set_gain_calls = [v for n, v in device.calls if n == "setGain"]

        # AGC disabled at every step where it's been touched.
        assert gain_mode_calls, gain_mode_calls
        assert all(v is False for v in gain_mode_calls), gain_mode_calls
        # Airspy override is the last setGain call; target = 10 - 5 = 5.0 dB.
        assert set_gain_calls[-1] == 5.0, set_gain_calls
    finally:
        receiver.stop()
        monkeypatch.delitem(sys.modules, "SoapySDR", raising=False)


def test_dynamic_buffer_size_calculation():
    """Test that buffer size is calculated dynamically based on sample rate."""
    # Test with low sample rate (48kHz) - should use minimum buffer
    config_low = ReceiverConfig(
        identifier="test-low",
        driver="rtlsdr",
        frequency_hz=162_550_000,
        sample_rate=48_000,  # Low sample rate
        gain=10.0,
        auto_start=False,
    )
    receiver_low = RTLSDRReceiver(config_low)
    buffer_size_low = receiver_low._calculate_buffer_size()
    # 48kHz * 50ms = 2400 samples, but min is 16384
    assert buffer_size_low == 16384, f"Expected minimum buffer 16384, got {buffer_size_low}"

    # Test with medium sample rate (2.4MHz RTL-SDR) - should be proportional
    config_med = ReceiverConfig(
        identifier="test-med",
        driver="rtlsdr",
        frequency_hz=162_550_000,
        sample_rate=2_400_000,  # 2.4 MHz
        gain=10.0,
        auto_start=False,
    )
    receiver_med = RTLSDRReceiver(config_med)
    buffer_size_med = receiver_med._calculate_buffer_size()
    # 2.4MHz * 50ms = 120000 samples
    assert buffer_size_med == 120000, f"Expected 120000, got {buffer_size_med}"

    # Test with high sample rate (10MHz Airspy) - should cap at maximum
    config_high = ReceiverConfig(
        identifier="test-high",
        driver="airspy",
        frequency_hz=162_550_000,
        sample_rate=10_000_000,  # 10 MHz
        gain=10.0,
        auto_start=False,
    )
    receiver_high = AirspyReceiver(config_high)
    buffer_size_high = receiver_high._calculate_buffer_size()
    # 10MHz * 50ms = 500000 samples, but max is 262144
    assert buffer_size_high == 262144, f"Expected maximum buffer 262144, got {buffer_size_high}"

    # Test with typical Airspy R2 rate (2.5MHz)
    config_airspy = ReceiverConfig(
        identifier="test-airspy",
        driver="airspy",
        frequency_hz=162_550_000,
        sample_rate=2_500_000,  # 2.5 MHz typical Airspy
        gain=10.0,
        auto_start=False,
    )
    receiver_airspy = AirspyReceiver(config_airspy)
    buffer_size_airspy = receiver_airspy._calculate_buffer_size()
    # 2.5MHz * 50ms = 125000 samples
    assert buffer_size_airspy == 125000, f"Expected 125000, got {buffer_size_airspy}"
