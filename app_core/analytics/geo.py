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

When a GeoLite2 database resolves a public IP, :func:`classify_location` also
returns the ISO 3166-1 alpha-2 country code (e.g. ``"US"``) so the dashboard can
render a flag, mirroring awstats' "Countries" report.

The optional dependency keeps the core install lightweight: country-level
geolocation lights up automatically when an operator drops in a GeoLite2 DB and
points the setting at it, with zero code changes.

:func:`resolve_hostname` performs an awstats-style reverse-DNS lookup (PTR
record) so visitor IPs can be shown as hostnames. Lookups hit the network, so
they are bounded by a short timeout, cached (positive *and* negative), and are
only ever called from the background recorder thread — never on the request
path.
"""

import ipaddress
import logging
import socket
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Cache of opened geoip2 readers keyed by database path so we open the (memory
# mapped) database once rather than per request.
_readers: dict = {}
_readers_lock = threading.Lock()
# Paths we already failed to open — don't retry/log on every single request.
_failed_paths: set = set()

# Reverse-DNS cache: maps an IP string to its resolved hostname, or ``None`` when
# a previous lookup found no PTR record (negative caching avoids hammering the
# resolver for the same address). Bounded so a flood of unique IPs can't grow it
# without limit.
_hostname_cache: Dict[str, Optional[str]] = {}
_hostname_lock = threading.Lock()
_HOSTNAME_CACHE_MAX = 50000
# Default per-lookup timeout (seconds) for reverse DNS.
_DEFAULT_DNS_TIMEOUT = 1.5
# Sentinel distinguishing "not cached" from a cached ``None`` (negative result).
_SENTINEL = object()


# Cache of database types keyed by path (e.g. "GeoLite2-City", "GeoLite2-ASN").
_db_types: dict = {}


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
            try:
                _db_types[db_path] = reader.metadata().database_type
            except Exception:  # pragma: no cover - defensive
                _db_types[db_path] = ""
            logger.info(
                "GeoIP database loaded from %s (%s)",
                db_path,
                _db_types.get(db_path, "?"),
            )
            return reader
        except Exception as exc:  # pragma: no cover - optional dependency/path
            logger.warning("GeoIP database unavailable (%s): %s", db_path, exc)
            _failed_paths.add(db_path)
            return None


def classify_location(
    ip: Optional[str], geoip_db_path: Optional[str] = None
) -> Dict[str, Optional[str]]:
    """Return ``{"label": <str>, "country_code": <str|None>}`` for *ip*.

    ``label`` is a human-readable location/network string (the same value
    :func:`classify_ip` returns). ``country_code`` is the ISO 3166-1 alpha-2
    code (e.g. ``"US"``) when a GeoLite2 database resolves a public address,
    otherwise ``None`` — local/loopback/link-local addresses and unresolved
    public IPs have no flag.

    Never raises and never makes a network call.
    """
    if not ip:
        return {"label": "Unknown", "country_code": None}

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return {"label": "Unknown", "country_code": None}

    if addr.is_loopback:
        return {"label": "Local (loopback)", "country_code": None}
    if addr.is_link_local:
        return {"label": "Local (link-local)", "country_code": None}
    if addr.is_private:
        return {"label": "Local Network", "country_code": None}

    # Public address — try optional country (and city) resolution.
    if geoip_db_path:
        reader = _get_reader(geoip_db_path)
        if reader is not None:
            db_type = _db_types.get(geoip_db_path, "")
            try:
                if "City" in db_type:
                    response = reader.city(ip)
                    city = response.city.name
                else:
                    response = reader.country(ip)
                    city = None
                name = response.country.name
                iso = response.country.iso_code
                if name:
                    return {
                        "label": name,
                        "country_code": iso.upper() if iso else None,
                        "city": city,
                    }
            except Exception:  # pragma: no cover - address not in DB, etc.
                pass

    return {"label": "Internet (Public)", "country_code": None, "city": None}


def classify_ip(ip: Optional[str], geoip_db_path: Optional[str] = None) -> str:
    """Return a location/network label for *ip* (see :func:`classify_location`).

    Thin string-only wrapper retained for backwards compatibility.
    """
    return classify_location(ip, geoip_db_path)["label"]


def resolve_asn(ip: Optional[str], asn_db_path: Optional[str] = None) -> Optional[str]:
    """Return the network operator / ISP (AS organisation) for a public *ip*.

    Requires a MaxMind GeoLite2-ASN database. Returns ``None`` for private/local
    addresses, when no ASN database is configured, or when the lookup misses.
    Never raises and never makes a network call.
    """
    if not ip or not asn_db_path:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.is_loopback or addr.is_link_local or addr.is_private:
        return None
    reader = _get_reader(asn_db_path)
    if reader is None:
        return None
    try:
        org = reader.asn(ip).autonomous_system_organization
        return org[:128] if org else None
    except Exception:  # pragma: no cover - address not in DB, etc.
        return None


def resolve_hostname(
    ip: Optional[str], timeout: float = _DEFAULT_DNS_TIMEOUT
) -> Optional[str]:
    """Reverse-resolve *ip* to a hostname (PTR record), or ``None``.

    awstats-style reverse DNS. Results are cached (positive and negative) so a
    given address is only looked up once. A short socket timeout bounds the cost
    of a slow or unreachable resolver. This makes a network call and is intended
    to run from the background recorder thread, never on the request path.
    """
    if not ip:
        return None

    cached = _hostname_cache.get(ip, _SENTINEL)
    if cached is not _SENTINEL:
        return cached  # type: ignore[return-value]

    # Don't attempt reverse DNS for non-addresses.
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        _cache_hostname(ip, None)
        return None

    hostname: Optional[str] = None
    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(max(0.1, float(timeout)))
        hostname = socket.gethostbyaddr(ip)[0] or None
        if hostname:
            hostname = hostname[:255]
    except Exception:
        # NXDOMAIN, timeout, no PTR record, etc. — cache the miss.
        hostname = None
    finally:
        try:
            socket.setdefaulttimeout(previous_timeout)
        except Exception:  # pragma: no cover - defensive
            pass

    _cache_hostname(ip, hostname)
    return hostname


def _cache_hostname(ip: str, hostname: Optional[str]) -> None:
    """Store a reverse-DNS result, bounding the cache size."""
    with _hostname_lock:
        if len(_hostname_cache) >= _HOSTNAME_CACHE_MAX:
            # Cheap eviction: clear the whole cache rather than tracking LRU.
            _hostname_cache.clear()
        _hostname_cache[ip] = hostname


def reset_readers() -> None:
    """Close and forget cached readers (used when the DB path changes)."""
    with _readers_lock:
        for reader in _readers.values():
            try:
                reader.close()
            except Exception:
                pass
        _readers.clear()
        _db_types.clear()
        _failed_paths.clear()


__all__ = [
    "classify_ip",
    "classify_location",
    "resolve_asn",
    "resolve_hostname",
    "reset_readers",
]
