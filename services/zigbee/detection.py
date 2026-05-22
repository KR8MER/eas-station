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

"""Zigbee coordinator USB detection."""

import os
from typing import Dict, List


# Known Zigbee coordinator USB device signatures (vid, pid, label)
# Used for auto-detection via pyserial and /dev/serial/by-id
_ZIGBEE_USB_SIGNATURES = [
    (0x10c4, 0xea60, "Silicon Labs CP210x — Argon Industria V5 / SONOFF / SMLIGHT / CC2652P"),
    (0x10c4, 0x8a2a, "Silicon Labs CP2105"),
    (0x1cf1, 0x0030, "Dresden Elektronik ConBee II"),
    (0x0451, 0x16a8, "Texas Instruments CC2531"),
    (0x1a86, 0x7523, "CH340 USB-Serial"),
    (0x0403, 0x6001, "FTDI FT232R"),
    (0x0403, 0x6015, "FTDI FT231X"),
]

# Substrings in /dev/serial/by-id symlink names that suggest a Zigbee coordinator
_ZIGBEE_BYID_KEYWORDS = [
    "cp210", "silabs", "silicon_labs", "sonoff", "itead", "conbee",
    "dresden", "argon", "smlight", "cc2531", "cc2652", "skyconnect",
]


def detect_zigbee_coordinator() -> List[Dict[str, str]]:
    """Detect connected Zigbee coordinator USB devices.

    Returns a list of dicts, each with keys:
        port        - device path e.g. /dev/ttyUSB0
        description - human-readable label
        confidence  - 'high' (VID/PID match) or 'medium' (by-id name match)
    Ordered by confidence (high first), then by port path.
    """
    detected: Dict[str, Dict[str, str]] = {}  # keyed by port path to avoid duplicates

    # Method 1: pyserial list_ports — gives USB VID/PID, most reliable
    try:
        from serial.tools import list_ports
        for info in list_ports.comports():
            if info.vid is None:
                continue
            for vid, pid, label in _ZIGBEE_USB_SIGNATURES:
                if info.vid == vid and info.pid == pid:
                    detected[info.device] = {
                        'port': info.device,
                        'description': f"{label}",
                        'vid': f"{vid:04x}",
                        'pid': f"{pid:04x}",
                        'confidence': 'high',
                    }
                    break
    except Exception:
        pass

    # Method 2: /dev/serial/by-id symlinks — works without pyserial VID/PID support
    try:
        import glob as _glob
        for symlink in _glob.glob('/dev/serial/by-id/*'):
            real = os.path.realpath(symlink)
            name_lower = os.path.basename(symlink).lower()
            if any(kw in name_lower for kw in _ZIGBEE_BYID_KEYWORDS):
                if real not in detected:
                    detected[real] = {
                        'port': real,
                        'description': os.path.basename(symlink),
                        'confidence': 'medium',
                    }
    except Exception:
        pass

    results = sorted(
        detected.values(),
        key=lambda x: (0 if x['confidence'] == 'high' else 1, x['port'])
    )
    return results
