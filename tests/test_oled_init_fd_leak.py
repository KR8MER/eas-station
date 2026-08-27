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

"""Regression test for the OLED I2C file-descriptor leak.

``ArgonOLEDController.__init__`` opens the I2C bus (via luma.core's ``i2c``
serial wrapper, backed by ``smbus2.SMBus`` which owns a raw fd with no
``__del__``) *before* handing it to ``ssd1306()`` for the device handshake.
When no OLED is physically attached, ``ssd1306()`` raises
``DeviceNotFoundError`` -- and until this fix, the already-open ``serial``
object was simply dropped on that path, leaking one file descriptor per
failed attempt.

``initialise_oled_display()`` retries this every 5 seconds forever with no
cap on a host with no OLED hardware, so in production this leaked ~30,000
``/dev/i2c-1`` file descriptors and drove the displays subsystem from a
~240MB baseline to 8.9GB RSS over about 4 days of uptime.
"""

import pytest
from unittest.mock import Mock, patch

pytestmark = pytest.mark.unit


def test_failed_ssd1306_handshake_cleans_up_i2c_serial():
    """If ssd1306() fails, the just-opened i2c serial must be cleaned up."""
    mock_serial = Mock()

    with patch('app_core.oled.Image'), \
         patch('app_core.oled.ImageDraw'), \
         patch('app_core.oled.ImageFont'), \
         patch('app_core.oled.i2c', return_value=mock_serial) as mock_i2c, \
         patch('app_core.oled.ssd1306', side_effect=RuntimeError("I2C device not found on address: 0x3C")):

        from app_core.oled import ArgonOLEDController

        with pytest.raises(RuntimeError):
            ArgonOLEDController(
                width=128,
                height=64,
                i2c_bus=1,
                i2c_address=0x3C,
            )

        mock_i2c.assert_called_once()
        # The leaked resource: the i2c serial wrapper's cleanup() closes the
        # underlying smbus2.SMBus fd. Before the fix, nothing called this on
        # the failure path and the fd leaked for the life of the process.
        mock_serial.cleanup.assert_called_once()


def test_successful_init_does_not_call_cleanup():
    """A successful handshake must not close the bus it's about to use."""
    mock_serial = Mock()
    mock_device = Mock()

    with patch('app_core.oled.Image'), \
         patch('app_core.oled.ImageDraw'), \
         patch('app_core.oled.ImageFont') as mock_font, \
         patch('app_core.oled.i2c', return_value=mock_serial), \
         patch('app_core.oled.ssd1306', return_value=mock_device):

        mock_font.load_default = Mock(return_value=Mock())
        mock_font.truetype = Mock(return_value=Mock())

        from app_core.oled import ArgonOLEDController

        controller = ArgonOLEDController(
            width=128,
            height=64,
            i2c_bus=1,
            i2c_address=0x3C,
        )

        assert controller.device is mock_device
        mock_serial.cleanup.assert_not_called()
