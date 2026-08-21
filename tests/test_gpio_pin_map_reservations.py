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

"""Regression test for a false-positive GPIO Pin Map conflict on BCM 14.

BCM 14 is statically reserved for the Argon OLED module's wiring
(app_utils/pi_pinout.py) regardless of whether the OLED is enabled. The
pin map's conflict formula used to treat that static label as an active
claimant unconditionally, so a station with GPS or Zigbee enabled on the
Pi's default primary UART (also BCM 14) -- and the Argon OLED disabled --
was shown a "conflict" against a feature that isn't even present.
"""

from webapp.routes.system_controls import pin_reservation_is_active


def test_argon_oled_reservation_inactive_when_oled_disabled():
    """The exact bug: GPS/Zigbee on BCM 14 with the OLED off must not conflict."""
    assert pin_reservation_is_active("Argon OLED module", oled_enabled=False) is False


def test_argon_oled_reservation_active_when_oled_enabled():
    """With the OLED genuinely installed and enabled, the reservation is real."""
    assert pin_reservation_is_active("Argon OLED module", oled_enabled=True) is True


def test_no_reservation_is_never_active():
    assert pin_reservation_is_active(None, oled_enabled=True) is False
    assert pin_reservation_is_active("", oled_enabled=True) is False


def test_other_fixed_reservations_are_unconditionally_active():
    """Non-OLED static reservations (if any are ever added) still gate pins."""
    assert pin_reservation_is_active("Some other fixed wiring", oled_enabled=False) is True
