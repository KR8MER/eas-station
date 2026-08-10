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

"""The capture-free helpers that were nested inside ``register``.

``symtable`` says these four close over nothing from ``register``, so moving
them to module scope is semantically identical — the ``ast.dump`` of each is
unchanged. The helpers that *do* capture (``repo_root``, ``route_logger``,
``app``) stay nested inside their topic module's ``register`` instead.
"""

from typing import Iterable, List

from flask import request

from app_core.audio.self_test import AlertSelfTestResult
from app_core.location import get_location_settings


def _load_configured_fips(override: Iterable[str]) -> List[str]:
    override_list = [str(code).strip() for code in (override or []) if str(code).strip()]
    if override_list:
        return override_list

    settings = get_location_settings()
    return list(settings.get("fips_codes") or [])

def _result_to_dict(item: AlertSelfTestResult) -> dict:
    return {
        "audio_path": item.audio_path,
        "status": item.status.value,
        "reason": item.reason,
        "event_code": item.event_code,
        "originator": item.originator,
        "alert_fips_codes": item.alert_fips_codes,
        "matched_fips_codes": item.matched_fips_codes,
        "confidence": item.confidence,
        "duration_seconds": item.duration_seconds,
        "raw_text": item.raw_text,
        "duplicate": item.duplicate,
        "error": item.error,
        "timestamp": item.timestamp,
    }

def _resolve_window_days() -> int:
    value = request.values.get("days", type=int)
    if value is None:
        return 30
    return max(1, min(int(value), 365))

def _serialize_csv_rows(records):
    for record in records:
        targets = ", ".join(
            f"{target['target']} ({target['status']})"
            for target in record.get("target_details", [])
        )
        issues = "; ".join(record.get("issues") or [])
        yield {
            "cap_identifier": record.get("identifier") or "",
            "event": record.get("event") or "",
            "sent_utc": (record.get("sent").isoformat() if record.get("sent") else ""),
            "source": record.get("source") or "",
            "delivery_status": record.get("delivery_status") or "unknown",
            "average_latency_seconds": (
                round(record["average_latency_seconds"], 2)
                if isinstance(record.get("average_latency_seconds"), (int, float))
                else ""
            ),
            "targets": targets,
            "issues": issues,
        }
