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

"""Web-traffic analytics models and helpers (webalizer/awstats-style).

This module backs the Traffic Analytics dashboard. Every (non-static) HTTP
request handled by the Flask app is recorded as a :class:`WebRequestLog` row by
the buffered recorder in ``traffic_recorder.py``. The dashboard then aggregates
those rows into the familiar web-stats views: hits over time, top pages, top
visitors, status-code mix, browser/OS breakdown, and referrers.

:class:`TrafficAnalyticsSettings` is a single-row settings table that lets an
operator enable/disable collection, set the retention window, and tune what is
recorded entirely from the web UI (no environment variables, no CLI).
"""

from typing import Any, Dict, Optional

import re

from app_core.extensions import db
from app_utils import utc_now

# Path prefixes that are never recorded — high-volume, low-information noise that
# would bloat the table without adding analytical value. Static assets and the
# Socket.IO transport are pure plumbing; the favicon and health probe fire on a
# fixed cadence regardless of real visitor activity.
ALWAYS_EXCLUDED_PREFIXES = (
    "/static/",
    "/socket.io/",
    "/favicon",
    "/health",
    "/api/system_status",
    "/api/system_health",
    "/api/traffic/",  # don't let the dashboard's own polling skew its numbers
)

# Lightweight, dependency-free User-Agent classification. Order matters: the
# first matching needle wins, so more specific tokens are listed before the
# generic engines they are built on (e.g. Edge before Chrome).
_BOT_NEEDLES = (
    "bot", "spider", "crawl", "slurp", "bingpreview", "facebookexternalhit",
    "monitoring", "uptime", "curl", "wget", "python-requests", "httpx",
    "go-http-client", "headlesschrome", "semrush", "ahrefs", "pingdom",
)
_BROWSER_NEEDLES = (
    ("Edg", "Edge"),
    ("OPR", "Opera"),
    ("Opera", "Opera"),
    ("SamsungBrowser", "Samsung Internet"),
    ("Firefox", "Firefox"),
    ("Chrome", "Chrome"),
    ("Safari", "Safari"),
    ("MSIE", "Internet Explorer"),
    ("Trident", "Internet Explorer"),
)
_OS_NEEDLES = (
    ("Windows NT 10", "Windows 10/11"),
    ("Windows", "Windows"),
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Android", "Android"),
    ("Mac OS X", "macOS"),
    ("Macintosh", "macOS"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def parse_excluded_paths(raw: Optional[str]) -> tuple:
    """Split an operator's newline/comma-separated skip-path list into prefixes."""
    if not raw:
        return ()
    parts = (p.strip() for chunk in raw.split("\n") for p in chunk.split(","))
    return tuple(p for p in parts if p)


def is_excluded_path(path: str, extra_prefixes: tuple = ()) -> bool:
    """Return ``True`` when *path* should never be recorded for analytics.

    Always rejects the built-in plumbing prefixes; *extra_prefixes* adds any
    operator-configured skip paths (awstats-style "SkipFiles").
    """
    if not path:
        return True
    if any(path.startswith(prefix) for prefix in ALWAYS_EXCLUDED_PREFIXES):
        return True
    return any(path.startswith(prefix) for prefix in extra_prefixes if prefix)


# Friendly names for common robots/spiders, matched against the lowercased UA.
# Order matters only for overlapping tokens; first match wins.
_BOT_NAMES = (
    ("googlebot", "Googlebot"), ("bingbot", "Bingbot"), ("yandexbot", "YandexBot"),
    ("duckduckbot", "DuckDuckBot"), ("baiduspider", "Baidu Spider"),
    ("applebot", "Applebot"), ("petalbot", "PetalBot"), ("bytespider", "Bytespider"),
    ("ahrefsbot", "AhrefsBot"), ("semrushbot", "SemrushBot"), ("mj12bot", "Majestic"),
    ("dotbot", "DotBot"), ("facebookexternalhit", "Facebook"), ("twitterbot", "Twitterbot"),
    ("slackbot", "Slackbot"), ("telegrambot", "TelegramBot"), ("discordbot", "Discordbot"),
    ("gptbot", "GPTBot"), ("claudebot", "ClaudeBot"), ("anthropic", "ClaudeBot"),
    ("ccbot", "CCBot"), ("perplexitybot", "PerplexityBot"), ("amazonbot", "Amazonbot"),
    ("uptimerobot", "UptimeRobot"), ("pingdom", "Pingdom"), ("statuscake", "StatusCake"),
    ("bingpreview", "Bing Preview"), ("slurp", "Yahoo Slurp"),
    ("curl", "curl"), ("wget", "Wget"), ("python-requests", "python-requests"),
    ("httpx", "httpx"), ("go-http-client", "Go HTTP client"), ("headlesschrome", "HeadlessChrome"),
)


def classify_bot(user_agent: Optional[str]) -> str:
    """Return a friendly robot/spider name for a bot User-Agent string."""
    if not user_agent:
        return "Unknown bot"
    low = user_agent.lower()
    for needle, label in _BOT_NAMES:
        if needle in low:
            return label
    return "Other bot"


def _extract_browser_version(user_agent: str, needle: str) -> Optional[str]:
    """Pull a ``major.minor`` version for the matched browser *needle*.

    Most engines report ``Name/<version>``; Safari is the exception — it carries
    its user-facing version in a separate ``Version/<x.y>`` token while
    ``Safari/<build>`` is the (unhelpful) WebKit build number.
    """
    token = "Version" if needle == "Safari" else needle
    match = re.search(re.escape(token) + r"[/ ]?(\d+(?:\.\d+)?)", user_agent)
    return match.group(1) if match else None


def classify_user_agent(user_agent: Optional[str]) -> Dict[str, Any]:
    """Best-effort classification of a User-Agent string.

    Returns a dict with ``browser``, ``browser_version``, ``os`` and ``is_bot``.
    Intentionally simple substring matching — adequate for a single-station
    appliance and avoids a heavyweight UA-parsing dependency.
    """
    if not user_agent:
        return {"browser": None, "browser_version": None, "os": None, "is_bot": False}

    ua = user_agent
    ua_lower = ua.lower()

    is_bot = any(needle in ua_lower for needle in _BOT_NEEDLES)

    browser: Optional[str] = None
    browser_version: Optional[str] = None
    for needle, label in _BROWSER_NEEDLES:
        if needle in ua:
            browser = label
            browser_version = _extract_browser_version(ua, needle)
            break

    os_name: Optional[str] = None
    for needle, label in _OS_NEEDLES:
        if needle in ua:
            os_name = label
            break

    return {
        "browser": browser,
        "browser_version": browser_version,
        "os": os_name,
        "is_bot": is_bot,
    }


class WebRequestLog(db.Model):
    """A single recorded HTTP request, for web-traffic analytics.

    Rows are written asynchronously by the buffered recorder so the request path
    itself never pays for a synchronous database write.
    """

    __tablename__ = "web_request_logs"

    id = db.Column(db.Integer, primary_key=True)

    timestamp = db.Column(
        db.DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    # Request line
    method = db.Column(db.String(8), nullable=False)
    path = db.Column(db.String(512), nullable=False, index=True)
    status_code = db.Column(db.Integer, nullable=False, index=True)
    response_time_ms = db.Column(db.Integer, nullable=True)
    content_length = db.Column(db.Integer, nullable=True)

    # Who / from where
    ip_address = db.Column(db.String(64), nullable=True, index=True)
    # Reverse-DNS (PTR) hostname for ip_address, resolved by the background
    # recorder when hostname resolution is enabled (awstats-style). Null when
    # resolution is disabled, pending, or the address has no PTR record.
    hostname = db.Column(db.String(255), nullable=True, index=True)
    user_agent = db.Column(db.String(512), nullable=True)
    referer = db.Column(db.String(512), nullable=True)

    # Authenticated identity (denormalized so deleting a user keeps history)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    username = db.Column(db.String(128), nullable=True)
    is_authenticated = db.Column(db.Boolean, nullable=False, default=False)

    # Derived classification
    is_api = db.Column(db.Boolean, nullable=False, default=False)
    is_bot = db.Column(db.Boolean, nullable=False, default=False, index=True)
    browser = db.Column(db.String(64), nullable=True)
    # Browser major[.minor] version parsed from the UA (e.g. "120" or "16.1").
    browser_version = db.Column(db.String(32), nullable=True)
    os = db.Column(db.String(64), nullable=True)

    # Extended awstats-style attributes
    # screen_resolution e.g. "1920x1080" — captured client-side via a beacon and
    # carried on subsequent requests in the session cookie.
    screen_resolution = db.Column(db.String(20), nullable=True)
    # country/network label from geo.classify_location (e.g. "Local Network", a
    # country name when a GeoIP DB is configured, or "Internet (Public)").
    country = db.Column(db.String(64), nullable=True)
    # ISO 3166-1 alpha-2 country code (e.g. "US") when GeoIP resolved a public
    # address, used to render a flag on the dashboard. Null otherwise.
    country_code = db.Column(db.String(2), nullable=True)
    # City name when a GeoLite2 City database is configured (null for Country DBs).
    city = db.Column(db.String(128), nullable=True)
    # State / province (most-specific subdivision) and its short ISO code
    # (e.g. "Ohio"/"OH") — also from a GeoLite2 City database. Lets the dashboard
    # disambiguate same-named cities ("Springfield, IL" vs "Springfield, MO").
    region = db.Column(db.String(96), nullable=True)
    region_code = db.Column(db.String(8), nullable=True)
    # Autonomous System organisation / ISP when a GeoLite2 ASN database is set.
    asn_org = db.Column(db.String(128), nullable=True)
    # Preferred language parsed from the Accept-Language header (e.g. "en-US").
    language = db.Column(db.String(20), nullable=True)

    __table_args__ = (
        db.Index("idx_web_request_logs_path_time", "path", "timestamp"),
        db.Index("idx_web_request_logs_ip_time", "ip_address", "timestamp"),
        db.Index("idx_web_request_logs_bot_time", "is_bot", "timestamp"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert the record to a dictionary for API responses."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "content_length": self.content_length,
            "ip_address": self.ip_address,
            "hostname": self.hostname,
            "user_agent": self.user_agent,
            "referer": self.referer,
            "user_id": self.user_id,
            "username": self.username,
            "is_authenticated": bool(self.is_authenticated),
            "is_api": bool(self.is_api),
            "is_bot": bool(self.is_bot),
            "browser": self.browser,
            "browser_version": self.browser_version,
            "os": self.os,
            "screen_resolution": self.screen_resolution,
            "country": self.country,
            "country_code": self.country_code,
            "city": self.city,
            "region": self.region,
            "region_code": self.region_code,
            "asn_org": self.asn_org,
            "language": self.language,
        }


class TrafficAnalyticsSettings(db.Model):
    """Single-row configuration for web-traffic collection.

    Managed entirely through the Traffic Analytics dashboard UI. Use
    :meth:`get_settings` to fetch the live row (creating defaults on first use)
    and :meth:`as_config` for the lightweight dict the recorder caches.
    """

    __tablename__ = "traffic_analytics_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Master switch for request collection.
    enabled = db.Column(db.Boolean, nullable=False, default=True)

    # How long recorded rows are kept before the recorder prunes them.
    retention_days = db.Column(db.Integer, nullable=False, default=90)

    # Whether to record /api/ requests (XHR/JSON traffic) in addition to pages.
    log_api_requests = db.Column(db.Boolean, nullable=False, default=True)

    # Whether to record only authenticated requests (privacy-conscious mode).
    log_authenticated_only = db.Column(db.Boolean, nullable=False, default=False)

    # Whether to drop requests classified as bots/crawlers rather than store them.
    exclude_bots = db.Column(db.Boolean, nullable=False, default=False)

    # Optional path to a MaxMind GeoLite2 .mmdb database. When set (and the
    # geoip2 package is installed), public visitor IPs resolve to country names
    # on the dashboard. Leave blank for local-network-only classification.
    geoip_database_path = db.Column(db.String(512), nullable=True)

    # Optional path to a MaxMind GeoLite2-ASN .mmdb. When set, public visitor IPs
    # resolve to their network operator / ISP (autonomous-system organisation).
    geoip_asn_database_path = db.Column(db.String(512), nullable=True)

    # Whether the background recorder performs reverse-DNS (PTR) lookups to show
    # visitor hostnames (awstats-style). Off by default: lookups hit the network
    # and may leak visitor IPs to the configured DNS resolver.
    resolve_hostnames = db.Column(db.Boolean, nullable=False, default=False)

    # Drop requests coming from the loopback interface (127.0.0.1/::1). These are
    # server-internal service-to-service calls (poller, hardware services, health
    # probes) rather than real visitors, so excluding them keeps the analytics
    # focused on actual web traffic. Real LAN/Internet clients are unaffected.
    exclude_loopback = db.Column(db.Boolean, nullable=False, default=True)

    # awstats-style "SkipFiles": newline/comma-separated path prefixes to ignore
    # in addition to the always-excluded plumbing (e.g. "/api/audio/,/metrics").
    excluded_paths = db.Column(db.Text, nullable=True)

    # Privacy: when enabled, visitor IPs are irreversibly masked at capture time
    # (IPv4 last octet / IPv6 host bits zeroed) so a raw address is never stored.
    anonymize_ip = db.Column(db.Boolean, nullable=False, default=False)

    # Anomaly detection: master switch + operator-tunable thresholds. Surfaced
    # on the dashboard banner and the /api/traffic/anomalies endpoint.
    anomaly_detection_enabled = db.Column(db.Boolean, nullable=False, default=True)
    # Error rate (% of all hits returning 4xx/5xx) that flags an anomaly.
    anomaly_error_rate_pct = db.Column(db.Integer, nullable=False, default=25)
    # Absolute 5xx count in the window that flags a server-error surge.
    anomaly_5xx_threshold = db.Column(db.Integer, nullable=False, default=25)
    # Failed logins from a single IP that flag a brute-force attempt.
    anomaly_failed_login_threshold = db.Column(db.Integer, nullable=False, default=10)
    # 4xx responses from a single IP that flag a likely vulnerability scanner.
    anomaly_scanner_threshold = db.Column(db.Integer, nullable=False, default=50)

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    DEFAULTS: Dict[str, Any] = {
        "enabled": True,
        "retention_days": 90,
        "log_api_requests": True,
        "log_authenticated_only": False,
        "exclude_bots": False,
        "geoip_database_path": None,
        "geoip_asn_database_path": None,
        "resolve_hostnames": False,
        "exclude_loopback": True,
        "excluded_paths": None,
        "anonymize_ip": False,
        "anomaly_detection_enabled": True,
        "anomaly_error_rate_pct": 25,
        "anomaly_5xx_threshold": 25,
        "anomaly_failed_login_threshold": 10,
        "anomaly_scanner_threshold": 50,
    }

    @classmethod
    def get_settings(cls) -> "TrafficAnalyticsSettings":
        """Return the singleton settings row, creating defaults if absent."""
        row = cls.query.first()
        if row is None:
            row = cls(**cls.DEFAULTS)
            db.session.add(row)
            db.session.commit()
        return row

    def as_config(self) -> Dict[str, Any]:
        """Return the recorder-facing config dict (no DB objects)."""
        return {
            "enabled": bool(self.enabled),
            "retention_days": int(self.retention_days or 90),
            "log_api_requests": bool(self.log_api_requests),
            "log_authenticated_only": bool(self.log_authenticated_only),
            "exclude_bots": bool(self.exclude_bots),
            "geoip_database_path": self.geoip_database_path or None,
            "geoip_asn_database_path": self.geoip_asn_database_path or None,
            "resolve_hostnames": bool(self.resolve_hostnames),
            "exclude_loopback": bool(self.exclude_loopback),
            "excluded_paths": self.excluded_paths or None,
            "anonymize_ip": bool(self.anonymize_ip),
            "anomaly_detection_enabled": bool(self.anomaly_detection_enabled),
            "anomaly_error_rate_pct": int(self.anomaly_error_rate_pct or 25),
            "anomaly_5xx_threshold": int(self.anomaly_5xx_threshold or 25),
            "anomaly_failed_login_threshold": int(self.anomaly_failed_login_threshold or 10),
            "anomaly_scanner_threshold": int(self.anomaly_scanner_threshold or 50),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to a dictionary for API responses."""
        data = self.as_config()
        data["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return data


__all__ = [
    "WebRequestLog",
    "TrafficAnalyticsSettings",
    "classify_user_agent",
    "classify_bot",
    "is_excluded_path",
    "parse_excluded_paths",
    "ALWAYS_EXCLUDED_PREFIXES",
]
