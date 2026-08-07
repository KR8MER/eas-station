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

"""The XML sitemap for the public surface."""

from app_core.models import (
    CAPAlert,
)
from app_utils import utc_now
from flask import url_for, Response
from html import escape
from typing import Dict, List, Tuple


def register(app, route_logger) -> None:
    """Attach the sitemap routes to the Flask app."""
    @app.route("/sitemap.xml")
    def sitemap():
        """Expose an XML sitemap for search engines and uptime robots."""

        urls: List[Dict[str, str]] = []
        today_iso = utc_now().date().isoformat()

        static_endpoints: List[Tuple[str, str, str]] = [
            ("index", "daily", "1.0"),
            ("stats", "daily", "0.8"),
            ("alerts", "hourly", "0.9"),
            ("help_page", "weekly", "0.5"),
            ("about_page", "weekly", "0.5"),
            ("attribution_page", "monthly", "0.4"),
            ("privacy_page", "yearly", "0.3"),
            ("terms_page", "yearly", "0.3"),
            ("sms_compliance_page", "yearly", "0.3"),
            ("system_health_page", "hourly", "0.6"),
            ("logs", "hourly", "0.4"),
        ]

        for endpoint, changefreq, priority in static_endpoints:
            try:
                urls.append(
                    {
                        "loc": url_for(endpoint, _external=True),
                        "lastmod": today_iso,
                        "changefreq": changefreq,
                        "priority": priority,
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive
                route_logger.debug("Skipping sitemap endpoint %s: %s", endpoint, exc)

        alert_entries: List[CAPAlert] = []
        try:
            alert_entries = (
                CAPAlert.query.order_by(CAPAlert.sent.desc())
                .limit(app.config.get("SITEMAP_ALERT_LIMIT", 50))
                .all()
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.warning("Unable to load alerts for sitemap: %s", exc)

        for alert in alert_entries:
            try:
                alert_url = url_for("api.alert_detail", alert_id=alert.id, _external=True)
            except Exception as exc:  # pragma: no cover - defensive
                route_logger.debug("Skipping alert %s in sitemap: %s", alert.id, exc)
                continue

            last_modified = alert.updated_at or alert.sent or utc_now()
            urls.append(
                {
                    "loc": alert_url,
                    "lastmod": last_modified.isoformat(),
                    "changefreq": "hourly",
                    "priority": "0.7",
                }
            )

        xml_lines = [
            "<?xml version='1.0' encoding='UTF-8'?>",
            "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>",
        ]

        for entry in urls:
            xml_lines.append("  <url>")
            xml_lines.append(f"    <loc>{escape(entry['loc'])}</loc>")
            if entry.get("lastmod"):
                xml_lines.append(f"    <lastmod>{escape(entry['lastmod'])}</lastmod>")
            xml_lines.append(f"    <changefreq>{entry['changefreq']}</changefreq>")
            xml_lines.append(f"    <priority>{entry['priority']}</priority>")
            xml_lines.append("  </url>")

        xml_lines.append("</urlset>")

        return Response("\n".join(xml_lines), mimetype="application/xml")


__all__ = ["register"]
