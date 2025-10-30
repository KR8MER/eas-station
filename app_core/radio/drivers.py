"""Receiver driver implementations for specific SDR front-ends."""

from __future__ import annotations

import datetime
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from .manager import ReceiverConfig, ReceiverInterface, ReceiverStatus, RadioManager


class _SoapySDRHandle:
    """Thin wrapper storing objects needed for a SoapySDR stream."""

    def __init__(self, device, stream, sdr_module, numpy_module) -> None:
        self.device = device
        self.stream = stream
        self.sdr = sdr_module
        self.numpy = numpy_module


class _CaptureTicket:
    """Track the progress of a capture request for a single receiver."""

    def __init__(
        self,
        *,
        identifier: str,
        path: Path,
        samples_required: int,
        mode: str,
        numpy_module,
    ) -> None:
        self.identifier = identifier
        self.path = path
        self.samples_required = samples_required
        self.mode = mode
        self.numpy = numpy_module
        self.samples_captured = 0
        self.error: Optional[Exception] = None
        self.event = threading.Event()
        self._file = None

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "wb")

    @property
    def completed(self) -> bool:
        return self.error is not None or self.samples_captured >= self.samples_required

    def write(self, samples) -> None:
        if self.completed or self._file is None:
            return

        remaining = self.samples_required - self.samples_captured
        if remaining <= 0:
            self.close()
            return

        to_take = min(len(samples), remaining)
        if to_take <= 0:
            return

        chunk = samples[:to_take]
        try:
            if self.mode == "pcm":
                interleaved = self.numpy.empty((to_take * 2,), dtype=self.numpy.float32)
                interleaved[0::2] = chunk.real.astype(self.numpy.float32, copy=False)
                interleaved[1::2] = chunk.imag.astype(self.numpy.float32, copy=False)
                interleaved.tofile(self._file)
            else:
                chunk.astype(self.numpy.complex64, copy=False).tofile(self._file)
        except Exception as exc:
            self.fail(exc)
            return

        self.samples_captured += to_take
        if self.samples_captured >= self.samples_required:
            self.close()

    def fail(self, exc: Exception) -> None:
        self.error = exc
        self.close()

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            finally:
                self._file = None
        self.event.set()

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
        self._capture_requests: List[_CaptureTicket] = []
        self._capture_lock = threading.Lock()

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
        self._cancel_capture_requests(RuntimeError("Receiver stopped"))
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
                capture_mode=self._status.capture_mode,
                capture_path=self._status.capture_path,
                reported_at=self._status.reported_at,
            )

    def _update_status(
        self,
        *,
        locked: Optional[bool] = None,
        signal_strength: Optional[float] = None,
        last_error: Optional[str] = None,
        capture_mode: Optional[str] = None,
        capture_path: Optional[str] = None,
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
            if capture_mode is not None:
                self._status.capture_mode = capture_mode
            if capture_path is not None:
                self._status.capture_path = capture_path
            self._status.reported_at = datetime.datetime.now(datetime.timezone.utc)

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
                if result.ret > 0:
                    self._process_capture(buffer[: result.ret])
            except Exception as exc:
                self._update_status(locked=False, last_error=str(exc))
                self._running.clear()
                break

        self._cancel_capture_requests(RuntimeError("Capture loop exited"))

    def capture_to_file(
        self,
        duration_seconds: float,
        output_dir: Path,
        prefix: str,
        *,
        mode: str = "iq",
    ) -> Path:
        if not self._running.is_set() or not self._handle:
            raise RuntimeError("Receiver is not running")

        safe_mode = (mode or "iq").lower()
        if safe_mode not in {"iq", "pcm"}:
            raise ValueError("Capture mode must be 'iq' or 'pcm'")

        if duration_seconds <= 0:
            raise ValueError("Capture duration must be positive")

        total_samples = max(1, int(self.config.sample_rate * float(duration_seconds)))
        timestamp = time.strftime("%Y%m%dT%H%M%S")
        extension = "iq" if safe_mode == "iq" else "pcm"
        filename = f"{prefix}_{timestamp}.{extension}" if prefix else f"capture_{timestamp}.{extension}"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / filename

        ticket = _CaptureTicket(
            identifier=self.config.identifier,
            path=path,
            samples_required=total_samples,
            mode=safe_mode,
            numpy_module=self._handle.numpy,
        )

        with self._capture_lock:
            self._capture_requests.append(ticket)

        timeout = max(5.0, float(duration_seconds) * 2.0)
        completed = ticket.event.wait(timeout=timeout)

        with self._capture_lock:
            if ticket in self._capture_requests:
                self._capture_requests.remove(ticket)

        if not completed:
            ticket.fail(TimeoutError(f"Timed out capturing samples for {self.config.identifier}"))
            raise ticket.error  # type: ignore[misc]

        if ticket.error:
            raise ticket.error

        self._update_status(capture_mode=safe_mode, capture_path=str(path))
        return path

    def _process_capture(self, samples) -> None:
        with self._capture_lock:
            pending = list(self._capture_requests)

        if not pending:
            return

        for ticket in pending:
            if ticket.completed:
                continue
            ticket.write(samples)

        with self._capture_lock:
            self._capture_requests = [ticket for ticket in self._capture_requests if not ticket.completed]

    def _cancel_capture_requests(self, exc: Exception) -> None:
        with self._capture_lock:
            pending = self._capture_requests
            self._capture_requests = []

        for ticket in pending:
            ticket.fail(exc)
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
