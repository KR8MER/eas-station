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

from __future__ import annotations

"""Receiver driver implementations for specific SDR front-ends."""

import datetime
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from .manager import ReceiverConfig, ReceiverInterface, ReceiverStatus, RadioManager

# Import ring buffer at module level to avoid repeated import overhead
try:
    from .ring_buffer import SDRRingBuffer, calculate_buffer_size
    _RING_BUFFER_AVAILABLE = True
except ImportError:
    _RING_BUFFER_AVAILABLE = False
    SDRRingBuffer = None
    calculate_buffer_size = None

# SciPy is used to build a proper anti-alias FIR for the early decimator.
# If unavailable we fall back to the legacy block-average path with a
# one-shot warning at stream start (preserves operation on minimal hosts).
try:
    from scipy import signal as _scipy_signal  # type: ignore
    _SCIPY_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only on minimal hosts
    _scipy_signal = None
    _SCIPY_AVAILABLE = False


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
        -7: "Receiver not locked or buffer underflow - PLL may not yet be locked (SOAPY_SDR_NOT_LOCKED/UNDERFLOW)",
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
        
        # Spectrum/Waterfall support
        self._spectrum_buffer = None
        self._spectrum_update_interval = 0.1  # 100ms
        self._last_spectrum_update = 0.0
        self._fft_size = 2048
        self._window = None
        
        # Ring buffer for robust SDR reading (handles USB timing variations and backpressure)
        # This is the SDRRingBuffer from ring_buffer.py for production use
        # Provides overflow/underflow detection, backpressure monitoring, and reliable buffering
        self._ring_buffer = None  # Will be initialized with SDRRingBuffer instance
        self._ring_buffer_enabled = True  # Enable robust ring buffer operation
        self._consecutive_timeouts = 0
        # Configurable timeout threshold - increased from 10 to 30 for weak signals
        # For very weak signals, even 30 timeouts may be normal before signal acquisition
        # Can be overridden per-receiver via config if needed
        self._max_consecutive_timeouts = int(os.environ.get('SDR_MAX_CONSECUTIVE_TIMEOUTS', '30'))
        # Exponential backoff on TIMEOUT: start at 10 ms and double up to
        # ~2 s.  The old 0.5 s cap was too aggressive for weak signals and
        # the previous "clamp-before-double" arithmetic meant the backoff
        # never actually grew.  With 30 timeouts allowed, the worst-case
        # total wait before giving up is ~30 × 2 s = 1 minute, matching the
        # Redis/DB retry budgets elsewhere in the codebase.
        self._initial_timeout_backoff = 0.01
        self._max_timeout_backoff = 2.0
        self._timeout_backoff = self._initial_timeout_backoff

        self._retry_backoff = 0.25
        self._max_retry_backoff = 5.0
        self._last_logged_error: Optional[str] = None
        # Connection health tracking
        self._connection_attempts = 0
        self._connection_failures = 0
        self._last_successful_connection: Optional[datetime.datetime] = None
        self._stream_errors_count = 0

        # Ring buffer overflow logging rate-limiting
        self._overflow_last_log_time = 0.0
        self._overflow_log_interval = 5.0  # Log at most every 5 seconds
        self._overflow_dropped_since_last_log = 0

        # Device enumeration warning rate-limiting (avoid log spam during retries)
        self._no_devices_last_log_time = 0.0
        self._no_devices_log_interval = 30.0  # Log "no devices found" at most every 30 seconds
        self._fallback_last_log_time = 0.0
        self._fallback_log_interval = 30.0  # Log fallback messages at most every 30 seconds

        # Early decimation in USB callback to reduce sample rate BEFORE ring buffer
        # This is critical for high sample rate SDRs (2.5 MHz+) because Python/NumPy
        # cannot process that many samples in real-time. Decimating early reduces
        # both ring buffer memory usage and downstream processing load.
        # Target ~250 kHz intermediate rate (sufficient for FM stereo with 38 kHz subcarrier)
        self._early_decim_target_rate = 250000  # Target output rate after decimation
        self._early_decim_factor = 1  # Will be calculated on stream start
        self._early_decim_buffer = None  # Accumulator for partial decimation blocks
        self._effective_sample_rate = config.sample_rate  # Effective rate after decimation
        # Anti-alias FIR for the early decimator.  When SciPy is available
        # we build a proper linear-phase lowpass at stream start; the
        # `_zi` state is carried across reads so block boundaries don't
        # ring up from zero.  When SciPy is unavailable we fall back to
        # the legacy boxcar (block-average) path and emit a one-shot
        # warning so operators know RBDS / 38 kHz stereo will see aliased
        # adjacent-channel energy.
        self._early_decim_aa_filter = None
        self._early_decim_aa_zi = None
        self._early_decim_boxcar_warned = False

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

    def _calculate_buffer_size(self) -> int:
        """Calculate a dynamic read buffer size based on the configured sample rate.

        The buffer targets approximately 50 ms of IQ samples, clamped between
        a minimum of 16 384 and a maximum of 262 144 samples.

        Returns:
            Buffer size in samples.
        """
        _MIN_BUFFER = 16384
        _MAX_BUFFER = 262144
        target = int(self.config.sample_rate * 0.05)  # 50 ms
        return max(_MIN_BUFFER, min(target, _MAX_BUFFER))

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

        # Check for "no match" error - specific troubleshooting
        if "no match" in lowered or "nomatch" in lowered:
            if driver == "airspy":
                hints.append("'No match' error for Airspy is usually caused by missing packages. "
                           "Install required packages: 'sudo apt-get install airspy libairspy0 soapysdr-module-airspy'. "
                           "Verify with: 'airspy_info' and 'SoapySDRUtil --probe=\"driver=airspy\"'")
            else:
                hints.append("'No match' error indicates the driver cannot find the device. "
                           "This may be a USB timing issue, missing driver module, or incorrect device arguments")
        
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
        """Enumerate available SoapySDR devices for diagnostic purposes.

        Uses driver-specific enumeration to avoid issues with problematic
        modules (e.g., soapysdr-module-remote failing on avahi).
        """
        all_devices = []

        # First try driver-specific enumeration for our driver
        # This avoids issues with other modules (like remote) failing during enum
        if self.driver_hint:
            try:
                driver_devices = sdr_module.Device.enumerate(f"driver={self.driver_hint}")
                for dev in driver_devices:
                    all_devices.append(dict(dev))
                if driver_devices:
                    self._interface_logger.debug(
                        "Found %d device(s) for driver %s",
                        len(driver_devices),
                        self.driver_hint
                    )
            except Exception as exc:
                # Log at warning level if driver-specific enumeration fails
                # This could indicate missing driver modules or permissions issues
                self._interface_logger.warning(
                    "Driver-specific enumeration failed for %s: %s. "
                    "Check if SoapySDR module is installed (e.g., soapysdr-module-%s)",
                    self.driver_hint,
                    exc,
                    self.driver_hint
                )

        # If driver-specific found nothing, try general enumeration
        # but wrap it to handle module failures gracefully
        if not all_devices:
            try:
                devices = sdr_module.Device.enumerate()
                for dev in devices:
                    dev_dict = dict(dev)
                    # Avoid duplicates
                    if dev_dict not in all_devices:
                        all_devices.append(dev_dict)
            except Exception as exc:
                # General enumeration can fail if ANY module has issues
                # (e.g., soapysdr-module-remote fails without avahi)
                # Log at warning level so users know why devices aren't found
                self._interface_logger.warning(
                    "General device enumeration failed (some SoapySDR modules may have issues): %s. "
                    "Common cause: soapysdr-module-remote without avahi-daemon. "
                    "This may prevent detecting %s devices.",
                    exc,
                    self.driver_hint
                )

        return all_devices

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

        # Signal ring buffer to wake up any waiting consumers
        if self._ring_buffer is not None:
            try:
                self._ring_buffer.signal_shutdown()
            except Exception as e:
                self._interface_logger.debug(
                    "Error signaling ring buffer shutdown for %s: %s",
                    self.config.identifier,
                    e
                )

        # Attempt to stop the stream to unblock readStream if it's stuck
        # This is critical for drivers that block indefinitely on readStream
        if self._handle:
            try:
                self._handle.device.deactivateStream(self._handle.stream)
            except Exception:
                # Ignore errors here - we're shutting down anyway
                # and _teardown_handle will try again
                pass

        if self._thread:
            self._thread.join(timeout=2.0)

        self._teardown_handle()
        self._cancel_capture_requests(RuntimeError("Receiver stopped"), teardown=False)
        self._update_status(locked=False)

    def set_frequency(self, frequency_hz: float) -> bool:  # noqa: D401 - documented in base class
        """Retune the live SDR stream to ``frequency_hz`` without restarting it.

        SoapySDR's ``setFrequency`` is safe to call concurrently with an active
        ``readStream``, so we can change the tuner mid-flight.  The new
        frequency is also persisted into ``self.config`` so subsequent samples
        published to Redis report the correct ``center_frequency`` and the
        downstream demodulator/RBDS state can reset cleanly.
        """
        from dataclasses import replace as _replace_dc

        try:
            freq_hz = float(frequency_hz)
        except (TypeError, ValueError):
            self._interface_logger.error(
                "set_frequency: invalid frequency value %r for %s",
                frequency_hz,
                self.config.identifier,
            )
            return False

        if freq_hz <= 0:
            self._interface_logger.error(
                "set_frequency: non-positive frequency %s for %s",
                freq_hz,
                self.config.identifier,
            )
            return False

        handle = self._handle
        if handle is None or not self._running.is_set():
            self._interface_logger.warning(
                "set_frequency: cannot retune %s while device is not open/running",
                self.config.identifier,
            )
            return False

        # Apply the same PPM correction as the initial tune so the actual
        # tuner frequency matches what the operator selected after correction.
        corrected_freq = freq_hz
        if self.config.frequency_correction_ppm:
            correction_factor = 1.0 + (self.config.frequency_correction_ppm / 1_000_000.0)
            corrected_freq = freq_hz * correction_factor

        channel = self.config.channel if self.config.channel is not None else 0

        try:
            handle.device.setFrequency(handle.sdr.SOAPY_SDR_RX, channel, corrected_freq)
        except Exception as exc:
            self._interface_logger.error(
                "Live retune failed for %s to %.6f MHz: %s",
                self.config.identifier,
                freq_hz / 1_000_000,
                exc,
            )
            self._update_status(last_error=f"Live retune failed: {exc}", context="set_frequency")
            return False

        # Persist the new frequency so status payloads, Redis sample messages,
        # and any subsequent restart use the new value.  ReceiverConfig is a
        # frozen dataclass, so we rebind ``self.config`` to a new instance.
        self.config = _replace_dc(self.config, frequency_hz=freq_hz)

        # Best-effort readback for diagnostics.
        try:
            actual_freq = handle.device.getFrequency(handle.sdr.SOAPY_SDR_RX, channel)
            self._interface_logger.info(
                "Live-retuned %s to %.6f MHz (corrected: %.6f MHz, readback: %.6f MHz)",
                self.config.identifier,
                freq_hz / 1_000_000,
                corrected_freq / 1_000_000,
                actual_freq / 1_000_000,
            )
        except Exception:
            self._interface_logger.info(
                "Live-retuned %s to %.6f MHz",
                self.config.identifier,
                freq_hz / 1_000_000,
            )

        self._emit_event(
            "INFO",
            f"{self.config.identifier} retuned to {freq_hz / 1_000_000:.6f} MHz",
            module_suffix="set_frequency",
            details={
                "identifier": self.config.identifier,
                "frequency_hz": freq_hz,
                "ppm_corrected_hz": corrected_freq,
            },
        )
        return True

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
        
        # Calculate early decimation factor for high sample rate SDRs
        # This is critical for rates > 500 kHz because Python can't process that in real-time
        if self.config.sample_rate > self._early_decim_target_rate * 2:
            self._early_decim_factor = max(1, self.config.sample_rate // self._early_decim_target_rate)
            self._effective_sample_rate = self.config.sample_rate // self._early_decim_factor
            self._early_decim_buffer = numpy_module.array([], dtype=numpy_module.complex64)
            # Build a proper linear-phase anti-alias FIR sized from the
            # input rate.  Cutoff preserves the 57 kHz RBDS subcarrier
            # (upper edge ~60 kHz) and the 38 kHz FM-stereo L-R sideband
            # while keeping the stopband edge below post-decim Nyquist
            # so adjacent FM channels at ±200 / ±400 kHz of tune don't
            # fold back onto the 57 kHz / 38 kHz bands.  Tap-count and
            # cutoff heuristic mirror the secondary RBDS anti-alias
            # filter in FMDemodulator.__init__ so the two stages stay
            # consistent: cap of 1025 bounds CPU even at Airspy's
            # 10 MHz native rate.
            self._early_decim_aa_zi = None
            if _SCIPY_AVAILABLE:
                post_decim_nyquist = self._effective_sample_rate / 2.0
                cutoff = min(80_000.0, max(63_000.0, post_decim_nyquist * 0.4 * 2.0))
                # 0.4 * post-decim Nyquist gives a comfortable transition
                # band; clamp to [63 kHz, 80 kHz] to keep RBDS / stereo
                # passband flat regardless of the user's chosen rate.
                taps = max(127, min(1025, (int(self.config.sample_rate / 4000) | 1)))
                try:
                    h = _scipy_signal.firwin(
                        taps,
                        cutoff,
                        window='blackman',
                        fs=self.config.sample_rate,
                    )
                    self._early_decim_aa_filter = numpy_module.asarray(
                        h, dtype=numpy_module.float32
                    )
                    self._interface_logger.info(
                        "Early-decim anti-alias FIR for %s: %d taps, cutoff %.1f kHz "
                        "(post-decim Nyquist %.1f kHz)",
                        self.config.identifier,
                        taps,
                        cutoff / 1000.0,
                        post_decim_nyquist / 1000.0,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self._early_decim_aa_filter = None
                    self._interface_logger.warning(
                        "Failed to build early-decim FIR for %s (%s); "
                        "falling back to boxcar averaging",
                        self.config.identifier,
                        exc,
                    )
            else:
                self._early_decim_aa_filter = None
                if not self._early_decim_boxcar_warned:
                    self._early_decim_boxcar_warned = True
                    self._interface_logger.warning(
                        "SciPy not available; early decimation for %s uses "
                        "boxcar averaging.  Adjacent-channel energy will fold "
                        "onto the 38 kHz / 57 kHz subcarriers and degrade RBDS "
                        "and stereo decode.",
                        self.config.identifier,
                    )
            self._interface_logger.info(
                "Early decimation enabled for %s: %dx (%d Hz -> %d Hz)",
                self.config.identifier,
                self._early_decim_factor,
                self.config.sample_rate,
                self._effective_sample_rate
            )
        else:
            self._early_decim_factor = 1
            self._effective_sample_rate = self.config.sample_rate
            self._early_decim_buffer = None
            self._early_decim_aa_filter = None
            self._early_decim_aa_zi = None

        # Initialize SDRRingBuffer for robust USB reading if enabled
        if self._ring_buffer_enabled and _RING_BUFFER_AVAILABLE:
            try:
                # Calculate buffer size for ~2 seconds of DECIMATED samples
                # Use effective sample rate after decimation for buffer sizing
                buffer_size = calculate_buffer_size(self._effective_sample_rate, buffer_time_seconds=2.0)

                self._ring_buffer = SDRRingBuffer(
                    size=buffer_size,
                    numpy_module=numpy_module,
                    identifier=self.config.identifier
                )
                self._interface_logger.info(
                    "Initialized ring buffer for %s: %d samples (%.2f MB, %.2fs at %d Hz effective)",
                    self.config.identifier,
                    buffer_size,
                    buffer_size * 8 / 1024 / 1024,  # complex64 = 8 bytes
                    buffer_size / self._effective_sample_rate,
                    self._effective_sample_rate
                )
            except Exception as e:
                self._interface_logger.warning(
                    "Failed to initialize ring buffer for %s, continuing without it: %s",
                    self.config.identifier,
                    e
                )
                self._ring_buffer = None
                self._ring_buffer_enabled = False
        elif self._ring_buffer_enabled and not _RING_BUFFER_AVAILABLE:
            self._interface_logger.warning(
                "Ring buffer requested for %s but module not available",
                self.config.identifier
            )
            self._ring_buffer_enabled = False

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
        # IMPORTANT: Airspy driver does NOT support the 'label' parameter and will
        # return "no match" if it's present. Only set label for drivers that support it.
        if self.config.identifier and self.driver_hint != "airspy":
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
            # Rate-limit "no devices found" warning to avoid log spam during retries
            now = time.time()
            if now - self._no_devices_last_log_time >= self._no_devices_log_interval:
                self._interface_logger.warning(
                    "No SoapySDR devices found. Ensure device is connected and drivers are installed."
                )
                self._no_devices_last_log_time = now

        # Add a small delay after enumeration to allow libusb to settle
        # This helps avoid "no match" errors caused by timing/race conditions
        # between enumeration and device opening (especially with USB3 hubs)
        time.sleep(0.1)

        # Retry Device.make() specifically for "no match" errors
        # These can occur due to libusb timing issues, USB module interference,
        # or missing driver packages (especially for Airspy)
        device = None
        last_exc = None
        no_match_retries = 5  # Increased from 3 to handle more timing issues
        no_match_delay = 0.5

        # Convert args dict to string format for SoapySDR.Device()
        # IMPORTANT: String format ("driver=airspy,serial=xxx") works reliably
        # while dict format ({"driver": "airspy"}) can fail with "no match"
        # on some Python/SWIG versions. Use string format for compatibility.
        args_string = ",".join(f"{k}={v}" for k, v in args.items())
        self._interface_logger.debug("Opening device with args: %s", args_string)

        for attempt in range(no_match_retries):
            try:
                device = SoapySDR.Device(args_string)
                break  # Success
            except Exception as exc:
                last_exc = exc
                error_str = str(exc).lower()

                # Check if this is a "no match" error that might benefit from retry
                if "no match" in error_str or "nomatch" in error_str:
                    if attempt < no_match_retries - 1:
                        self._interface_logger.warning(
                            "Device.make() returned 'no match' for %s (attempt %d/%d). "
                            "This may be a USB timing issue or missing driver package. Retrying in %.1fs...",
                            self.config.identifier,
                            attempt + 1,
                            no_match_retries,
                            no_match_delay
                        )
                        time.sleep(no_match_delay)
                        no_match_delay *= 2  # Exponential backoff
                        continue
                    else:
                        # After all retries failed, provide detailed diagnostic information
                        error_msg = (
                            f"Device.make() returned 'no match' after {no_match_retries} retries for {self.config.identifier}. "
                        )
                        
                        if self.driver_hint == "airspy":
                            # Airspy-specific troubleshooting
                            error_msg += (
                                "For Airspy devices, this usually means missing packages. "
                                "Install: 'sudo apt-get install airspy libairspy0 soapysdr-module-airspy'. "
                                "Then verify: 'airspy_info' (should show device) and "
                                "'SoapySDRUtil --probe=\"driver=airspy\"' (should succeed). "
                            )
                        else:
                            # General troubleshooting
                            error_msg += (
                                "The device was enumerated but cannot be opened. "
                                "This may indicate a libusb issue, USB hub problem, or missing driver package. "
                            )
                        
                        self._interface_logger.error(error_msg)
                # For non "no match" errors, try fallback immediately
                break

        if device is None and last_exc is not None:
            device = self._retry_device_open_without_serial(
                SoapySDR, args, last_exc
            )

        try:
            device.setSampleRate(SoapySDR.SOAPY_SDR_RX, channel, self.config.sample_rate)

            # Apply frequency correction (PPM) if specified
            # RTL-SDR and other low-cost SDRs have crystal oscillator drift
            # Typical values: -50 to +50 PPM, extreme range: -200 to +200 PPM
            corrected_freq = self.config.frequency_hz
            if self.config.frequency_correction_ppm != 0.0:
                # Validate PPM range - reject extreme values that are likely errors
                if not -200.0 <= self.config.frequency_correction_ppm <= 200.0:
                    error_msg = (
                        f"Invalid frequency correction PPM: {self.config.frequency_correction_ppm}. "
                        f"Valid range is -200 to +200 PPM. Typical values are -50 to +50 PPM. "
                        f"Extreme PPM values indicate configuration error."
                    )
                    self._interface_logger.error(error_msg)
                    raise ValueError(error_msg)

                correction_factor = 1.0 + (self.config.frequency_correction_ppm / 1_000_000.0)
                corrected_freq = self.config.frequency_hz * correction_factor
                self._interface_logger.info(
                    "Applying %+.1f PPM frequency correction for %s: %.6f MHz -> %.6f MHz",
                    self.config.frequency_correction_ppm,
                    self.config.identifier,
                    self.config.frequency_hz / 1_000_000,
                    corrected_freq / 1_000_000
                )
            
            device.setFrequency(SoapySDR.SOAPY_SDR_RX, channel, corrected_freq)
            
            # Log the frequency that was set for diagnostics
            try:
                actual_freq = device.getFrequency(SoapySDR.SOAPY_SDR_RX, channel)
                self._interface_logger.info(
                    "Tuned %s to %.6f MHz (requested: %.6f MHz, readback: %.6f MHz)",
                    self.config.identifier,
                    self.config.frequency_hz / 1_000_000,
                    corrected_freq / 1_000_000,
                    actual_freq / 1_000_000
                )
                # Warn if readback differs significantly (more than 1 kHz)
                if abs(actual_freq - corrected_freq) > 1000:
                    self._interface_logger.warning(
                        "Frequency readback mismatch for %s: requested %.6f MHz, got %.6f MHz (%.1f kHz error)",
                        self.config.identifier,
                        corrected_freq / 1_000_000,
                        actual_freq / 1_000_000,
                        (actual_freq - corrected_freq) / 1000
                    )
            except Exception as e:
                # Some devices don't support getFrequency, that's OK
                self._interface_logger.debug(
                    "Could not read back frequency for %s: %s",
                    self.config.identifier,
                    e
                )
            
            # Configure Gain
            external_lna_db = float(self.config.external_lna_db or 0.0)
            if self.config.gain is not None:
                try:
                    device.setGain(SoapySDR.SOAPY_SDR_RX, channel, float(self.config.gain))
                    self._interface_logger.info(
                        "Set gain to %.1f dB for %s (external LNA: %+.1f dB)",
                        float(self.config.gain),
                        self.config.identifier,
                        external_lna_db,
                    )
                except Exception as exc:
                    self._interface_logger.warning(
                        "Failed to set gain to %.1f dB for %s: %s",
                        float(self.config.gain),
                        self.config.identifier,
                        exc
                    )
            elif external_lna_db > 0.0:
                # An external LNA is present and the user didn't pin a gain.
                # Hardware AGC has no visibility into the outboard amp, so
                # leaving it on tends to drive the front-end into clipping.
                # Disable AGC and pick a manual gain biased down by the LNA's
                # contribution.
                try:
                    if device.hasGainMode(SoapySDR.SOAPY_SDR_RX, channel):
                        device.setGainMode(SoapySDR.SOAPY_SDR_RX, channel, False)
                    gain_range = device.getGainRange(SoapySDR.SOAPY_SDR_RX, channel)
                    g_min = float(gain_range.minimum())
                    g_max = float(gain_range.maximum())
                    # Aim at the lower-middle of the range, then back off by the
                    # external LNA's gain. Clamp to the device range.
                    target = g_min + 0.4 * (g_max - g_min) - external_lna_db
                    target = max(g_min, min(g_max, target))
                    device.setGain(SoapySDR.SOAPY_SDR_RX, channel, target)
                    self._interface_logger.info(
                        "Disabled AGC for %s and set manual gain to %.1f dB "
                        "(range %.1f-%.1f, external LNA: %+.1f dB)",
                        self.config.identifier,
                        target,
                        g_min,
                        g_max,
                        external_lna_db,
                    )
                except Exception as exc:
                    self._interface_logger.warning(
                        "Failed to set LNA-compensated gain for %s: %s",
                        self.config.identifier,
                        exc,
                    )
            else:
                # Enable AGC if gain is not specified and device supports it
                try:
                    if device.hasGainMode(SoapySDR.SOAPY_SDR_RX, channel):
                        device.setGainMode(SoapySDR.SOAPY_SDR_RX, channel, True)
                        self._interface_logger.info(
                            "Enabled Automatic Gain Control (AGC) for %s (no fixed gain specified)",
                            self.config.identifier
                        )
                    else:
                        self._interface_logger.debug(
                            "Device %s does not support AGC and no gain specified",
                            self.config.identifier
                        )
                except Exception as exc:
                    self._interface_logger.debug(
                        "Failed to enable AGC for %s: %s",
                        self.config.identifier,
                        exc
                    )

            # Set bandwidth to match sample rate if supported (helps with anti-aliasing)
            try:
                device.setBandwidth(SoapySDR.SOAPY_SDR_RX, channel, self.config.sample_rate)
            except Exception:
                # Not all devices support setting bandwidth, which is fine
                pass

            # Log available antennas for diagnostics
            try:
                antennas = device.listAntennas(SoapySDR.SOAPY_SDR_RX, channel)
                if antennas:
                    current_antenna = device.getAntenna(SoapySDR.SOAPY_SDR_RX, channel)
                    self._interface_logger.info(
                        "Available antennas: %s. Using: %s", 
                        antennas, 
                        current_antenna
                    )
            except Exception:
                pass

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
            # Rate-limit fallback warnings to avoid log spam during repeated retries
            now = time.time()
            should_log = now - self._fallback_last_log_time >= self._fallback_log_interval
            if should_log:
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
                self._fallback_last_log_time = now

            try:
                # Use string format for better compatibility
                fallback_args_str = ",".join(f"{k}={v}" for k, v in fallback_args.items())
                device = sdr_module.Device(fallback_args_str)
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
        # Rate-limit this warning as well
        now = time.time()
        if now - self._fallback_last_log_time >= self._fallback_log_interval:
            self._interface_logger.warning(
                "Attempting to open device with driver-only filter (serial '%s' was not found)",
                serial,
            )
            self._fallback_last_log_time = now

        try:
            # Use string format for better compatibility
            minimal_args_str = ",".join(f"{k}={v}" for k, v in minimal_args.items())
            device = sdr_module.Device(minimal_args_str)
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

    def _compute_spectrum(self, samples, numpy_module) -> None:
        """Compute power spectral density using Welch method."""
        if len(samples) < self._fft_size:
            return

        # Initialize window if needed
        if self._window is None:
            self._window = numpy_module.hanning(self._fft_size)

        # Apply Hann window for spectral leakage reduction
        # Take the center samples if we have more than needed
        start_idx = (len(samples) - self._fft_size) // 2
        windowed = samples[start_idx:start_idx + self._fft_size] * self._window

        # FFT with zero-padding for better resolution (implicit in numpy if n > len)
        # Use fftshift to center DC at 0
        spectrum = numpy_module.abs(numpy_module.fft.fftshift(numpy_module.fft.fft(windowed, n=self._fft_size)))

        # Convert to dB (10*log10 for power)
        # Avoid log(0) by clamping to small value
        power_db = 20 * numpy_module.log10(numpy_module.maximum(spectrum, 1e-10))

        # Normalize to 0-100 scale for visualization (approximate -100dBm to 0dBm range)
        # This is somewhat arbitrary but works for visualization
        normalized = numpy_module.clip((power_db + 100) / 100 * 100, 0, 100)

        self._spectrum_buffer = normalized.astype(numpy_module.float32)
        self._last_spectrum_update = time.time()

    def get_spectrum(self) -> Optional[List[float]]:
        """Get the latest computed spectrum data."""
        if self._spectrum_buffer is None:
            return None
        # Return as list for JSON serialization
        return self._spectrum_buffer.tolist()

    def _capture_loop(self) -> None:
        handle = self._handle
        buffer = None
        if handle is not None:
            # Use larger buffer to reduce USB transfer overhead and prevent SOAPY_SDR_OVERFLOW (-4)
            # High-speed SDRs like AirSpy generate data faster than smaller buffers can handle
            buffer = handle.numpy.zeros(16384, dtype=handle.numpy.complex64)

        retry_delay = self._retry_backoff
        consecutive_failures = 0

        last_spectrum_time = 0

        # Diagnostic counters for debugging playback issues
        samples_produced = 0
        reads_successful = 0
        reads_empty = 0
        last_stats_time = time.time()
        stats_interval = 5.0  # Log stats every 5 seconds

        while self._running.is_set():
            if handle is None:
                if not self._running.is_set():
                    break

                consecutive_failures += 1
                self._connection_attempts += 1
                try:
                    # Log retry attempts, but less verbosely after many failures
                    # First 5 retries: log each one
                    # After that: log every 10th retry or every 60 seconds
                    if consecutive_failures <= 5 or consecutive_failures % 10 == 0:
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
                # Read with backpressure handling
                result = handle.device.readStream(handle.stream, [buffer], len(buffer))
                
                if result.ret < 0:
                    # Handle different error types differently
                    error_code = result.ret
                    message = self._describe_soapysdr_error(error_code)
                    message = self._annotate_lock_hint(message)
                    
                    # TIMEOUT (-1) - Exponential backoff.
                    #
                    # Timeouts are normal on weak signals while the SDR
                    # hasn't produced a sample buffer yet.  We sleep for a
                    # growing interval so we don't spin the CPU, then retry.
                    # After _max_consecutive_timeouts in a row we give up
                    # and force a reconnect (handled above via RuntimeError).
                    #
                    # Previously this clamped `backoff` itself to 0.5 before
                    # doubling, so `backoff * 2` got re-clamped back to 0.5
                    # every iteration — the exponential growth never
                    # happened.  Now we double the stored state and clamp
                    # on read, matching the Redis/DB retry patterns
                    # elsewhere in the codebase.
                    if error_code == -1:
                        self._consecutive_timeouts += 1
                        if self._consecutive_timeouts > self._max_consecutive_timeouts:
                             # Too many timeouts, force reconnection
                             raise RuntimeError(f"SDR timed out {self._consecutive_timeouts} times")

                        backoff = min(self._timeout_backoff, self._max_timeout_backoff)
                        time.sleep(backoff)
                        self._timeout_backoff = min(
                            self._timeout_backoff * 2,
                            self._max_timeout_backoff,
                        )
                        continue
                    else:
                        self._consecutive_timeouts = 0
                        self._timeout_backoff = self._initial_timeout_backoff
                    
                    # OVERFLOW (-4) / UNDERFLOW (-7)
                    if error_code in (-4, -7):
                        self._stream_errors_count += 1
                        if self._stream_errors_count == 1 or self._stream_errors_count % 100 == 0:
                            self._interface_logger.warning(
                                "Transient stream error for %s (error %d, total: %d): %s. Continuing...",
                                self.config.identifier,
                                error_code,
                                self._stream_errors_count,
                                message
                            )
                        self._update_status(
                            locked=True,
                            last_error=message,
                            context="read_stream_transient",
                        )
                        continue
                    
                    # Other errors require full reconnection
                    raise RuntimeError(message)

                # Success - reset timeout counters
                self._consecutive_timeouts = 0
                self._timeout_backoff = self._initial_timeout_backoff

                if result.ret > 0:
                    reads_successful += 1
                    raw_samples = buffer[: result.ret]

                    # Early decimation to reduce sample rate BEFORE ring buffer
                    # This is critical for high sample rate SDRs (2.5 MHz+).
                    # When SciPy is available we use a proper linear-phase
                    # anti-alias FIR (lfilter + stride downsample) carrying
                    # `zi` across reads so block boundaries don't ring up
                    # from zero.  Without SciPy we fall back to the legacy
                    # boxcar (block-average) path — see warning at stream
                    # start; this folds adjacent-channel energy onto the
                    # 38 kHz / 57 kHz subcarriers and degrades RBDS / stereo.
                    decimated_samples = None
                    if self._early_decim_factor > 1:
                        # Accumulate samples with any leftover from previous read
                        to_decimate = raw_samples
                        if self._early_decim_buffer is not None and len(self._early_decim_buffer) > 0:
                            to_decimate = handle.numpy.concatenate([self._early_decim_buffer, raw_samples])

                        decim = self._early_decim_factor

                        if self._early_decim_aa_filter is not None and _SCIPY_AVAILABLE:
                            # Proper anti-alias path: lfilter then stride-N downsample.
                            if len(to_decimate) > 0:
                                if self._early_decim_aa_zi is None:
                                    # Seed the lfilter delay line so the very
                                    # first chunk doesn't ring up from zero.
                                    # Same convention used by FMDemodulator's
                                    # secondary RBDS anti-alias stage.
                                    zi = _scipy_signal.lfilter_zi(
                                        self._early_decim_aa_filter, 1.0
                                    ).astype(handle.numpy.complex64)
                                    self._early_decim_aa_zi = zi * to_decimate[0]
                                filtered, self._early_decim_aa_zi = _scipy_signal.lfilter(
                                    self._early_decim_aa_filter,
                                    1.0,
                                    to_decimate,
                                    zi=self._early_decim_aa_zi,
                                )
                                # Stride-N downsample.  Aliasing has just
                                # been suppressed by the FIR above so
                                # [::N] is safe.  Keep the residual
                                # samples that don't land on a stride
                                # boundary so the next read continues
                                # at the right phase.
                                n_complete = (len(filtered) // decim) * decim
                                if n_complete >= decim:
                                    decimated_samples = filtered[:n_complete:decim].astype(
                                        handle.numpy.complex64
                                    )
                                    self._early_decim_buffer = to_decimate[n_complete:].copy()
                                else:
                                    self._early_decim_buffer = to_decimate.copy()
                            else:
                                self._early_decim_buffer = to_decimate.copy()
                        else:
                            # Fallback boxcar (block-average) path.  Used
                            # only when SciPy is unavailable; warning was
                            # emitted at stream start.
                            n_complete = (len(to_decimate) // decim) * decim
                            if n_complete >= decim:
                                decimated_samples = to_decimate[:n_complete].reshape(-1, decim).mean(axis=1)
                                decimated_samples = decimated_samples.astype(handle.numpy.complex64)
                                self._early_decim_buffer = to_decimate[n_complete:].copy()
                            else:
                                self._early_decim_buffer = to_decimate.copy()
                    else:
                        # No decimation needed
                        decimated_samples = raw_samples

                    # Write DECIMATED samples to ring buffer if enabled
                    # This provides overflow detection and backpressure monitoring
                    if self._ring_buffer is not None and decimated_samples is not None and len(decimated_samples) > 0:
                        samples_produced += len(decimated_samples)
                        try:
                            written = self._ring_buffer.write(decimated_samples)
                            if written < len(decimated_samples):
                                # Overflow detected - ring buffer is full
                                # This is a significant operational issue indicating
                                # processing can't keep up with USB data rate
                                dropped = len(decimated_samples) - written
                                self._overflow_dropped_since_last_log += dropped

                                # Rate-limit overflow logging to avoid log spam
                                now = time.time()
                                if now - self._overflow_last_log_time >= self._overflow_log_interval:
                                    self._interface_logger.warning(
                                        "Ring buffer overflow for %s: dropped %d samples in last %.1fs (processing too slow)",
                                        self.config.identifier,
                                        self._overflow_dropped_since_last_log,
                                        now - self._overflow_last_log_time if self._overflow_last_log_time > 0 else 0.0
                                    )
                                    self._overflow_last_log_time = now
                                    self._overflow_dropped_since_last_log = 0
                        except Exception as e:
                            self._interface_logger.debug(
                                "Error writing to ring buffer for %s: %s",
                                self.config.identifier,
                                e
                            )
                    
                    # 1. Compute Spectrum (if interval elapsed) - use RAW samples for full bandwidth
                    now = time.time()
                    if now - last_spectrum_time > self._spectrum_update_interval:
                        self._compute_spectrum(raw_samples, handle.numpy)
                        last_spectrum_time = now

                    # 2. Update Signal Strength - use RAW samples for accurate measurement
                    magnitude = float(handle.numpy.mean(handle.numpy.abs(raw_samples)))
                    self._update_status(locked=True, signal_strength=magnitude)

                    # 3. Update Audio Sample Buffer (fallback when ring buffer not available)
                    # Uses decimated samples if available for consistency with ring buffer
                    if decimated_samples is not None:
                        self._update_sample_buffer(decimated_samples)

                    # 4. Process Capture (IQ recording) - use RAW samples for full bandwidth
                    self._process_capture(raw_samples)

                    # 5. Periodic stats logging for debugging playback issues
                    now = time.time()
                    if now - last_stats_time >= stats_interval:
                        fill_pct = 0.0
                        if self._ring_buffer is not None:
                            fill_pct = self._ring_buffer.fill_level / self._ring_buffer.size * 100

                        samples_per_sec = samples_produced / (now - last_stats_time)
                        self._interface_logger.info(
                            "SDR stats for %s: %.1f kHz effective, %d reads, %d samples, "
                            "buffer %.1f%% full, %.0f samples/sec",
                            self.config.identifier,
                            self._effective_sample_rate / 1000,
                            reads_successful,
                            samples_produced,
                            fill_pct,
                            samples_per_sec
                        )
                        samples_produced = 0
                        reads_successful = 0
                        last_stats_time = now

                else:
                    reads_empty += 1
                    self._update_status(locked=True, signal_strength=0.0)

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

    def get_effective_sample_rate(self) -> int:
        """Get the effective sample rate after early decimation.

        For high sample rate SDRs (2.5 MHz+), early decimation reduces the rate
        before samples enter the ring buffer. This returns the rate that downstream
        consumers (demodulator, audio pipeline) should use.

        Returns:
            Effective sample rate in Hz (after decimation)
        """
        return self._effective_sample_rate

    def get_samples(self, num_samples: Optional[int] = None):
        """Get recent IQ samples from the receiver for real-time processing.

        Args:
            num_samples: Number of samples to retrieve. If None, returns all available samples.

        Returns:
            numpy array of complex64 samples, or None if receiver is not running
        """
        if not self._running.is_set():
            return None

        # If ring buffer is available, read from it (this drains the buffer)
        if self._ring_buffer is not None:
            if num_samples is None:
                # Read as many samples as available, up to a reasonable limit
                num_samples = min(self._ring_buffer.fill_level, self._sample_buffer_size)

            if num_samples == 0:
                return None

            # Read from ring buffer with sufficient timeout for continuous streaming
            # CRITICAL: Short timeouts cause audio gaps when the consumer (audio pipeline)
            # runs slightly faster than the producer (USB read). The timeout should be
            # long enough to handle USB bus contention, system load spikes, and GC pauses.
            # 500ms timeout provides headroom for real-world conditions while still
            # allowing timely detection of actual hardware failures.
            samples = self._ring_buffer.read(num_samples, timeout=0.5)
            return samples

        # Fallback to sample buffer if ring buffer not available
        if self._sample_buffer is None:
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

    def get_ring_buffer_stats(self) -> Optional[Dict[str, object]]:
        """Get ring buffer health statistics.
        
        Returns dictionary with buffer metrics for monitoring, or None if
        the ring buffer is not available or receiver is not running.
        """
        if not self._running.is_set():
            return None
        
        # Use SDRRingBuffer stats if available
        if self._ring_buffer is not None:
            try:
                stats = self._ring_buffer.get_stats()
                return stats.to_dict()
            except Exception as e:
                self._interface_logger.debug(
                    "Error getting ring buffer stats for %s: %s",
                    self.config.identifier,
                    e
                )
        
        # Fallback to simple sample buffer stats if ring buffer not available
        if self._sample_buffer is not None:
            with self._sample_buffer_lock:
                fill_level = self._sample_buffer_pos
                fill_percentage = (fill_level / self._sample_buffer_size * 100) if self._sample_buffer_size > 0 else 0
                
                return {
                    'size': self._sample_buffer_size,
                    'fill_level': fill_level,
                    'fill_percentage': fill_percentage,
                    'samples_available': fill_level,
                    'buffer_type': 'simple',
                    'total_samples_written': 0,
                    'total_samples_read': 0,
                    'overflow_count': 0,
                    'underflow_count': 0,
                    'uptime_seconds': 0.0,
                }
        
        return None


class RTLSDRReceiver(_SoapySDRReceiver):
    """Driver for RTL2832U based SDRs via the SoapyRTLSDR module."""

    driver_hint = "rtlsdr"


class AirspyReceiver(_SoapySDRReceiver):
    """Driver for Airspy receivers using the SoapyAirspy module.

    Airspy R2 (most common) only supports 2.5 MHz and 10 MHz sample rates.

    Gain Settings:
    - When gain is None/not set: AGC is enabled (auto gain)
    - When gain is set to a value: Manual gain mode with linearity optimization
    - Airspy has a range of 0-21 dB in "linearity" mode
    - For strong signals (local FM stations), use 0-5 dB to prevent ADC overload
    - For weak signals, use 15-21 dB for better sensitivity
    """

    driver_hint = "airspy"

    # Airspy R2 valid sample rates - ONLY these two are supported
    AIRSPY_R2_SAMPLE_RATES = [2_500_000, 10_000_000]

    def _open_handle(self) -> _SoapySDRHandle:
        """Open Airspy device with Airspy-specific configuration.

        Overrides parent to add:
        1. Sample rate validation (must be exactly 2.5 MHz or 10 MHz for R2)
        2. AGC or manual gain mode based on config
        3. Explicit frequency component tuning
        4. Bias-T configuration if supported
        """
        # Validate sample rate for Airspy R2 before opening device
        # Airspy R2 hardware ONLY supports these two rates - no other rates work
        if self.config.sample_rate not in self.AIRSPY_R2_SAMPLE_RATES:
            error_msg = (
                f"Invalid Airspy R2 sample rate: {self.config.sample_rate} Hz. "
                f"Airspy R2 hardware ONLY supports 2.5 MHz (2500000) or 10 MHz (10000000). "
                f"Using any other sample rate will cause continuous stream errors. "
                f"Please reconfigure the receiver with a valid sample rate."
            )
            self._interface_logger.error(error_msg)
            raise ValueError(error_msg)

        # Open device using parent implementation
        handle = super()._open_handle()

        try:
            # Get channel
            channel = self.config.channel if self.config.channel is not None else 0

            # Configure gain mode based on whether gain is specified
            external_lna_db = float(self.config.external_lna_db or 0.0)
            if self.config.gain is None and external_lna_db <= 0.0:
                # No gain specified and no outboard amp - enable hardware AGC
                try:
                    handle.device.setGainMode(handle.sdr.SOAPY_SDR_RX, channel, True)  # Enable AGC
                    self._interface_logger.info(
                        "Enabled AGC (automatic gain) for Airspy %s",
                        self.config.identifier
                    )
                except Exception as e:
                    self._interface_logger.warning(
                        "Could not enable AGC for Airspy %s: %s - falling back to manual gain",
                        self.config.identifier,
                        e
                    )
                    # Fallback: set a moderate default gain
                    try:
                        handle.device.setGainMode(handle.sdr.SOAPY_SDR_RX, channel, False)
                        handle.device.setGain(handle.sdr.SOAPY_SDR_RX, channel, 10.0)
                    except Exception:
                        pass
            else:
                # Either the user pinned a gain, or there's an external LNA in
                # front of the SDR. In the LNA case, hardware AGC has no idea
                # the outboard amp exists and will overload the front-end, so
                # we disable AGC and pick a manual gain biased down by the
                # LNA's gain. Airspy linearity range is 0-21 dB.
                if self.config.gain is not None:
                    requested_gain = float(self.config.gain)
                else:
                    # Aim ~10 dB without an LNA; back off as the LNA grows.
                    requested_gain = 10.0 - external_lna_db
                actual_gain = max(0.0, min(21.0, requested_gain))
                try:
                    handle.device.setGainMode(handle.sdr.SOAPY_SDR_RX, channel, False)  # Disable AGC
                    handle.device.setGain(handle.sdr.SOAPY_SDR_RX, channel, actual_gain)
                    self._interface_logger.info(
                        "Set Airspy %s to manual gain %.1f dB (range 0-21, "
                        "external LNA: %+.1f dB)",
                        self.config.identifier,
                        actual_gain,
                        external_lna_db,
                    )
                except Exception as e:
                    self._interface_logger.warning(
                        "Could not set Airspy gain for %s: %s",
                        self.config.identifier,
                        e
                    )

            # Explicitly set the frequency using the RF component
            # Some SoapySDR drivers need explicit component tuning
            try:
                freq_hz = self.config.frequency_hz
                # Try to set RF frequency component explicitly
                handle.device.setFrequency(handle.sdr.SOAPY_SDR_RX, channel, "RF", freq_hz)
                self._interface_logger.info(
                    "Set Airspy %s RF frequency to %.6f MHz",
                    self.config.identifier,
                    freq_hz / 1_000_000
                )
            except Exception as e:
                # If RF component doesn't work, the parent already set the main frequency
                self._interface_logger.debug(
                    "Could not set RF frequency component for %s (using default tuning): %s",
                    self.config.identifier,
                    e
                )

            # Verify the actual tuned frequency
            try:
                actual_freq = handle.device.getFrequency(handle.sdr.SOAPY_SDR_RX, channel)
                expected_freq = self.config.frequency_hz
                freq_error_khz = (actual_freq - expected_freq) / 1000.0

                if abs(freq_error_khz) > 10:  # More than 10 kHz error
                    self._interface_logger.warning(
                        "⚠️ Airspy %s frequency mismatch: expected %.6f MHz, actual %.6f MHz (%.1f kHz error)",
                        self.config.identifier,
                        expected_freq / 1_000_000,
                        actual_freq / 1_000_000,
                        freq_error_khz
                    )
                else:
                    self._interface_logger.info(
                        "Airspy %s tuned to %.6f MHz (error: %.1f kHz)",
                        self.config.identifier,
                        actual_freq / 1_000_000,
                        freq_error_khz
                    )
            except Exception as e:
                self._interface_logger.debug(
                    "Could not verify Airspy frequency for %s: %s",
                    self.config.identifier,
                    e
                )

            # Try to disable Bias-T by default (can damage some equipment if left on)
            try:
                if hasattr(handle.device, 'writeSetting'):
                    handle.device.writeSetting('biastee', 'false')
                    self._interface_logger.debug(
                        "Disabled Bias-T for Airspy %s",
                        self.config.identifier
                    )
            except Exception as e:
                # Not all Airspy modules support bias-T, that's OK
                pass

            # Log final configuration
            gain_mode = "AGC" if self.config.gain is None else f"{self.config.gain} dB manual"
            self._interface_logger.info(
                "✅ Airspy %s configured: %.6f MHz, %d Hz sample rate, %s",
                self.config.identifier,
                self.config.frequency_hz / 1_000_000,
                self.config.sample_rate,
                gain_mode
            )

        except Exception as exc:
            # If Airspy-specific config fails, clean up and raise
            self._teardown_handle(handle)
            raise RuntimeError(
                f"Failed to configure Airspy-specific settings for {self.config.identifier}: {exc}"
            ) from exc

        return handle

    def set_frequency(self, frequency_hz: float) -> bool:  # noqa: D401 - documented in base class
        """Live-retune Airspy, including the explicit "RF" component."""
        if not super().set_frequency(frequency_hz):
            return False

        # _open_handle() sets the "RF" component explicitly because some
        # SoapyAirspy builds need it.  Mirror that here so a live retune
        # actually moves the tuner instead of leaving it on the previous LO.
        handle = self._handle
        if handle is None:
            return True  # parent already logged; treat as success of the main set

        try:
            channel = self.config.channel if self.config.channel is not None else 0
            corrected_freq = self.config.frequency_hz
            if self.config.frequency_correction_ppm:
                corrected_freq *= 1.0 + (self.config.frequency_correction_ppm / 1_000_000.0)
            handle.device.setFrequency(handle.sdr.SOAPY_SDR_RX, channel, "RF", corrected_freq)
        except Exception as exc:
            # Best-effort: parent already moved the main frequency; log and continue.
            self._interface_logger.debug(
                "Airspy %s: could not set RF component during live retune: %s",
                self.config.identifier,
                exc,
            )
        return True


def register_builtin_drivers(manager: RadioManager) -> None:
    """Register the built-in SDR drivers against a radio manager instance."""

    manager.register_driver("rtl2832u", RTLSDRReceiver)
    manager.register_driver("rtl-sdr", RTLSDRReceiver)
    manager.register_driver("rtlsdr", RTLSDRReceiver)

    manager.register_driver("airspy", AirspyReceiver)

    # File replay driver: stream a previously-captured complex64 .npy
    # through the radio pipeline. Useful for decoder regression tests
    # without live SDR hardware. See app_core/radio/file_replay.py.
    from .file_replay import register_driver as _register_file_replay
    _register_file_replay(manager)


__all__ = [
    "AirspyReceiver",
    "RTLSDRReceiver",
    "register_builtin_drivers",
]
