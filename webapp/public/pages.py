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

"""Static and near-static public pages: landing, about/help, policy documents."""

from app_core.system_health import get_system_health
from app_utils import format_bytes, format_uptime
from flask import render_template
from webapp import documentation


def register(app, route_logger, policy_docs_root) -> None:
    """Attach the pages routes to the Flask app."""
    def _render_policy_page(doc_filename: str, page_title: str):
        policy_path = policy_docs_root / doc_filename
        try:
            with policy_path.open("r", encoding="utf-8") as md_file:
                markdown_content = md_file.read()
            html_content = documentation._markdown_to_html(markdown_content)
            structure = documentation._get_docs_structure()
            return render_template(
                "doc_viewer.html",
                title=page_title,
                content=html_content,
                doc_path=f"policies/{policy_path.stem}",
                structure=structure,
            )
        except FileNotFoundError:
            route_logger.error("Policy document not found: %s", policy_path)
        except Exception as exc:  # pragma: no cover - renderable fallback
            route_logger.error("Error rendering policy page %s: %s", doc_filename, exc)

        # Fallback to legacy static templates to keep the route available
        return render_template(f"{policy_path.stem}.html")

    @app.route("/")
    def index():
        try:
            return render_template("index.html")
        except Exception as exc:  # pragma: no cover - fallback rendering
            route_logger.error("Error rendering index template: %s", exc)
            return (
                "<h1>NOAA CAP Alerts System</h1><p>Map interface loading...</p>"
                "<p><a href='/stats'>📊 Statistics</a> | "
                "<a href='/alerts'>📝 Alerts History</a> | "
                "<a href='/admin'>⚙️ Admin</a></p>"
            )

    @app.route("/about")
    def about_page():
        try:
            return render_template("about.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering about page: %s", exc)
            return (
                "<h1>About</h1><p>Project documentation is available in docs/reference/ABOUT.md on the server.</p>"
            )

    @app.route("/help")
    def help_page():
        try:
            return render_template("help.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering help page: %s", exc)
            return (
                "<h1>Help</h1><p>Refer to docs/guides/HELP.md in the repository for the full operations guide.</p>"
            )

    @app.route("/style-guide")
    def style_guide_page():
        """Design-system reference: the standard page header, cards, and components."""
        try:
            return render_template("style_guide.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering style guide page: %s", exc)
            return (
                "<h1>Style Guide</h1><p>See templates/style_guide.html and "
                "docs/frontend/COMPONENT_LIBRARY.md in the repository.</p>"
            )

    @app.route("/attribution")
    def attribution_page():
        """Dedicated page crediting open-source dependencies, data sources, and licensing."""
        try:
            return render_template("attribution.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering attribution page: %s", exc)
            return (
                "<h1>Attribution &amp; Credits</h1>"
                "<p>EAS Station is built on open-source software. See "
                "docs/reference/dependency_attribution.md in the repository for the full list.</p>"
            )

    @app.route("/support")
    def support_page():
        """Dedicated page inviting users to support the project on Ko-fi."""
        try:
            return render_template("support.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering support page: %s", exc)
            return (
                "<h1>Support EAS Station</h1>"
                "<p>EAS Station is free and open source. You can support development "
                "at <a href='https://ko-fi.com/easstation'>ko-fi.com/easstation</a>.</p>"
            )

    @app.route("/navigation")
    def site_navigation():
        """Quick access page showing all features organized by category."""
        try:
            return render_template("site_navigation.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering site navigation page: %s", exc)
            return (
                "<h1>Site Navigation</h1><p>Quick access to all pages.</p>"
                "<p><a href='/'>Dashboard</a> | <a href='/alerts'>Alerts</a> | <a href='/admin'>Admin</a></p>"
            )

    @app.route("/terms")
    def terms_page():
        return _render_policy_page("TERMS_OF_USE.md", "Terms of Use")

    @app.route("/privacy")
    def privacy_page():
        return _render_policy_page("PRIVACY_POLICY.md", "Privacy Policy")

    @app.route("/sms-compliance")
    def sms_compliance_page():
        return render_template("sms_compliance.html")

    @app.route("/system_health")
    def system_health_page():
        try:
            health_data = get_system_health(logger=route_logger)

            # Check if the backend returned an error instead of health data
            if "error" in health_data and "system" not in health_data:
                error_msg = health_data.get("error", "Unknown error")
                route_logger.error("System health backend error: %s", error_msg)
                return (
                    "<h1>Error loading system health</h1>"
                    f"<p>{error_msg}</p><p><a href='/'>← Back to Main</a></p>"
                )

            template_context = dict(health_data)
            template_context["format_bytes"] = format_bytes
            template_context["format_uptime"] = format_uptime
            # Pass raw health_data for tojson filter in template (handles HTML-safe escaping)
            template_context["health_data_raw"] = health_data
            return render_template("system_health.html", **template_context)
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error loading system health: %s", exc)
            return (
                "<h1>Error loading system health</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/audio-monitor")
    def audio_monitoring():
        """Audio monitoring page with live audio playback."""
        try:
            return render_template("audio_monitoring.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error loading audio monitoring: %s", exc)
            return (
                "<h1>Error loading audio monitoring</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )


__all__ = ["register"]
