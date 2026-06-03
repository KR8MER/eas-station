"""Tests for u-blox MON-HW polling via ubxtool while running under gpsd.

In gpsd mode the manager does not own the serial port, so the in-process
UBX poller (_maybe_send_ubx_polls) cannot write to the receiver and the
antenna / jamming dashboard tiles stayed dark ("via gpsd · polls
disabled"). The manager now shells out to ``ubxtool`` — which polls
through gpsd's control channel — captures the raw byte stream with
``-R``, and decodes UBX-MON-HW with the existing binary parser. These
tests cover that path end to end with ubxtool mocked out.
"""

import struct

import app_core.gps.gps_manager as gm
from app_core.gps import ubx
from app_core.gps.gps_manager import GPSManager


def _manager():
    # Empty config → defaults; __init__ starts no threads or I/O.
    return GPSManager(config={}, redis_client=None)


def _mon_hw_frame(*, a_status=2, a_power=1, jamming=1, jam_ind=48, noise=42, agc=8190):
    """Build a 60-byte UBX-MON-HW frame for the given field values."""
    payload = bytearray(60)
    struct.pack_into("<H", payload, 16, noise)        # noisePerMS
    struct.pack_into("<H", payload, 18, agc)          # agcCnt
    payload[20] = a_status                            # aStatus
    payload[21] = a_power                             # aPower
    payload[22] = (jamming & 0x03) << 2               # jammingState bits 2..3
    payload[45] = jam_ind                             # jamInd (0..255)
    return ubx.build_poll(ubx.CLASS_MON, ubx.ID_MON_HW, bytes(payload))


def test_parse_surfaces_jam_indicator():
    # Mirrors the real receiver: supervisor + ITFM off (status/jamming
    # report "unknown") but jamInd / noise / agc are live.
    fields = ubx.parse_mon_hw(bytes(_mon_hw_frame(
        a_status=1, a_power=2, jamming=0, jam_ind=53, noise=99, agc=2730))[6:-2])
    assert fields["antenna_status"] == "unknown"
    assert fields["antenna_power"] == "unknown"
    assert fields["jamming_state"] == "unknown"
    assert fields["jam_indicator"] == 53
    assert fields["noise_level"] == 99
    assert fields["agc_count"] == 2730


def test_parse_tolerates_short_payload_without_jam_indicator():
    # A truncated payload (< 46 bytes) still yields the base fields but
    # no jamInd — it must come back None rather than raising.
    short = bytearray(24)
    short[20] = 2  # aStatus ok
    fields = ubx.parse_mon_hw(bytes(short))
    assert fields["antenna_status"] == "ok"
    assert fields["jam_indicator"] is None


def _fake_ubxtool(raw_payload):
    """Return a subprocess.run stand-in that writes ``raw_payload`` to the
    file named after the ``-R`` flag, mimicking ubxtool's raw capture."""

    def _run(cmd, *args, **kwargs):
        raw_path = cmd[cmd.index("-R") + 1]
        with open(raw_path, "wb") as fh:
            fh.write(raw_payload)

        class _Completed:
            returncode = 0
            stdout = b""
            stderr = b""

        return _Completed()

    return _run


def _nav_timels_frame(*, curr_ls=18, valid=0x01, src=2):
    """Build a 24-byte UBX-NAV-TIMELS frame (current leap seconds only)."""
    payload = bytearray(24)
    payload[8] = src                                 # srcOfCurrLs (2=gps)
    struct.pack_into("<b", payload, 9, curr_ls)      # currLs (signed)
    payload[23] = valid                              # bit0=currLsValid
    return ubx.build_poll(ubx.CLASS_NAV, ubx.ID_NAV_TIMELS, bytes(payload))


def test_poll_nav_timels_returns_leap_seconds(monkeypatch):
    mgr = _manager()
    mgr._gpsd_ubx_device = "/dev/ttyTEST"  # skip live gpsd discovery
    raw = b"$GPGGA,foo*00\r\n" + bytes(_nav_timels_frame(curr_ls=18))
    monkeypatch.setattr(gm.subprocess, "run", _fake_ubxtool(raw))

    fields = mgr._run_ubxtool_poll(
        "NAV-TIMELS", ubx.CLASS_NAV, ubx.ID_NAV_TIMELS, ubx.parse_nav_timels
    )

    assert fields is not None
    assert fields["leap_seconds"] == 18
    assert fields["leap_source"] == "gps"


def test_parse_nav_pvt_time_accuracy():
    payload = bytearray(92)
    struct.pack_into("<I", payload, 12, 22)  # tAcc = 22 ns
    fields = ubx.parse_nav_pvt(bytes(payload))
    assert fields["time_accuracy_ns"] == 22


def test_parse_nav_status_spoof_state():
    # flags2 bits 3..4 = spoofDetState; 1 = "none".
    payload = bytearray(16)
    payload[7] = 1 << 3
    assert ubx.parse_nav_status(bytes(payload))["spoof_state"] == "none"
    payload[7] = 2 << 3
    assert ubx.parse_nav_status(bytes(payload))["spoof_state"] == "indicated"


