"""Receiver driver implementations for specific SDR front-ends."""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from .manager import ReceiverConfig, ReceiverInterface, ReceiverStatus, RadioManager


class _SoapySDRHandle:
    """Thin wrapper storing objects needed for a SoapySDR stream."""

    def __init__(self, device, stream, sdr_module, numpy_module) -> None:
        self.device = device
        self.stream = stream
        self.sdr = sdr_module
        self.numpy = numpy_module


class _SoapySDRReceiver(ReceiverInterface):
    """Common functionality for receivers implemented via SoapySDR."""

    driver_hint: str = ""

    def __init__(self, config: ReceiverConfig) -> None:
        super().__init__(config)
        self._handle: Optional[_SoapySDRHandle] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._status = ReceiverStatus(identifier=config.identifier, locked=False)
        self._status_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def start(self) -> None:  # noqa: D401 - documented in base class
        if self._running.is_set():
            return

        try:
            handle = self._open_handle()
        except Exception as exc:
            self._update_status(locked=False, last_error=str(exc))
            raise

        self._handle = handle
        self._running.set()

        thread_name = f"{self.__class__.__name__}-{self.config.identifier}"
        self._thread = threading.Thread(target=self._capture_loop, name=thread_name, daemon=True)
        self._thread.start()

    def stop(self) -> None:  # noqa: D401 - documented in base class
        if not self._running.is_set():
            return

        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2.0)

        self._teardown_handle()
        self._update_status(locked=False)

    # ------------------------------------------------------------------
    # Status reporting
    # ------------------------------------------------------------------
    def get_status(self) -> ReceiverStatus:  # noqa: D401 - documented in base class
        with self._status_lock:
            return ReceiverStatus(
                identifier=self._status.identifier,
                locked=self._status.locked,
                signal_strength=self._status.signal_strength,
                last_error=self._status.last_error,
            )

    def _update_status(
        self,
        *,
        locked: Optional[bool] = None,
        signal_strength: Optional[float] = None,
        last_error: Optional[str] = None,
    ) -> None:
        with self._status_lock:
            if locked is not None:
                self._status.locked = locked
            if signal_strength is not None:
                self._status.signal_strength = signal_strength
            if last_error is not None:
                self._status.last_error = last_error
            elif locked:
                # Clear stale error state when the receiver reports healthy.
                self._status.last_error = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _open_handle(self) -> _SoapySDRHandle:
        try:
            import SoapySDR  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency missing in CI
            raise RuntimeError(
                "SoapySDR Python bindings are required for SDR receivers."
            ) from exc

        try:
            import numpy  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency missing in CI
            raise RuntimeError("NumPy is required for SoapySDR based receivers.") from exc

        channel = self.config.channel if self.config.channel is not None else 0

        args: Dict[str, str] = {"driver": self.driver_hint}
        if self.config.identifier:
            args.setdefault("label", self.config.identifier)
        # Provide optional hints that some Soapy drivers expect.
        if self.config.channel is not None:
            device_id = str(self.config.channel)
            args.setdefault("device_id", device_id)
            args.setdefault("serial", device_id)

        try:
            device = SoapySDR.Device(args)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to open SoapySDR device for driver '{self.driver_hint}': {exc}"
            ) from exc

        try:
            device.setSampleRate(SoapySDR.SOAPY_SDR_RX, channel, self.config.sample_rate)
            device.setFrequency(SoapySDR.SOAPY_SDR_RX, channel, self.config.frequency_hz)
            if self.config.gain is not None:
                device.setGain(SoapySDR.SOAPY_SDR_RX, channel, float(self.config.gain))

            stream = device.setupStream(
                SoapySDR.SOAPY_SDR_RX,
                SoapySDR.SOAPY_SDR_CF32,
            )
            device.activateStream(stream)
        except Exception:
            # Ensure hardware resources are released before bubbling the error up.
            try:
                device.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            raise

        return _SoapySDRHandle(device=device, stream=stream, sdr_module=SoapySDR, numpy_module=numpy)

    def _teardown_handle(self) -> None:
        handle = self._handle
        if not handle:
            return

        try:
            handle.device.deactivateStream(handle.stream)
        except Exception:  # pragma: no cover - best-effort cleanup
            pass

        try:
            handle.device.closeStream(handle.stream)
        except Exception:  # pragma: no cover - best-effort cleanup
            pass

        try:
            handle.device.unmake()  # type: ignore[attr-defined]
        except AttributeError:
            # Older SoapySDR bindings expose `close()` instead of `unmake()`.
            try:
                handle.device.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
        except Exception:  # pragma: no cover - best-effort cleanup
            pass

        self._handle = None

    def _capture_loop(self) -> None:
        assert self._handle is not None
        handle = self._handle
        buffer = handle.numpy.zeros(4096, dtype=handle.numpy.complex64)

        while self._running.is_set():
            try:
                result = handle.device.readStream(handle.stream, [buffer], len(buffer))
                if result.ret < 0:
                    raise RuntimeError(f"SoapySDR readStream error: {result.ret}")

                if result.ret > 0:
                    magnitude = float(handle.numpy.mean(handle.numpy.abs(buffer[: result.ret])))
                else:
                    magnitude = 0.0

                self._update_status(locked=True, signal_strength=magnitude)
            except Exception as exc:
                self._update_status(locked=False, last_error=str(exc))
                self._running.clear()
                break

            # Yield to the scheduler to avoid busy-spinning when readStream returns quickly.
            time.sleep(0.01)

        self._teardown_handle()
        self._update_status(locked=False)


class RTLSDRReceiver(_SoapySDRReceiver):
    """Driver for RTL2832U based SDRs via the SoapyRTLSDR module."""

    driver_hint = "rtlsdr"


class AirspyReceiver(_SoapySDRReceiver):
    """Driver for Airspy receivers using the SoapyAirspy module."""

    driver_hint = "airspy"


def register_builtin_drivers(manager: RadioManager) -> None:
    """Register the built-in SDR drivers against a radio manager instance."""

    manager.register_driver("rtl2832u", RTLSDRReceiver)
    manager.register_driver("rtl-sdr", RTLSDRReceiver)
    manager.register_driver("rtlsdr", RTLSDRReceiver)

    manager.register_driver("airspy", AirspyReceiver)


__all__ = [
    "AirspyReceiver",
    "RTLSDRReceiver",
    "register_builtin_drivers",
]
