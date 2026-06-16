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

"""Traffic anomaly detection for the Traffic Analytics dashboard.

Computes operationally interesting deviations from the recorded request log so
the dashboard can surface them prominently (and an API endpoint can expose
them). Detection is intentionally on-demand and self-contained — it runs over
the same window the operator is already viewing and never couples to the EAS
broadcast notification pipeline.

Checks (each tunable from the Traffic settings UI):

* **High error rate** — 4xx/5xx as a share of all hits exceeds a threshold.
* **5xx surge** — absolute count of server errors exceeds a threshold.
* **Scanner activity** — a single source IP produced many 4xx responses
  (typical of vulnerability scanners probing for files that don't exist).
* **Login brute force** — a single source IP produced many failed logins.
* **Traffic spike** — total hits jumped sharply versus the previous,
  equal-length period.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import func

from app_core.extensions import db
from app_core.analytics.traffic_filters import TrafficFilters
from app_core.analytics.web_traffic import WebRequestLog

# Below this many hits in the window, ratio-based checks are too noisy to be
# meaningful, so they're skipped (a 100% error rate on 2 requests isn't news).
_MIN_HITS_FOR_RATE = 20
# A traffic spike must be at least this multiple of the previous period *and*
# clear an absolute floor, so tiny baselines don't trigger constant alerts.
_SPIKE_RATIO = 3.0
_SPIKE_MIN_HITS = 100


def _settings_thresholds() -> Dict[str, Any]:
    """Load anomaly thresholds from settings, falling back to defaults."""
    from app_core.analytics.web_traffic import TrafficAnalyticsSettings

    defaults = {
        "anomaly_detection_enabled": True,
        "anomaly_error_rate_pct": 25,
        "anomaly_5xx_threshold": 25,
        "anomaly_failed_login_threshold": 10,
        "anomaly_scanner_threshold": 50,
    }
    try:
        row = TrafficAnalyticsSettings.query.first()
        if row is None:
            return defaults
        return {
            "anomaly_detection_enabled": bool(getattr(row, "anomaly_detection_enabled", True)),
            "anomaly_error_rate_pct": int(getattr(row, "anomaly_error_rate_pct", 25) or 25),
            "anomaly_5xx_threshold": int(getattr(row, "anomaly_5xx_threshold", 25) or 25),
            "anomaly_failed_login_threshold": int(
                getattr(row, "anomaly_failed_login_threshold", 10) or 10
            ),
            "anomaly_scanner_threshold": int(getattr(row, "anomaly_scanner_threshold", 50) or 50),
        }
    except Exception:  # pragma: no cover - defensive: never break the dashboard
        try:
            db.session.rollback()
        except Exception:
            pass
        return defaults


def _anomaly(severity: str, kind: str, title: str, detail: str, value, threshold, **extra) -> Dict[str, Any]:
    item = {
        "severity": severity,  # "critical" | "warning" | "info"
        "type": kind,
        "title": title,
        "detail": detail,
        "value": value,
        "threshold": threshold,
    }
    item.update(extra)
    return item


def detect_anomalies(
    days: int = 30, filters: Optional[TrafficFilters] = None
) -> List[Dict[str, Any]]:
    """Return a list of detected anomalies for the active window/filters."""
    flt = filters if filters is not None else TrafficFilters(days=days)
    cfg = _settings_thresholds()
    if not cfg["anomaly_detection_enabled"]:
        return []

    anomalies: List[Dict[str, Any]] = []
    try:
        anomalies.extend(_check_error_rate(flt, cfg))
        anomalies.extend(_check_5xx_surge(flt, cfg))
        anomalies.extend(_check_scanners(flt, cfg))
        anomalies.extend(_check_login_bruteforce(flt, cfg))
        anomalies.extend(_check_traffic_spike(flt))
    except Exception:  # pragma: no cover - defensive
        try:
            db.session.rollback()
        except Exception:
            pass
        return []

    # Most severe first so the dashboard banner leads with the worst news.
    rank = {"critical": 0, "warning": 1, "info": 2}
    anomalies.sort(key=lambda a: rank.get(a["severity"], 3))
    return anomalies


def _check_error_rate(flt: TrafficFilters, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    total = flt.apply(WebRequestLog.query).count()
    if total < _MIN_HITS_FOR_RATE:
        return []
    errors = flt.apply(WebRequestLog.query.filter(WebRequestLog.status_code >= 400)).count()
    rate = round(100.0 * errors / total, 1)
    threshold = cfg["anomaly_error_rate_pct"]
    if rate >= threshold:
        severity = "critical" if rate >= threshold * 2 else "warning"
        return [
            _anomaly(
                severity,
                "error_rate",
                f"Elevated error rate: {rate}%",
                f"{errors:,} of {total:,} requests returned 4xx/5xx "
                f"(threshold {threshold}%).",
                rate,
                threshold,
                drilldown={"status_family": 4},
            )
        ]
    return []


def _check_5xx_surge(flt: TrafficFilters, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    count = flt.apply(
        WebRequestLog.query.filter(
            WebRequestLog.status_code >= 500, WebRequestLog.status_code < 600
        )
    ).count()
    threshold = cfg["anomaly_5xx_threshold"]
    if count >= threshold:
        severity = "critical" if count >= threshold * 2 else "warning"
        return [
            _anomaly(
                severity,
                "server_errors",
                f"Server errors (5xx): {count:,}",
                f"{count:,} server-error responses in this window "
                f"(threshold {threshold}). Check application logs.",
                count,
                threshold,
                drilldown={"status_family": 5},
            )
        ]
    return []


def _check_scanners(flt: TrafficFilters, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    threshold = cfg["anomaly_scanner_threshold"]
    row = (
        flt.apply(
            db.session.query(
                WebRequestLog.ip_address,
                func.count(WebRequestLog.id).label("errors"),
            ).filter(
                WebRequestLog.status_code >= 400,
                WebRequestLog.status_code < 500,
                WebRequestLog.ip_address.isnot(None),
            )
        )
        .group_by(WebRequestLog.ip_address)
        .order_by(func.count(WebRequestLog.id).desc())
        .first()
    )
    if row and int(row.errors) >= threshold:
        return [
            _anomaly(
                "warning",
                "scanner",
                f"Possible scanner: {row.ip_address}",
                f"{int(row.errors):,} client-error (4xx) responses from a single "
                f"source (threshold {threshold}) — typical of a vulnerability scanner.",
                int(row.errors),
                threshold,
                ip_address=row.ip_address,
                drilldown={"ip": row.ip_address},
            )
        ]
    return []


def _check_login_bruteforce(flt: TrafficFilters, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    from app_core.auth.audit import AuditAction, AuditLog

    threshold = cfg["anomaly_failed_login_threshold"]
    row = (
        flt.filter_timestamp(
            db.session.query(
                AuditLog.ip_address,
                func.count(AuditLog.id).label("failures"),
            ).filter(
                AuditLog.action == AuditAction.LOGIN_FAILURE.value,
                AuditLog.ip_address.isnot(None),
            ),
            AuditLog.timestamp,
        )
        .group_by(AuditLog.ip_address)
        .order_by(func.count(AuditLog.id).desc())
        .first()
    )
    if row and int(row.failures) >= threshold:
        severity = "critical" if int(row.failures) >= threshold * 2 else "warning"
        return [
            _anomaly(
                severity,
                "brute_force",
                f"Failed-login burst: {row.ip_address}",
                f"{int(row.failures):,} failed login attempts from a single source "
                f"(threshold {threshold}) — possible brute-force attempt.",
                int(row.failures),
                threshold,
                ip_address=row.ip_address,
            )
        ]
    return []


def _check_traffic_spike(flt: TrafficFilters) -> List[Dict[str, Any]]:
    current = flt.apply(WebRequestLog.query).count()
    if current < _SPIKE_MIN_HITS:
        return []
    prev = flt.previous().apply(WebRequestLog.query).count()
    if prev <= 0:
        return []
    ratio = current / prev
    if ratio >= _SPIKE_RATIO:
        return [
            _anomaly(
                "info",
                "traffic_spike",
                f"Traffic spike: {ratio:.1f}× previous period",
                f"{current:,} hits vs {prev:,} in the previous equal-length period.",
                current,
                prev,
            )
        ]
    return []


__all__ = ["detect_anomalies"]
