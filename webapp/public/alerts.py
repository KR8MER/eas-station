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

"""The /alerts browse surface and its PDF export."""

from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.eas_storage import get_eas_static_prefix, format_local_datetime
from app_core.extensions import db
from app_core.models import (
    CAPAlert,
    EASMessage,
    ManualEASActivation,
)
from app_utils import utc_now
from app_utils.pdf_generator import generate_pdf_document
from datetime import datetime
from flask import render_template, request, url_for, Response
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError
from typing import Any, Dict, List, Optional


def register(app, route_logger) -> None:
    """Attach the alerts routes to the Flask app."""
    @app.route("/alerts")
    def alerts():
        try:
            # Rollback any failed transaction before starting new queries.
            # This prevents "current transaction is aborted" errors that occur when
            # a previous request left the database connection in a bad state.
            # PostgreSQL requires a rollback before new commands can be issued when
            # a transaction has failed. This is a defensive measure for robustness.
            try:
                db.session.rollback()
            except Exception:
                pass

            # Validate pagination parameters
            page = request.args.get("page", 1, type=int)
            page = max(1, page)  # Ensure page is at least 1
            per_page = request.args.get("per_page", 25, type=int)
            per_page = min(max(per_page, 10), 100)  # Clamp between 10 and 100

            search = request.args.get("search", "").strip()
            status_filter = request.args.get("status", "").strip()
            severity_filter = request.args.get("severity", "").strip()
            event_filter = request.args.get("event", "").strip()
            source_filter = request.args.get("source", "").strip()
            vtec_office_filter = request.args.get("vtec_office", "").strip()
            vtec_etn_filter = request.args.get("vtec_etn", "").strip()
            vtec_year_filter = request.args.get("vtec_year", "").strip()
            show_expired_raw = request.args.get("show_expired", "")
            show_expired = str(show_expired_raw).lower() in {
                "true",
                "1",
                "t",
                "yes",
                "on",
            }
            show_superseded_raw = request.args.get("show_superseded", "")
            show_superseded = str(show_superseded_raw).lower() in {
                "true",
                "1",
                "t",
                "yes",
                "on",
            }
            date_from = request.args.get("date_from", "").strip()
            date_to = request.args.get("date_to", "").strip()

            # Sorting parameters
            _sortable_columns = {
                "event": CAPAlert.event,
                "severity": CAPAlert.severity,
                "status": CAPAlert.status,
                "source": CAPAlert.source,
                "sent": CAPAlert.sent,
                "expires": CAPAlert.expires,
                "headline": CAPAlert.headline,
                "area": CAPAlert.area_desc,
            }
            sort_by = request.args.get("sort", "sent").strip().lower()
            sort_dir = request.args.get("direction", "desc").strip().lower()
            if sort_by not in _sortable_columns:
                sort_by = "sent"
            if sort_dir not in {"asc", "desc"}:
                sort_dir = "desc"

            # Fetch filter options and counts for the template
            # Default values in case of database errors
            statuses: List[str] = []
            severities: List[str] = []
            events: List[str] = []
            sources: List[str] = []
            active_alerts: int = 0
            expired_alerts: int = 0
            total_alerts: int = 0
            superseded_count: int = 0

            try:
                # Fetch all distinct filter options in a single database transaction
                statuses = [
                    row[0] for row in
                    db.session.query(CAPAlert.status)
                    .filter(CAPAlert.status.isnot(None))
                    .distinct()
                    .order_by(CAPAlert.status)
                    .all()
                ]
                severities = [
                    row[0] for row in
                    db.session.query(CAPAlert.severity)
                    .filter(CAPAlert.severity.isnot(None))
                    .distinct()
                    .order_by(CAPAlert.severity)
                    .all()
                ]
                events = [
                    row[0] for row in
                    db.session.query(CAPAlert.event)
                    .filter(CAPAlert.event.isnot(None))
                    .distinct()
                    .order_by(CAPAlert.event)
                    .all()
                ]
                sources = [
                    row[0] for row in
                    db.session.query(CAPAlert.source)
                    .filter(CAPAlert.source.isnot(None))
                    .distinct()
                    .order_by(CAPAlert.source)
                    .all()
                ]
                # Get alert counts
                active_alerts = get_active_alerts_query().count()
                expired_alerts = get_expired_alerts_query().count()
                total_alerts = CAPAlert.query.count()
                superseded_count = (
                    CAPAlert.query
                    .filter(CAPAlert.superseded_by_id.isnot(None))
                    .count()
                )
            except OperationalError as exc:
                # Database connection or operational error - rollback and use defaults
                db.session.rollback()
                route_logger.warning("Database operational error fetching filter options: %s", exc)
            except Exception as exc:
                # Unexpected error - rollback and log
                db.session.rollback()
                route_logger.warning("Error fetching filter options for alerts page: %s", exc)

            query = CAPAlert.query

            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    or_(
                        CAPAlert.headline.ilike(search_term),
                        CAPAlert.description.ilike(search_term),
                        CAPAlert.event.ilike(search_term),
                        CAPAlert.area_desc.ilike(search_term),
                    )
                )

            if status_filter:
                query = query.filter(CAPAlert.status == status_filter)
            if severity_filter:
                query = query.filter(CAPAlert.severity == severity_filter)
            if event_filter:
                query = query.filter(CAPAlert.event == event_filter)
            if source_filter:
                query = query.filter(CAPAlert.source == source_filter)

            if date_from:
                try:
                    date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
                    query = query.filter(CAPAlert.sent >= date_from_dt)
                except ValueError:
                    date_from = ""

            if date_to:
                try:
                    from datetime import timedelta
                    date_to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
                    query = query.filter(CAPAlert.sent < date_to_dt)
                except ValueError:
                    date_to = ""

            if vtec_office_filter:
                query = query.filter(CAPAlert.vtec_office == vtec_office_filter)
            if vtec_etn_filter:
                try:
                    query = query.filter(CAPAlert.vtec_etn == int(vtec_etn_filter))
                except ValueError:
                    pass
            if vtec_year_filter:
                try:
                    query = query.filter(CAPAlert.vtec_year == int(vtec_year_filter))
                except ValueError:
                    pass

            # When filtering by VTEC event chain, always include expired/cancelled/superseded alerts
            vtec_filter_active = bool(vtec_office_filter or vtec_etn_filter or vtec_year_filter)
            if not show_expired and not vtec_filter_active:
                query = query.filter(
                    or_(CAPAlert.expires.is_(None), CAPAlert.expires > utc_now())
                ).filter(CAPAlert.status != "Expired")

            # Hide superseded alerts by default; they are shown when the operator
            # explicitly requests them or is browsing a VTEC event chain.
            if not show_superseded and not vtec_filter_active:
                query = query.filter(CAPAlert.superseded_by_id.is_(None))

            sort_col = _sortable_columns[sort_by]
            query = query.order_by(sort_col.asc() if sort_dir == "asc" else sort_col.desc())

            total_count = 0
            try:
                pagination = query.paginate(page=page, per_page=per_page, error_out=False)
                alerts_list = pagination.items
                total_count = pagination.total
            except Exception as exc:
                route_logger.warning("Pagination error: %s", exc)
                try:
                    db.session.rollback()
                except Exception:
                    pass

                try:
                    total_count = query.count()
                    offset = (page - 1) * per_page
                    alerts_list = query.offset(offset).limit(per_page).all()
                except Exception as fallback_exc:
                    db.session.rollback()
                    route_logger.error("Fallback pagination failed: %s", fallback_exc)
                    alerts_list = []
                    total_count = 0

                class MockPagination:
                    def __init__(self, page_num: int, page_size: int, total: int, items):
                        self.page = page_num
                        self.per_page = page_size
                        self.total = total
                        self.items = items
                        self.pages = (
                            (total + page_size - 1) // page_size if page_size > 0 else 1
                        )
                        self.has_prev = page_num > 1
                        self.has_next = page_num < self.pages
                        self.prev_num = page_num - 1 if self.has_prev else None
                        self.next_num = page_num + 1 if self.has_next else None

                    def iter_pages(
                        self,
                        left_edge: int = 2,
                        left_current: int = 2,
                        right_current: int = 3,
                        right_edge: int = 2,
                    ):
                        last = self.pages
                        for num in range(1, last + 1):
                            if (
                                num <= left_edge
                                or (self.page - left_current - 1 < num < self.page + right_current)
                                or num > last - right_edge
                            ):
                                yield num
                            elif num == left_edge + 1 or num == self.page + right_current:
                                yield None

                pagination = MockPagination(page, per_page, total_count, alerts_list)

            audio_map: Dict[int, List[Dict[str, Any]]] = {}
            if alerts_list:
                alert_ids = [alert.id for alert in alerts_list if getattr(alert, "id", None)]
                if alert_ids:
                    try:
                        eas_messages = (
                            EASMessage.query
                            .filter(EASMessage.cap_alert_id.in_(alert_ids))
                            .order_by(EASMessage.created_at.desc())
                            .all()
                        )

                        static_prefix = get_eas_static_prefix()

                        def _static_path(filename: Optional[str]) -> Optional[str]:
                            if not filename:
                                return None
                            parts = [static_prefix, filename] if static_prefix else [filename]
                            return "/".join(part for part in parts if part)

                        for message in eas_messages:
                            if not message.cap_alert_id:
                                continue

                            audio_entries = audio_map.setdefault(message.cap_alert_id, [])

                            audio_url = url_for("eas_message_audio", message_id=message.id)
                            if message.text_payload:
                                text_url = url_for("eas_message_summary", message_id=message.id)
                            else:
                                text_path = _static_path(message.text_filename)
                                text_url = (
                                    url_for("static", filename=text_path) if text_path else None
                                )

                            audio_entries.append(
                                {
                                    "id": message.id,
                                    "created_at": message.created_at,
                                    "audio_url": audio_url,
                                    "text_url": text_url,
                                    "detail_url": url_for(
                                        "audio_detail", message_id=message.id
                                    ),
                                }
                            )
                    except Exception as exc:
                        db.session.rollback()
                        route_logger.warning("Error loading EAS messages for alerts: %s", exc)

            manual_messages: List[ManualEASActivation] = []
            try:
                manual_messages = (
                    ManualEASActivation.query
                    .order_by(ManualEASActivation.created_at.desc())
                    .limit(10)
                    .all()
                )
            except Exception as exc:
                db.session.rollback()
                route_logger.warning("Error loading manual activations: %s", exc)

            # Lazy audio extraction: backfill IPAWS audio for alerts on this page
            # that were inserted before the audio extraction code was added.
            if alerts_list:
                import os as _os
                try:
                    from app_utils.ipaws_enrichment import save_ipaws_audio
                    eas_output = _os.getenv('EAS_OUTPUT_DIR') or _os.path.join(
                        _os.getenv('EAS_STATIC_DIR', _os.path.join(_os.getcwd(), 'static')),
                        'eas_messages',
                    )
                    for alert_obj in alerts_list:
                        if getattr(alert_obj, 'ipaws_audio_url', None):
                            continue
                        raw_json = alert_obj.raw_json if isinstance(alert_obj.raw_json, dict) else {}
                        resources = raw_json.get('properties', {}).get('resources', [])
                        has_audio = any(
                            ('audio' in (r.get('mimeType') or '').lower()
                             or 'eas broadcast' in (r.get('resourceDesc') or '').lower())
                            and r.get('derefUri')
                            for r in resources
                        )
                        if has_audio:
                            audio_fn = save_ipaws_audio(
                                raw_json,
                                alert_obj.identifier or str(alert_obj.id),
                                eas_output,
                            )
                            if audio_fn:
                                alert_obj.ipaws_audio_url = audio_fn
                    db.session.commit()
                except Exception as exc:
                    db.session.rollback()
                    route_logger.warning("Lazy IPAWS audio backfill failed: %s", exc)

            current_filters = {
                "search": search,
                "status": status_filter,
                "severity": severity_filter,
                "event": event_filter,
                "source": source_filter,
                "per_page": per_page,
                "show_expired": show_expired,
                "show_superseded": show_superseded,
                "date_from": date_from,
                "date_to": date_to,
                "vtec_office": vtec_office_filter,
                "vtec_etn": vtec_etn_filter,
                "vtec_year": vtec_year_filter,
                "sort": sort_by,
                "direction": sort_dir,
            }

            return render_template(
                "alerts.html",
                alerts=alerts_list,
                pagination=pagination,
                audio_map=audio_map,
                manual_messages=manual_messages,
                current_filters=current_filters,
                statuses=statuses,
                severities=severities,
                events=events,
                sources=sources,
                active_alerts=active_alerts,
                expired_alerts=expired_alerts,
                total_alerts=total_alerts,
                superseded_count=superseded_count,
                vtec_filter_active=vtec_filter_active,
            )
        except Exception as exc:  # pragma: no cover - fallback content
            db.session.rollback()
            route_logger.error("Error loading alerts: %s", exc)
            return (
                "<h1>Error loading alerts</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/alerts/export.pdf")
    def alerts_export_pdf():
        """
        Export alerts list as PDF - server-side from database.

        This endpoint generates a PDF document containing filtered alerts from the
        alerts history page. It respects all current filters applied by the user and
        provides a tamper-proof, archival-quality export for compliance and reporting.

        Query Parameters:
            search (str): Text search across headline, description, event, area_desc
            status (str): Filter by alert status (Actual, Test, Exercise, etc.)
            severity (str): Filter by severity (Extreme, Severe, Moderate, Minor)
            event (str): Filter by event type (e.g., "Tornado Warning")
            source (str): Filter by alert source (e.g., "NWS")
            show_expired (bool): Include expired alerts (accepts: true, 1, t, yes, on)
            per_page (str): Pagination setting (informational, not used in PDF export)

        Returns:
            Response: PDF document with application/pdf mimetype
                     Includes Content-Disposition header for inline display
                     Filename format: alerts_export_YYYYMMDD.pdf

        Limits:
            - Maximum 500 alerts per PDF for performance
            - Descriptions truncated to 500 characters
            - Text-only export (no audio or multimedia)

        See Also:
            - /alerts route for main alerts page
            - /alerts/<id>/export.pdf for individual alert PDF export
            - docs/alerts-pdf-export.md for comprehensive documentation
        """
        try:
            from datetime import datetime

            # ============================================================
            # STEP 1: Parse and validate query parameters
            # ============================================================
            # Extract filter parameters from request - these mirror the
            # filters available on the main /alerts page to ensure
            # consistency between the UI and exported PDF

            search = request.args.get("search", "").strip()
            status_filter = request.args.get("status", "").strip()
            severity_filter = request.args.get("severity", "").strip()
            event_filter = request.args.get("event", "").strip()
            source_filter = request.args.get("source", "").strip()

            # Handle show_expired as boolean - accepts multiple formats
            # for maximum compatibility with different URL builders
            show_expired_raw = request.args.get("show_expired", "")
            show_expired = str(show_expired_raw).lower() in {
                "true",
                "1",
                "t",
                "yes",
                "on",
            }

            # per_page captured but not used - PDF export ignores pagination
            per_page = request.args.get("per_page", "25", type=str)

            # ============================================================
            # STEP 2: Build database query with filters
            # ============================================================
            # Uses same query logic as /alerts route to ensure exported
            # data matches what user sees in the UI

            query = CAPAlert.query

            # Text search: case-insensitive partial match across multiple fields
            # Uses OR logic so matching any field will include the alert
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    or_(
                        CAPAlert.headline.ilike(search_term),
                        CAPAlert.description.ilike(search_term),
                        CAPAlert.event.ilike(search_term),
                        CAPAlert.area_desc.ilike(search_term),
                    )
                )

            # Exact match filters: Apply each filter independently
            # Empty strings are treated as "no filter" (show all)
            if status_filter:
                query = query.filter(CAPAlert.status == status_filter)
            if severity_filter:
                query = query.filter(CAPAlert.severity == severity_filter)
            if event_filter:
                query = query.filter(CAPAlert.event == event_filter)
            if source_filter:
                query = query.filter(CAPAlert.source == source_filter)

            # Expired alerts filter: By default, exclude expired alerts
            # This matches the default behavior of the /alerts page
            if not show_expired:
                query = query.filter(
                    or_(CAPAlert.expires.is_(None), CAPAlert.expires > utc_now())
                ).filter(CAPAlert.status != "Expired")

            # Order by sent timestamp descending (newest first)
            query = query.order_by(CAPAlert.sent.desc())

            # ============================================================
            # STEP 3: Execute query with performance limit
            # ============================================================
            # Hard limit of 500 alerts prevents excessive memory usage
            # and ensures reasonable PDF file size (typically 50-500KB)
            alerts_list = query.limit(500).all()

            # ============================================================
            # STEP 4: Format alert data for PDF output
            # ============================================================
            # Build structured text sections with all relevant alert details
            # Each alert is formatted as a text block with consistent field order

            sections = []
            alert_lines = []

            for alert in alerts_list:
                # Format timestamps with local time + UTC for compliance
                # Fallback to 'Unknown' if sent time is missing (shouldn't happen)
                sent_str = format_local_datetime(alert.sent, include_utc=True) if alert.sent else 'Unknown'
                expires_str = format_local_datetime(alert.expires, include_utc=True) if alert.expires else 'No expiration'

                # Core fields: Always included for every alert
                alert_block = [
                    f"Event: {alert.event}",
                    f"Severity: {alert.severity or 'N/A'}",
                    f"Status: {alert.status}",
                    f"Source: {alert.source or 'Unknown'}",
                    f"Sent: {sent_str}",
                    f"Expires: {expires_str}",
                ]

                # Optional fields: Only included if present
                if alert.headline:
                    alert_block.append(f"Headline: {alert.headline}")

                if alert.area_desc:
                    alert_block.append(f"Area: {alert.area_desc}")

                if alert.description:
                    # Truncate long descriptions to prevent excessively long PDFs
                    # Full description available in alert detail page
                    desc = alert.description[:500] + '...' if len(alert.description) > 500 else alert.description
                    alert_block.append(f"Description: {desc}")

                # Add alert block to output and separate with blank line
                alert_lines.extend(alert_block)
                alert_lines.append("")  # Empty line between alerts for readability

            # ============================================================
            # STEP 5: Build filter summary for PDF subtitle
            # ============================================================
            # Create human-readable summary of applied filters
            # This appears in the PDF subtitle for context and documentation

            filter_parts = []
            if search:
                filter_parts.append(f"Search: {search}")
            if status_filter:
                filter_parts.append(f"Status: {status_filter}")
            if severity_filter:
                filter_parts.append(f"Severity: {severity_filter}")
            if event_filter:
                filter_parts.append(f"Event: {event_filter}")
            if source_filter:
                filter_parts.append(f"Source: {source_filter}")
            if not show_expired:
                filter_parts.append("Active alerts only")

            # Join all filter parts with pipe separator, or show "All alerts" if no filters
            filter_summary = " | ".join(filter_parts) if filter_parts else "All alerts"

            # Add content section with heading showing alert count
            sections.append({
                'heading': f'Alerts Export ({len(alerts_list)} alerts)',
                'content': alert_lines if alert_lines else ['No alerts found'],
            })

            # ============================================================
            # STEP 6: Generate PDF using common utility
            # ============================================================
            # Uses shared pdf_generator module for consistency across all
            # PDF exports in the application (logs, audit logs, alerts, etc.)
            pdf_bytes = generate_pdf_document(
                title="Alerts Export",
                sections=sections,
                subtitle=filter_summary,
                footer_text="Generated by EAS Station™ — Emergency Alert System Platform"
            )

            # ============================================================
            # STEP 7: Return PDF response with proper headers
            # ============================================================
            # Content-Disposition: inline = display in browser (vs attachment = download)
            # Filename includes date for easy organization of saved PDFs
            response = Response(pdf_bytes, mimetype="application/pdf")
            response.headers["Content-Disposition"] = (
                f"inline; filename=alerts_export_{datetime.now().strftime('%Y%m%d')}.pdf"
            )
            return response

        except Exception as exc:
            # ============================================================
            # Error handling: Log and return user-friendly error page
            # ============================================================
            db.session.rollback()
            route_logger.error("Error generating alerts PDF: %s", exc)
            return (
                "<h1>Error generating PDF</h1>"
                f"<p>{exc}</p><p><a href='/alerts'>← Back to Alerts</a></p>"
            ), 500


__all__ = ["register"]
