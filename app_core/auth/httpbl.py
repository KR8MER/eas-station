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

"""
Project Honeypot http:BL reputation client.

http:BL is a DNS-based lookup, not a bulk-downloadable list: for a visitor
at a.b.c.d, ask DNS for ``<api_key>.d.c.b.a.dnsbl.httpbl.org`` and decode the
returned ``127.<days_since_activity>.<threat_score>.<visitor_type>`` A
record. IPv4 only -- http:BL has no IPv6 lookup format. Results are cached
in Redis (24h) both to cut repeat lookups and because free http:BL keys
carry a daily query quota, so this is only ever queried from the login flow
(see webapp/admin/auth.py), never on every request.

Get a free key at https://www.projecthoneypot.org/
"""

import ipaddress
import logging
import os
import socket
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_LOOKUP_SUFFIX = "dnsbl.httpbl.org"
_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_PREFIX = "httpbl:"
_CACHE_EMPTY = "-"  # sentinel meaning "queried, not listed" (vs. cache miss)
_DNS_TIMEOUT_SECONDS = 2.0

# Visitor type bits in the response's 4th octet (may be OR'd together).
TYPE_SEARCH_ENGINE = 0
TYPE_SUSPICIOUS = 1
TYPE_HARVESTER = 2
TYPE_COMMENT_SPAMMER = 4

# A harvester/comment-spammer hit is treated as bad on its own -- those bits
# are specific enough to be low false-positive. Plain "suspicious" is the
# noisiest bit, so it additionally needs a real threat score before acting.
_SUSPICIOUS_THREAT_THRESHOLD = 25
_AUTO_BAN_HOURS = 72


def _get_settings():
    from app_core.models import ApplicationSettings
    try:
        return ApplicationSettings.query.first()
    except Exception:
        return None


def get_api_key() -> Optional[str]:
    """Configured http:BL access key: DB setting first, then HTTPBL_API_KEY env."""
    settings = _get_settings()
    if settings and settings.httpbl_api_key:
        return settings.httpbl_api_key
    return os.environ.get('HTTPBL_API_KEY') or None


def is_enabled() -> bool:
    """Whether http:BL checks are turned on AND a key is actually configured."""
    settings = _get_settings()
    if not settings or not settings.httpbl_enabled:
        return False
    return bool(get_api_key())


def _reverse_ipv4(ip_address: str) -> Optional[str]:
    try:
        ip_obj = ipaddress.ip_address(ip_address)
    except ValueError:
        return None
    if ip_obj.version != 4:
        return None
    return ".".join(reversed(ip_address.split(".")))


def _cache_get(ip_address: str):
    """Returns (result_or_None, was_cached: bool)."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        raw = client.get(_CACHE_PREFIX + ip_address)
        if raw is None:
            return None, False
        if raw == _CACHE_EMPTY:
            return None, True
        days, threat, vtype = (int(x) for x in raw.split(","))
        return {"days_since_last_activity": days, "threat_score": threat, "visitor_type": vtype}, True
    except Exception:
        return None, False


def _cache_set(ip_address: str, result: Optional[Dict]) -> None:
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        value = (
            _CACHE_EMPTY if result is None
            else f"{result['days_since_last_activity']},{result['threat_score']},{result['visitor_type']}"
        )
        client.setex(_CACHE_PREFIX + ip_address, _CACHE_TTL_SECONDS, value)
    except Exception:
        pass  # caching is purely an optimization -- never let it be fatal


def query_httpbl(ip_address: str, api_key: Optional[str] = None) -> Optional[Dict]:
    """Query http:BL for *ip_address*.

    Returns a dict with days_since_last_activity/threat_score/visitor_type,
    or None if not listed, IPv6, unreachable, or misconfigured. None is "no
    signal" -- callers must never treat it as "confirmed safe". Never raises.
    """
    reversed_octets = _reverse_ipv4(ip_address)
    if not reversed_octets:
        return None

    cached, hit = _cache_get(ip_address)
    if hit:
        return cached

    key = api_key or get_api_key()
    if not key:
        return None

    query = f"{key}.{reversed_octets}.{_LOOKUP_SUFFIX}"
    result = None
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(_DNS_TIMEOUT_SECONDS)
        answer = socket.gethostbyname(query)
        octets = [int(o) for o in answer.split(".")]
        if len(octets) == 4 and octets[0] == 127:
            result = {
                "days_since_last_activity": octets[1],
                "threat_score": octets[2],
                "visitor_type": octets[3],
            }
    except socket.gaierror:
        result = None  # NXDOMAIN -- not listed, the common case
    except Exception:
        logger.debug("http:BL lookup failed for %s", ip_address, exc_info=True)
        result = None
    finally:
        socket.setdefaulttimeout(old_timeout)

    _cache_set(ip_address, result)
    return result


def describe_visitor_type(visitor_type: int) -> str:
    labels = []
    if visitor_type & TYPE_SUSPICIOUS:
        labels.append("suspicious")
    if visitor_type & TYPE_HARVESTER:
        labels.append("harvester")
    if visitor_type & TYPE_COMMENT_SPAMMER:
        labels.append("comment spammer")
    return ", ".join(labels) if labels else "search engine"


def check_httpbl_and_ban(ip_address: str):
    """Query http:BL for *ip_address* and auto-ban it if it looks malicious.

    Only call this from the login flow. A per-request DNS lookup on every
    page load would add latency everywhere and quickly burn through a free
    key's daily query quota; login attempts are a naturally low-frequency
    choke point that also happens to be exactly where a harvester/spammer
    reputation signal is most actionable.

    Returns the created IPFilter row if banned, else None. Never raises --
    a lookup problem must never block or delay a real login.
    """
    if not ip_address or not is_enabled():
        return None
    if ip_address in ('127.0.0.1', '::1'):
        return None

    try:
        result = query_httpbl(ip_address)
        if not result:
            return None

        visitor_type = result["visitor_type"]
        threat_score = result["threat_score"]
        is_bad = (
            visitor_type & (TYPE_HARVESTER | TYPE_COMMENT_SPAMMER)
            or (visitor_type & TYPE_SUSPICIOUS and threat_score >= _SUSPICIOUS_THREAT_THRESHOLD)
        )
        if not is_bad:
            return None

        from app_core.auth.ip_filter import IPFilter, IPFilterReason, IPFilterSource, IPFilterType
        existing = IPFilter.query.filter_by(
            ip_address=ip_address,
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True,
        ).first()
        if existing:
            return None

        logger.warning(
            "http:BL flagged %s as %s (threat score %d) -- auto-banning for %dh",
            ip_address, describe_visitor_type(visitor_type), threat_score, _AUTO_BAN_HOURS,
        )
        return IPFilter.add_to_blocklist(
            ip_address=ip_address,
            reason=IPFilterReason.AUTO_MALICIOUS.value,
            description=(
                f"Project Honeypot http:BL: {describe_visitor_type(visitor_type)}, "
                f"threat score {threat_score}, last active "
                f"{result['days_since_last_activity']}d ago"
            ),
            source=IPFilterSource.HTTPBL.value,
            expires_in_hours=_AUTO_BAN_HOURS,
        )
    except Exception:
        logger.exception("http:BL check failed for %s", ip_address)
        return None
