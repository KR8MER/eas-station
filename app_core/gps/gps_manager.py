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

"""GPS receiver manager for the Adafruit Ultimate GPS HAT (#2324).

Reads NMEA-0183 sentences from the serial port, parses position and time
data, and publishes it to Redis for consumption by the web UI and other
services.

Hardware:
- Adafruit Ultimate GPS HAT for Raspberry Pi (#2324)
- UART interface: /dev/serial0 (BCM UART), 9600 baud
- PPS output: GPIO BCM 4 (configurable)

Dependencies:
- pyserial: Serial port I/O
- pynmea2: NMEA-0183 sentence parser
- gpiozero (optional): PPS pulse reading via GPIO interrupt
"""

import json
import logging
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional


# Redis key used for GPS status storage
REDIS_KEY = "gps:status"
# Redis key used for the rolling NMEA sentence log
REDIS_NMEA_KEY = "gps:nmea"
# TTL in seconds for the Redis key (refreshed every poll cycle)
REDIS_TTL = 15
# Maximum number of raw NMEA sentences kept in the rolling log
NMEA_LOG_SIZE = 50

def _nmea_checksum(payload: str) -> str:
    """Return the two-character XOR checksum used in NMEA / PMTK sentences."""
    cs = 0
    for ch in payload:
        cs ^= ord(ch)
    return f"{cs:02X}"


