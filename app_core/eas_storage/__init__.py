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

"""Helpers for managing persisted EAS audio and metadata payloads.

This package replaces the former single-file ``app_core/eas_storage.py``
(2,825 lines, 57 top-level functions across ~10 independent topics -- audio
decode logging, file caching, schema migrations, backfills, delivery
records/trends, the FCC compliance log, weekly/monthly summary reports, and
precedence). Every name below is re-exported exactly as it was importable
from the old module path, so ``from app_core.eas_storage import X`` keeps
working unchanged for every existing caller.
"""

from app_utils.time import format_local_datetime, utc_now  # noqa: F401 (re-export)

from .audio_decode_log import (
    load_recent_audio_decodes,
    record_audio_decode_result,
)
from .backfill import (
    backfill_eas_message_payloads,
    backfill_manual_eas_audio,
)
from .compliance_export import (
    generate_compliance_log_csv,
    generate_compliance_log_pdf,
)
from .compliance_log import (
    TEST_EVENT_KEYWORDS,
    collect_compliance_dashboard_data,
    collect_compliance_log_entries,
)
from .delivery_records import (
    DELIVERED_EVENT_STATUSES,
    FAILED_EVENT_STATUSES,
    PENDING_EVENT_STATUSES,
    collect_alert_delivery_records,
)
from .delivery_trends import build_alert_delivery_trends
from .file_cache import (
    PURGE_CHUNK,
    get_eas_static_prefix,
    load_or_cache_audio_data,
    load_or_cache_summary_payload,
    purge_eas_messages,
    remove_eas_files,
    resolve_eas_disk_path,
)
from .precedence import (
    PRECEDENCE_AVAILABLE,
    PrecedenceLevel,
    determine_alert_precedence,
    enrich_playout_events_with_precedence,
    get_precedence_statistics,
)
from .reports_common import (
    REPORT_DECISION_FILTERS,
    REPORT_MAX_ROWS,
    resolve_report_window,
)
from .reports_export import (
    REPORT_BUILDERS,
    generate_report_csv,
    generate_report_pdf,
)
from .reports_received_initiated import (
    build_initiated_alerts_report,
    build_received_alerts_report,
)
from .reports_summary import (
    build_monthly_summary_report,
    build_weekly_summary_report,
)
from .schema_migrations import (
    ensure_eas_audio_columns,
    ensure_eas_message_foreign_key,
    ensure_eas_settings_columns,
    ensure_manual_eas_audio_columns,
)

__all__ = [
    "DELIVERED_EVENT_STATUSES",
    "FAILED_EVENT_STATUSES",
    "PENDING_EVENT_STATUSES",
    "PRECEDENCE_AVAILABLE",
    "PURGE_CHUNK",
    "PrecedenceLevel",
    "REPORT_BUILDERS",
    "REPORT_DECISION_FILTERS",
    "REPORT_MAX_ROWS",
    "TEST_EVENT_KEYWORDS",
    "backfill_eas_message_payloads",
    "backfill_manual_eas_audio",
    "build_alert_delivery_trends",
    "build_initiated_alerts_report",
    "build_monthly_summary_report",
    "build_received_alerts_report",
    "build_weekly_summary_report",
    "collect_alert_delivery_records",
    "collect_compliance_dashboard_data",
    "collect_compliance_log_entries",
    "determine_alert_precedence",
    "enrich_playout_events_with_precedence",
    "ensure_eas_audio_columns",
    "ensure_eas_message_foreign_key",
    "ensure_eas_settings_columns",
    "ensure_manual_eas_audio_columns",
    "format_local_datetime",
    "generate_compliance_log_csv",
    "generate_compliance_log_pdf",
    "generate_report_csv",
    "generate_report_pdf",
    "get_eas_static_prefix",
    "get_precedence_statistics",
    "load_or_cache_audio_data",
    "load_or_cache_summary_payload",
    "load_recent_audio_decodes",
    "purge_eas_messages",
    "record_audio_decode_result",
    "remove_eas_files",
    "resolve_eas_disk_path",
    "resolve_report_window",
    "utc_now",
]