def test_scan_capture_extracts_nav_pvt_from_mixed_stream():
    # tAcc must be recoverable from a capture taken for a MON-HW poll,
    # since NAV-PVT streams alongside it.
    pvt = bytearray(92)
    struct.pack_into("<I", pvt, 12, 35)
    raw = bytes(_mon_hw_frame()) + bytes(
        ubx.build_poll(ubx.CLASS_NAV, ubx.ID_NAV_PVT, bytes(pvt)))
    got = GPSManager._scan_capture(raw, ubx.CLASS_NAV, ubx.ID_NAV_PVT, ubx.parse_nav_pvt)
    assert got == {"time_accuracy_ns": 35}


def test_poll_decodes_mon_hw_from_ubxtool_capture(monkeypatch):
    mgr = _manager()
    mgr._gpsd_ubx_device = "/dev/ttyTEST"  # skip live gpsd discovery
    # Capture includes leading junk + an NMEA line, like a real stream.
    raw = b"$GPGGA,foo*00\r\n\x00\x01" + bytes(_mon_hw_frame(jamming=2))
    monkeypatch.setattr(gm.subprocess, "run", _fake_ubxtool(raw))

    fields = mgr._poll_mon_hw_via_ubxtool()

    assert fields is not None
    assert fields["antenna_status"] == "ok"
    assert fields["antenna_power"] == "on"
    assert fields["jamming_state"] == "warning"
    assert fields["noise_level"] == 42
    assert fields["agc_count"] == 8190


def test_poll_names_device_in_ubxtool_target(monkeypatch):
    """gpsd rejects an unqualified poll when several devices are attached,
    so the discovered device path must be appended as host:port:device."""
    mgr = _manager()
    mgr._gpsd_ubx_device = "/dev/ttyAMA0"
    captured = {}

    def _capture(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        raw_path = cmd[cmd.index("-R") + 1]
        open(raw_path, "wb").close()  # empty capture is fine here

        class _C:
            returncode = 0
            stdout = stderr = b""

        return _C()

    monkeypatch.setattr(gm.subprocess, "run", _capture)
    mgr._poll_mon_hw_via_ubxtool()

    assert captured["cmd"][-1] == "127.0.0.1:2947:/dev/ttyAMA0"


def test_poll_returns_none_when_no_frame(monkeypatch):
    mgr = _manager()
    mgr._gpsd_ubx_device = "/dev/ttyTEST"  # skip live gpsd discovery
    monkeypatch.setattr(gm.subprocess, "run", _fake_ubxtool(b"no ubx here\r\n"))
    assert mgr._poll_mon_hw_via_ubxtool() is None


def test_discover_gpsd_device_prefers_ublox(monkeypatch):
    mgr = _manager()
    reply = (
        b'{"class":"VERSION"}\n'
        b'{"class":"DEVICES","devices":['
        b'{"path":"/dev/pps0","driver":"PPS"},'
        b'{"path":"/dev/ttyAMA0","driver":"u-blox"}]}\n'
    )

    class _FakeSock:
        def __init__(self):
            self._buf = reply

        def settimeout(self, _t):
            pass

        def sendall(self, _data):
            pass

        def recv(self, _n):
            data, self._buf = self._buf, b""
            return data

        def close(self):
            pass

    monkeypatch.setattr(gm.socket, "create_connection", lambda *a, **k: _FakeSock())
    assert mgr._discover_gpsd_device() == "/dev/ttyAMA0"


def test_apply_ubx_fields_marks_supported():
    mgr = _manager()
    assert mgr._fix["ubx_poll_supported"] is None
    assert mgr._fix["antenna_status"] is None

    mgr._apply_ubx_fields(ubx.parse_mon_hw(bytes(_mon_hw_frame())[6:-2]))

    assert mgr._fix["antenna_status"] == "ok"
    assert mgr._fix["ubx_poll_supported"] is True
    assert mgr._fix["ubx_last_poll_at"] is not None


def test_poller_not_started_when_ubxtool_missing(monkeypatch):
    mgr = _manager()
    monkeypatch.setattr(gm.shutil, "which", lambda _name: None)

    mgr._start_gpsd_ubx_poller()

    assert mgr._gpsd_ubx_thread is None
    # Tile is marked unsupported so the UI explains itself.
    assert mgr._fix["ubx_poll_supported"] is False


def test_poller_disabled_when_interval_zero(monkeypatch):
    mgr = _manager()
    mgr._ubx_poll_interval_s = 0
    # which() should never be consulted once the interval guard trips.
    monkeypatch.setattr(
        gm.shutil, "which",
        lambda _name: (_ for _ in ()).throw(AssertionError("which() called")),
    )

    mgr._start_gpsd_ubx_poller()

    assert mgr._gpsd_ubx_thread is None
    assert mgr._fix["ubx_poll_supported"] is False
