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

"""GPS receiver manager for UART NMEA-0183 GPS HATs.

Reads NMEA-0183 sentences from the serial port, parses position and time
data, and publishes it to Redis for consumption by the web UI and other
services.

Hardware (supported by default; any NMEA-0183 UART GPS module will work):
- Uputronics Raspberry Pi GPS/RTC Expansion Board (u-blox MAX-M8Q,
  multi-GNSS GPS+GLONASS+Galileo+BeiDou, PPS on BCM 18, DS3231 RTC)
- Adafruit Ultimate GPS HAT for Raspberry Pi (#2324, MTK3339 GPS,
  PPS on BCM 4)
- UART interface: /dev/serial0 (BCM UART), 9600 baud
- PPS output: configurable GPIO BCM pin (default 18 for Uputronics)

Dependencies:
- pyserial: Serial port I/O
- pynmea2: NMEA-0183 sentence parser
- RPi.GPIO (optional): PPS pulse reading on systems without the
  ``pps-gpio`` kernel overlay. When the overlay is loaded
  (``dtoverlay=pps-gpio,gpiopin=N``) the manager prefers the kernel's
  ``/sys/class/pps/ppsX`` interface, since the overlay claims the GPIO
  exclusively and userspace cannot attach an edge interrupt to it.
"""

import ctypes
import ctypes.util
import json
import logging
import os
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Set

# ---------------------------------------------------------------------------
# clock_settime(2) helpers — used by _apply_system_time to set CLOCK_REALTIME
# directly without sudo.  The systemd unit grants CAP_SYS_TIME via
# AmbientCapabilities so the call succeeds under NoNewPrivileges=true.
# ---------------------------------------------------------------------------
_CLOCK_REALTIME = 0


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)

# Redis key used for GPS status storage
REDIS_KEY = "gps:status"
# TTL in seconds for the Redis key (refreshed every poll cycle)
REDIS_TTL = 15

# NMEA fix quality codes
_FIX_QUALITY = {
    0: "no_fix",
    1: "gps_fix",
    2: "dgps_fix",
    3: "pps_fix",
    4: "rtk_fix",
    5: "float_rtk",
    6: "estimated",
    7: "manual",
    8: "simulation",
}


