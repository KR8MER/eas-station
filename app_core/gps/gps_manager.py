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
import math
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from . import ubx
from .sysprobe import read_cpu_temp_c, safe_read
from .timing_stats import (
    compute_allan_deviation,
    compute_jitter_summary,
    derive_leap_state,
    holdover_seconds,
)

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
# Redis key persisting the wall-clock instant of the last 3D fix.  The
# holdover timer is measured from this anchor; keeping it in Redis (rather
# than memory only) means a manager/service restart *during* a holdover
# period no longer resets it to "unknown" — which is what left the
# dashboard's holdover card blank while the receiver was still coasting.
# No TTL: it is overwritten on every 3D fix and is meaningless to expire.
REDIS_LAST_3D_KEY = "gps:last_3d_fix_at"

# NMEA fix quality codes.
#
# Gotcha on u-blox timing receivers (e.g. NEO-M8T): leaving SBAS enabled
# makes gpsd misreport a genuine TIME/survey-in fix as a DGPS fix (code 2)
# rather than a PPS fix (code 3).  If a fixed-location station that should
# be reporting "pps_fix" persistently shows "dgps_fix", disable SBAS on the
# receiver (GPS+Galileo+GLONASS, SBAS off) — see the upstream u-blox
# configuration notes.  We map the code at face value here; the diagnostic
# is documented so the dashboard's fix-quality readout isn't mistaken for a
# fault.
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

        # Serial NMEA watchdog. A healthy receiver emits sentences at
        # ~1 Hz, so a long stretch with zero bytes means the receiver or
        # USB-serial adapter is wedged even though the port still reports
        # "open" — read(1) just times out forever and nothing upstream
        # notices. After this many seconds of silence the reader closes
        # and reopens the port to reset the adapter. 0 disables the
        # watchdog. gpsd mode is unaffected: it has its own socket
        # reconnect-with-backoff logic.
        raw_watchdog = config.get("serial_watchdog_s")
        if raw_watchdog is None:
            raw_watchdog = os.environ.get("GPS_SERIAL_WATCHDOG_S", 30)
        try:
            self._serial_watchdog_s: float = max(0.0, float(raw_watchdog))
        except (TypeError, ValueError):
            self._serial_watchdog_s = 30.0
        self._watchdog_restarts: int = 0

        # gpsd watchdogs. Two distinct failure modes, two stages:
        #
        # 1. Data silence — gpsd's socket stays open but no JSON events
        #    arrive. With a WATCH active gpsd emits TPV/SKY at ~1 Hz even
        #    without a fix, so a long silence means gpsd (or its device
        #    link) is wedged. Remedy: drop and reconnect the socket.
        # 2. Stuck acquiring — events keep flowing but TPV never reaches
        #    mode 2/3. gpsd is known to wedge in this state after serial
        #    or USB hiccups, and historically only a reboot cleared it.
        #    Remedy: restart the gpsd daemon itself (sudoers rule in
        #    config/sudoers-eas-station), rate-limited by a cooldown so a
        #    genuinely poor sky view can't cause a restart loop.
        #
        # Both default on; 0 disables either stage independently.
        raw_gpsd_watchdog = config.get("gpsd_watchdog_s")
        if raw_gpsd_watchdog is None:
            raw_gpsd_watchdog = os.environ.get("GPS_GPSD_WATCHDOG_S", 60)
        try:
            self._gpsd_watchdog_s: float = max(0.0, float(raw_gpsd_watchdog))
        except (TypeError, ValueError):
            self._gpsd_watchdog_s = 60.0

        raw_stuck = config.get("gpsd_stuck_acquiring_s")
        if raw_stuck is None:
            raw_stuck = os.environ.get("GPS_GPSD_STUCK_ACQUIRING_S", 900)
        try:
            self._gpsd_stuck_acquiring_s: float = max(0.0, float(raw_stuck))
        except (TypeError, ValueError):
            self._gpsd_stuck_acquiring_s = 900.0

        # Minimum spacing between gpsd daemon restarts (stage 2). Keeps a
        # station with an unplugged antenna from bouncing gpsd (and the
        # chrony refclock fed by it) more than twice an hour.
        self._gpsd_restart_cooldown_s: float = 1800.0

        self._gpsd_watchdog_reconnects: int = 0
        self._gpsd_daemon_restarts: int = 0
        self._gpsd_last_event_monotonic: Optional[float] = None
        self._gpsd_last_fix_monotonic: Optional[float] = None
        self._gpsd_last_daemon_restart_monotonic: Optional[float] = None

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
        # Per-PRN tracking history — keyed by ``"<talker><prn:02d>"`` (e.g.
        # ``"GP05"``).  Populated whenever a satellite shows up in GSV /
        # GSA, used by the dashboard's "Almanac & Ephemeris staleness"
        # tile to colour-code PRNs by how recently they were seen / used
        # in the fix.  Reader thread only — protected only when published
        # via :py:meth:`get_status`.
        self._sat_history: Dict[str, Dict[str, Any]] = {}
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
        # gpsd mode only: a side thread that shells out to ``ubxtool`` to
        # poll UBX-MON-HW *through* gpsd.  In gpsd mode we don't own the
        # serial port, so the in-process poller in _maybe_send_ubx_polls()
        # can't write to the receiver — but ubxtool can, because gpsd
        # forwards its control writes.  This is how the antenna / jamming
        # tiles light up on a station that runs gpsd (the common case).
        self._gpsd_ubx_thread: Optional[threading.Thread] = None
        # The GNSS device path gpsd has the receiver on (e.g.
        # ``/dev/ttyAMA0``).  ubxtool must be told this explicitly when
        # gpsd has more than one device attached — a station with a PPS
        # refclock always does (the tty *and* /dev/ppsN), so gpsd rejects
        # an unqualified poll with "No path specified in DEVICE".
        # Discovered from gpsd's ?DEVICES reply and cached on success.
        self._gpsd_ubx_device: Optional[str] = None

        # Inter-pulse intervals in nanoseconds, captured from the kernel
        # PPS device's nanosecond-precision assert timestamp.  Used by
        # get_status() to derive a jitter histogram and overlapping
        # Allan deviation at τ = 1 / 10 / 100 / 1000 s.  Capacity is
        # sized so τ=1000 s ADEV has a meaningful number of overlapping
        # pairs: ~16 384 1 Hz pulses ≈ 4.5 h, leaving (N − 2m) ≈ 14 384
        # terms at τ=1000 s while costing ~130 KB of RAM.
        self._pps_interval_ns: Deque[int] = deque(maxlen=16384)
        # Captured at last 3D fix (from GSA fix_mode==3) so the dashboard
        # can compute a holdover timer when the receiver loses lock but
        # we're still steering chrony from the host clock.  Restored from
        # Redis so the holdover timer survives a manager restart instead of
        # blanking the dashboard card mid-holdover.
        self._last_3d_fix_at: Optional[datetime] = None
        self._load_persisted_3d_fix()

        # UBX poll cadence (seconds).  30 s is well below the ~100 ms
        # NMEA cycle the dashboard reads at, so the antenna and leap
        # tiles stay fresh, but it's also low enough that we don't add
        # measurable load to a 9600-baud serial link (a single MON-HW
        # response is ~70 bytes including the frame).  Set to 0 to
        # disable; we'll honour that for tests and for gpsd mode where
        # we can't share the receiver.
        self._ubx_poll_interval_s: float = 30.0
        # Monotonic timestamp of the last poll *attempt* (whether or
        # not the receiver replied) — set in the reader loop so the
        # cadence stays steady even when the response is slow.
        self._ubx_last_poll_mono: float = 0.0
        # Read-side accumulator for the byte-level demuxer.  The
        # serial reader appends raw bytes here and pulls completed
        # frames off the front via ubx.find_frame() / NMEA scan.
        self._ubx_buf: bytearray = bytearray()

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

        # Throttle for _publish_current_fix(): without this we serialize+
        # SETEX the full fix dict on every NMEA sentence (≈10 Hz on a typical
        # multi-constellation receiver). At ~3 KiB JSON per write that was
        # the dominant CPU consumer in this process. Consumers (UI, trend
        # sampler) only refresh at 1–5 s anyway, so 1 Hz is more than
        # enough — but we still publish immediately on lifecycle events
        # (start/stop/reconnect) by passing force=True.
        self._last_publish_mono: float = 0.0
        self._publish_min_interval_s: float = 1.0

        # Cache for the expensive parts of get_status().  Every call would
        # otherwise:
        #   * copy the full PPS interval ring (up to 16384 ints)
        #   * walk it again to build a 16384-float phase array for ADEV
        #   * deep-copy every _sat_history entry (~200 dicts)
        # That's roughly 250 KB of transient heap per call.  The GPS
        # dashboard polls /api/hardware/gps/status at 1 Hz and the trend
        # sampler reads it every 5 s — together that pushes ~1 MB/s of
        # short-lived allocations through glibc, which sits right at the
        # MALLOC_TRIM_THRESHOLD_=131072 boundary the hardware-service
        # systemd unit sets.  Arenas grow but never trim back, so RSS
        # creeps up while ``tracemalloc.peak`` stays flat — exactly the
        # signature described in PR #2065.  Caching the derived values
        # for ``_status_cache_min_interval_s`` collapses repeated polls
        # to a single compute per cadence, without changing the data the
        # dashboard sees (ADEV/jitter only shift meaningfully on PPS-ring
        # turnover, not on 1-second polling cadence).
        self._status_cache_at_mono: float = 0.0
        self._status_cache_min_interval_s: float = 1.0
        # The stability block (ADEV + TDEV + MTIE over up to 16384
        # phase samples) costs ~3× the jitter histogram, and its output
        # only shifts as the 1 Hz PPS ring turns over — so it runs on a
        # slower throttle than the rest of the cached snapshot.  5 s
        # matches the trend sampler's cadence, the fastest consumer
        # that archives these numbers.
        self._adev_cache_at_mono: float = 0.0
        self._adev_min_interval_s: float = 5.0
        self._cached_jitter: Dict[str, Any] = {}
        self._cached_allan: Dict[str, Any] = {}
        self._cached_sat_history: List[Dict[str, Any]] = []
        self._cached_pps_interval_count: int = 0
        self._cached_cpu_temp: Optional[float] = None

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
        # We can't write UBX polls down the serial port (gpsd owns it),
        # but ``ubxtool`` can poll through gpsd's control channel — so
        # spin up a side thread that does exactly that to keep the
        # antenna / jamming tiles populated.  ``ubx_poll_supported`` is
        # left at None ("polling…") until the first reply lands.
        self._start_gpsd_ubx_poller()
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
        if self._gpsd_ubx_thread and self._gpsd_ubx_thread.is_alive():
            self._gpsd_ubx_thread.join(timeout=3)
        self._gpsd_ubx_thread = None
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

    def _mark_3d_fix(self) -> None:
        """Record the current instant as the holdover anchor and persist it.

        Called from both the NMEA and gpsd reader paths whenever a 3D fix is
        observed.  Persisting to Redis (best-effort, never fatal) lets the
        holdover timer survive a manager/service restart — without it the
        in-memory anchor reset to ``None`` on restart and the dashboard's
        holdover card went blank even while the receiver was still in
        holdover.  Acquires no lock: it mirrors the prior inline assignment,
        whose callers already hold ``self._lock``.
        """
        now = datetime.now(timezone.utc)
        self._last_3d_fix_at = now
        if self._redis:
            try:
                self._redis.set(REDIS_LAST_3D_KEY, now.isoformat())
            except Exception as exc:  # never let a Redis hiccup drop the fix
                self._logger.debug("Failed to persist 3D-fix anchor: %s", exc)


    def _load_persisted_3d_fix(self) -> None:
        """Restore the holdover anchor from Redis on startup, if present."""
        if self._last_3d_fix_at is not None or not self._redis:
            return
        try:
            raw = self._redis.get(REDIS_LAST_3D_KEY)
        except Exception as exc:
            self._logger.debug("Failed to read persisted 3D-fix anchor: %s", exc)
            return
        if not raw:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            self._last_3d_fix_at = datetime.fromisoformat(raw)
        except (ValueError, TypeError) as exc:
            self._logger.debug(
                "Ignoring malformed persisted 3D-fix anchor %r: %s", raw, exc
            )

    def get_status(self) -> Dict[str, Any]:
        """Return the most-recently parsed GPS fix as a dictionary.

        In addition to the raw fix fields the dict carries a handful of
        derived values that the GPS dashboard renders directly:

        * ``pps_pulse_age_s`` — seconds since the last PPS rising edge.
        * ``pps_jitter`` — ``{histogram, mean_ns, stddev_ns, peak_ns,
          sample_count}`` summarising the inter-pulse interval ring buffer.
        * ``allan_deviation`` — overlapping ADEV at τ = 1, 10, 100, 1000 s
          (returned as ``{tau_s: σ_y}`` with float values; entries omitted
          when the buffer is too short for that τ).
        * ``fix_age_s`` — seconds since the last NMEA sentence carrying a
          fix updated the manager.
        * ``holdover_s`` — seconds since the last 3D fix (None until we
          have ever seen one).  When a 3D fix is currently held this is
          ``0``.
        * ``leap_state`` — best-effort leap-second annunciator from the
          NMEA path; chrony's ``leap_status`` is the authoritative
          source on the dashboard, this is just a fallback.
        """
        with self._lock:
            data = dict(self._fix)
            data["recent_sentences"] = list(self._recent_sentences)
            last_3d = self._last_3d_fix_at
        now_utc = datetime.now(timezone.utc)
        now_mono = time.monotonic()

        # Heavy snapshots / derived stats — throttled.  See
        # ``_status_cache_min_interval_s`` in __init__ for rationale.
        # We always serve a result; the cache just decides whether the
        # current call recomputes or reuses the previous one.
        if (
            self._status_cache_at_mono == 0.0
            or now_mono - self._status_cache_at_mono >= self._status_cache_min_interval_s
        ):
            with self._lock:
                interval_samples = list(self._pps_interval_ns)
                # Copy individual entries so callers can mutate the
                # result without racing the reader-thread updates.
                sat_history = [dict(v) for v in self._sat_history.values()]
            self._cached_jitter = compute_jitter_summary(interval_samples)
            # Stability metrics ride a slower throttle — see
            # ``_adev_min_interval_s`` in __init__ for the rationale.
            if (
                self._adev_cache_at_mono == 0.0
                or now_mono - self._adev_cache_at_mono >= self._adev_min_interval_s
            ):
                self._cached_allan = compute_allan_deviation(interval_samples)
                self._adev_cache_at_mono = now_mono
            # Host SoC temperature — sampled on the same throttle so the
            # dashboard can correlate oscillator frequency against the
            # board's thermal state (TCXO drift is mostly thermal).
            self._cached_cpu_temp = read_cpu_temp_c()
            # Sort once at cache time so per-call output is a direct read
            # of the cached list — no per-call sort, no per-call copy.
            sat_history.sort(key=lambda e: (e.get("constellation") or "", e.get("prn") or 0))
            self._cached_sat_history = sat_history
            self._cached_pps_interval_count = len(interval_samples)
            self._status_cache_at_mono = now_mono

        # Diagnostic: which PPS backend is active and how many
        # intervals have we captured?  Lets the operator self-diagnose
        # the "Waiting for PPS pulses…" empty state on the dashboard.
        if self._pps_kernel_device:
            data["pps_backend"] = "kernel"
        elif self._pps_gpio_active:
            data["pps_backend"] = "gpio"
        else:
            data["pps_backend"] = "none"
        data["pps_interval_samples"] = self._cached_pps_interval_count

        # Compute age of the last PPS pulse so the UI can colour the blinkenlite
        last_pulse = data.get("pps_last_pulse_at")
        if last_pulse:
            try:
                pulse_dt = datetime.fromisoformat(last_pulse)
                age = (now_utc - pulse_dt).total_seconds()
                data["pps_pulse_age_s"] = round(age, 2)
            except Exception:
                data["pps_pulse_age_s"] = None
        else:
            data["pps_pulse_age_s"] = None

        # Jitter histogram & Allan deviation from the interval buffer.
        # Served from cache — see the throttle block earlier in this
        # method.  Both helpers tolerate empty input and return
        # JSON-friendly dicts so the dashboard can render without
        # special-casing the cold-start window.
        data["pps_jitter"] = self._cached_jitter
        data["allan_deviation"] = self._cached_allan
        data["cpu_temp_c"] = getattr(self, "_cached_cpu_temp", None)

        # Fix age — drives the "GPS Fix Age" tile.  When we have an active
        # fix this tracks NMEA freshness; when we don't, it's the time
        # since the last sentence (handy for spotting a frozen UART).
        last_sentence = data.get("last_sentence_at")
        if last_sentence:
            try:
                sentence_dt = datetime.fromisoformat(last_sentence)
                data["fix_age_s"] = round(
                    (now_utc - sentence_dt).total_seconds(), 2
                )
            except Exception:
                data["fix_age_s"] = None
        else:
            data["fix_age_s"] = None

        # Holdover timer — wall-clock seconds since the last 3D fix.
        # ``0`` while we currently hold a 3D fix; ``None`` when we have
        # never seen one (e.g. cold start with no antenna).  Shared with
        # _publish_current_fix() so the live and Redis-cached views agree.
        data["holdover_s"] = holdover_seconds(
            last_3d, data.get("fix_mode"), now_utc
        )
        data["last_3d_fix_at"] = last_3d.isoformat() if last_3d else None

        # Leap-second annunciator — Phase 2 will replace this with a
        # UBX-NAV-TIMELS poll; for now we surface a best-effort string
        # so the UI tile has something to display.  Chrony's leap_status
        # remains the authoritative source on the dashboard.
        data["leap_state"] = derive_leap_state(data)

        # Per-PRN tracking history for the dashboard's almanac /
        # ephemeris staleness panel.  Cached + pre-sorted; see the
        # throttle block earlier in this method.
        data["satellite_history"] = self._cached_sat_history

        return data

    # ------------------------------------------------------------------
    # Per-PRN tracking history
    # ------------------------------------------------------------------
    # Cap on how many PRNs we keep around — even a multi-GNSS receiver
    # rarely sees more than ~50 distinct SVIDs in a session.  The cap
    # protects against a flapping receiver that would otherwise grow the
    # dict unboundedly with phantom PRNs.
    _SAT_HISTORY_MAX = 200

    @staticmethod
    def _sat_key(talker: Optional[str], prn: int) -> str:
        return f"{(talker or 'GN').upper()}{int(prn):02d}"

    def _record_sat_seen(self, talker: Optional[str], prn: int, snr: Optional[int]) -> None:
        """Record a PRN sighting from GSV.  Tracks first-seen + last-seen
        timestamps and a running min/max/last SNR.  Called from the GSV
        parser path under the reader thread; no lock needed because
        ``_sat_history`` is only mutated here.
        """
        try:
            key = self._sat_key(talker, prn)
        except Exception:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        entry = self._sat_history.get(key)
        if entry is None:
            if len(self._sat_history) >= self._SAT_HISTORY_MAX:
                # Drop the oldest seen entry to make room.  Cheap because
                # the cap is small.
                oldest_key = min(
                    self._sat_history,
                    key=lambda k: self._sat_history[k].get("last_seen_at") or "",
                )
                self._sat_history.pop(oldest_key, None)
            entry = {
                "prn_string": key,
                "constellation": (talker or "GN").upper(),
                "prn": int(prn),
                "first_seen_at": now_iso,
                "last_seen_at": now_iso,
                "last_used_at": None,
                "last_snr": snr,
                "max_snr": snr,
                "min_snr": snr,
            }
            self._sat_history[key] = entry
            return
        entry["last_seen_at"] = now_iso
        if isinstance(snr, (int, float)):
            entry["last_snr"] = snr
            cur_max = entry.get("max_snr")
            cur_min = entry.get("min_snr")
            if cur_max is None or snr > cur_max:
                entry["max_snr"] = snr
            if cur_min is None or snr < cur_min:
                entry["min_snr"] = snr

    def _record_sat_used(self, talker: Optional[str], prn: int) -> None:
        """Mark a PRN as used-in-fix as of now.  Called from the GSA
        parser.  Updates only entries that already exist in the history
        (so a stale GSA referencing a PRN we never saw in GSV doesn't
        manufacture a phantom record).
        """
        try:
            key = self._sat_key(talker, prn)
        except Exception:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        entry = self._sat_history.get(key)
        if entry is None:
            # Some receivers emit GSA before GSV; create a thin record so
            # we don't lose the "first used" anchor.  The next GSV will
            # populate elevation/azimuth/SNR.
            self._record_sat_seen(talker, prn, None)
            entry = self._sat_history.get(key)
            if entry is None:
                return
        entry["last_used_at"] = now_iso


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
            # TDOP (Time Dilution of Precision).  Only populated in gpsd
            # mode — the NMEA GSA sentence carries P/H/V DOP but not TDOP,
            # so it stays None on direct-NMEA receivers.  It is the DOP term
            # that bounds *timing* accuracy, which is what matters for the
            # PPS/chrony discipline an EAS station relies on.
            "tdop": None,
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
            # Times the serial watchdog reopened a silent port (serial
            # source only; cumulative since manager start).
            "watchdog_restarts": 0,
            # gpsd-mode watchdog counters (cumulative since manager start):
            # socket reconnects forced by event silence, and gpsd daemon
            # restarts triggered by the stuck-acquiring detector.
            "gpsd_watchdog_reconnects": 0,
            "gpsd_daemon_restarts": 0,
            "gpsd_last_daemon_restart_at": None,
            # Raw NMEA sentences (populated separately, not stored in _fix)
            "recent_sentences": [],
            # UBX-MON-HW telemetry (Phase 2).  All None until the first
            # successful MON-HW response is parsed; the dashboard
            # renders "—" / "polling" when unset.
            "antenna_status": None,         # init|unknown|ok|short|open
            "antenna_power": None,          # off|on|unknown
            "jamming_state": None,          # unknown|ok|warning|critical
            "jam_indicator": None,          # 0..255 broadband CW jamming
            "noise_level": None,            # raw 16-bit "noise per ms"
            "agc_count": None,              # raw 16-bit AGC count
            "time_accuracy_ns": None,       # NAV-PVT tAcc — receiver's own
                                            # 1σ time estimate (ns)
            "spoof_state": None,            # NAV-STATUS spoofDetState:
                                            # unknown|none|indicated|multiple
            "ubx_last_poll_at": None,       # ISO timestamp of last reply
            "ubx_poll_supported": None,     # True after first reply,
                                            # False after timeout or
                                            # explicit "skip in gpsd"
            # UBX-NAV-TIMELS telemetry — authoritative leap-second
            # state from the receiver (overrides chrony's leap_status
            # on the dashboard when present).
            "leap_seconds": None,
            "leap_source": None,
            "leap_pending": None,
            "leap_seconds_to_event": None,
            "leap_event_gps_week": None,
            "leap_event_gps_dow": None,
            # Per-PRN tracking history (filled by the GSV/GSA parsers).
            # Always present so the dashboard's staleness panel can
            # render an empty state instead of "undefined".
            "satellite_history": [],
        }

    def _watchdog_reopen_serial(self) -> None:
        """Close and reopen the serial port after prolonged NMEA silence.

        Called from the reader thread when no bytes have arrived for
        ``self._serial_watchdog_s`` seconds. Retries the reopen every
        5 s until it succeeds or the manager is stopped, so an unplugged
        receiver recovers automatically when it is plugged back in (the
        device node may disappear and reappear in between).
        """
        self._watchdog_restarts += 1
        self._logger.warning(
            "GPS watchdog: no serial data for %.0fs — reopening %s (restart #%d)",
            self._serial_watchdog_s,
            self._serial_port,
            self._watchdog_restarts,
        )
        with self._lock:
            self._fix["watchdog_restarts"] = self._watchdog_restarts
            self._fix["status"] = "watchdog_reopen"

        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass

        import serial  # pyserial — already imported once by _start_serial_only

        while self._running:
            try:
                self._ser = serial.Serial(
                    self._serial_port,
                    baudrate=self._baudrate,
                    timeout=2,
                )
                self._logger.info(
                    "GPS watchdog: serial port %s reopened", self._serial_port
                )
                with self._lock:
                    self._fix["status"] = "reading"
                return
            except Exception as exc:
                self._logger.warning(
                    "GPS watchdog: reopen of %s failed (%s); retrying in 5s",
                    self._serial_port,
                    exc,
                )
                time.sleep(5)

    def _reader_loop(self) -> None:
        """Main reader loop — demuxes NMEA + UBX from the serial stream.

        The loop pulls raw bytes (rather than line-buffered text) so it
        can interleave UBX poll responses with NMEA sentences.  A small
        state machine in ``_drain_buffer()`` extracts whichever message
        type comes off the front of ``self._ubx_buf`` next:

        * Bytes leading up to ``$`` are treated as NMEA (terminated by
          ``\\n``) and dispatched to :py:meth:`_handle_sentence`.
        * Bytes leading with the ``B5 62`` sync pair are framed as UBX
          and dispatched to :py:meth:`_handle_ubx`.
        * Anything else is junk; we drop a single byte and retry so a
          stray binary byte can't desync the parser permanently.

        Periodically (every ``self._ubx_poll_interval_s``) we write a
        ``UBX-MON-HW`` and a ``UBX-NAV-TIMELS`` poll request; the
        receiver's responses come back through the same stream and are
        captured by the demuxer.
        """
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
        # Cap the buffer so a malicious / corrupted stream can't OOM
        # the service.  16 KiB is ~17 s of 9600-baud traffic — anything
        # larger means we're not draining and we're better off dropping.
        MAX_BUF = 16 * 1024
        last_data_monotonic = time.monotonic()

        while self._running:
            try:
                if not self._ser or not self._ser.is_open:
                    break

                # Pull whatever's currently in the kernel buffer.  read(1)
                # blocks for up to the serial timeout (2 s, set in
                # _start_serial_only); follow it with an in_waiting drain
                # so a burst of bytes is consumed in a single syscall
                # batch instead of one byte per readline iteration.
                chunk = self._ser.read(1)
                if chunk:
                    waiting = getattr(self._ser, "in_waiting", 0)
                    if waiting:
                        chunk += self._ser.read(waiting)
                    self._ubx_buf.extend(chunk)
                    if len(self._ubx_buf) > MAX_BUF:
                        # Drop the oldest half rather than the whole
                        # buffer so a partial NMEA or UBX frame at the
                        # tail still has a chance of completing.
                        del self._ubx_buf[: len(self._ubx_buf) // 2]

                # Drain whatever framed messages are now available.
                self._drain_buffer(pynmea2)

                # Send the next UBX poll if it's due.  Writes are
                # independent of reads, so there's no risk of stalling
                # the NMEA stream.
                self._maybe_send_ubx_polls()

                # Apply system time if a sync was queued (outside lock)
                if self._pending_time_sync is not None:
                    pending = self._pending_time_sync
                    self._pending_time_sync = None
                    self._apply_system_time(pending)

                if chunk:
                    consecutive_errors = 0
                    last_data_monotonic = time.monotonic()
                elif (
                    self._serial_watchdog_s > 0
                    and time.monotonic() - last_data_monotonic
                    >= self._serial_watchdog_s
                ):
                    self._watchdog_reopen_serial()
                    last_data_monotonic = time.monotonic()

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

    def _drain_buffer(self, pynmea2_mod) -> None:
        """Pull complete NMEA lines and UBX frames off ``self._ubx_buf``.

        Runs in the reader thread.  Each iteration looks at the first
        byte: ``$`` starts an NMEA sentence (terminated by ``\\n``);
        ``0xB5`` is the first UBX sync byte (followed by ``0x62``).
        Anything else is dropped one byte at a time so the parser can
        re-sync on the next valid header.
        """
        buf = self._ubx_buf
        while buf:
            head = buf[0]
            if head == ord("$"):
                # NMEA: find the terminating \n.  If none yet, we need
                # more bytes — leave the partial line in the buffer.
                nl = buf.find(b"\n")
                if nl < 0:
                    return
                line_bytes = bytes(buf[:nl]).rstrip(b"\r")
                del buf[: nl + 1]
                try:
                    line = line_bytes.decode("ascii", errors="replace").strip()
                except Exception:
                    continue
                if not line.startswith("$"):
                    continue
                with self._lock:
                    self._recent_sentences.append(line)
                try:
                    msg = pynmea2_mod.parse(line)
                except pynmea2_mod.ParseError:
                    with self._lock:
                        self._fix["sentence_errors"] = (
                            self._fix.get("sentence_errors", 0) + 1
                        )
                    continue
                self._handle_sentence(msg)
            elif head == ubx.UBX_SYNC_1:
                # UBX: try to extract a complete frame.  None means we
                # need more bytes (the frame isn't fully arrived yet) —
                # break and let the next read top up the buffer.
                # Note that find_frame() consumes any leading garbage
                # AND the frame itself when successful, so we don't
                # need to del[] here.
                if len(buf) < 2:
                    return
                if buf[1] != ubx.UBX_SYNC_2:
                    # False sync — drop the lone B5 and keep scanning.
                    del buf[0]
                    continue
                result = ubx.find_frame(buf)
                if result is None:
                    return
                _leading, cls, mid, payload = result
                self._handle_ubx(cls, mid, payload)
            else:
                # Stray byte — drop it and re-evaluate.  Common after a
                # partial UBX frame whose checksum failed: find_frame
                # leaves the remainder of the discarded frame in the
                # buffer for us to skip past.
                del buf[0]

    def _maybe_send_ubx_polls(self) -> None:
        """Issue MON-HW + NAV-TIMELS polls when the cadence elapses.

        Called from the reader thread only.  Writes are best-effort: a
        failed write is logged at debug and the next attempt happens
        on schedule.  ``ubx_poll_supported`` is set to True the first
        time we get a reply (see :py:meth:`_handle_ubx`); until then
        the dashboard tile shows "polling…" instead of "—".
        """
        if self._ubx_poll_interval_s <= 0:
            return
        if self._active_source != "serial":
            # gpsd owns the port in gpsd mode; we'd have to teach
            # gpsd to forward our writes which is a much bigger
            # rabbit hole (Phase 3 territory).  Surface that we're
            # not polling so the UI tile can explain why.
            with self._lock:
                self._fix["ubx_poll_supported"] = False
            return
        if not self._ser or not self._ser.is_open:
            return

        now = time.monotonic()
        if now - self._ubx_last_poll_mono < self._ubx_poll_interval_s:
            return
        self._ubx_last_poll_mono = now
        try:
            self._ser.write(ubx.POLL_MON_HW)
            self._ser.write(ubx.POLL_NAV_TIMELS)
            try:
                self._ser.flush()
            except Exception:
                pass
        except Exception as exc:
            self._logger.debug("UBX poll write failed: %s", exc)

    def _handle_ubx(self, class_id: int, msg_id: int, payload: bytes) -> None:
        """Decode a UBX response and merge it into the live fix dict.

        Unknown class/id combinations are silently ignored — receivers
        will sometimes emit other UBX messages we never asked for
        (e.g. ``UBX-NAV-PVT`` if a previous session enabled it via
        ``CFG-MSG``), and we don't want those to look like errors.
        """
        try:
            if class_id == ubx.CLASS_MON and msg_id == ubx.ID_MON_HW:
                fields = ubx.parse_mon_hw(payload)
            elif class_id == ubx.CLASS_NAV and msg_id == ubx.ID_NAV_TIMELS:
                fields = ubx.parse_nav_timels(payload)
            else:
                return
        except Exception as exc:
            self._logger.debug(
                "UBX parse error for class=0x%02X id=0x%02X: %s",
                class_id, msg_id, exc,
            )
            return
        if not fields:
            return

        self._apply_ubx_fields(fields)

    def _apply_ubx_fields(self, fields: Dict[str, Any]) -> None:
        """Merge a decoded UBX field dict into the live fix under the lock.

        Shared by the serial reader (:py:meth:`_handle_ubx`) and the
        gpsd-mode ubxtool poller so both paths stamp ``ubx_last_poll_at``
        and flip ``ubx_poll_supported`` to True identically.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for key, value in fields.items():
                self._fix[key] = value
            self._fix["ubx_last_poll_at"] = now_iso
            self._fix["ubx_poll_supported"] = True

    # ------------------------------------------------------------------
    # gpsd-mode UBX polling (via ubxtool)
    # ------------------------------------------------------------------
    def _start_gpsd_ubx_poller(self) -> None:
        """Launch the ubxtool-through-gpsd poll thread, if appropriate.

        Honoured guards:
          * ``_ubx_poll_interval_s <= 0`` disables polling entirely
            (tests set this) — we mark the tile unsupported and bail.
          * ``ubxtool`` missing from PATH — nothing we can do under
            gpsd, so mark unsupported so the UI explains itself rather
            than sitting on "polling…" forever.
        """
        if self._ubx_poll_interval_s <= 0:
            with self._lock:
                self._fix["ubx_poll_supported"] = False
            return
        if shutil.which("ubxtool") is None:
            self._logger.info(
                "ubxtool not found on PATH — u-blox antenna/jamming status "
                "is unavailable while running under gpsd (install gpsd-clients)"
            )
            with self._lock:
                self._fix["ubx_poll_supported"] = False
            return
        self._gpsd_ubx_thread = threading.Thread(
            target=self._gpsd_ubx_poll_loop,
            name="gps-ubx-gpsd",
            daemon=True,
        )
        self._gpsd_ubx_thread.start()

    def _gpsd_ubx_poll_loop(self) -> None:
        """Poll UBX-MON-HW + NAV-TIMELS via ubxtool on the serial cadence.

        Runs only while the manager is up and gpsd is the active source.
        A failed/empty poll is non-fatal: we leave ``ubx_poll_supported``
        as-is (None → the dashboard keeps showing "polling…") and retry
        on the next tick, so a transient gpsd hiccup doesn't latch the
        tile into an error state.  MON-HW feeds the antenna/jamming
        tiles; NAV-TIMELS feeds the leap-second fields — mirroring what
        serial mode polls in :py:meth:`_maybe_send_ubx_polls`.
        """
        interval = self._ubx_poll_interval_s if self._ubx_poll_interval_s > 0 else 30.0
        while self._running and self._active_source == "gpsd":
            try:
                # One capture for MON-HW also sweeps up the streaming
                # NAV-PVT, so we get tAcc (time-accuracy estimate) for
                # free without a second ubxtool invocation.
                raw = self._capture_ubxtool("MON-HW")
                if raw:
                    mon = self._scan_capture(
                        raw, ubx.CLASS_MON, ubx.ID_MON_HW, ubx.parse_mon_hw)
                    if mon:
                        self._apply_ubx_fields(mon)
                    pvt = self._scan_capture(
                        raw, ubx.CLASS_NAV, ubx.ID_NAV_PVT, ubx.parse_nav_pvt)
                    if pvt:
                        self._apply_ubx_fields(pvt)
                # NAV-TIMELS (leap) and NAV-STATUS (spoofing) don't stream
                # by default, so poll each explicitly.
                leap = self._run_ubxtool_poll(
                    "NAV-TIMELS", ubx.CLASS_NAV, ubx.ID_NAV_TIMELS,
                    ubx.parse_nav_timels)
                if leap:
                    self._apply_ubx_fields(leap)
                spoof = self._run_ubxtool_poll(
                    "NAV-STATUS", ubx.CLASS_NAV, ubx.ID_NAV_STATUS,
                    ubx.parse_nav_status)
                if spoof:
                    self._apply_ubx_fields(spoof)
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.debug("gpsd UBX poll error: %s", exc)
            # Sleep in small slices so stop() stays responsive.
            slept = 0.0
            while self._running and self._active_source == "gpsd" and slept < interval:
                time.sleep(0.5)
                slept += 0.5

    def _poll_mon_hw_via_ubxtool(self) -> Optional[Dict[str, Any]]:
        """Poll UBX-MON-HW (antenna/jamming) through gpsd."""
        return self._run_ubxtool_poll(
            "MON-HW", ubx.CLASS_MON, ubx.ID_MON_HW, ubx.parse_mon_hw
        )

    def _run_ubxtool_poll(
        self,
        preset: str,
        want_class: int,
        want_id: int,
        parser,
    ) -> Optional[Dict[str, Any]]:
        """Poll one UBX message through gpsd via ubxtool and decode it.

        Thin convenience wrapper: capture the ``preset`` poll and scan
        the result for the requested class/id.  Returns ``None`` when no
        matching frame arrived.
        """
        raw = self._capture_ubxtool(preset)
        if not raw:
            return None
        return self._scan_capture(raw, want_class, want_id, parser)

    def _capture_ubxtool(self, preset: str) -> Optional[bytes]:
        """Send a ``preset`` poll through gpsd and return the raw stream.

        ``ubxtool`` writes the poll over gpsd's control channel and we
        capture the raw bytes it sees with ``-R``.  A single capture also
        contains whatever else streams during the ~2 s window (e.g.
        NAV-PVT), so callers can scan it for more than one message.
        Returns ``None`` on timeout / spawn failure / empty capture.
        """
        wait_s = 2.0
        # gpsd needs the device named when several are attached (tty +
        # PPS).  Discover it lazily and cache the result; until we have
        # it, fall back to an unqualified target (works on single-device
        # gpsd setups and degrades to a logged error otherwise).
        if self._gpsd_ubx_device is None:
            self._gpsd_ubx_device = self._discover_gpsd_device()
        target = f"{self._gpsd_host}:{self._gpsd_port}"
        if self._gpsd_ubx_device:
            target += f":{self._gpsd_ubx_device}"

        fd, raw_path = tempfile.mkstemp(prefix="ubx-", suffix=".bin")
        os.close(fd)
        try:
            cmd = [
                "ubxtool",
                "-p", preset,         # poll this message
                "-w", str(wait_s),    # wait this long for the reply
                "-R", raw_path,       # save the raw device stream here
                target,               # gpsd host:port[:device]
            ]
            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=wait_s + 5.0,
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                self._logger.debug("ubxtool %s poll failed: %s", preset, exc)
                return None
            with open(raw_path, "rb") as fh:
                raw = fh.read()
        finally:
            try:
                os.unlink(raw_path)
            except OSError:
                pass
        return raw or None

    @staticmethod
    def _scan_capture(
        raw: bytes,
        want_class: int,
        want_id: int,
        parser,
    ) -> Optional[Dict[str, Any]]:
        """Scan a raw UBX capture for the freshest matching frame.

        Decodes with our own :py:func:`ubx.find_frame` + ``parser`` so we
        reuse the tested binary decoders rather than scraping ubxtool's
        version-dependent text.  Returns the last matching field dict, or
        ``None`` when no frame of the requested class/id is present.
        """
        buf = bytearray(raw)
        latest: Optional[Dict[str, Any]] = None
        while True:
            frame = ubx.find_frame(buf)
            if frame is None:
                break
            _leading, class_id, msg_id, payload = frame
            if class_id == want_class and msg_id == want_id:
                parsed = parser(payload)
                if parsed:
                    latest = parsed
        return latest

    def _discover_gpsd_device(self) -> Optional[str]:
        """Ask gpsd for the GNSS receiver's device path via ?DEVICES.

        Opens a short-lived control connection (separate from the reader
        socket), requests the device list, and returns the path of the
        receiver — preferring a device whose driver names u-blox, else
        the first non-PPS tty.  Returns ``None`` on any failure; the
        caller retries on the next poll.
        """
        try:
            sock = socket.create_connection(
                (self._gpsd_host, self._gpsd_port), timeout=3.0
            )
        except OSError as exc:
            self._logger.debug("gpsd device discovery connect failed: %s", exc)
            return None
        try:
            sock.settimeout(3.0)
            sock.sendall(b"?DEVICES;\n")
            buf = b""
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and len(buf) < 65536:
                try:
                    chunk = sock.recv(4096)
                except (OSError, socket.timeout):
                    break
                if not chunk:
                    break
                buf += chunk
                if b'"class":"DEVICES"' in buf and buf.rstrip().endswith(b"}"):
                    break
        finally:
            try:
                sock.close()
            except OSError:
                pass

        for line in buf.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8", "replace"))
            except (ValueError, UnicodeDecodeError):
                continue
            if obj.get("class") != "DEVICES":
                continue
            devices = obj.get("devices") or []
            ublox = [
                d for d in devices
                if "blox" in str(d.get("driver", "")).lower()
            ]
            non_pps = [
                d for d in devices
                if not str(d.get("path", "")).startswith("/dev/pps")
            ]
            for candidate in (ublox or non_pps):
                path = candidate.get("path")
                if path:
                    self._logger.info(
                        "u-blox UBX polling will target gpsd device %s", path
                    )
                    return path
        return None

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
                        snr_val = _safe_int(getattr(msg, "snr_%d" % i, None))
                        bucket[prn] = {
                            "prn": prn,
                            "constellation": talker,
                            "elevation": _safe_int(
                                getattr(msg, "elevation_deg_%d" % i, None)
                            ),
                            "azimuth": _safe_int(
                                getattr(msg, "azimuth_%d" % i, None)
                            ),
                            "snr": snr_val,
                        }
                        # Per-PRN history — dashboard's "Almanac &
                        # Ephemeris staleness" panel reads this to show
                        # how long each satellite has been visible and
                        # when it was last contributing to a fix.
                        self._record_sat_seen(talker, prn, snr_val)
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
                    # Mark each PRN reported in this GSA as currently
                    # used-in-fix.  GSA carries the talker that sourced
                    # it (GPGSA, GLGSA, …) so we can disambiguate in
                    # the rare case where two constellations re-use the
                    # same PRN number.
                    gsa_talker = getattr(msg, "talker", None) or "GN"
                    for used_prn in this_gsa:
                        self._record_sat_used(gsa_talker, used_prn)
                    # Fix mode: 1=no fix, 2=2D, 3=3D
                    fix_mode_raw = getattr(msg, "mode_fix_type", None)
                    if fix_mode_raw is not None:
                        try:
                            mode_int = int(fix_mode_raw)
                            self._fix["fix_mode"] = mode_int
                            # Holdover anchor — the wall-clock instant of
                            # the most recent 3D fix.  Used by get_status()
                            # to compute holdover_s once the receiver loses
                            # lock.  We capture at any 3D fix in the stream
                            # so even brief reacquisitions reset the timer.
                            if mode_int == 3:
                                self._mark_3d_fix()
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

    def _publish_current_fix(self, force: bool = False) -> None:
        """Write the current fix dict to Redis.

        Throttled to at most ``self._publish_min_interval_s`` (1 s by
        default) — see ``_last_publish_mono`` in __init__ for rationale.
        Pass ``force=True`` for lifecycle events (start, stop, reconnect)
        where the UI should see the new state immediately.
        """
        if not self._redis:
            return
        if not force:
            now_mono = time.monotonic()
            if now_mono - self._last_publish_mono < self._publish_min_interval_s:
                return
            self._last_publish_mono = now_mono
        else:
            self._last_publish_mono = time.monotonic()
        try:
            with self._lock:
                data = dict(self._fix)
                data["recent_sentences"] = list(self._recent_sentences)
                last_3d = self._last_3d_fix_at
            # Derive the holdover timer here too — not just in get_status().
            # Consumers that read this Redis blob (the /status fallback when
            # the live manager handle isn't in their process, the trend
            # sampler's cached path) would otherwise never see holdover_s and
            # the dashboard's holdover card/tile would render blank while the
            # receiver is in holdover.
            data["holdover_s"] = holdover_seconds(
                last_3d, data.get("fix_mode"), datetime.now(timezone.utc)
            )
            data["last_3d_fix_at"] = last_3d.isoformat() if last_3d else None
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
        self._publish_current_fix(force=True)

        buf = b""
        now = time.monotonic()
        self._gpsd_last_event_monotonic = now
        # Anchor the stuck-acquiring timer at loop start so a fresh
        # connection gets the full window before remediation can fire.
        self._gpsd_last_fix_monotonic = now
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
                self._gpsd_last_event_monotonic = time.monotonic()
            if self._gpsd_watchdog_check():
                # Watchdog dropped the socket; reconnect on the next pass.
                continue
            try:
                chunk = sock.recv(8192)
            except socket.timeout:
                # Steady-state read timeout. gpsd sends events at ~1 Hz
                # when there's a fix and stays quiet otherwise. A 15s
                # silence isn't fatal — we just loop (the watchdog above
                # decides when silence has gone on long enough).
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
            self._gpsd_last_event_monotonic = time.monotonic()
            # Defensive cap: gpsd events are bounded (a few KiB at most),
            # so anything past 1 MiB without a newline indicates the
            # other end is misbehaving (or we're being fed garbage). Drop
            # the buffer rather than letting it grow without bound — this
            # is one of the few code paths in the hot loop that *could*
            # leak Python heap if the peer never delimited messages.
            if len(buf) > 1_048_576:
                self._logger.warning(
                    "gpsd: %d bytes buffered without newline; resetting",
                    len(buf),
                )
                buf = b""
                continue
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
        self._publish_current_fix(force=True)

    def _gpsd_watchdog_check(self) -> bool:
        """Run both gpsd watchdog stages. Returns True if the socket was
        dropped (caller should skip recv and reconnect).

        Called once per reader-loop iteration, so at least every 15s (the
        socket read timeout). Reader thread only.
        """
        now = time.monotonic()

        # Stage 1: event silence — gpsd should emit TPV/SKY at ~1 Hz with
        # a WATCH active, fix or no fix. Prolonged silence on an open
        # socket means gpsd is wedged; force a reconnect.
        last_event = self._gpsd_last_event_monotonic
        if (
            self._gpsd_watchdog_s > 0
            and last_event is not None
            and now - last_event >= self._gpsd_watchdog_s
        ):
            self._gpsd_watchdog_reconnects += 1
            self._logger.warning(
                "GPS watchdog: no gpsd events for %.0fs — reconnecting "
                "(reconnect #%d)",
                self._gpsd_watchdog_s,
                self._gpsd_watchdog_reconnects,
            )
            with self._lock:
                self._fix["gpsd_watchdog_reconnects"] = self._gpsd_watchdog_reconnects
            self._close_gpsd_socket()
            self._gpsd_last_event_monotonic = now
            return True

        # Stage 2: stuck acquiring — events are flowing but no 2D/3D fix
        # has arrived for a long time. gpsd can wedge in this state after
        # serial/USB hiccups; restarting the daemon clears it. The anchor
        # includes the last daemon restart so each attempt gets a full
        # window, and the cooldown bounds the worst case (bad antenna) to
        # one restart per cooldown period.
        if self._gpsd_stuck_acquiring_s > 0:
            anchor = self._gpsd_last_fix_monotonic or now
            last_restart = self._gpsd_last_daemon_restart_monotonic
            if last_restart is not None:
                anchor = max(anchor, last_restart)
            cooldown_ok = (
                last_restart is None
                or now - last_restart >= self._gpsd_restart_cooldown_s
            )
            if now - anchor >= self._gpsd_stuck_acquiring_s and cooldown_ok:
                self._logger.warning(
                    "GPS watchdog: gpsd has reported no 2D/3D fix for %.0fs "
                    "— restarting the gpsd daemon",
                    self._gpsd_stuck_acquiring_s,
                )
                self._gpsd_last_daemon_restart_monotonic = now
                self._restart_gpsd_daemon()
                # gpsd restart drops our connection; reconnect cleanly.
                self._close_gpsd_socket()
                self._gpsd_last_event_monotonic = time.monotonic()
                return True

        return False

    def _restart_gpsd_daemon(self) -> bool:
        """Restart the gpsd system service (stuck-acquiring remediation).

        Tries ``sudo -n systemctl restart <unit>`` first (the rule ships
        in config/sudoers-eas-station), then plain ``systemctl`` for
        root-run deployments. Returns True if any restart succeeded.
        """
        self._gpsd_daemon_restarts += 1
        with self._lock:
            self._fix["gpsd_daemon_restarts"] = self._gpsd_daemon_restarts
            self._fix["gpsd_last_daemon_restart_at"] = datetime.now(
                timezone.utc
            ).isoformat()

        any_ok = False
        for unit in ("gpsd.service", "gpsd.socket"):
            unit_ok = False
            for cmd in (
                ["sudo", "-n", "/usr/bin/systemctl", "restart", unit],
                ["systemctl", "restart", unit],
            ):
                try:
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=30
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    self._logger.debug(
                        "GPS watchdog: %s failed to launch: %s", cmd, exc
                    )
                    continue
                if result.returncode == 0:
                    unit_ok = True
                    break
                self._logger.debug(
                    "GPS watchdog: %s exited %d: %s",
                    cmd,
                    result.returncode,
                    (result.stderr or "").strip()[:200],
                )
            any_ok = any_ok or unit_ok

        if any_ok:
            self._logger.info(
                "GPS watchdog: gpsd daemon restarted (restart #%d)",
                self._gpsd_daemon_restarts,
            )
        else:
            self._logger.error(
                "GPS watchdog: could not restart gpsd — ensure the gpsd "
                "entries from config/sudoers-eas-station are installed in "
                "/etc/sudoers.d/eas-station (re-run install.sh to update)"
            )
        return any_ok

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
        if mode in (2, 3):
            # Feed the stuck-acquiring watchdog (reader thread only).
            self._gpsd_last_fix_monotonic = time.monotonic()
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
            if mode == 3:
                # Mirror the NMEA path's holdover anchor in gpsd mode.
                self._mark_3d_fix()
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
            # Per-PRN tracking history — same dashboard panel as the
            # NMEA path.  ``_record_sat_seen`` / ``_record_sat_used``
            # mutate ``_sat_history`` only; safe to call without the
            # lock here because gpsd I/O lives on its own thread.
            self._record_sat_seen(entry["constellation"], prn, entry["snr"])
            if entry["used"]:
                self._record_sat_used(entry["constellation"], prn)
        with self._lock:
            self._fix["satellites_in_view"] = in_view
            self._fix["active_satellite_prns"] = used_prns
            self._fix["satellites"] = len(used_prns)
            # gpsd's SKY object carries tdop alongside hdop/vdop/pdop; the
            # direct-NMEA path can't (GSA omits it), so this is the only
            # place tdop becomes available.
            for src, dst in (("hdop", "hdop"), ("vdop", "vdop"),
                             ("pdop", "pdop"), ("tdop", "tdop")):
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


    def _start_pps_kernel_monitor(self, device: str) -> None:
        """Spawn a low-rate poller of ``<device>/assert`` and update the fix."""
        # Capture the current sequence so pps_pulse_count reflects pulses
        # observed since this manager started, matching the existing
        # RPi.GPIO semantic.  ``_read_pps_assert`` returns a 3-tuple
        # ``(seq, ts_ns, ts_iso)`` — taking just the sequence here is
        # all we need for the baseline.
        baseline = self._read_pps_assert(device)
        self._pps_kernel_baseline_seq = baseline[0] if baseline else 0
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

    def _read_pps_assert(self, device: str) -> Optional[Tuple[int, int, str]]:
        """Parse ``<device>/assert`` and return ``(sequence, ts_ns, ts_iso)``.

        The kernel exports the line as ``<seconds>.<nanoseconds>#<sequence>``
        (see ``Documentation/ABI/testing/sysfs-pps``).  The integer
        nanosecond timestamp is what enables sub-microsecond jitter
        and Allan deviation calculations downstream — float seconds
        loses ~100 ns of precision near current epoch values.  Returns
        ``None`` if the file is missing or the sequence is zero.
        """
        try:
            raw = safe_read(Path(device) / "assert")
            if not raw or "#" not in raw:
                return None
            ts_part, _, seq_part = raw.partition("#")
            seq = int(seq_part.strip())
            if seq <= 0:
                return None
            secs_str, _, ns_str = ts_part.partition(".")
            secs = int(secs_str)
            ns = int(ns_str.ljust(9, "0")[:9]) if ns_str else 0
            ts_ns = secs * 1_000_000_000 + ns
            ts = datetime.fromtimestamp(secs + ns / 1e9, tz=timezone.utc)
            return seq, ts_ns, ts.isoformat()
        except Exception as exc:
            self._logger.debug("Failed to parse %s/assert: %s", device, exc)
            return None

    def _pps_kernel_loop(self) -> None:
        """Poll the kernel PPS device at 10 Hz while the manager runs.

        The 10 Hz cadence is fast enough to never miss a 1 Hz pulse while
        still being trivially cheap (one sysfs read per 100 ms).  When
        a new sequence number is observed we append the inter-pulse
        interval (in nanoseconds) to ``self._pps_interval_ns`` so
        ``get_status()`` can derive jitter/ADEV later — gaps from
        missed pulses are skipped (interval > 1.5 s) so a flapping
        receiver doesn't poison the histogram.
        """
        last_seq: Optional[int] = self._pps_kernel_baseline_seq
        last_ts_ns: Optional[int] = None
        device = self._pps_kernel_device or ""
        while self._running and device:
            try:
                result = self._read_pps_assert(device)
                if result is not None:
                    seq, ts_ns, ts_iso = result
                    if last_seq is None or seq != last_seq:
                        # Only count intervals when the sequence advanced
                        # by exactly one — anything else is a missed pulse
                        # or a baseline catch-up and would skew jitter.
                        if (
                            last_seq is not None
                            and last_ts_ns is not None
                            and seq == last_seq + 1
                        ):
                            interval_ns = ts_ns - last_ts_ns
                            # Drop bogus intervals (clock step, rollover).
                            if 500_000_000 <= interval_ns <= 1_500_000_000:
                                with self._lock:
                                    self._pps_interval_ns.append(interval_ns)
                        baseline = self._pps_kernel_baseline_seq or 0
                        count = max(0, seq - baseline)
                        with self._lock:
                            self._fix["pps_last_pulse_at"] = ts_iso
                            self._fix["pps_pulse_count"] = count
                        last_seq = seq
                        last_ts_ns = ts_ns
            except Exception as exc:
                self._logger.debug("PPS kernel poll error: %s", exc)
            time.sleep(0.1)

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
        """Called by the RPi.GPIO interrupt thread on each PPS rising edge.

        We also capture the inter-pulse interval here (using
        ``time.monotonic_ns`` rather than the kernel's ns-precision
        assert timestamp) so the dashboard's jitter histogram and
        Allan-deviation panels still render meaningful data on hosts
        that don't have the ``pps-gpio`` kernel overlay loaded.

        Caveat: monotonic_ns timestamps go through Python's GIL and
        the RPi.GPIO C extension's IRQ handler, which adds tens of µs
        of jitter on top of the receiver's actual PPS edge.  That's
        good enough for the histogram (whose smallest bucket is 20 µs
        anyway) but the absolute σ value will read higher than the
        kernel-PPS path would report on the same hardware.
        """
        now_mono_ns = time.monotonic_ns()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            last_mono = getattr(self, "_pps_gpio_last_mono_ns", None)
            self._pps_gpio_last_mono_ns = now_mono_ns
            self._fix["pps_last_pulse_at"] = now_iso
            self._fix["pps_pulse_count"] = self._fix.get("pps_pulse_count", 0) + 1
            if last_mono is not None:
                interval_ns = now_mono_ns - last_mono
                # Mirror the kernel-loop sanity gate: drop pathological
                # intervals (clock step, dropped pulse) so they don't
                # poison the histogram or ADEV calculation.
                if 500_000_000 <= interval_ns <= 1_500_000_000:
                    self._pps_interval_ns.append(interval_ns)

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
