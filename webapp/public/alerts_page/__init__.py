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

"""The /alerts browse surface, as a pipeline.

``webapp/public/alerts.py`` used to hold a 385-line ``alerts()`` handler and a
~175-line PDF export. Neither was a dispatch or an accumulation — the page is a
**sequence of stages**, each of which can be read and tested on its own:

    parse_filters      request args -> AlertFilters   (clamped, allow-listed)
    load_filter_options    dropdown values + headline counts
    build_alert_query      AlertFilters -> a filtered, sorted query
    paginate_alerts        a page of rows, with a fallback if paginate() fails
    build_audio_map        generated EAS audio for the rows on this page
    load_manual_messages   recent operator-originated activations
    backfill_ipaws_audio   lazy extraction for pre-extractor alerts

``build_alerts_page`` runs them and returns the template context.
"""

from typing import Any, Dict

from .enrichment import backfill_ipaws_audio, build_audio_map, load_manual_messages
from .filters import AlertFilters, parse_filters
from .options import load_filter_options
from .pagination import MockPagination, paginate_alerts
from .query import build_alert_query
from .pdf_export import (
    MAX_EXPORT_ALERTS,
    build_export_query,
    build_export_sections,
    build_filter_summary,
)


def build_alerts_page(request, route_logger) -> Dict[str, Any]:
    """Everything ``alerts.html`` needs, for one request."""
    filters = parse_filters(request)

    options = load_filter_options(route_logger)
    query = build_alert_query(filters)
    pagination, alerts_list = paginate_alerts(
        query, filters.page, filters.per_page, route_logger
    )

    audio_map = build_audio_map(alerts_list, route_logger)
    manual_messages = load_manual_messages(route_logger)
    backfill_ipaws_audio(alerts_list, route_logger)

    return {
        "alerts": alerts_list,
        "pagination": pagination,
        "audio_map": audio_map,
        "manual_messages": manual_messages,
        "current_filters": filters.as_template_dict(),
        "vtec_filter_active": filters.vtec_active,
        **options,
    }


__all__ = [
    "MAX_EXPORT_ALERTS",
    "AlertFilters",
    "MockPagination",
    "backfill_ipaws_audio",
    "build_alert_query",
    "build_alerts_page",
    "build_audio_map",
    "build_export_query",
    "build_export_sections",
    "build_filter_summary",
    "load_filter_options",
    "load_manual_messages",
    "paginate_alerts",
    "parse_filters",
]
