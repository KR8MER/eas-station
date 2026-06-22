"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""
Direct ctypes wrapper for libairspy - bypasses SoapySDR/SWIG.

This module provides direct access to libairspy, similar to how dump1090
and other C programs access SDR hardware. It avoids Python/SWIG ABI
compatibility issues that can occur with python3-soapysdr.

Usage:
    from app_core.radio.libairspy import AirspyDevice

    # List devices
    serials = AirspyDevice.list_devices()

    # Open and use device
    with AirspyDevice() as dev:
        dev.set_sample_rate(2_500_000)
        dev.set_frequency(162_550_000)
        dev.set_lna_gain(10)
        dev.start_rx(callback)
"""

import ctypes
import ctypes.util
import logging
import threading
import time
from ctypes import (
    CFUNCTYPE, POINTER, Structure, byref, c_char_p, c_float, c_int,
    c_int16, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p,
)
from enum import IntEnum
from typing import Callable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# Error Codes
# =============================================================================

class AirspyError(IntEnum):
    """Airspy error codes from airspy.h"""
    SUCCESS = 0
    TRUE = 1
    INVALID_PARAM = -2
    NOT_FOUND = -5
    BUSY = -6
    NO_MEM = -11
    LIBUSB = -1000
    THREAD = -1001
    STREAMING_THREAD_ERR = -1002
    STREAMING_STOPPED = -1003
    OTHER = -9999


class AirspySampleType(IntEnum):
    """Sample type enumeration"""
    FLOAT32_IQ = 0      # 2x32-bit float per sample
    FLOAT32_REAL = 1    # 1x32-bit float per sample (real only)
    INT16_IQ = 2        # 2x16-bit int per sample
    INT16_REAL = 3      # 1x16-bit int per sample (real only)
    UINT16_REAL = 4     # 1x16-bit unsigned per sample
    RAW = 5             # Raw ADC samples


class AirspyBoardId(IntEnum):
    """Board identification"""
    PROTO_AIRSPY = 0
    INVALID = 0xFF


# =============================================================================
# Structures
# =============================================================================

class AirspyDevice_t(Structure):
    """Opaque device handle"""
    _fields_ = []


class AirspyTransfer(Structure):
    """Transfer structure passed to callback"""
    _fields_ = [
        ("device", POINTER(AirspyDevice_t)),
        ("ctx", c_void_p),
        ("samples", c_void_p),
        ("sample_count", c_int),
        ("dropped_samples", c_uint64),
        ("sample_type", c_int),
    ]


class AirspyLibVersion(Structure):
    """Library version info"""
    _fields_ = [
        ("major_version", c_uint32),
        ("minor_version", c_uint32),
        ("revision", c_uint32),
    ]


class AirspyReadPartidSerialno(Structure):
    """Part ID and serial number"""
    _fields_ = [
        ("part_id", c_uint32 * 2),
        ("serial_no", c_uint32 * 4),
    ]


# Callback type: int (*airspy_sample_block_cb_fn)(airspy_transfer_t* transfer)
AIRSPY_SAMPLE_CALLBACK = CFUNCTYPE(c_int, POINTER(AirspyTransfer))


# =============================================================================
# Library Loading
# =============================================================================

def _load_libairspy():
    """Load libairspy shared library."""
    # Try common library names
    lib_names = [
        "airspy",
        "libairspy",
        "libairspy.so.0",
        "libairspy.so",
    ]

    # Also try ctypes.util to find the library
    found_path = ctypes.util.find_library("airspy")
    if found_path:
        lib_names.insert(0, found_path)

    for name in lib_names:
        try:
            lib = ctypes.CDLL(name)
            logger.debug(f"Loaded libairspy from: {name}")
            return lib
        except OSError:
            continue

    raise OSError(
        "Could not load libairspy. Install with: sudo apt-get install libairspy0"
    )


# Load library
_lib = _load_libairspy()


# =============================================================================
# Function Prototypes
# =============================================================================

# Version info
_lib.airspy_lib_version.argtypes = [POINTER(AirspyLibVersion)]
_lib.airspy_lib_version.restype = None

# Device enumeration
_lib.airspy_list_devices.argtypes = [POINTER(c_uint64), c_int]
_lib.airspy_list_devices.restype = c_int

# Device open/close
_lib.airspy_open_sn.argtypes = [POINTER(POINTER(AirspyDevice_t)), c_uint64]
_lib.airspy_open_sn.restype = c_int

_lib.airspy_open.argtypes = [POINTER(POINTER(AirspyDevice_t))]
_lib.airspy_open.restype = c_int

_lib.airspy_close.argtypes = [POINTER(AirspyDevice_t)]
_lib.airspy_close.restype = c_int

# Streaming
_lib.airspy_start_rx.argtypes = [POINTER(AirspyDevice_t), AIRSPY_SAMPLE_CALLBACK, c_void_p]
_lib.airspy_start_rx.restype = c_int

_lib.airspy_stop_rx.argtypes = [POINTER(AirspyDevice_t)]
_lib.airspy_stop_rx.restype = c_int

_lib.airspy_is_streaming.argtypes = [POINTER(AirspyDevice_t)]
_lib.airspy_is_streaming.restype = c_int

# Sample rate
_lib.airspy_get_samplerates.argtypes = [POINTER(AirspyDevice_t), POINTER(c_uint32), c_uint32]
_lib.airspy_get_samplerates.restype = c_int

_lib.airspy_set_samplerate.argtypes = [POINTER(AirspyDevice_t), c_uint32]
_lib.airspy_set_samplerate.restype = c_int

# Sample type
_lib.airspy_set_sample_type.argtypes = [POINTER(AirspyDevice_t), c_int]
_lib.airspy_set_sample_type.restype = c_int

# Frequency
_lib.airspy_set_freq.argtypes = [POINTER(AirspyDevice_t), c_uint32]
_lib.airspy_set_freq.restype = c_int

# Gain controls
_lib.airspy_set_lna_gain.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_lna_gain.restype = c_int

_lib.airspy_set_mixer_gain.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_mixer_gain.restype = c_int

_lib.airspy_set_vga_gain.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_vga_gain.restype = c_int

_lib.airspy_set_lna_agc.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_lna_agc.restype = c_int

_lib.airspy_set_mixer_agc.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_mixer_agc.restype = c_int

_lib.airspy_set_linearity_gain.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_linearity_gain.restype = c_int

_lib.airspy_set_sensitivity_gain.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_sensitivity_gain.restype = c_int

# Bias-T
_lib.airspy_set_rf_bias.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_rf_bias.restype = c_int

# Packing
_lib.airspy_set_packing.argtypes = [POINTER(AirspyDevice_t), c_uint8]
_lib.airspy_set_packing.restype = c_int

# Device info
_lib.airspy_board_id_read.argtypes = [POINTER(AirspyDevice_t), POINTER(c_uint8)]
_lib.airspy_board_id_read.restype = c_int

_lib.airspy_board_partid_serialno_read.argtypes = [
    POINTER(AirspyDevice_t), POINTER(AirspyReadPartidSerialno)
]
_lib.airspy_board_partid_serialno_read.restype = c_int

_lib.airspy_version_string_read.argtypes = [POINTER(AirspyDevice_t), c_char_p, c_uint8]
_lib.airspy_version_string_read.restype = c_int

# Error handling
_lib.airspy_error_name.argtypes = [c_int]
_lib.airspy_error_name.restype = c_char_p

_lib.airspy_board_id_name.argtypes = [c_int]
_lib.airspy_board_id_name.restype = c_char_p


# =============================================================================
# Helper Functions
# =============================================================================

def get_lib_version() -> str:
    """Get libairspy version string."""
    ver = AirspyLibVersion()
    _lib.airspy_lib_version(byref(ver))
    return f"{ver.major_version}.{ver.minor_version}.{ver.revision}"


def error_name(code: int) -> str:
    """Get error name for code."""
    name = _lib.airspy_error_name(code)
    return name.decode() if name else f"UNKNOWN({code})"


def _check_error(result: int, operation: str = ""):
    """Check result code and raise exception if error."""
    if result != AirspyError.SUCCESS and result != AirspyError.TRUE:
        raise AirspyException(result, operation)


class AirspyException(Exception):
    """Exception raised for Airspy errors."""

    def __init__(self, code: int, operation: str = ""):
        self.code = code
        self.operation = operation
        msg = f"Airspy error: {error_name(code)} ({code})"
        if operation:
            msg = f"{operation}: {msg}"
        super().__init__(msg)


# =============================================================================
# Main Device Class
# =============================================================================

class AirspyDevice:
    """
    Direct libairspy device wrapper.

    This bypasses SoapySDR and SWIG entirely, accessing the C library
    directly via ctypes.

    Example:
        with AirspyDevice() as dev:
            dev.set_sample_rate(2_500_000)
            dev.set_frequency(162_550_000)
            dev.set_linearity_gain(15)

            # Blocking read
            samples = dev.read_samples(65536)

            # Or streaming with callback
            def callback(iq_samples):
                process(iq_samples)
            dev.start_streaming(callback)
    """

    def __init__(self, serial: Optional[int] = None):
        """
        Open Airspy device.

        Args:
            serial: Device serial number (64-bit). If None, opens first device.
        """
        self._handle = POINTER(AirspyDevice_t)()
        self._serial = serial
        self._streaming = False
        self._callback = None
        self._callback_ref = None  # prevent GC
        self._sample_type = AirspySampleType.FLOAT32_IQ
        self._sample_rate = 2_500_000
        self._buffer_lock = threading.Lock()
        self._sample_buffer = []
        self._max_buffer_samples = 1_000_000  # ~400ms at 2.5MHz

        # Open device
        if serial is not None:
            result = _lib.airspy_open_sn(byref(self._handle), c_uint64(serial))
            _check_error(result, f"airspy_open_sn({serial:016x})")
        else:
            result = _lib.airspy_open(byref(self._handle))
            _check_error(result, "airspy_open")

        logger.info(f"Opened Airspy device (libairspy {get_lib_version()})")

        # Set default sample type to float32 IQ
        self.set_sample_type(AirspySampleType.FLOAT32_IQ)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """Close the device."""
        if self._handle:
            if self._streaming:
                self.stop_streaming()
            _lib.airspy_close(self._handle)
            self._handle = None
            logger.info("Closed Airspy device")

    @staticmethod
    def list_devices() -> List[int]:
        """
        List connected Airspy devices by serial number.

        Returns:
            List of 64-bit serial numbers
        """
        # First call to get count
        count = _lib.airspy_list_devices(None, 0)
        if count <= 0:
            return []

        # Second call to get serials
        serials = (c_uint64 * count)()
        result = _lib.airspy_list_devices(serials, count)
        if result < 0:
            return []

        return [serials[i] for i in range(result)]

    def get_serial(self) -> str:
        """Get device serial number as hex string."""
        info = AirspyReadPartidSerialno()
        result = _lib.airspy_board_partid_serialno_read(self._handle, byref(info))
        _check_error(result, "board_partid_serialno_read")

        # Combine 4x32-bit serial parts into hex string
        serial_hex = "".join(f"{info.serial_no[i]:08x}" for i in range(4))
        return serial_hex

    def get_firmware_version(self) -> str:
        """Get device firmware version."""
        buf = ctypes.create_string_buffer(64)
        result = _lib.airspy_version_string_read(self._handle, buf, 64)
        _check_error(result, "version_string_read")
        return buf.value.decode()

    def get_board_id(self) -> str:
        """Get board ID name."""
        board_id = c_uint8()
        result = _lib.airspy_board_id_read(self._handle, byref(board_id))
        _check_error(result, "board_id_read")
        name = _lib.airspy_board_id_name(board_id.value)
        return name.decode() if name else f"UNKNOWN({board_id.value})"

    def get_sample_rates(self) -> List[int]:
        """Get supported sample rates."""
        # Get count first
        count = c_uint32()
        result = _lib.airspy_get_samplerates(self._handle, byref(count), 0)
        _check_error(result, "get_samplerates(count)")

        # Get actual rates
        rates = (c_uint32 * count.value)()
        result = _lib.airspy_get_samplerates(self._handle, rates, count.value)
        _check_error(result, "get_samplerates")

        return [rates[i] for i in range(count.value)]

    def set_sample_rate(self, rate: int):
        """Set sample rate in Hz."""
        result = _lib.airspy_set_samplerate(self._handle, c_uint32(rate))
        _check_error(result, f"set_samplerate({rate})")
        self._sample_rate = rate
        logger.debug(f"Set sample rate: {rate/1e6:.1f} MHz")

    def set_sample_type(self, sample_type: AirspySampleType):
        """Set sample output type."""
        result = _lib.airspy_set_sample_type(self._handle, int(sample_type))
        _check_error(result, f"set_sample_type({sample_type.name})")
        self._sample_type = sample_type

    def set_frequency(self, freq_hz: int):
        """Set center frequency in Hz."""
        result = _lib.airspy_set_freq(self._handle, c_uint32(freq_hz))
        _check_error(result, f"set_freq({freq_hz})")
        logger.debug(f"Set frequency: {freq_hz/1e6:.3f} MHz")

    def set_lna_gain(self, gain: int):
        """Set LNA gain (0-15)."""
        result = _lib.airspy_set_lna_gain(self._handle, c_uint8(gain))
        _check_error(result, f"set_lna_gain({gain})")

    def set_mixer_gain(self, gain: int):
        """Set mixer gain (0-15)."""
        result = _lib.airspy_set_mixer_gain(self._handle, c_uint8(gain))
        _check_error(result, f"set_mixer_gain({gain})")

    def set_vga_gain(self, gain: int):
        """Set VGA gain (0-15)."""
        result = _lib.airspy_set_vga_gain(self._handle, c_uint8(gain))
        _check_error(result, f"set_vga_gain({gain})")

    def set_linearity_gain(self, gain: int):
        """Set linearity-optimized gain (0-21)."""
        result = _lib.airspy_set_linearity_gain(self._handle, c_uint8(gain))
        _check_error(result, f"set_linearity_gain({gain})")

    def set_sensitivity_gain(self, gain: int):
        """Set sensitivity-optimized gain (0-21)."""
        result = _lib.airspy_set_sensitivity_gain(self._handle, c_uint8(gain))
        _check_error(result, f"set_sensitivity_gain({gain})")

    def set_lna_agc(self, enable: bool):
        """Enable/disable LNA AGC."""
        result = _lib.airspy_set_lna_agc(self._handle, c_uint8(1 if enable else 0))
        _check_error(result, f"set_lna_agc({enable})")

    def set_mixer_agc(self, enable: bool):
        """Enable/disable mixer AGC."""
        result = _lib.airspy_set_mixer_agc(self._handle, c_uint8(1 if enable else 0))
        _check_error(result, f"set_mixer_agc({enable})")

    def set_rf_bias(self, enable: bool):
        """Enable/disable bias-T power."""
        result = _lib.airspy_set_rf_bias(self._handle, c_uint8(1 if enable else 0))
        _check_error(result, f"set_rf_bias({enable})")

    def set_packing(self, enable: bool):
        """Enable/disable sample packing."""
        result = _lib.airspy_set_packing(self._handle, c_uint8(1 if enable else 0))
        _check_error(result, f"set_packing({enable})")

    def is_streaming(self) -> bool:
        """Check if device is currently streaming."""
        return _lib.airspy_is_streaming(self._handle) == AirspyError.TRUE

    def _internal_callback(self, transfer_ptr: POINTER(AirspyTransfer)) -> int:
        """Internal callback that receives samples from libairspy."""
        try:
            transfer = transfer_ptr.contents
            sample_count = transfer.sample_count

            if sample_count <= 0:
                return 0

            # Convert samples based on type
            if self._sample_type == AirspySampleType.FLOAT32_IQ:
                # Float32 IQ: 2 floats per sample
                arr = np.ctypeslib.as_array(
                    ctypes.cast(transfer.samples, POINTER(c_float)),
                    shape=(sample_count * 2,)
                ).copy()
                # Convert interleaved to complex
                samples = arr[0::2] + 1j * arr[1::2]
            elif self._sample_type == AirspySampleType.INT16_IQ:
                # Int16 IQ: 2 int16 per sample
                arr = np.ctypeslib.as_array(
                    ctypes.cast(transfer.samples, POINTER(c_int16)),
                    shape=(sample_count * 2,)
                ).copy()
                # Convert to float complex, normalized
                samples = (arr[0::2].astype(np.float32) + 1j * arr[1::2].astype(np.float32)) / 32768.0
            else:
                # For other types, just copy raw
                logger.warning(f"Unsupported sample type: {self._sample_type}")
                return 0

            # Store in buffer
            with self._buffer_lock:
                self._sample_buffer.append(samples)
                # Trim buffer if too large
                total = sum(len(s) for s in self._sample_buffer)
                while total > self._max_buffer_samples and len(self._sample_buffer) > 1:
                    removed = self._sample_buffer.pop(0)
                    total -= len(removed)

            # Call user callback if set
            if self._callback:
                try:
                    self._callback(samples)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

            return 0  # Continue streaming

        except Exception as e:
            logger.error(f"Internal callback error: {e}")
            return -1  # Stop streaming

    def start_streaming(self, callback: Optional[Callable[[np.ndarray], None]] = None):
        """
        Start async sample streaming.

        Args:
            callback: Optional function called with each sample block (complex64 array)
        """
        if self._streaming:
            return

        self._callback = callback
        self._callback_ref = AIRSPY_SAMPLE_CALLBACK(self._internal_callback)

        result = _lib.airspy_start_rx(self._handle, self._callback_ref, None)
        _check_error(result, "start_rx")

        self._streaming = True
        logger.info("Started Airspy streaming")

    def stop_streaming(self):
        """Stop sample streaming."""
        if not self._streaming:
            return

        result = _lib.airspy_stop_rx(self._handle)
        _check_error(result, "stop_rx")

        self._streaming = False
        self._callback = None
        logger.info("Stopped Airspy streaming")

    def read_samples(self, num_samples: int, timeout: float = 1.0) -> Optional[np.ndarray]:
        """
        Read samples from buffer (blocking).

        Starts streaming if not already running.

        Args:
            num_samples: Number of complex samples to read
            timeout: Maximum time to wait in seconds

        Returns:
            Complex64 numpy array or None if timeout
        """
        if not self._streaming:
            self.start_streaming()

        start = time.time()
        while time.time() - start < timeout:
            with self._buffer_lock:
                total = sum(len(s) for s in self._sample_buffer)
                if total >= num_samples:
                    # Concatenate and return requested samples
                    combined = np.concatenate(self._sample_buffer)
                    result = combined[:num_samples]
                    # Keep remainder
                    if len(combined) > num_samples:
                        self._sample_buffer = [combined[num_samples:]]
                    else:
                        self._sample_buffer = []
                    return result.astype(np.complex64)
            time.sleep(0.001)

        return None

    def get_samples(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Non-blocking sample read from buffer.

        Args:
            num_samples: Number of samples to read

        Returns:
            Available samples (may be less than requested) or None
        """
        with self._buffer_lock:
            if not self._sample_buffer:
                return None
            combined = np.concatenate(self._sample_buffer)
            if len(combined) == 0:
                return None
            result = combined[:num_samples]
            # Keep remainder
            if len(combined) > num_samples:
                self._sample_buffer = [combined[num_samples:]]
            else:
                self._sample_buffer = []
            return result.astype(np.complex64)


# =============================================================================
# Convenience Functions
# =============================================================================

def enumerate_airspy_devices() -> List[dict]:
    """
    Enumerate connected Airspy devices.

    Returns:
        List of dicts with 'serial' (hex string) and 'driver' keys
    """
    serials = AirspyDevice.list_devices()
    devices = []
    for serial in serials:
        devices.append({
            'driver': 'airspy',
            'serial': f"{serial:016x}",
            'label': f"Airspy [{serial:016x}]",
        })
    return devices


def open_airspy(serial: Optional[str] = None) -> AirspyDevice:
    """
    Open Airspy device.

    Args:
        serial: Hex serial string (optional)

    Returns:
        AirspyDevice instance
    """
    if serial:
        serial_int = int(serial, 16)
        return AirspyDevice(serial=serial_int)
    return AirspyDevice()
