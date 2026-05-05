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
- RPi.GPIO (optional): PPS pulse reading
"""

import ctypes
import ctypes.util
import json
import logging
import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
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

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ser = None  # serial.Serial instance

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
        # PPS GPIO interrupt state
        self._pps_gpio_active: bool = False

        # Recent raw NMEA sentences (protected by _lock)
        self._recent_sentences: Deque[str] = deque(maxlen=20)

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
        """Open the serial port and start the reader thread.

        Returns:
            True if the serial port was opened successfully, False otherwise.
        """
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

        self._running = True
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="gps-reader",
            daemon=True,
        )
        self._thread.start()
        self._start_pps_monitor()
        self._logger.info(
            "✅ GPS reader started on %s @ %d baud (PPS GPIO %d)",
            port_path,
            self._baudrate,
            self._pps_pin,
        )
        return True

    def stop(self) -> None:
        """Stop the reader thread and close the serial port."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
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

    def _start_pps_monitor(self) -> None:
        """Set up an RPi.GPIO rising-edge interrupt to detect PPS pulses.

        Silently no-ops if RPi.GPIO is unavailable (e.g. development host)
        or if the GPIO pin cannot be configured.
        """
        if not self._pps_pin:
            return
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
