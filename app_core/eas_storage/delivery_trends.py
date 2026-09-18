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

"""Aggregate delivery-trend statistics across a set of delivery records."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app_core.extensions import db
from app_core.models import AlertDeliveryReport
from app_utils import ALERT_SOURCE_UNKNOWN
from app_utils.time import utc_now

from .delivery_records import _resolve_delay_threshold_seconds


def _summarize_delivery_trends(
    records: Sequence[Dict[str, Any]],
    *,
    delay_threshold: int,
) -> Dict[str, Dict[str, Any]]:
    originators: Dict[str, Dict[str, Any]] = {}
    stations: Dict[str, Dict[str, Any]] = {}

    for record in records:
        originator = record.get("source") or ALERT_SOURCE_UNKNOWN
        origin_entry = originators.setdefault(
            originator,
            {
                "label": originator,
                "total": 0,
                "delivered": 0,
                "delayed": 0,
                "latency_sum": 0.0,
                "latency_count": 0,
            },
        )
        origin_entry["total"] += 1

        if record.get("delivery_status") in {"delivered", "partial"}:
            origin_entry["delivered"] += 1

        max_latency = record.get("max_latency_seconds")
        if isinstance(max_latency, (int, float)) and max_latency > float(delay_threshold):
            origin_entry["delayed"] += 1

        for sample in record.get("latency_samples", []):
            if isinstance(sample, (int, float)):
                origin_entry["latency_sum"] += float(sample)
                origin_entry["latency_count"] += 1

        for target in record.get("target_details", []):
            target_label = target.get("target") or "unknown"
            station_entry = stations.setdefault(
                target_label,
                {
                    "label": target_label,
                    "total": 0,
                    "delivered": 0,
                    "delayed": 0,
                    "latency_sum": 0.0,
                    "latency_count": 0,
                },
            )
            station_entry["total"] += 1
            if target.get("delivered"):
                station_entry["delivered"] += 1
            latency_value = target.get("latency_seconds")
            if isinstance(latency_value, (int, float)):
                station_entry["latency_sum"] += float(latency_value)
                station_entry["latency_count"] += 1
                if float(latency_value) > float(delay_threshold):
                    station_entry["delayed"] += 1

    def _finalize(summary: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        finalized: List[Dict[str, Any]] = []
        for entry in summary.values():
            total = entry["total"]
            delivered = entry["delivered"]
            delayed = entry["delayed"]
            latency_avg = None
            if entry["latency_count"]:
                latency_avg = entry["latency_sum"] / entry["latency_count"]
            finalized.append(
                {
                    "label": entry["label"],
                    "total": total,
                    "delivered": delivered,
                    "delayed": delayed,
                    "delivery_rate": (delivered / total * 100.0) if total else None,
                    "average_latency_seconds": latency_avg,
                }
            )
        finalized.sort(key=lambda item: (item["delivery_rate"] or 0.0), reverse=True)
        return finalized

    return {
        "originators": _finalize(originators),
        "stations": _finalize(stations),
    }

def build_alert_delivery_trends(
    records: Sequence[Dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
    delay_threshold: Optional[int] = None,
    logger=None,
) -> Dict[str, Any]:
    threshold = delay_threshold if delay_threshold is not None else _resolve_delay_threshold_seconds()

    trends = _summarize_delivery_trends(records, delay_threshold=threshold)
    generated_at = utc_now()

    report_rows: List[AlertDeliveryReport] = []

    for entry in trends["originators"]:
        report_rows.append(
            AlertDeliveryReport(
                generated_at=generated_at,
                window_start=window_start,
                window_end=window_end,
                scope="originator",
                originator=entry["label"],
                station=None,
                total_alerts=entry["total"],
                delivered_alerts=entry["delivered"],
                delayed_alerts=entry["delayed"],
                average_latency_seconds=(
                    int(entry["average_latency_seconds"])
                    if entry["average_latency_seconds"] is not None
                    else None
                ),
            )
        )

    for entry in trends["stations"]:
        report_rows.append(
            AlertDeliveryReport(
                generated_at=generated_at,
                window_start=window_start,
                window_end=window_end,
                scope="station",
                originator=None,
                station=entry["label"],
                total_alerts=entry["total"],
                delivered_alerts=entry["delivered"],
                delayed_alerts=entry["delayed"],
                average_latency_seconds=(
                    int(entry["average_latency_seconds"])
                    if entry["average_latency_seconds"] is not None
                    else None
                ),
            )
        )

    if report_rows:
        try:
            (
                db.session.query(AlertDeliveryReport)
                .filter(
                    AlertDeliveryReport.window_start == window_start,
                    AlertDeliveryReport.window_end == window_end,
                )
                .delete(synchronize_session=False)
            )
            db.session.add_all(report_rows)
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive fallback
            if logger is not None:
                logger.warning("Failed to persist alert delivery reports: %s", exc)
            try:
                db.session.rollback()
            except Exception:  # pragma: no cover - defensive fallback
                pass

    return {
        "generated_at": generated_at,
        "delay_threshold_seconds": threshold,
        "originators": trends["originators"],
        "stations": trends["stations"],
    }
