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

"""Top-level package for split hardware-side services.

Each module under this package owns one piece of hardware that used to live
in the monolithic ``hardware_service.py`` (GPIO, GPS, OLED, LED, VFD, Zigbee,
alert indicators, screen rotation, network configuration).  Shared startup
scaffolding lives in ``services.common``.
"""
