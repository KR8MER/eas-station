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


def _mon_hw_frame(*, a_status=2, a_power=1, jamming=1, noise=42, agc=8190):
    """Build a 60-byte UBX-MON-HW frame for the given field values."""
    payload = bytearray(60)
    struct.pack_into("<H", payload, 16, noise)        # noisePerMS
    struct.pack_into("<H", payload, 18, agc)          # agcCnt
    payload[20] = a_status                            # aStatus
    payload[21] = a_power                             # aPower
    payload[22] = (jamming & 0x03) << 2               # jammingState bits 2..3
    return ubx.build_poll(ubx.CLASS_MON, ubx.ID_MON_HW, bytes(payload))


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


def test_poll_decodes_mon_hw_from_ubxtool_capture(monkeypatch):
    mgr = _manager()
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


def test_poll_returns_none_when_no_frame(monkeypatch):
    mgr = _manager()
    monkeypatch.setattr(gm.subprocess, "run", _fake_ubxtool(b"no ubx here\r\n"))
    assert mgr._poll_mon_hw_via_ubxtool() is None


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
