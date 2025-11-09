import pathlib
import sys
import time
import types

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.drivers import RTLSDRReceiver
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
        return _Result(-4)

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

    def readStream(self, stream, buffers, length):  # noqa: N802 - mimic Soapy API
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
