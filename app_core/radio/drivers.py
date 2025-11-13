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

    def __init__(
        self,
        config: ReceiverConfig,
        *,
        event_logger=None,
    ) -> None:
        super().__init__(config, event_logger=event_logger)
        self._handle: Optional[_SoapySDRHandle] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._status = ReceiverStatus(identifier=config.identifier, locked=False)
        self._status_lock = threading.Lock()
        self._capture_requests: List[_CaptureTicket] = []
        self._capture_lock = threading.Lock()
        # Real-time sample buffer for audio streaming
        self._sample_buffer = None  # Will be a numpy array ring buffer
        self._sample_buffer_size = 32768  # Store ~0.67 seconds at 48kHz
        self._sample_buffer_pos = 0
        self._sample_buffer_lock = threading.Lock()
        self._retry_backoff = 0.25
        self._max_retry_backoff = 5.0
        self._last_logged_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def start(self) -> None:  # noqa: D401 - documented in base class
        if self._running.is_set():
            return

        try:
            handle = self._open_handle()
        except Exception as exc:
            self._update_status(locked=False, last_error=str(exc), context="startup")
            raise

        self._handle = handle
        self._initialize_sample_buffer(handle.numpy)

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
        self._cancel_capture_requests(RuntimeError("Receiver stopped"), teardown=False)
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
        context: Optional[str] = None,
    ) -> None:
        with self._status_lock:
            if locked is not None:
                self._status.locked = locked
            if signal_strength is not None:
                self._status.signal_strength = signal_strength
            sanitized_error = last_error
            if isinstance(sanitized_error, str):
                sanitized_error = sanitized_error.strip()
            if sanitized_error == "":
                sanitized_error = None
            if sanitized_error is not None:
                self._status.last_error = sanitized_error
            elif locked:
                # Clear stale error state when the receiver reports healthy.
                self._status.last_error = None
            if capture_mode is not None:
                self._status.capture_mode = capture_mode
            if capture_path is not None:
                self._status.capture_path = capture_path
            self._status.reported_at = datetime.datetime.now(datetime.timezone.utc)

            current_error = self._status.last_error

        if sanitized_error is not None and current_error:
            details = self._build_event_details(context=context)
            details["error"] = current_error
            self._emit_event(
                "ERROR",
                f"{self.config.identifier}: {current_error}",
                details=details,
            )
            self._last_logged_error = current_error
        elif sanitized_error is None and locked and self._last_logged_error:
            details = self._build_event_details(context=context)
            details["previous_error"] = self._last_logged_error
            self._emit_event(
                "INFO",
                f"{self.config.identifier} recovered and resumed streaming",
                details=details,
            )
            self._last_logged_error = None

    def _build_event_details(self, *, context: Optional[str] = None) -> Dict[str, object]:
        with self._status_lock:
            locked = bool(self._status.locked)
            signal_strength = self._status.signal_strength
            capture_mode = self._status.capture_mode
            capture_path = self._status.capture_path
            reported_at = self._status.reported_at

        details: Dict[str, object] = {
            "identifier": self.config.identifier,
            "driver": self.config.driver,
            "driver_hint": self.driver_hint,
            "frequency_hz": self.config.frequency_hz,
            "sample_rate": self.config.sample_rate,
            "gain": self.config.gain,
            "serial": self.config.serial,
            "locked": locked,
            "signal_strength": signal_strength,
        }

        if capture_mode is not None:
            details["capture_mode"] = capture_mode
        if capture_path is not None:
            details["capture_path"] = capture_path
        if reported_at is not None:
            details["reported_at"] = reported_at.isoformat()
        if context:
            details["context"] = context

        return details

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _initialize_sample_buffer(self, numpy_module) -> None:
        """Reset the rolling IQ sample buffer using the provided numpy module."""
        with self._sample_buffer_lock:
            self._sample_buffer = numpy_module.zeros(self._sample_buffer_size, dtype=numpy_module.complex64)
            self._sample_buffer_pos = 0

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

        # Use the device serial number if available for precise device identification
        if self.config.serial:
            args["serial"] = self.config.serial
        # Use channel/device_id as fallback identification only if no serial
        elif self.config.channel is not None:
            # Only set device_id, not serial (serial is for hardware serial numbers only)
            args["device_id"] = str(self.config.channel)

        # Label is for human reference only, not device identification
        if self.config.identifier:
            args.setdefault("label", self.config.identifier)

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

    def _teardown_handle(self, handle: Optional[_SoapySDRHandle] = None) -> None:
        if handle is None:
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

        if handle is self._handle:
            self._handle = None

    def _capture_loop(self) -> None:
        handle = self._handle
        buffer = None
        if handle is not None:
            buffer = handle.numpy.zeros(4096, dtype=handle.numpy.complex64)

        retry_delay = self._retry_backoff

        while self._running.is_set():
            if handle is None:
                if not self._running.is_set():
                    break

                try:
                    new_handle = self._open_handle()
                except Exception as exc:
                    self._update_status(
                        locked=False,
                        last_error=str(exc),
                        context="open_stream",
                    )
                    time.sleep(min(retry_delay, self._max_retry_backoff))
                    retry_delay = min(retry_delay * 2.0, self._max_retry_backoff)
                    continue

                handle = self._handle = new_handle
                self._initialize_sample_buffer(new_handle.numpy)
                buffer = new_handle.numpy.zeros(4096, dtype=new_handle.numpy.complex64)
                retry_delay = self._retry_backoff
                continue

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
                    samples = buffer[: result.ret]
                    self._update_sample_buffer(samples)
                    self._process_capture(samples)
            except Exception as exc:
                self._update_status(
                    locked=False,
                    last_error=str(exc),
                    context="read_stream",
                )
                self._teardown_handle(handle)
                handle = None
                buffer = None
                self._cancel_capture_requests(RuntimeError(f"Capture error: {exc}"), teardown=False)
                if not self._running.is_set():
                    break
                time.sleep(min(retry_delay, self._max_retry_backoff))
                retry_delay = min(retry_delay * 2.0, self._max_retry_backoff)

        self._cancel_capture_requests(RuntimeError("Capture loop exited"), teardown=False)

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

    def _cancel_capture_requests(self, exc: Exception, *, teardown: bool = True) -> None:
        with self._capture_lock:
            pending = self._capture_requests
            self._capture_requests = []

        for ticket in pending:
            ticket.fail(exc)
            # Yield to the scheduler to avoid busy-spinning when readStream returns quickly.
            time.sleep(0.01)

        if teardown:
            self._teardown_handle()
        self._update_status(locked=False)

    def _update_sample_buffer(self, samples) -> None:
        """Update the real-time sample ring buffer with new samples."""
        if self._sample_buffer is None:
            return

        with self._sample_buffer_lock:
            num_samples = len(samples)
            if num_samples >= self._sample_buffer_size:
                # If we got more samples than buffer size, just take the latest
                self._sample_buffer[:] = samples[-self._sample_buffer_size:]
                self._sample_buffer_pos = 0
            else:
                # Write samples to ring buffer
                end_pos = self._sample_buffer_pos + num_samples
                if end_pos <= self._sample_buffer_size:
                    # Samples fit without wrapping
                    self._sample_buffer[self._sample_buffer_pos:end_pos] = samples
                else:
                    # Samples wrap around
                    first_chunk = self._sample_buffer_size - self._sample_buffer_pos
                    self._sample_buffer[self._sample_buffer_pos:] = samples[:first_chunk]
                    self._sample_buffer[:num_samples - first_chunk] = samples[first_chunk:]

                self._sample_buffer_pos = end_pos % self._sample_buffer_size

    def get_samples(self, num_samples: Optional[int] = None):
        """Get recent IQ samples from the receiver for real-time processing.

        Args:
            num_samples: Number of samples to retrieve. If None, returns all available samples.

        Returns:
            numpy array of complex64 samples, or None if receiver is not running
        """
        if not self._running.is_set() or self._sample_buffer is None:
            return None

        with self._sample_buffer_lock:
            if num_samples is None or num_samples >= self._sample_buffer_size:
                # Return entire buffer in correct order
                if self._sample_buffer_pos == 0:
                    return self._sample_buffer.copy()
                else:
                    # Reorder ring buffer to put oldest samples first
                    handle = self._handle
                    if not handle:
                        return None
                    result = handle.numpy.concatenate([
                        self._sample_buffer[self._sample_buffer_pos:],
                        self._sample_buffer[:self._sample_buffer_pos]
                    ])
                    return result
            else:
                # Return most recent num_samples
                if num_samples > self._sample_buffer_size:
                    num_samples = self._sample_buffer_size

                handle = self._handle
                if not handle:
                    return None

                # Calculate start position for most recent samples
                start_pos = (self._sample_buffer_pos - num_samples) % self._sample_buffer_size
                if start_pos < self._sample_buffer_pos:
                    # No wrap
                    return self._sample_buffer[start_pos:self._sample_buffer_pos].copy()
                else:
                    # Wrapped
                    return handle.numpy.concatenate([
                        self._sample_buffer[start_pos:],
                        self._sample_buffer[:self._sample_buffer_pos]
                    ])


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