def _safe_int(val) -> Optional[int]:
    """Convert a value to int, returning None for empty/None/invalid values."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


# How often (seconds) to update the system clock from GPS when use_for_time=True.
_TIME_SYNC_INTERVAL_S: int = 3600


# gpsd's gnssid → NMEA-style talker IDs. The UI groups satellites by
# talker (GP/GL/GA/GB) and we want gpsd-mode output to look the same as
# direct-NMEA mode, so we translate up front. Anything we don't recognise
# is reported as the unknown talker so the UI can render it generically.
_GPSD_GNSSID_TO_TALKER = {
    0: "GP",  # GPS
    1: "SB",  # SBAS — UI doesn't filter on this today, but it's correct
    2: "GA",  # Galileo
    3: "GB",  # BeiDou
    4: "IM",  # IMES
    5: "GQ",  # QZSS
    6: "GL",  # GLONASS
    7: "GI",  # NavIC / IRNSS
}


def _gpsd_gnssid_to_talker(gnssid: Any) -> str:
    if isinstance(gnssid, int):
        return _GPSD_GNSSID_TO_TALKER.get(gnssid, "GN")
    return "GN"


class GPSManager:
    """Background thread that reads NMEA sentences from a GPS serial port
    and publishes position/time data to Redis.

    Args:
        config: GPS configuration dict (from get_gps_settings())
        redis_client: Redis client instance (may be None for no-op mode)
        logger: Optional logger; defaults to module logger
    """

    def __init__(
        self,
        config: Dict[str, Any],
        redis_client=None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._config = config
        self._redis = redis_client
        self._logger = logger or logging.getLogger(__name__)

        self._serial_port: str = config.get("serial_port", "/dev/serial0")
        self._baudrate: int = int(config.get("baudrate", 9600))
        self._pps_pin: int = int(config.get("pps_gpio_pin", 4))
        self._min_satellites: int = int(config.get("min_satellites", 4))

        self._use_for_time: bool = bool(config.get("use_for_time", False))

        # NMEA source selection. One of:
        #   "serial" — open the configured /dev/serial0 directly (legacy /
        #              fallback when gpsd isn't running). What this manager
        #              has always done.
        #   "gpsd"   — connect to gpsd's TCP socket on localhost:2947 and
        #              consume its JSON event stream. Lets chrony share the
        #              GPS for stratum-1 PPS time without port contention.
        #   "auto"   — prefer gpsd when reachable; fall back to serial.
        # Anything unrecognised collapses to "auto" so a stale config row
        # cannot brick the manager.
        raw_source = str(config.get("gps_source", "auto") or "auto").lower()
        self._source: str = raw_source if raw_source in ("serial", "gpsd", "auto") else "auto"
        self._gpsd_host: str = str(config.get("gpsd_host", "127.0.0.1") or "127.0.0.1")
        self._gpsd_port: int = int(config.get("gpsd_port", 2947) or 2947)
        # Set by start() once we know which backend actually started; the
        # diagnostic code surfaces this so operators can see whether a
        # fallback fired.
        self._active_source: str = "stopped"

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ser = None  # serial.Serial instance
        self._gpsd_sock = None  # socket.socket when source=="gpsd"

        # Most-recently parsed fix data (protected by _lock)
        self._lock = threading.Lock()
        self._fix: Dict[str, Any] = self._empty_fix()

        # GSV accumulation buffers, one bucket per talker (GP, GL, GA, GB, …).
        # Multi-GNSS receivers emit one GSV group per constellation; if we
        # shared a single buffer, the start of GLGSV (msg_num==1) would wipe
        # the GPGSV satellites we just accumulated, leaving the published
        # satellites_in_view empty — reader thread only, no lock needed.
        self._gsv_buffer: Dict[str, Dict[int, Dict[str, Any]]] = {}
        # GSA per-cycle accumulator. Multi-GNSS receivers emit one GSA per
        # constellation (e.g. $GPGSA, $GLGSA, $GAGSA, or several $GNGSA in a
        # row). We union active PRNs across all GSA sentences within a single
        # NMEA cycle so the "used" count reflects the full multi-constellation
        # solution. The accumulator is reset on the next GGA (which marks the
        # start of a new cycle) — reader thread only, no lock needed.
        self._gsa_accumulator: Set[int] = set()
        self._gsa_cycle_started: bool = False
        # PPS monitoring state. Two mutually-exclusive backends:
        #   * kernel: poll /sys/class/pps/ppsX/assert (preferred whenever
        #     the pps-gpio overlay is loaded — the overlay owns the pin
        #     and userspace edge interrupts on the same GPIO will not fire)
        #   * RPi.GPIO: rising-edge interrupt on the configured BCM pin
        #     (used only when no /sys/class/pps device is present)
        self._pps_gpio_active: bool = False
        self._pps_kernel_device: Optional[str] = None  # e.g. "/sys/class/pps/pps0"
        self._pps_kernel_baseline_seq: Optional[int] = None
        self._pps_kernel_thread: Optional[threading.Thread] = None

        # Recent raw NMEA sentences (protected by _lock).  Sized for ~20s of
        # traffic on a multi-GNSS receiver so the UI's filter/pause UX has
        # something to scroll through.
        self._recent_sentences: Deque[str] = deque(maxlen=100)

        # Time-sync state — reader thread only, no lock needed
        self._time_synced: bool = False
        self._ntp_disabled: bool = False
        self._last_time_sync_mono: float = 0.0
        # Set by _handle_sentence (under _lock), cleared and acted on by _reader_loop
        self._pending_time_sync: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Open the configured NMEA source (serial port or gpsd) and start
        the reader thread.

        Source selection follows ``self._source``:

        * ``"serial"`` — open ``self._serial_port`` directly. Legacy path.
        * ``"gpsd"``   — connect to ``gpsd_host:gpsd_port`` (default
          127.0.0.1:2947). Lets chrony share the GPS receiver.
        * ``"auto"``   — try gpsd first; fall back to serial if gpsd isn't
          reachable. Default for new installs.

        Returns:
            True if a source was opened, False otherwise.
        """
        if self._source == "gpsd":
            return self._start_gpsd_only()
        if self._source == "serial":
            return self._start_serial_only()
        # auto
        if self._start_gpsd_only(quiet=True):
            return True
        self._logger.info(
            "gpsd not reachable on %s:%d — falling back to direct serial read",
            self._gpsd_host, self._gpsd_port,
        )
        return self._start_serial_only()

    def _start_serial_only(self) -> bool:
        port_path = self._serial_port
        if not os.path.exists(port_path):
            self._logger.warning(
                "GPS serial port %s does not exist. "
                "Check hardware connection and settings.",
                port_path,
            )
            self._set_error_status("port_not_found")
            return False

        try:
            import serial  # pyserial

            self._ser = serial.Serial(
                port_path,
                baudrate=self._baudrate,
                timeout=2,
            )
        except ImportError:
            self._logger.warning(
                "pyserial not installed — GPS reader unavailable. "
                "Install with: pip install pyserial"
            )
            self._set_error_status("pyserial_missing")
            return False
        except Exception as exc:
            self._logger.warning("Cannot open GPS serial port %s: %s", port_path, exc)
            self._set_error_status("port_open_failed")
            return False

        self._active_source = "serial"
        self._running = True
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="gps-reader",
            daemon=True,
        )
        self._thread.start()
        self._start_pps_monitor()
        self._logger.info(
            "✅ GPS reader started on %s @ %d baud (PPS GPIO %d, source=serial)",
            port_path,
            self._baudrate,
            self._pps_pin,
        )
        return True

    def _start_gpsd_only(self, quiet: bool = False) -> bool:
        """Connect to gpsd, send WATCH, kick off the reader thread.

        ``quiet=True`` suppresses the warning log line on failure (used
        when ``source==auto`` and we're going to fall back to serial
        next — the failure isn't an error in that case).
        """
        sock = self._gpsd_connect(quiet=quiet)
        if sock is None:
            return False
        self._gpsd_sock = sock
        self._active_source = "gpsd"
        self._running = True
        self._thread = threading.Thread(
            target=self._gpsd_reader_loop,
            name="gps-reader-gpsd",
            daemon=True,
        )
        self._thread.start()
        # PPS monitor still works in gpsd mode — the kernel exposes
        # /sys/class/pps/pps0 regardless of who's reading the serial port.
        self._start_pps_monitor()
        self._logger.info(
            "✅ GPS reader started via gpsd at %s:%d (PPS GPIO %d, source=gpsd)",
            self._gpsd_host, self._gpsd_port, self._pps_pin,
        )
        return True

    def _gpsd_connect(self, *, quiet: bool = False) -> Optional[socket.socket]:
        """Open a TCP connection to gpsd, send WATCH, validate the greeting.

        Returns the socket on success, None on any failure. The greeting
        validation is intentionally cheap — we only check that gpsd
        responds with a JSON-shaped line within the connect timeout.
        """
        try:
            sock = socket.create_connection(
                (self._gpsd_host, self._gpsd_port),
                timeout=3.0,
            )
        except (OSError, socket.timeout) as exc:
            if not quiet:
                self._logger.warning(
                    "Cannot connect to gpsd at %s:%d: %s",
                    self._gpsd_host, self._gpsd_port, exc,
                )
            return None
        try:
            sock.settimeout(3.0)
            # Read gpsd's VERSION greeting before subscribing — proves we
            # really are talking to gpsd and not, say, a stray HTTP server.
            greeting = b""
            while b"\n" not in greeting:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                greeting += chunk
                if len(greeting) > 4096:
                    break
            if b'"class":"VERSION"' not in greeting:
                if not quiet:
                    self._logger.warning(
                        "gpsd at %s:%d did not send a VERSION greeting (got %r)",
                        self._gpsd_host, self._gpsd_port, greeting[:120],
                    )
                sock.close()
                return None
            # Subscribe to JSON event stream — `pps:true` asks gpsd to
            # forward kernel PPS samples too, but it's harmless if the
            # gpsd build is too old to support it.
            sock.sendall(b'?WATCH={"enable":true,"json":true,"pps":true}\n')
            # Use a long read timeout in the steady state; reconnect logic
            # in the loop handles dropped connections.
            sock.settimeout(15.0)
            return sock
        except (OSError, socket.timeout) as exc:
            if not quiet:
                self._logger.warning(
                    "gpsd handshake failed at %s:%d: %s",
                    self._gpsd_host, self._gpsd_port, exc,
                )
            try:
                sock.close()
            except OSError:
                pass
            return None

    def stop(self) -> None:
        """Stop the reader thread and close the serial port / gpsd socket."""
        self._running = False
        # Close the gpsd socket from the outside so the recv() in
        # _gpsd_reader_loop returns immediately. shutdown() is needed
        # because plain close() on a blocked recv() doesn't always wake
        # the thread on Linux.
        if self._gpsd_sock is not None:
            try:
                self._gpsd_sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._close_gpsd_socket()
        if self._pps_kernel_thread and self._pps_kernel_thread.is_alive():
            self._pps_kernel_thread.join(timeout=2)
        self._pps_kernel_thread = None
        self._pps_kernel_device = None
        if self._pps_gpio_active:
            try:
                import RPi.GPIO as GPIO  # type: ignore[import]
                GPIO.remove_event_detect(self._pps_pin)
            except Exception:
                pass
            self._pps_gpio_active = False
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        self._active_source = "stopped"
        self._logger.info("GPS reader stopped")

    def get_status(self) -> Dict[str, Any]:
        """Return the most-recently parsed GPS fix as a dictionary."""
        with self._lock:
            data = dict(self._fix)
            data["recent_sentences"] = list(self._recent_sentences)
        # Compute age of the last PPS pulse so the UI can colour the blinkenlite
        last_pulse = data.get("pps_last_pulse_at")
        if last_pulse:
            try:
                pulse_dt = datetime.fromisoformat(last_pulse)
                age = (datetime.now(timezone.utc) - pulse_dt).total_seconds()
                data["pps_pulse_age_s"] = round(age, 2)
            except Exception:
                data["pps_pulse_age_s"] = None
        else:
            data["pps_pulse_age_s"] = None
        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _empty_fix(self) -> Dict[str, Any]:
        return {
            "running": False,
            "has_fix": False,
            "fix_quality": "no_fix",
            "latitude": None,
            "longitude": None,
            "altitude_m": None,
            "speed_knots": None,
            "track_angle": None,
            "satellites": None,
            "hdop": None,
            "gps_utc_time": None,
            "last_sentence_at": None,
            "serial_port": self._serial_port,
            "baudrate": self._baudrate,
            "pps_gpio_pin": self._pps_pin,
            "status": "stopped",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Per-satellite view data (from GSV / GSA)
            "satellites_in_view": [],
            "active_satellite_prns": [],
            # GSA fix mode: 1=no fix, 2=2D, 3=3D (None until first GSA)
            "fix_mode": None,
            "pdop": None,
            "vdop": None,
            # PPS pulse tracking
            "pps_last_pulse_at": None,
            "pps_pulse_count": 0,
            # Time sync status
            "use_for_time": self._use_for_time,
            "time_synced": False,
            "ntp_disabled": False,
            # Diagnostics — extra fields parsed from GGA/RMC for the UI
            # diagnostics disclosure. Optional, may stay None on receivers
            # that don't emit them (e.g. no DGPS reference station).
            "geoid_separation_m": None,
            "magnetic_variation": None,
            "magnetic_variation_dir": None,
            "dgps_age_s": None,
            "dgps_station_id": None,
            # Per-type sentence counters (cumulative since manager start) so
            # the UI can derive arrival rates and surface "this receiver isn't
            # emitting GSA" type problems.
            "sentence_counts": {},
            "sentence_errors": 0,
            # Raw NMEA sentences (populated separately, not stored in _fix)
            "recent_sentences": [],
        }

    def _reader_loop(self) -> None:
        """Main NMEA reader loop — runs in background thread."""
        try:
            import pynmea2  # type: ignore[import]
        except ImportError:
            self._logger.warning(
                "pynmea2 not installed — GPS NMEA parsing unavailable. "
                "Install with: pip install pynmea2"
            )
            self._set_error_status("pynmea2_missing")
            return

        self._logger.info("GPS reader loop started")
        with self._lock:
            self._fix["running"] = True
            self._fix["status"] = "reading"

        consecutive_errors = 0

        while self._running:
            try:
                if not self._ser or not self._ser.is_open:
                    break

                raw = self._ser.readline()
                if not raw:
                    continue

                line = raw.decode("ascii", errors="replace").strip()
                if not line.startswith("$"):
                    continue

                # Store raw sentence for UI display
                with self._lock:
                    self._recent_sentences.append(line)

                consecutive_errors = 0

                try:
                    msg = pynmea2.parse(line)
                except pynmea2.ParseError:
                    # pynmea2 validates the NMEA checksum during parse; this
                    # branch is a useful health signal for noisy UART wiring.
                    with self._lock:
                        self._fix["sentence_errors"] = (
                            self._fix.get("sentence_errors", 0) + 1
                        )
                    continue

                self._handle_sentence(msg)

                # Apply system time if a sync was queued (outside lock)
                if self._pending_time_sync is not None:
                    pending = self._pending_time_sync
                    self._pending_time_sync = None
                    self._apply_system_time(pending)

            except Exception as exc:
                consecutive_errors += 1
                self._logger.debug("GPS read error (#%d): %s", consecutive_errors, exc)
                if consecutive_errors >= 10:
                    self._logger.warning(
                        "GPS reader: 10 consecutive errors, pausing 5s"
                    )
                    time.sleep(5)
                    consecutive_errors = 0

        with self._lock:
            self._fix["running"] = False
            self._fix["status"] = "stopped"
        self._publish_status("stopped")
        self._logger.info("GPS reader loop exited")

    def _handle_sentence(self, msg) -> None:
        """Update internal fix state from a parsed NMEA sentence."""
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            self._fix["last_sentence_at"] = now_iso
            self._fix["timestamp"] = now_iso

            sentence_type = msg.sentence_type

            # Per-type counter (cumulative); the UI computes arrival rates
            # from poll-to-poll deltas.
            counts = self._fix.get("sentence_counts") or {}
            counts[sentence_type] = counts.get(sentence_type, 0) + 1
            self._fix["sentence_counts"] = counts

            if sentence_type == "GGA":
                # GGA marks the start of a new NMEA cycle. The next GSA we see
                # will start a fresh accumulation; we keep the previously
                # published active_satellite_prns until that GSA arrives so
                # the UI doesn't briefly flicker to "0 used" on every cycle.
                self._gsa_cycle_started = False

                # Global Positioning System Fix Data
                fix_qual = int(msg.gps_qual) if msg.gps_qual else 0
                has_fix = fix_qual > 0
                num_sats = int(msg.num_sats) if msg.num_sats else 0

                self._fix["has_fix"] = has_fix
                self._fix["fix_quality"] = _FIX_QUALITY.get(fix_qual, "unknown")
                self._fix["satellites"] = num_sats
                if has_fix and num_sats >= self._min_satellites:
                    new_status = "fix"
                elif has_fix:
                    new_status = "acquiring"
                else:
                    # No fix yet — show "acquiring" when we already have satellites
                    # in view from the previous GSV cycle (typical NMEA order is
                    # GGA → GSA → GSV, so satellites_in_view reflects last cycle).
                    sats_tracked = len(self._fix.get("satellites_in_view", []))
                    new_status = "acquiring" if sats_tracked > 0 else "no_fix"
                self._fix["status"] = new_status

                if has_fix and msg.latitude and msg.longitude:
                    self._fix["latitude"] = msg.latitude
                    self._fix["longitude"] = msg.longitude

                if msg.altitude:
                    try:
                        self._fix["altitude_m"] = float(msg.altitude)
                    except (ValueError, TypeError):
                        pass

                if msg.horizontal_dil:
                    try:
                        self._fix["hdop"] = float(msg.horizontal_dil)
                    except (ValueError, TypeError):
                        pass

                if msg.timestamp:
                    self._fix["gps_utc_time"] = str(msg.timestamp)

                # Geoid separation (height of MSL above WGS-84 ellipsoid).
                # Useful for users converting our MSL-altitude to ellipsoid
                # height (or vice versa) without looking up a geoid model.
                geo_sep = getattr(msg, "geo_sep", None)
                if geo_sep not in (None, ""):
                    try:
                        self._fix["geoid_separation_m"] = float(geo_sep)
                    except (ValueError, TypeError):
                        pass

                # DGPS correction age and reference station ID — only emitted
                # when the receiver is using DGPS/SBAS corrections.
                dgps_age = getattr(msg, "age_gps_data", None)
                if dgps_age not in (None, ""):
                    try:
                        self._fix["dgps_age_s"] = float(dgps_age)
                    except (ValueError, TypeError):
                        pass
                ref_id = getattr(msg, "ref_station_id", None)
                if ref_id not in (None, ""):
                    self._fix["dgps_station_id"] = str(ref_id)

            elif sentence_type == "RMC":
                # Recommended Minimum Navigation Information
                if msg.status == "A":  # Active (valid fix)
                    if msg.latitude and msg.longitude:
                        self._fix["latitude"] = msg.latitude
                        self._fix["longitude"] = msg.longitude
                    if msg.spd_over_grnd:
                        try:
                            self._fix["speed_knots"] = float(msg.spd_over_grnd)
                        except (ValueError, TypeError):
                            pass
                    if msg.true_course:
                        try:
                            self._fix["track_angle"] = float(msg.true_course)
                        except (ValueError, TypeError):
                            pass
                    # Magnetic variation (degrees + E/W direction).
                    # Diagnostic-only — useful for users with a magnetic
                    # compass to derive true-vs-magnetic offset at the
                    # current location.
                    mag_var = getattr(msg, "mag_variation", None)
                    if mag_var not in (None, ""):
                        try:
                            self._fix["magnetic_variation"] = float(mag_var)
                        except (ValueError, TypeError):
                            pass
                    mag_var_dir = getattr(msg, "mag_var_dir", None)
                    if mag_var_dir not in (None, ""):
                        self._fix["magnetic_variation_dir"] = str(mag_var_dir)
                    if msg.datestamp and msg.timestamp:
                        try:
                            dt = datetime.combine(msg.datestamp, msg.timestamp)
                            self._fix["gps_utc_time"] = dt.isoformat() + "Z"
                            # Queue a system-clock sync if enabled and due
                            if self._use_for_time and self._pending_time_sync is None:
                                now_mono = time.monotonic()
                                if (
                                    not self._time_synced
                                    or (now_mono - self._last_time_sync_mono) >= _TIME_SYNC_INTERVAL_S
                                ):
                                    self._pending_time_sync = dt.replace(
                                        tzinfo=timezone.utc
                                    )
                        except Exception:
                            self._fix["gps_utc_time"] = str(msg.timestamp)

            elif sentence_type == "GSV":
                # Satellites in View — parse per-satellite PRN/elevation/azimuth/SNR.
                # Multi-GNSS receivers send one GSV group per constellation
                # (e.g. $GPGSV,3,1.. → 3,2 → 3,3 then $GLGSV,1,1..). We must
                # bucket per-talker so the start of one constellation's group
                # doesn't wipe another's — and union the buckets when
                # publishing so satellites_in_view reflects all visible sats.
                try:
                    talker = getattr(msg, "talker", None) or "GN"
                    total_msgs = int(msg.num_messages) if msg.num_messages else 1
                    msg_num = int(msg.msg_num) if msg.msg_num else 1
                    if msg_num == 1:
                        self._gsv_buffer[talker] = {}
                    bucket = self._gsv_buffer.setdefault(talker, {})
                    for i in range(1, 5):
                        prn_raw = getattr(msg, "sv_prn_num_%d" % i, None)
                        if not prn_raw:
                            break
                        try:
                            prn = int(prn_raw)
                        except (ValueError, TypeError):
                            continue
                        bucket[prn] = {
                            "prn": prn,
                            "constellation": talker,
                            "elevation": _safe_int(
                                getattr(msg, "elevation_deg_%d" % i, None)
                            ),
                            "azimuth": _safe_int(
                                getattr(msg, "azimuth_%d" % i, None)
                            ),
                            "snr": _safe_int(
                                getattr(msg, "snr_%d" % i, None)
                            ),
                        }
                    if msg_num >= total_msgs:
                        merged: Dict[int, Dict[str, Any]] = {}
                        for tbucket in self._gsv_buffer.values():
                            merged.update(tbucket)
                        self._fix["satellites_in_view"] = sorted(
                            merged.values(),
                            key=lambda s: s["prn"],
                        )
                except Exception:
                    pass

            elif sentence_type == "GSA":
                # GPS DOP and Active Satellites. Multi-GNSS receivers emit one
                # GSA per constellation per cycle, so we accumulate PRNs across
                # all GSAs in the current cycle (reset on each GGA) and publish
                # the union as active_satellite_prns. Without this, the last
                # GSA of the cycle silently overwrites the earlier ones — and
                # if it happens to carry no active sats (e.g. an empty GLGSA
                # with no GLONASS lock), the UI shows "0 used" even though
                # GPGSA reported 8+ active sats moments earlier.
                try:
                    this_gsa = []
                    for i in range(1, 13):
                        prn_raw = getattr(msg, "sv_id%02d" % i, None)
                        if prn_raw and str(prn_raw).strip():
                            try:
                                this_gsa.append(int(prn_raw))
                            except (ValueError, TypeError):
                                pass
                    if not self._gsa_cycle_started:
                        self._gsa_accumulator = set()
                        self._gsa_cycle_started = True
                    self._gsa_accumulator.update(this_gsa)
                    self._fix["active_satellite_prns"] = sorted(
                        self._gsa_accumulator
                    )
                    # Fix mode: 1=no fix, 2=2D, 3=3D
                    fix_mode_raw = getattr(msg, "mode_fix_type", None)
                    if fix_mode_raw is not None:
                        try:
                            self._fix["fix_mode"] = int(fix_mode_raw)
                        except (ValueError, TypeError):
                            pass
                    # Position dilution of precision
                    pdop_raw = getattr(msg, "pdop", None)
                    if pdop_raw:
                        try:
                            self._fix["pdop"] = float(pdop_raw)
                        except (ValueError, TypeError):
                            pass
                    vdop_raw = getattr(msg, "vdop", None)
                    if vdop_raw:
                        try:
                            self._fix["vdop"] = float(vdop_raw)
                        except (ValueError, TypeError):
                            pass
                except Exception:
                    pass

        # Publish to Redis after releasing lock
        self._publish_current_fix()

    def _publish_current_fix(self) -> None:
        """Write the current fix dict to Redis."""
        if not self._redis:
            return
        try:
            with self._lock:
                data = dict(self._fix)
                data["recent_sentences"] = list(self._recent_sentences)
            self._redis.setex(REDIS_KEY, REDIS_TTL, json.dumps(data))
        except Exception as exc:
            self._logger.debug("Failed to publish GPS status to Redis: %s", exc)

    # ------------------------------------------------------------------
    # gpsd reader path
    # ------------------------------------------------------------------
    #
    # Wire format: gpsd serves JSON-Lines over TCP. After we send
    # ``?WATCH={"enable":true,"json":true,"pps":true}`` it streams events
    # of the form documented at https://gpsd.gitlab.io/gpsd/gpsd_json.html
    # — primarily TPV (time/position/velocity), SKY (satellite snapshot),
    # and GST (error estimates), interleaved with periodic VERSION /
    # WATCH / DEVICES bookkeeping events we mostly ignore.
    #
    # We map gpsd events into the same _fix dict the serial reader
    # populates so the UI doesn't care which backend produced the data.
    # ------------------------------------------------------------------

    # gpsd's TPV.mode → fix_quality / has_fix mapping. Closer to NMEA
    # GGA quality codes than to gpsd's own enum so the UI rendering
    # logic (which already knows about "no_fix" / "gps_fix") doesn't
    # have to learn a new vocabulary.
    _GPSD_MODE_TO_QUALITY = {
        0: ("no_fix", False),    # MODE_NOT_SEEN
        1: ("no_fix", False),    # MODE_NO_FIX
        2: ("gps_fix", True),    # MODE_2D
        3: ("gps_fix", True),    # MODE_3D
    }

    def _gpsd_reader_loop(self) -> None:
        """Read JSON events from gpsd until shutdown, populating self._fix.

        Reconnects with exponential backoff on socket errors. The reader
        thread owns the socket exclusively; ``stop()`` closes it from the
        outside to break out of recv() promptly.
        """
        backoff = 1.0
        with self._lock:
            self._fix["status"] = "running"
            self._fix["running"] = True
            self._fix["source"] = "gpsd"
        self._publish_current_fix()

        buf = b""
        while self._running:
            sock = self._gpsd_sock
            if sock is None:
                # Initial connection lost; try to reopen.
                sock = self._gpsd_connect(quiet=True)
                if sock is None:
                    time.sleep(min(backoff, 30.0))
                    backoff = min(backoff * 2, 30.0)
                    continue
                self._gpsd_sock = sock
                backoff = 1.0
            try:
                chunk = sock.recv(8192)
            except socket.timeout:
                # Steady-state read timeout. gpsd sends events at ~1 Hz
                # when there's a fix and stays quiet otherwise. A 15s
                # silence isn't fatal — we just loop.
                continue
            except (OSError, ConnectionResetError) as exc:
                if not self._running:
                    break
                self._logger.warning("gpsd socket error: %s; reconnecting", exc)
                self._close_gpsd_socket()
                time.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if not chunk:
                # gpsd closed the connection. Reconnect.
                if not self._running:
                    break
                self._logger.info("gpsd closed the connection; reconnecting")
                self._close_gpsd_socket()
                time.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                if not line.strip():
                    continue
                self._record_recent_sentence(line.decode("utf-8", errors="replace"))
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._logger.debug("gpsd malformed JSON %r: %s", line[:120], exc)
                    with self._lock:
                        self._fix["sentence_errors"] = self._fix.get("sentence_errors", 0) + 1
                    continue
                self._handle_gpsd_message(obj)
            self._publish_current_fix()

        # Clean shutdown
        self._close_gpsd_socket()
        with self._lock:
            self._fix["status"] = "stopped"
            self._fix["running"] = False
        self._publish_current_fix()

    def _record_recent_sentence(self, line: str) -> None:
        """Append a raw line to the rolling buffer the UI shows. Threadsafe."""
        with self._lock:
            self._recent_sentences.append(line.strip())

    def _close_gpsd_socket(self) -> None:
        sock = self._gpsd_sock
        self._gpsd_sock = None
        if sock is None:
            return
        try:
            sock.close()
        except OSError:
            pass

    def _handle_gpsd_message(self, obj: Dict[str, Any]) -> None:
        """Dispatch one JSON event from gpsd into the _fix dict."""
        cls = obj.get("class")
        if not isinstance(cls, str):
            return
        # Track per-class arrival counts so the UI can spot a receiver
        # that's emitting GGA but no SKY (and vice versa).
        with self._lock:
            counts = self._fix.setdefault("sentence_counts", {})
            counts[cls] = counts.get(cls, 0) + 1
            self._fix["last_sentence_at"] = datetime.now(timezone.utc).isoformat()

        if cls == "TPV":
            self._handle_gpsd_tpv(obj)
        elif cls == "SKY":
            self._handle_gpsd_sky(obj)
        elif cls == "GST":
            self._handle_gpsd_gst(obj)
        elif cls == "PPS":
            # gpsd's PPS event carries a real_sec/real_nsec stamp — the
            # kernel-PPS poller in _start_pps_monitor handles the
            # pulse-count UI signal already, so we just use this as a
            # liveness hint.
            with self._lock:
                self._fix["pps_last_pulse_at"] = datetime.now(timezone.utc).isoformat()
        # VERSION / DEVICES / WATCH events arrive once at handshake time
        # and after device hot-plugs; we already updated the counter
        # above so we drop them on the floor.

    def _handle_gpsd_tpv(self, obj: Dict[str, Any]) -> None:
        mode = obj.get("mode")
        quality, has_fix = self._GPSD_MODE_TO_QUALITY.get(
            mode if isinstance(mode, int) else 0, ("no_fix", False),
        )
        # gpsd `speed` is metres-per-second; the existing UI expects knots.
        speed_mps = obj.get("speed")
        speed_knots = (
            round(float(speed_mps) * 1.943844, 3)
            if isinstance(speed_mps, (int, float)) else None
        )
        # gpsd reports altitude as `altMSL` (mean sea level — what users
        # actually want) on modern releases, but older releases only have
        # `alt` (which is HAE on some receivers). Prefer altMSL.
        alt = obj.get("altMSL")
        if alt is None:
            alt = obj.get("alt")
        with self._lock:
            self._fix["fix_quality"] = quality
            self._fix["has_fix"] = has_fix
            self._fix["fix_mode"] = mode if mode in (1, 2, 3) else None
            if isinstance(obj.get("lat"), (int, float)):
                self._fix["latitude"] = float(obj["lat"])
            if isinstance(obj.get("lon"), (int, float)):
                self._fix["longitude"] = float(obj["lon"])
            if isinstance(alt, (int, float)):
                self._fix["altitude_m"] = float(alt)
            if speed_knots is not None:
                self._fix["speed_knots"] = speed_knots
            if isinstance(obj.get("track"), (int, float)):
                self._fix["track_angle"] = float(obj["track"])
            t = obj.get("time")
            if isinstance(t, str):
                self._fix["gps_utc_time"] = t
                # In gpsd mode, the gps_manager does NOT call clock_settime
                # itself — chrony reads gpsd's SHM segments + /dev/pps0 and
                # is the sole authority for the system clock. The TIME pill
                # in the UI reads this flag, though, so flip it on once
                # gpsd is delivering us GPS-derived time. The actual
                # system-clock discipline is happening one layer down via
                # chrony's refclock SHM + refclock PPS, which is what makes
                # this strictly more accurate than the serial-mode direct
                # clock_settime path it replaces.
                if has_fix:
                    self._fix["time_synced"] = True
            # Optional error-estimate passthrough for the diagnostics
            # disclosure the UI surfaces under the GPS card.
            for src, dst in (("epx", "epx_m"), ("epy", "epy_m"), ("epv", "epv_m")):
                v = obj.get(src)
                if isinstance(v, (int, float)):
                    self._fix[dst] = float(v)

    def _handle_gpsd_sky(self, obj: Dict[str, Any]) -> None:
        sats = obj.get("satellites")
        if not isinstance(sats, list):
            return
        in_view: List[Dict[str, Any]] = []
        used_prns: List[int] = []
        for s in sats:
            if not isinstance(s, dict):
                continue
            prn = s.get("PRN")
            if not isinstance(prn, int):
                continue
            entry = {
                "prn": prn,
                "elevation": s.get("el") if isinstance(s.get("el"), (int, float)) else None,
                "azimuth":   s.get("az") if isinstance(s.get("az"), (int, float)) else None,
                "snr":       s.get("ss") if isinstance(s.get("ss"), (int, float)) else None,
                "used":      bool(s.get("used")),
                # Map gpsd's gnssid (0=GPS, 1=SBAS, 2=Galileo, 3=BeiDou,
                # 5=QZSS, 6=GLONASS) to the NMEA talker-id strings the UI
                # already groups by. The direct-NMEA path emits this same
                # field as "constellation"; using the same key here is what
                # lets the sky-plot and satellite table colour-code by
                # constellation in gpsd mode (otherwise every sat falls
                # back to neutral grey because sat.constellation is
                # undefined).
                "constellation": _gpsd_gnssid_to_talker(s.get("gnssid")),
            }
            in_view.append(entry)
            if entry["used"]:
                used_prns.append(prn)
        with self._lock:
            self._fix["satellites_in_view"] = in_view
            self._fix["active_satellite_prns"] = used_prns
            self._fix["satellites"] = len(used_prns)
            for src, dst in (("hdop", "hdop"), ("vdop", "vdop"), ("pdop", "pdop")):
                v = obj.get(src)
                if isinstance(v, (int, float)):
                    self._fix[dst] = float(v)

    def _handle_gpsd_gst(self, obj: Dict[str, Any]) -> None:
        # GST carries 1-sigma error estimates in metres along principal
        # axes. We forward the diagonal terms so the diagnostics block
        # can surface them next to HDOP/VDOP.
        with self._lock:
            for src, dst in (
                ("major", "gst_major_m"),
                ("minor", "gst_minor_m"),
                ("orient", "gst_orient_deg"),
                ("alt", "gst_alt_m"),
                ("lat", "gst_lat_m"),
                ("lon", "gst_lon_m"),
            ):
                v = obj.get(src)
                if isinstance(v, (int, float)):
                    self._fix[dst] = float(v)

    def _start_pps_monitor(self) -> None:
        """Begin counting PPS pulses, preferring the kernel pps-gpio device.

        Order of attempts:

        1. ``/sys/class/pps/pps0`` (or the first ``ppsN`` whose source is
           ``pps-gpio``). This is what ``dtoverlay=pps-gpio,gpiopin=N``
           creates, and is also what chrony's ``refclock PPS`` consumes.
        2. RPi.GPIO rising-edge interrupt on ``self._pps_pin``.

        We prefer (1) because the pps-gpio kernel driver claims the GPIO
        exclusively. RPi.GPIO can still register an event handler against
        it, but the rising edges have already been consumed by the kernel
        IRQ, so the callback never fires and ``pps_pulse_count`` stays at
        zero — which is what manifests in the UI as a dim PPS indicator
        despite ``ppstest /dev/pps0`` showing healthy pulses.

        Both backends are silent no-ops when the relevant facility is
        unavailable (development host, missing module, etc.).
        """
        if not self._pps_pin:
            return

        device = self._find_kernel_pps_device()
        if device:
            self._start_pps_kernel_monitor(device)
            return

        self._start_pps_gpio_monitor()

    def _find_kernel_pps_device(self) -> Optional[str]:
        """Return the sysfs path of a pps-gpio device, or None.

        Discriminator: pps-gpio is a platform device whose ``device``
        symlink resolves to ``/sys/devices/platform/pps@N`` (or similar).
        gpsd's line-discipline PPS devices instead point at a tty
        (e.g. ``…/tty/ttyAMA0``). We pick the first entry that is not a
        tty-backed pps device — counting line-discipline pulses would
        double up with the GPIO source.
        """
        try:
            base = Path("/sys/class/pps")
            if not base.exists():
                return None
            for entry in sorted(base.iterdir()):
                if not entry.name.startswith("pps"):
                    continue
                device_link = entry / "device"
                try:
                    target = os.fspath(device_link.resolve())
                except Exception:
                    target = ""
                # Line-discipline PPS resolves under /sys/.../tty/ttyXXX —
                # skip those. Anything else (platform/pps@N, of/...) is the
                # pps-gpio overlay we want.
                if "/tty/" in target or "/tty" in Path(target).name:
                    continue
                # Confirm we can at least read the assert attribute. If it
                # never existed (e.g. driver bound but never enabled) we
                # don't want to claim kernel-mode.
                if not (entry / "assert").exists():
                    continue
                return str(entry)
            return None
        except Exception as exc:
            self._logger.debug("Failed to scan /sys/class/pps: %s", exc)
            return None

    @staticmethod
    def _safe_read(path: Path) -> Optional[str]:
        try:
            return path.read_text().strip()
        except Exception:
            return None

    def _start_pps_kernel_monitor(self, device: str) -> None:
        """Spawn a low-rate poller of ``<device>/assert`` and update the fix."""
        # Capture the current sequence so pps_pulse_count reflects pulses
        # observed since this manager started, matching the existing
        # RPi.GPIO semantic.
        seq, _ts = self._read_pps_assert(device) or (None, None)
        self._pps_kernel_baseline_seq = seq if seq is not None else 0
        self._pps_kernel_device = device

        thread = threading.Thread(
            target=self._pps_kernel_loop,
            name="gps-pps-kernel",
            daemon=True,
        )
        self._pps_kernel_thread = thread
        thread.start()
        self._logger.info(
            "PPS blinkenlite armed via kernel device %s (baseline seq=%s)",
            device,
            self._pps_kernel_baseline_seq,
        )

    def _read_pps_assert(self, device: str) -> Optional[tuple]:
        """Parse ``<device>/assert`` and return ``(sequence, timestamp_iso)``.

        The kernel exports the line as ``<seconds>.<nanoseconds>#<sequence>``
        (see ``Documentation/ABI/testing/sysfs-pps``). Returns ``None`` if
        the file is missing or the sequence is zero (no pulse yet seen).
        """
        try:
            raw = self._safe_read(Path(device) / "assert")
            if not raw or "#" not in raw:
                return None
            ts_part, _, seq_part = raw.partition("#")
            seq = int(seq_part.strip())
            if seq <= 0:
                return None
            secs_str, _, ns_str = ts_part.partition(".")
            secs = int(secs_str)
            ns = int(ns_str.ljust(9, "0")[:9]) if ns_str else 0
            ts = datetime.fromtimestamp(secs + ns / 1e9, tz=timezone.utc)
            return seq, ts.isoformat()
        except Exception as exc:
            self._logger.debug("Failed to parse %s/assert: %s", device, exc)
            return None

    def _pps_kernel_loop(self) -> None:
        """Poll the kernel PPS device once a second while the manager runs."""
        last_seq: Optional[int] = self._pps_kernel_baseline_seq
        device = self._pps_kernel_device or ""
        while self._running and device:
            try:
                result = self._read_pps_assert(device)
                if result is not None:
                    seq, ts_iso = result
                    if last_seq is None or seq != last_seq:
                        baseline = self._pps_kernel_baseline_seq or 0
                        count = max(0, seq - baseline)
                        with self._lock:
                            self._fix["pps_last_pulse_at"] = ts_iso
                            self._fix["pps_pulse_count"] = count
                        last_seq = seq
            except Exception as exc:
                self._logger.debug("PPS kernel poll error: %s", exc)
            time.sleep(1.0)

    def _start_pps_gpio_monitor(self) -> None:
        """Set up an RPi.GPIO rising-edge interrupt to detect PPS pulses.

        Silently no-ops if RPi.GPIO is unavailable (e.g. development host)
        or if the GPIO pin cannot be configured. Used as a fallback when
        the pps-gpio kernel overlay is not loaded.
        """
        try:
            import RPi.GPIO as GPIO  # type: ignore[import]

            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pps_pin, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
            GPIO.add_event_detect(
                self._pps_pin,
                GPIO.RISING,
                callback=self._pps_pulse_callback,
            )
            self._pps_gpio_active = True
            self._logger.info(
                "PPS blinkenlite armed on GPIO BCM %d", self._pps_pin
            )
        except ImportError:
            self._logger.debug(
                "RPi.GPIO not available — PPS blinkenlite disabled"
            )
        except Exception as exc:
            self._logger.debug(
                "PPS GPIO setup failed on BCM %d: %s", self._pps_pin, exc
            )

    def _pps_pulse_callback(self, channel: int) -> None:
        """Called by the RPi.GPIO interrupt thread on each PPS rising edge."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._fix["pps_last_pulse_at"] = now
            self._fix["pps_pulse_count"] = self._fix.get("pps_pulse_count", 0) + 1

    def _apply_system_time(self, dt_utc: datetime) -> None:
        """Set the system clock to the GPS-provided UTC time.

        Called from the reader thread (outside any lock).  Only executed when
        ``use_for_time`` is True and the throttle has elapsed.

        Uses clock_settime(CLOCK_REALTIME) directly via ctypes so that the
        service does not need to fork sudo.  The systemd unit grants
        CAP_SYS_TIME via AmbientCapabilities which is preserved under
        NoNewPrivileges=true; no setuid escalation is required.

        When a PPS signal is active, NTP synchronisation (systemd-timesyncd or
        chrony) is disabled first so the kernel's NTP discipline does not
        immediately override the GPS-derived time.  NTP is only disabled once
        per manager lifetime to avoid churning the service state.
        """
        # Disable NTP the first time we have a PPS-backed sync so it does not
        # fight with the GPS clock.
        pps_active = self._fix.get("pps_pulse_count", 0) > 0
        if pps_active and not self._ntp_disabled:
            self._disable_ntp()

        try:
            ts = _Timespec(int(dt_utc.timestamp()), 0)
            ret = _libc.clock_settime(_CLOCK_REALTIME, ctypes.byref(ts))
            if ret != 0:
                errno = ctypes.get_errno()
                raise OSError(errno, os.strerror(errno))

            time_str = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
            self._time_synced = True
            self._last_time_sync_mono = time.monotonic()
            with self._lock:
                self._fix["time_synced"] = True
            self._logger.info("System time synced to GPS UTC: %s", time_str)
        except Exception as exc:
            self._logger.warning("GPS time sync error: %s", exc)

    def _disable_ntp(self) -> None:
        """Disable the system NTP client so GPS can own the clock.

        Calls the systemd D-Bus interface (org.freedesktop.timedate1.SetNTP)
        via ``busctl`` without sudo.  A polkit rule installed at
        /etc/polkit-1/rules.d/60-eas-station.rules grants the eas-station user
        permission to perform this action without authentication.

        Errors are logged but never propagated.
        """
        try:
            result = subprocess.run(
                [
                    "busctl", "call",
                    "org.freedesktop.timedate1",
                    "/org/freedesktop/timedate1",
                    "org.freedesktop.timedate1",
                    # "bb" = two booleans: enable-ntp=false, interactive=false
                    "SetNTP", "bb", "false", "false",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                self._ntp_disabled = True
                with self._lock:
                    self._fix["ntp_disabled"] = True
                self._logger.info("NTP disabled via D-Bus — GPS owns the clock")
                return
            self._logger.warning(
                "busctl SetNTP returned %d: %s",
                result.returncode,
                result.stderr.strip(),
            )
        except FileNotFoundError:
            self._logger.debug("busctl not found; NTP will not be disabled")
        except subprocess.TimeoutExpired:
            self._logger.warning("busctl SetNTP timed out")
        except Exception as exc:
            self._logger.warning("Failed to disable NTP: %s", exc)

    def _set_error_status(self, status: str) -> None:
        """Update the local fix dict and Redis with an error status.

        Keeps the manager alive so callers can retrieve the error reason via
        get_status() even after the Redis TTL expires.
        """
        with self._lock:
            self._fix["running"] = False
            self._fix["has_fix"] = False
            self._fix["status"] = status
            self._fix["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._publish_status(status)

    def _publish_status(self, status: str) -> None:
        """Write a minimal status entry to Redis."""
        if not self._redis:
            return
        try:
            self._redis.setex(
                REDIS_KEY,
                REDIS_TTL,
                json.dumps({
                    "running": False,
                    "has_fix": False,
                    "status": status,
                    "serial_port": self._serial_port,
                    "baudrate": self._baudrate,
                    "pps_gpio_pin": self._pps_pin,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }),
            )
        except Exception:
            pass
