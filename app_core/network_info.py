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

"""Shared local-network helpers for admin features that manage UFW rules
scoped to "the operator's LAN" (webapp.admin.ntp_server, webapp.admin.icecast).

Which subnets should be trusted for a given feature is inherently a
per-deployment decision with no correct default (a home LAN, an office VLAN,
a cloud box's provider-internal range that isn't the operator's real LAN at
all), so nothing here is ever applied to the firewall automatically --
callers surface these as suggestions and let the operator confirm.
"""

import ipaddress
import json
import subprocess


def validate_cidr(value: str) -> str:
    """Normalize and validate one subnet. Raises ValueError on anything
    that isn't a real IPv4/IPv6 network or host address.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("empty subnet")
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(f"'{value}' is not a valid IP address or CIDR range") from exc
    return str(network)


def detect_local_subnets() -> list[str]:
    """Best-effort suggestions for the admin: the actual subnet(s) this
    box's own non-loopback interfaces sit on. Purely informational --
    never applied automatically, since a cloud box's "local" interface
    subnet is usually a provider-internal range, not the operator's LAN.
    """
    try:
        result = subprocess.run(
            ["ip", "-json", "addr", "show"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        interfaces = json.loads(result.stdout or "[]")
    except Exception:
        return []

    subnets: list[str] = []
    for iface in interfaces:
        if "LOOPBACK" in (iface.get("flags") or []):
            continue
        for addr in iface.get("addr_info") or []:
            if addr.get("family") != "inet":
                continue
            local = addr.get("local")
            prefixlen = addr.get("prefixlen")
            if not local or prefixlen is None:
                continue
            try:
                network = ipaddress.ip_interface(f"{local}/{prefixlen}").network
            except ValueError:
                continue
            candidate = str(network)
            if candidate not in subnets:
                subnets.append(candidate)
    return subnets
