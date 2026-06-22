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

"""Privacy / data-subject tools for Traffic Analytics (GDPR-style).

Operators occasionally need to honour a data-subject request ("erase / mask the
records associated with my IP") without shell or SQL access. These helpers do
exactly that from the web UI:

* :func:`purge_ip` — permanently delete every recorded request for an IP.
* :func:`anonymize_ip` — keep the rows (so aggregate counts stay intact) but
  irreversibly mask the IP and clear its reverse-DNS hostname.

:func:`anonymize_value` is also used by the request recorder when the operator
enables "Anonymize visitor IPs" so addresses are masked *at capture time* and a
raw address is never persisted.
"""

import ipaddress
from typing import Dict, Optional

from app_core.extensions import db
from app_core.analytics.web_traffic import WebRequestLog


def anonymize_value(ip: Optional[str]) -> Optional[str]:
    """Return a privacy-masked form of *ip* (last octet / host bits zeroed).

    IPv4 ``a.b.c.d`` → ``a.b.c.0``; IPv6 is truncated to its /48 prefix. Local /
    loopback / link-local addresses are left untouched (they identify the
    station's own services, not a visitor). Non-addresses are returned as-is.
    Never raises.
    """
    if not ip:
        return ip
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.is_loopback or addr.is_link_local:
        return ip
    try:
        if addr.version == 4:
            net = ipaddress.ip_network(f"{addr}/24", strict=False)
            return str(net.network_address)
        net = ipaddress.ip_network(f"{addr}/48", strict=False)
        return str(net.network_address)
    except ValueError:  # pragma: no cover - defensive
        return ip


def _invalidate_dashboard_cache() -> None:
    """Drop the cached dashboard payload after a data-changing action.

    Imported lazily to avoid a circular import (``traffic_stats`` imports this
    module's :func:`anonymize_value`). Best-effort: a stale cache is corrected on
    the next TTL expiry, so a failure here must never break the purge itself.
    """
    try:
        from app_core.analytics.traffic_stats import invalidate_dashboard_cache

        invalidate_dashboard_cache()
    except Exception:  # pragma: no cover - defensive
        pass


def purge_ip(ip: str) -> Dict[str, int]:
    """Permanently delete every recorded request for *ip*.

    Returns ``{"deleted": <rows>}``. Raises on database error (caller rolls back).
    """
    deleted = (
        db.session.query(WebRequestLog)
        .filter(WebRequestLog.ip_address == ip)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    _invalidate_dashboard_cache()
    return {"deleted": int(deleted or 0)}


def purge_all() -> Dict[str, int]:
    """Permanently delete **every** recorded request (full analytics reset).

    Settings (and any configured GeoIP databases) are untouched — only the
    ``web_request_logs`` rows are removed. Returns ``{"deleted": <rows>}``.
    Raises on database error (caller rolls back).
    """
    deleted = db.session.query(WebRequestLog).delete(synchronize_session=False)
    db.session.commit()
    _invalidate_dashboard_cache()
    return {"deleted": int(deleted or 0)}


def anonymize_ip(ip: str) -> Dict[str, object]:
    """Mask the IP (and clear the hostname) on every recorded request for *ip*.

    Returns ``{"updated": <rows>, "masked": <masked-ip>}``. Rows are retained so
    aggregate counts are unaffected; only the identifying address/hostname change.
    """
    masked = anonymize_value(ip)
    updated = (
        db.session.query(WebRequestLog)
        .filter(WebRequestLog.ip_address == ip)
        .update(
            {WebRequestLog.ip_address: masked, WebRequestLog.hostname: None},
            synchronize_session=False,
        )
    )
    db.session.commit()
    _invalidate_dashboard_cache()
    return {"updated": int(updated or 0), "masked": masked}


__all__ = ["anonymize_value", "purge_ip", "purge_all", "anonymize_ip"]
