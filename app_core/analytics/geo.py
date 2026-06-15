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

"""Best-effort geolocation / network classification for visitor IPs.

EAS Station is typically an on-prem appliance, so most traffic comes from the
local network. This helper always classifies an address into a human-readable
"location" label without any network calls:

* loopback / private / link-local addresses -> "Local Network" style labels
* public addresses -> a country name *if* an optional MaxMind GeoLite2 database
  is configured (``geoip2`` installed + a ``.mmdb`` path set in the Traffic
  Analytics settings); otherwise the generic label "Internet (Public)".

The optional dependency keeps the core install lightweight: country-level
geolocation lights up automatically when an operator drops in a GeoLite2 DB and
points the setting at it, with zero code changes.
"""

import ipaddress
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Cache of opened geoip2 readers keyed by database path so we open the (memory
# mapped) database once rather than per request.
_readers: dict = {}
_readers_lock = threading.Lock()
# Paths we already failed to open — don't retry/log on every single request.
_failed_paths: set = set()


def _get_reader(db_path: str):
    """Return a cached geoip2 reader for *db_path*, or ``None`` if unavailable."""
    if not db_path or db_path in _failed_paths:
        return None
    reader = _readers.get(db_path)
    if reader is not None:
        return reader
    with _readers_lock:
        reader = _readers.get(db_path)
        if reader is not None:
            return reader
        try:
            import geoip2.database  # type: ignore

            reader = geoip2.database.Reader(db_path)
            _readers[db_path] = reader
            logger.info("GeoIP database loaded from %s", db_path)
            return reader
        except Exception as exc:  # pragma: no cover - optional dependency/path
            logger.warning("GeoIP database unavailable (%s): %s", db_path, exc)
            _failed_paths.add(db_path)
            return None


def classify_ip(ip: Optional[str], geoip_db_path: Optional[str] = None) -> str:
    """Return a location/network label for *ip*.

    Never raises and never makes a network call. When *geoip_db_path* points at a
    readable GeoLite2 database (and ``geoip2`` is installed), public addresses
    resolve to a country name; otherwise they get a generic public label.
    """
    if not ip:
        return "Unknown"

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "Unknown"

    if addr.is_loopback:
        return "Local (loopback)"
    if addr.is_link_local:
        return "Local (link-local)"
    if addr.is_private:
        return "Local Network"

    # Public address — try optional country resolution.
    if geoip_db_path:
        reader = _get_reader(geoip_db_path)
        if reader is not None:
            try:
                country = reader.country(ip).country.name
                if country:
                    return country
            except Exception:  # pragma: no cover - address not in DB, etc.
                pass

    return "Internet (Public)"


def reset_readers() -> None:
    """Close and forget cached readers (used when the DB path changes)."""
    with _readers_lock:
        for reader in _readers.values():
            try:
                reader.close()
            except Exception:
                pass
        _readers.clear()
        _failed_paths.clear()


__all__ = ["classify_ip", "reset_readers"]