# MTK3339 PMTK command to enable RMC, GGA, GSA, GSV, VTG NMEA output.
#   RMC=1Hz, VTG=1Hz, GGA=1Hz, GSA=1Hz, GSV every 5 fixes (≈5s @1Hz),
#   all other sentences disabled.
# Adafruit's Ultimate GPS HAT (#2324) ships emitting RMC+GGA only — without
# this command the sky-view (GSV) and active-satellite (GSA) data never
# arrive, so the UI shows "No satellite data yet…" indefinitely.
_PMTK_SET_NMEA_OUTPUT_BODY = "PMTK314,0,1,1,1,1,5,0,0,0,0,0,0,0,0,0,0,0,0,0"
PMTK_SET_NMEA_OUTPUT = (
    f"${_PMTK_SET_NMEA_OUTPUT_BODY}*{_nmea_checksum(_PMTK_SET_NMEA_OUTPUT_BODY)}\r\n"
)

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

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ser = None  # serial.Serial instance

        # Most-recently parsed fix data (protected by _lock)
        self._lock = threading.Lock()
        self._fix: Dict[str, Any] = self._empty_fix()

        # GSV accumulation buffer — reader thread only, no lock needed
        self._gsv_buffer: Dict[int, Dict[str, Any]] = {}
        # PPS GPIO interrupt state
        self._pps_gpio_active: bool = False
        self._pps_device = None  # gpiozero.DigitalInputDevice instance
        self._pps_backend: Optional[str] = None  # 'gpiozero', 'rpi.gpio', or None
        self._pps_error: Optional[str] = None    # human-readable failure reason

        # Rolling raw NMEA sentence log (newest last) — protected by _lock
        self._nmea_log: Deque[Dict[str, Any]] = deque(maxlen=NMEA_LOG_SIZE)
        # Per-sentence-type counters (e.g. {"GGA": 17, "GSV": 4, ...})
        self._nmea_counts: Counter = Counter()
        # Counters for parse errors / sentence read errors
        self._nmea_parse_errors: int = 0
        self._nmea_total: int = 0

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

        # Send the PMTK command to enable GGA/GSA/GSV/RMC/VTG output. The
        # Adafruit GPS HAT only emits RMC+GGA out of the box, so without this
        # nudge the sky view and active-satellite list stay empty.
        self._configure_mtk3339()

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
        if self._pps_device is not None:
            try:
                self._pps_device.close()
            except Exception:
                pass
            self._pps_device = None
        if self._pps_gpio_active and self._pps_backend == "rpi.gpio":
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
            data["nmea_counts"] = dict(self._nmea_counts)
            data["nmea_total"] = self._nmea_total
            data["nmea_parse_errors"] = self._nmea_parse_errors
            data["nmea_recent"] = list(self._nmea_log)[-10:]
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
        data["pps_backend"] = self._pps_backend
        data["pps_error"] = self._pps_error
        data["pps_gpio_active"] = self._pps_gpio_active
        return data

    def get_nmea_log(self, limit: int = NMEA_LOG_SIZE) -> Dict[str, Any]:
        """Return the rolling NMEA sentence log + per-type counters."""
        with self._lock:
            log_items = list(self._nmea_log)
            counts = dict(self._nmea_counts)
            total = self._nmea_total
            parse_errors = self._nmea_parse_errors
        if limit > 0:
            log_items = log_items[-limit:]
        return {
            "running": self._running,
            "serial_port": self._serial_port,
            "baudrate": self._baudrate,
            "total_sentences": total,
            "parse_errors": parse_errors,
            "counts_by_type": counts,
            "sentences": log_items,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

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
            # PPS pulse tracking
            "pps_last_pulse_at": None,
            "pps_pulse_count": 0,
            "pps_backend": None,
            "pps_error": None,
            "pps_gpio_active": False,
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

                consecutive_errors = 0

                # Log the raw sentence regardless of whether it parses cleanly
                # so the diagnostics page can show the actual bytes coming
                # off the serial port (talker IDs, checksums, missing fields).
                parse_ok = True
                try:
                    msg = pynmea2.parse(line)
                except pynmea2.ParseError:
                    parse_ok = False
                    msg = None

                self._record_raw_sentence(line, parse_ok=parse_ok)

                if parse_ok and msg is not None:
                    self._handle_sentence(msg)

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
                # Global Positioning System Fix Data
                fix_qual = int(msg.gps_qual) if msg.gps_qual else 0
                has_fix = fix_qual > 0
                num_sats = int(msg.num_sats) if msg.num_sats else 0

                self._fix["has_fix"] = has_fix
                self._fix["fix_quality"] = _FIX_QUALITY.get(fix_qual, "unknown")
                self._fix["satellites"] = num_sats
                self._fix["status"] = "fix" if (
                    has_fix and num_sats >= self._min_satellites
                ) else ("acquiring" if has_fix else "no_fix")

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
                        except Exception:
                            self._fix["gps_utc_time"] = str(msg.timestamp)

            elif sentence_type == "GSV":
                # Satellites in View — parse per-satellite PRN/elevation/azimuth/SNR
                try:
                    total_msgs = int(msg.num_messages) if msg.num_messages else 1
                    msg_num = int(msg.msg_num) if msg.msg_num else 1
                    if msg_num == 1:
                        self._gsv_buffer.clear()
                    for i in range(1, 5):
                        prn_raw = getattr(msg, "sv_prn_num_%d" % i, None)
                        if not prn_raw:
                            break
                        try:
                            prn = int(prn_raw)
                        except (ValueError, TypeError):
                            continue
                        self._gsv_buffer[prn] = {
                            "prn": prn,
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
                        self._fix["satellites_in_view"] = sorted(
                            list(self._gsv_buffer.values()),
                            key=lambda s: s["prn"],
                        )
                except Exception:
                    pass

            elif sentence_type == "GSA":
                # GPS DOP and Active Satellites
                try:
                    active = []
                    for i in range(1, 13):
                        prn_raw = getattr(msg, "sv_id%02d" % i, None)
                        if prn_raw and str(prn_raw).strip():
                            try:
                                active.append(int(prn_raw))
                            except (ValueError, TypeError):
                                pass
                    self._fix["active_satellite_prns"] = active
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
            self._redis.setex(REDIS_KEY, REDIS_TTL, json.dumps(data))
        except Exception as exc:
            self._logger.debug("Failed to publish GPS status to Redis: %s", exc)

    def _record_raw_sentence(self, line: str, parse_ok: bool = True) -> None:
        """Append a raw NMEA sentence to the rolling log and update counters."""
        # Type code is the 3 chars after the talker (e.g. $GPGSV → GSV).
        # If the line is malformed we still record it as 'UNKNOWN' so the
        # diagnostics page can flag the operator to the bad bytes.
        sentence_type = "UNKNOWN"
        if parse_ok and line.startswith("$") and "," in line:
            head = line.split(",", 1)[0]  # $GPGSV
            if len(head) >= 6:
                sentence_type = head[3:6]
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._nmea_total += 1
            if not parse_ok:
                self._nmea_parse_errors += 1
            self._nmea_counts[sentence_type] += 1
            # Trim very long sentences so the JSON payload stays small
            text = line if len(line) <= 200 else (line[:197] + "...")
            self._nmea_log.append({
                "ts": now_iso,
                "type": sentence_type,
                "ok": parse_ok,
                "text": text,
            })

    def _configure_mtk3339(self) -> None:
        """Send the PMTK314 command to enable RMC/GGA/GSA/GSV/VTG output.

        The Adafruit Ultimate GPS HAT (#2324) ships emitting only RMC + GGA.
        Without this command the GSV (sky view) and GSA (active satellites)
        sentences never arrive, so the polar plot on the hardware page sits
        on "No satellite data yet…" forever even with a healthy 3D fix.

        Failures are logged and ignored — a non-MTK receiver may simply not
        understand the command.
        """
        if not self._ser:
            return
        try:
            self._ser.reset_input_buffer()
            self._ser.write(PMTK_SET_NMEA_OUTPUT.encode("ascii"))
            self._ser.flush()
            self._logger.info(
                "Sent PMTK314 to GPS (enable RMC/GGA/GSA/GSV/VTG output)"
            )
        except Exception as exc:
            self._logger.debug("Could not send PMTK314 command: %s", exc)

    def _start_pps_monitor(self) -> None:
        """Wire up a rising-edge GPIO callback so we can show PPS pulses.

        Tries gpiozero first (uses lgpio/rpi-lgpio, works on Pi 5 + Bookworm
        kernels). Falls back to the legacy RPi.GPIO library on older systems.
        Silently no-ops if neither library is available — the rest of the GPS
        manager keeps working, the UI just paints the PPS LED grey and shows
        "No PPS signal detected" on hover.
        """
        if not self._pps_pin:
            self._pps_error = "PPS GPIO pin not configured"
            return

        # Preferred path: gpiozero. It auto-selects the best pin factory
        # (LGPIOFactory on Pi 5, RPiGPIOFactory on older Pis) so we don't
        # have to deal with /dev/mem deprecation by hand.
        try:
            from gpiozero import DigitalInputDevice  # type: ignore[import]

            self._pps_device = DigitalInputDevice(
                self._pps_pin,
                pull_up=False,
                bounce_time=None,
            )
            self._pps_device.when_activated = self._pps_pulse_callback
            self._pps_gpio_active = True
            self._pps_backend = "gpiozero"
            self._pps_error = None
            self._logger.info(
                "PPS blinkenlite armed on GPIO BCM %d via gpiozero",
                self._pps_pin,
            )
            return
        except ImportError as exc:
            self._logger.debug("gpiozero not available: %s", exc)
            self._pps_error = "gpiozero not installed"
        except Exception as exc:
            self._logger.warning(
                "gpiozero PPS setup failed on BCM %d: %s — trying RPi.GPIO",
                self._pps_pin,
                exc,
            )
            self._pps_error = f"gpiozero: {exc}"
            self._pps_device = None

        # Legacy fallback for systems where gpiozero is unavailable but the
        # old RPi.GPIO module still works (e.g. Pi 4 on Bullseye).
        try:
            import RPi.GPIO as GPIO  # type: ignore[import]

            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pps_pin, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
            GPIO.add_event_detect(
                self._pps_pin,
                GPIO.RISING,
                callback=self._pps_pulse_callback_legacy,
            )
            self._pps_gpio_active = True
            self._pps_backend = "rpi.gpio"
            self._pps_error = None
            self._logger.info(
                "PPS blinkenlite armed on GPIO BCM %d via RPi.GPIO",
                self._pps_pin,
            )
        except ImportError:
            self._logger.warning(
                "Neither gpiozero nor RPi.GPIO available — PPS LED disabled. "
                "Install with: pip install gpiozero lgpio"
            )
            self._pps_error = self._pps_error or "no GPIO library available"
        except Exception as exc:
            self._logger.warning(
                "RPi.GPIO PPS setup failed on BCM %d: %s",
                self._pps_pin,
                exc,
            )
            self._pps_error = f"rpi.gpio: {exc}"

    def _pps_pulse_callback(self, *_args, **_kwargs) -> None:
        """Called by the gpiozero callback thread on each PPS rising edge."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._fix["pps_last_pulse_at"] = now
            self._fix["pps_pulse_count"] = self._fix.get("pps_pulse_count", 0) + 1

    def _pps_pulse_callback_legacy(self, channel: int) -> None:
        """Called by the RPi.GPIO interrupt thread on each PPS rising edge."""
        self._pps_pulse_callback()

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
