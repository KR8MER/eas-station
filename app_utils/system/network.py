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

"""Network interface traffic counters."""

import contextlib
from typing import Any, Dict, List, Optional, Tuple

import psutil


def _collect_network_traffic() -> Dict[str, Any]:
    """Return cumulative network I/O statistics."""

    result: Dict[str, Any] = {
        "available": False,
        "interfaces": [],
        "totals": {},
        "error": None,
    }

    try:
        totals = psutil.net_io_counters()
        result["totals"] = {
            "bytes_sent": totals.bytes_sent,
            "bytes_recv": totals.bytes_recv,
            "packets_sent": totals.packets_sent,
            "packets_recv": totals.packets_recv,
            "errin": totals.errin,
            "errout": totals.errout,
            "dropin": totals.dropin,
            "dropout": totals.dropout,
        }
        result["available"] = True
    except Exception as exc:  # pragma: no cover - depends on psutil support
        result["error"] = str(exc)

    try:
        pernic = psutil.net_io_counters(pernic=True)
    except Exception:
        pernic = {}

    stats = {}
    with contextlib.suppress(Exception):
        stats = psutil.net_if_stats()

    for name in sorted(pernic.keys()):
        counters = pernic[name]
        stat = stats.get(name)
        result["interfaces"].append(
            {
                "name": name,
                "bytes_sent": counters.bytes_sent,
                "bytes_recv": counters.bytes_recv,
                "packets_sent": counters.packets_sent,
                "packets_recv": counters.packets_recv,
                "errin": counters.errin,
                "errout": counters.errout,
                "dropin": counters.dropin,
                "dropout": counters.dropout,
                "speed_mbps": getattr(stat, "speed", None),
                "mtu": getattr(stat, "mtu", None),
                "is_up": getattr(stat, "isup", None),
                "duplex": getattr(stat, "duplex", None),
            }
        )

    if result["interfaces"]:
        result["available"] = True

    return result


def _select_primary_interface(interfaces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the most relevant network interface for display purposes."""

    if not interfaces:
        return None

    def interface_priority(entry: Dict[str, Any]) -> Tuple[int, int]:
        name = (entry.get("name") or "").lower()
        is_loopback = name in {"lo", "loopback"}
        is_up = bool(entry.get("is_up"))
        has_ipv4 = any(addr.get("type") == "IPv4" for addr in entry.get("addresses", []))
        priority = 0
        if is_loopback:
            priority += 2
        if not is_up:
            priority += 1
        if not has_ipv4:
            priority += 1
        return (priority, 0 if name else 1)

    sorted_interfaces = sorted(interfaces, key=interface_priority)
    return sorted_interfaces[0] if sorted_interfaces else None
