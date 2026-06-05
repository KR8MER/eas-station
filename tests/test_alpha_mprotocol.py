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

"""Alpha M-Protocol conformance tests for scripts/led_sign_controller.py.

These assert the on-the-wire encoding against the Alpha Sign Communications
Protocol manual (9708-8061F) — most importantly the checksum, which is verified
against the worked example on p.60 (``<STX>"AAHELLO"<ETX>`` -> ``01FB``).
See docs/reference/protocols/ALPHA_M_PROTOCOL.md.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from scripts.led_sign_controller import (
    Alpha9120CController,
    Color,
    DisplayMode,
    Font,
    SpecialFunction,
    Speed,
)


@pytest.fixture
def ctrl():
    """A controller whose connect()/init are stubbed (no network I/O), with the
    two transmit paths patched to capture frames instead of sending them."""
    with patch.object(Alpha9120CController, "connect", return_value=True), \
         patch.object(Alpha9120CController, "_send_initialization", return_value=True):
        c = Alpha9120CController("127.0.0.1", 10001, sign_id="00", type_code="Z")
    c.connected = True
    c.socket = object()  # truthy, satisfies the "connected" guards
    c.sent = []
    c._send_command_and_read_ack = lambda frame, timeout=2.0: (c.sent.append(frame), c.ACK)[1]
    c._send_raw_message = lambda msg: (c.sent.append(msg), True)[1]
    return c


# ── frame parsing helpers ─────────────────────────────────────────────────────

def _payload(frame: bytes) -> bytes:
    """Bytes between <STX> and <ETX> (the command + data)."""
    stx = frame.index(0x02)
    etx = frame.rindex(0x03)
    return frame[stx + 1:etx]


def _checksum(frame: bytes) -> str:
    etx = frame.rindex(0x03)
    return frame[etx + 1:etx + 5].decode("ascii")


def _assert_valid_checksum(frame: bytes):
    """The 4-digit checksum must equal the 16-bit sum of STX..ETX inclusive."""
    stx = frame.index(0x02)
    etx = frame.rindex(0x03)
    expected = sum(frame[stx:etx + 1]) & 0xFFFF
    assert _checksum(frame) == f"{expected:04X}"
    assert frame.endswith(b"\x04")  # EOT


# ── checksum (the critical fix) ───────────────────────────────────────────────

def test_checksum_matches_manual_example(ctrl):
    # Manual p.60: <STX>"AAHELLO"<ETX> -> "01FB"
    assert ctrl._calculate_checksum(b"\x02AAHELLO\x03") == "01FB"


def test_build_frame_uses_4digit_sum_checksum(ctrl):
    frame = ctrl._build_frame_from_payload("AAHELLO")
    assert b"\x02AAHELLO\x03" in frame
    assert _checksum(frame) == "01FB"
    assert len(_checksum(frame)) == 4
    _assert_valid_checksum(frame)


def test_build_message_frame_is_self_consistent(ctrl):
    frame = ctrl._build_message(["HELLO"], color=Color.GREEN, font=Font.FONT_7x9,
                                mode=DisplayMode.HOLD, speed=Speed.SPEED_3)
    assert frame is not None
    _assert_valid_checksum(frame)


# ── speed: single control byte 0x15-0x19, not 0x15 + digit ────────────────────

def test_speed_is_single_control_byte(ctrl):
    frame = ctrl._build_message(["HI"], speed=Speed.SPEED_5, color=Color.RED)
    data = _payload(frame)
    assert b"\x19" in data            # Speed 5
    assert b"\x15\x35" not in data    # not the old 0x15 + ASCII '5'


def test_speed_three_maps_to_0x17(ctrl):
    frame = ctrl._build_message(["HI"], speed=Speed.SPEED_3, color=Color.RED)
    assert b"\x17" in _payload(frame)


# ── character attributes: correct control codes ───────────────────────────────

def test_char_flash_uses_0x07(ctrl):
    frame = ctrl._build_message(["HI"], color=Color.RED,
                                special_functions=[SpecialFunction.CHAR_FLASH_ON])
    data = _payload(frame)
    assert b"\x07\x31" in data        # flash on = 07H + '1'
    assert b"\x1e\x34" not in data    # not the old 1EH + '4'


def test_wide_char_on_uses_0x12(ctrl):
    frame = ctrl._build_message(["HI"], color=Color.RED,
                                special_functions=[SpecialFunction.WIDE_CHAR_ON])
    assert b"\x12" in _payload(frame)


# ── colour / font codes match the manual ──────────────────────────────────────

def test_colour_code_amber(ctrl):
    frame = ctrl._build_message(["HI"], color=Color.AMBER)
    assert b"\x1c3" in _payload(frame)  # 1CH + '3' = Amber


# ── special-function commands ─────────────────────────────────────────────────

def test_set_day_of_week_code_and_data(ctrl):
    assert ctrl.set_day_of_week(0) is True          # Sunday
    assert _payload(ctrl.sent[-1]) == b"E&1"         # E + 0x26 + '1'
    ctrl.set_day_of_week(6)                          # Saturday
    assert _payload(ctrl.sent[-1]) == b"E&7"


def test_set_speaker_code_and_data(ctrl):
    ctrl.set_speaker(True)
    assert _payload(ctrl.sent[-1]) == b"E!00"        # enable
    ctrl.set_speaker(False)
    assert _payload(ctrl.sent[-1]) == b"E!FF"        # disable


def test_set_time_format_not_inverted(ctrl):
    ctrl.set_time_format(format_24h=True)
    assert _payload(ctrl.sent[-1]) == b"E'M"         # 24-hour = 'M'
    ctrl.set_time_format(format_24h=False)
    assert _payload(ctrl.sent[-1]) == b"E'S"         # am/pm = 'S'


def test_set_time_of_day_format(ctrl):
    ctrl.set_time_of_day(datetime(2026, 6, 5, 15, 30, 0))
    assert _payload(ctrl.sent[-1]) == b"E\x201530"   # E + 0x20 + 'HhMm'


def test_set_date_format(ctrl):
    ctrl.set_date(datetime(2026, 6, 5, 0, 0, 0))
    assert _payload(ctrl.sent[-1]) == b"E;060526"    # E + 0x3B + 'mmddyy'


def test_set_brightness_does_not_clear_memory(ctrl):
    assert ctrl.set_brightness(8) is True
    data = _payload(ctrl.sent[-1])
    assert b"E$" not in data       # must NOT be the Clear Memory command
    assert data.startswith(b"E/")  # Set Dimming Register


def test_all_frames_have_valid_checksums(ctrl):
    ctrl.set_speaker(True)
    ctrl.set_brightness(10)
    ctrl.set_day_of_week(2)
    for frame in ctrl.sent:
        _assert_valid_checksum(frame)


# ── housekeeping (new) ────────────────────────────────────────────────────────

def test_soft_reset_frame(ctrl):
    assert ctrl.soft_reset() is True
    assert _payload(ctrl.sent[-1]) == b"E,"          # E + 0x2C, no data


def test_set_serial_address_valid_and_invalid(ctrl):
    assert ctrl.set_serial_address("1F") is True
    assert _payload(ctrl.sent[-1]) == b"E71F"        # E + 0x37 + '1F'
    before = len(ctrl.sent)
    assert ctrl.set_serial_address("ZZ") is False     # invalid -> nothing sent
    assert len(ctrl.sent) == before


def test_run_time_table_frame(ctrl):
    assert ctrl.set_run_time_table("A", 0xFF, 0x00) is True
    assert _payload(ctrl.sent[-1]) == b"E)AFF00"


def test_run_day_table_frame(ctrl):
    assert ctrl.set_run_day_table("A", 8, 9) is True
    assert _payload(ctrl.sent[-1]) == b"E2A89"


def test_set_memory_configuration_record(ctrl):
    ok = ctrl.set_memory_configuration([
        {"label": "A", "type": "A", "protection": "U", "size": 0x0800, "qqqq": "FF00"},
    ])
    assert ok is True
    assert _payload(ctrl.sent[-1]) == b"E$AAU0800FF00"


def test_clear_memory_is_guarded(ctrl):
    assert ctrl.clear_memory() is False              # no confirm -> not sent
    assert ctrl.sent == []
    assert ctrl.clear_memory(confirm=True) is True
    assert _payload(ctrl.sent[-1]) == b"E$"


def test_set_run_mode_is_noop(ctrl):
    assert ctrl.set_run_mode(auto=True) is False      # not a real command
    assert ctrl.sent == []
