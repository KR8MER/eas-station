"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

from __future__ import annotations

"""Receiver driver implementations for specific SDR front-ends."""

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
    _SOAPY_ERROR_DESCRIPTIONS = {
        -1: "Timeout waiting for samples (SOAPY_SDR_TIMEOUT)",
        -2: "Stream reported a driver error (SOAPY_SDR_STREAM_ERROR)",
        -3: "Corrupted data from device (SOAPY_SDR_CORRUPTION)",
        -4: "Buffer overflow - system cannot keep up with data rate (SOAPY_SDR_OVERFLOW)",
        -5: "Operation not supported by device (SOAPY_SDR_NOT_SUPPORTED)",
        -6: "Timing error in stream (SOAPY_SDR_TIME_ERROR)",
        -7: "Buffer underflow - not enough data provided (SOAPY_SDR_UNDERFLOW)",
    }

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
        # Connection health tracking
        self._connection_attempts = 0
        self._connection_failures = 0
        self._last_successful_connection: Optional[datetime.datetime] = None
        self._stream_errors_count = 0

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    @classmethod
    def _describe_soapysdr_error(cls, code: int) -> str:
        """Return a human-readable message for a SoapySDR error code."""

        description = cls._SOAPY_ERROR_DESCRIPTIONS.get(code)
        if description:
            return f"SoapySDR readStream error {code}: {description}"
        return f"SoapySDR readStream error {code}: Unknown error"

    @staticmethod
    def _annotate_lock_hint(message: str) -> str:
        """Attach a PLL lock hint when SoapySDR reports NOT_LOCKED conditions."""

        if not isinstance(message, str):
            return message

        lowered = message.lower()
        keywords = (
            "not locked",
            "pll lock",
            "pll unlock",
            "soapysdr readstream error -7",
            "error -7",
            "soapysdr_not_locked",
        )
        if any(keyword in lowered for keyword in keywords):
            hint = (
                "Receiver PLL is not locked; ensure the SDR has a valid antenna, "
                "reference clock, and that the tuner frequency is supported."
            )
            if hint not in message:
                return f"{message} (hint: {hint})"
        return message

    @staticmethod
    def _annotate_device_open_hint(message: str, driver: str, serial: Optional[str] = None) -> str:
        """Enhance device open errors with troubleshooting hints."""

        if not isinstance(message, str):
            return message

        lowered = message.lower()
        hints = []

        # Check for common error patterns
        if "unable to open" in lowered or "failed to open" in lowered:
            hints.append("Common causes: device not connected, USB permissions issue, "
                        "device in use by another process, or driver not installed")

        if "permission" in lowered or "access denied" in lowered:
            hints.append("USB permissions issue detected. On Linux, you may need to add udev rules "
                        "or run 'sudo usermod -aG plugdev $USER' and reboot")

        if "device busy" in lowered or "resource busy" in lowered:
            hints.append("Device is in use by another process. Check for other SDR applications "
                        "or kill processes using: 'lsof | grep sdr'")

        if serial and ("serial" in lowered or "not found" in lowered):
            hints.append(f"Device with serial '{serial}' not found. Verify device is connected "
                        f"and serial number is correct using: 'SoapySDRUtil --find=\"driver={driver}\"'")

        # Add device-specific hints
        if driver == "airspy":
            hints.append("For Airspy: ensure SoapyAirspy module is installed and libairspy is available. "
                        "Test with: 'SoapySDRUtil --probe=\"driver=airspy\"'")
        elif driver == "rtlsdr":
            hints.append("For RTL-SDR: ensure SoapyRTLSDR module is installed and blacklist dvb_usb_rtl28xxu "
                        "kernel module if needed")

        if hints:
            hint_text = "; ".join(hints)
            return f"{message} (troubleshooting: {hint_text})"
        return message

    def _enumerate_available_devices(self, sdr_module) -> List[Dict[str, str]]:
        """Enumerate available SoapySDR devices for diagnostic purposes."""
        try:
            devices = sdr_module.Device.enumerate()
            return [dict(d) for d in devices]
        except Exception as exc:
            self._interface_logger.warning("Failed to enumerate devices: %s", exc)
            return []

    def get_connection_health(self) -> Dict[str, object]:
        """Get diagnostic information about device connection health.

        Returns:
            Dictionary containing connection statistics and health metrics
        """
        uptime = None
        if self._last_successful_connection:
            uptime = (datetime.datetime.now(datetime.timezone.utc) -
                     self._last_successful_connection).total_seconds()

        health = {
            "connection_attempts": self._connection_attempts,
            "connection_failures": self._connection_failures,
            "stream_errors": self._stream_errors_count,
            "last_successful_connection": self._last_successful_connection.isoformat() if self._last_successful_connection else None,
            "uptime_seconds": uptime,
            "running": self._running.is_set(),
            "device_open": self._handle is not None,
        }

        # Calculate success rate
        if self._connection_attempts > 0:
            health["connection_success_rate"] = (
                (self._connection_attempts - self._connection_failures) /
                self._connection_attempts * 100.0
            )
        else:
            health["connection_success_rate"] = 0.0

        return health

    def is_running(self) -> bool:  # noqa: D401 - documented in base class
        """Check if the receiver capture thread is actively running."""
        return self._running.is_set()

    def start(self) -> None:  # noqa: D401 - documented in base class
        if self._running.is_set():
            return

        # Retry initial device open with exponential backoff for hardware reliability
        max_startup_retries = 3
        retry_delay = self._retry_backoff
        last_exception = None

        for attempt in range(max_startup_retries):
            try:
                handle = self._open_handle()
                break  # Success - exit retry loop
            except Exception as exc:
                last_exception = exc
                self._update_status(locked=False, last_error=str(exc), context="startup")

                if attempt < max_startup_retries - 1:
                    self._interface_logger.warning(
                        "Failed to open device for %s (attempt %d/%d): %s. Retrying in %.1f seconds...",
                        self.config.identifier,
                        attempt + 1,
                        max_startup_retries,
                        exc,
                        retry_delay
                    )
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2.0, self._max_retry_backoff)
                else:
                    self._interface_logger.error(
                        "Failed to open device for %s after %d attempts. "
                        "Device will continue retrying in background capture loop.",
                        self.config.identifier,
                        max_startup_retries
                    )
                    # Don't raise - let the capture loop handle retries
                    handle = None
        else:
            # All retries failed - start capture loop anyway to keep retrying
            handle = None

        self._handle = handle
        if handle is not None:
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

        # Log available devices for diagnostics
        available_devices = self._enumerate_available_devices(SoapySDR)
        if available_devices:
            self._interface_logger.info(
                "Found %d SoapySDR device(s): %s",
                len(available_devices),
                [d.get("label", d.get("driver", "unknown")) for d in available_devices]
            )

            # Log detailed device information including serials for troubleshooting
            for dev in available_devices:
                dev_driver = dev.get("driver", "unknown")
                dev_serial = dev.get("serial", "N/A")
                dev_label = dev.get("label", "N/A")
                self._interface_logger.debug(
                    "  Device: driver=%s, serial=%s, label=%s",
                    dev_driver, dev_serial, dev_label
                )

            # Check if the requested device is in the list
            if self.config.serial:
                matching = [d for d in available_devices
                           if d.get("serial") == self.config.serial and
                           d.get("driver") == self.driver_hint]
                if not matching:
                    self._interface_logger.warning(
                        "Requested device with serial '%s' and driver '%s' not found in enumerated devices. "
                        "Available %s devices: %s",
                        self.config.serial,
                        self.driver_hint,
                        self.driver_hint,
                        [d.get("serial", "N/A") for d in available_devices
                         if d.get("driver") == self.driver_hint]
                    )
        else:
            self._interface_logger.warning(
                "No SoapySDR devices found. Ensure device is connected and drivers are installed."
            )

        try:
            device = SoapySDR.Device(args)
        except Exception as exc:
            device = self._retry_device_open_without_serial(
                SoapySDR, args, exc
            )

        try:
            device.setSampleRate(SoapySDR.SOAPY_SDR_RX, channel, self.config.sample_rate)
            device.setFrequency(SoapySDR.SOAPY_SDR_RX, channel, self.config.frequency_hz)
            if self.config.gain is not None:
                device.setGain(SoapySDR.SOAPY_SDR_RX, channel, float(self.config.gain))

            # Configure stream with appropriate MTU for USB bandwidth
            # AirSpy and other SDRs benefit from larger buffer sizes to prevent
            # USB transfer overhead and stream errors
            # SoapySDR setupStream signature: setupStream(direction, format, [channels], args={})
            # Note: Some drivers need bufflen as string, others as int - use string for compatibility
            stream_mtu = 16384  # Samples per USB transfer (optimized for AirSpy)
            stream_args = {}

            # Try setting buffer length if supported by the driver
            # AirSpy: uses internal buffering, bufflen may not be supported
            # RTL-SDR: supports bufflen parameter
            if self.driver_hint == "rtlsdr":
                stream_args["bufflen"] = str(stream_mtu)

            stream = device.setupStream(
                SoapySDR.SOAPY_SDR_RX,
                SoapySDR.SOAPY_SDR_CF32,
                [channel],  # channels list
                stream_args  # driver-specific stream args
            )
            device.activateStream(stream)
        except Exception as exc:
            # Ensure hardware resources are released before bubbling the error up.
            try:
                device.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            message = self._annotate_lock_hint(str(exc))
            raise RuntimeError(f"Failed to configure SoapySDR device: {message}") from exc

        return _SoapySDRHandle(device=device, stream=stream, sdr_module=SoapySDR, numpy_module=numpy)

    def _retry_device_open_without_serial(
        self,
        sdr_module,
        original_args: Dict[str, str],
        original_exc: Exception,
    ) -> object:
        serial = original_args.get("serial")
        if not serial:
            message = self._annotate_lock_hint(str(original_exc))
            message = self._annotate_device_open_hint(message, self.driver_hint, serial)
            raise RuntimeError(
                f"Unable to open SoapySDR device for driver '{self.driver_hint}': {message}"
            ) from original_exc

        # First fallback: Try without serial but keep other parameters
        # Note: AirSpy doesn't support device_id, only RTL-SDR and some other drivers do
        fallback_args = dict(original_args)
        fallback_args.pop("serial", None)
        if not fallback_args.get("driver"):
            fallback_args["driver"] = self.driver_hint
        # Only add device_id for drivers that support it (not airspy)
        if self.driver_hint != "airspy" and "device_id" not in fallback_args and self.config.channel is not None:
            fallback_args["device_id"] = str(self.config.channel)

        # Check if fallback_args is different from minimal args (just driver)
        # If they're the same, skip this fallback to avoid duplicate attempts
        minimal_args = {"driver": self.driver_hint}
        skip_first_fallback = (fallback_args == minimal_args)

        # Initialize fallback_exc before try/except to avoid scoping issues
        # (exception variables in except clauses are deleted after the block)
        fallback_exc = None

        if not skip_first_fallback:
            self._emit_event(
                "warning",
                "Falling back to autodetected SDR device after serial open failure",
                details={
                    "driver": self.driver_hint,
                    "serial": serial,
                    "error": str(original_exc),
                },
            )
            self._interface_logger.warning(
                "Failed to open SDR %s with serial %s (%s); retrying without serial filter",
                self.driver_hint or "unknown",
                serial,
                original_exc,
            )

            try:
                device = sdr_module.Device(fallback_args)
                self._emit_event(
                    "info",
                    "Opened SDR device without serial filter after fallback",
                    details={"driver": self.driver_hint, "serial": serial},
                )
                return device
            except Exception as e:
                fallback_exc = e  # Capture exception to persist beyond except block
        else:
            fallback_exc = original_exc  # Skip first fallback, use original exception

        # Second fallback: Try with ONLY driver (no serial, no device_id)
        self._interface_logger.warning(
            "Attempting to open device with driver-only filter (serial '%s' was not found)",
            serial,
        )

        try:
            device = sdr_module.Device(minimal_args)
            self._emit_event(
                "info",
                "Opened SDR device with driver-only filter after fallback",
                details={"driver": self.driver_hint, "serial": serial},
            )
            return device
        except Exception as minimal_exc:
            # All retries failed - provide comprehensive error message
            annotated_original = self._annotate_lock_hint(str(original_exc))
            annotated_original = self._annotate_device_open_hint(annotated_original, self.driver_hint, serial)

            # Build error message based on what we tried
            if skip_first_fallback:
                # We only tried original (with serial) and minimal (driver only)
                annotated_minimal = self._annotate_lock_hint(str(minimal_exc))
                annotated_minimal = self._annotate_device_open_hint(annotated_minimal, self.driver_hint, None)

                raise RuntimeError(
                    "Unable to open SoapySDR device for driver "
                    f"'{self.driver_hint}' using serial '{serial}': {annotated_original}; "
                    f"retry with driver-only also failed: {annotated_minimal}"
                ) from minimal_exc
            else:
                # We tried all three: original, fallback, and minimal
                annotated_fallback = self._annotate_lock_hint(str(fallback_exc))
                annotated_fallback = self._annotate_device_open_hint(annotated_fallback, self.driver_hint, None)
                annotated_minimal = self._annotate_lock_hint(str(minimal_exc))
                annotated_minimal = self._annotate_device_open_hint(annotated_minimal, self.driver_hint, None)

                raise RuntimeError(
                    "Unable to open SoapySDR device for driver "
                    f"'{self.driver_hint}' using serial '{serial}': {annotated_original}; "
                    f"retry without serial also failed: {annotated_fallback}; "
                    f"retry with driver-only also failed: {annotated_minimal}"
                ) from minimal_exc

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
            # Use larger buffer to reduce USB transfer overhead and prevent SOAPY_SDR_OVERFLOW (-4)
            # High-speed SDRs like AirSpy generate data faster than smaller buffers can handle
            buffer = handle.numpy.zeros(16384, dtype=handle.numpy.complex64)

        retry_delay = self._retry_backoff
        consecutive_failures = 0

        while self._running.is_set():
            if handle is None:
                if not self._running.is_set():
                    break

                consecutive_failures += 1
                self._connection_attempts += 1
                try:
                    self._interface_logger.info(
                        "Attempting to open device for %s (retry #%d, waiting %.1f seconds)...",
                        self.config.identifier,
                        consecutive_failures,
                        min(retry_delay, self._max_retry_backoff)
                    )
                    new_handle = self._open_handle()
                    consecutive_failures = 0  # Reset on success
                    self._last_successful_connection = datetime.datetime.now(datetime.timezone.utc)
                except Exception as exc:
                    self._connection_failures += 1
                    self._update_status(
                        locked=False,
                        last_error=str(exc),
                        context="open_stream",
                    )
                    time.sleep(min(retry_delay, self._max_retry_backoff))
                    retry_delay = min(retry_delay * 2.0, self._max_retry_backoff)
                    continue

                self._interface_logger.info(
                    "Successfully opened device for %s after %d attempt(s)",
                    self.config.identifier,
                    consecutive_failures + 1
                )
                handle = self._handle = new_handle
                self._initialize_sample_buffer(new_handle.numpy)
                # Use larger buffer to reduce USB transfer overhead and prevent SOAPY_SDR_OVERFLOW (-4)
                buffer = new_handle.numpy.zeros(16384, dtype=new_handle.numpy.complex64)
                retry_delay = self._retry_backoff
                continue

            try:
                result = handle.device.readStream(handle.stream, [buffer], len(buffer))
                if result.ret < 0:
                    # Handle different error types differently
                    error_code = result.ret
                    message = self._describe_soapysdr_error(error_code)
                    message = self._annotate_lock_hint(message)
                    
                    # OVERFLOW (-4) means the internal buffer is full because we're not
                    # reading fast enough. The SoapyAirspy driver drains the buffer on overflow,
                    # so we should immediately continue reading without any delay.
                    # UNDERFLOW (-7) typically occurs during TX but handle it similarly for safety.
                    if error_code in (-4, -7):
                        self._stream_errors_count += 1
                        # Log the first error and then every 100th error to reduce spam
                        if self._stream_errors_count == 1 or self._stream_errors_count % 100 == 0:
                            self._interface_logger.warning(
                                "Transient stream error for %s (error %d, total: %d): %s. Continuing...",
                                self.config.identifier,
                                error_code,
                                self._stream_errors_count,
                                message
                            )
                        self._update_status(
                            locked=True,  # Still consider locked - this is recoverable
                            last_error=message,
                            context="read_stream_transient",
                        )
                        # On overflow, immediately continue reading to drain the buffer.
                        # Do NOT add a delay here as that makes overflow worse.
                        continue
                    
                    # Other errors require full reconnection
                    raise RuntimeError(message)

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
                consecutive_failures += 1
                self._stream_errors_count += 1
                self._interface_logger.warning(
                    "Stream error for %s (failure #%d, total stream errors: %d): %s. Reconnecting...",
                    self.config.identifier,
                    consecutive_failures,
                    self._stream_errors_count,
                    exc
                )
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
