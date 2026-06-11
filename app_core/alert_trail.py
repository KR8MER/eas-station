"""Build the unified per-alert "trail" payload.

The trail page (``/alerts/<identifier>/trail``) reconstructs the full
lifecycle of a single alert by merging every row keyed to its correlation
identifier — CAP ingestion, OTA decode, system log lines, audio alerts,
EAS message generation, GPIO relay activations, manual activations — into
one chronological timeline plus a header card and any broadcast audio
that was produced.

The correlation ID is whatever ``app_core.logging_context`` bound during
the alert's lifecycle: a CAP identifier (e.g. ``NWS-IPAWS-…``) for feed
arrivals, or an ``OTA-<event>-<sha1[:8]>`` synthesized in the SAME
decoder for over-the-air arrivals.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app_core.extensions import db
from app_core.models import (
    AudioAlert,
    CAPAlert,
    EASMessage,
    GPIOActivationLog,
    ManualEASActivation,
    ReceivedEASAlert,
    SystemLog,
)


# Event categories used by the template to colour rows and group filters.
CATEGORIES = {
    "ingest": "Ingestion",
    "decode": "OTA decode",
    "forward": "Forwarding",
    "broadcast": "Broadcast",
    "gpio": "GPIO / relay",
    "audio": "Audio",
    "system": "System log",
    "manual": "Manual activation",
}


def _coerce_dt(value: Any) -> Optional[datetime]:
    """Return ``value`` if it is a datetime, else None."""
    return value if isinstance(value, datetime) else None


def _event(
    *,
    timestamp: Optional[datetime],
    category: str,
    source: str,
    summary: str,
    details: Optional[Dict[str, Any]] = None,
    level: str = "INFO",
    href: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build one timeline event row.  Returns None when *timestamp* is missing
    so rows with no usable time are dropped rather than rendered at epoch."""
    ts = _coerce_dt(timestamp)
    if ts is None:
        return None
    return {
        "timestamp": ts,
        "category": category,
        "source": source,
        "summary": summary,
        "details": details or {},
        "level": level,
        "href": href,
    }


def _forwarding_event(cap_alert) -> Optional[Dict[str, Any]]:
    """Build the timeline event describing the alert's forwarding outcome.

    ``eas_forwarding_reason`` is written by every exit path of
    ``auto_forward_cap_alert`` (at minimum an empty string), so a NULL reason
    with ``eas_forwarded=False`` means no forwarding decision was ever
    recorded — the ingest pipeline was interrupted (or is still running).
    That state is rendered distinctly from a deliberate suppression so an
    operator can tell "the system chose not to air this" apart from "the
    system never got to choose".
    """
    if cap_alert.eas_forwarded:
        summary = "Forwarded to air chain"
        level = "INFO"
        details: Dict[str, Any] = {"reason": cap_alert.eas_forwarding_reason}
    elif cap_alert.eas_forwarding_reason is None:
        summary = "Forwarding decision never recorded"
        level = "ERROR"
        details = {
            "reason": None,
            "note": (
                "The alert was saved but the ingest pipeline did not reach "
                "the auto-forward step (interrupted, or still in progress). "
                "Unexpired alerts are retried by the poller's forwarding "
                "catch-up sweep."
            ),
        }
    else:
        summary = "Forwarding suppressed"
        level = "WARNING"
        details = {"reason": cap_alert.eas_forwarding_reason}
    return _event(
        timestamp=cap_alert.updated_at or cap_alert.created_at,
        category="forward",
        source="auto_forward",
        summary=summary,
        details=details,
        level=level,
    )


def collect_alert_trail(identifier: str) -> Dict[str, Any]:
    """Aggregate every row associated with *identifier* into a trail payload.

    The function never raises on missing data — alerts that never made it
    to the database (e.g. logged but rolled back) still produce a payload
    with whatever signal we can find in ``system_log``/``audio_alerts``.

    Args:
        identifier: The correlation ID.  Matched against ``CAPAlert.identifier``,
            ``EASMessage.alert_identifier``, ``SystemLog.alert_identifier``,
            ``AudioAlert.alert_identifier``, ``GPIOActivationLog.alert_id``,
            and ``ManualEASActivation.identifier``.

    Returns:
        A dict with keys ``identifier``, ``alert`` (CAPAlert or None),
        ``messages`` (list of EASMessage), ``manual`` (list of
        ManualEASActivation), ``received`` (list of ReceivedEASAlert),
        ``events`` (chronological list), ``counts`` (per-category tally),
        and ``audio_urls`` (per-EASMessage stream URLs for the player).
    """
    def _safe(query_callable, default):
        """Run *query_callable* and return its result, or *default* on any
        error.  Used to keep one missing table or schema mismatch from
        blanking the whole trail page — partial data is more useful than
        a 500."""
        try:
            return query_callable()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return default

    cap_alert = _safe(
        lambda: CAPAlert.query.filter_by(identifier=identifier).first(),
        None,
    )

    messages: List[EASMessage] = _safe(
        lambda: (
            EASMessage.query.filter_by(alert_identifier=identifier)
            .order_by(EASMessage.created_at.asc())
            .all()
        ),
        [],
    )

    # Fallback: if the migration hasn't backfilled or the EASMessage was
    # written before alert_identifier propagation existed, fall back to the
    # CAP foreign key.  This means historical broadcasts still show up on
    # the trail page once a CAP row exists.
    if not messages and cap_alert is not None:
        messages = _safe(
            lambda: (
                EASMessage.query.filter_by(cap_alert_id=cap_alert.id)
                .order_by(EASMessage.created_at.asc())
                .all()
            ),
            [],
        )

    # ReceivedEASAlert has no alert_identifier column (OTA decoder predates
    # the correlation ID work).  Reach it through the EASMessage backref so
    # we still surface OTA decode events on the trail.
    received: List[ReceivedEASAlert] = []
    seen_received_ids: set[int] = set()
    for message in messages:
        for source_alert in getattr(message, "source_alerts", []) or []:
            if source_alert.id in seen_received_ids:
                continue
            seen_received_ids.add(source_alert.id)
            received.append(source_alert)

    manual: List[ManualEASActivation] = _safe(
        lambda: (
            ManualEASActivation.query.filter_by(identifier=identifier)
            .order_by(ManualEASActivation.created_at.asc())
            .all()
        ),
        [],
    )

    system_logs: List[SystemLog] = _safe(
        lambda: (
            SystemLog.query.filter_by(alert_identifier=identifier)
            .order_by(SystemLog.timestamp.asc())
            .all()
        ),
        [],
    )

    audio_alerts: List[AudioAlert] = _safe(
        lambda: (
            AudioAlert.query.filter_by(alert_identifier=identifier)
            .order_by(AudioAlert.created_at.asc())
            .all()
        ),
        [],
    )

    gpio_logs: List[GPIOActivationLog] = _safe(
        lambda: (
            GPIOActivationLog.query.filter_by(alert_id=identifier)
            .order_by(GPIOActivationLog.activated_at.asc())
            .all()
        ),
        [],
    )

    events: List[Dict[str, Any]] = []

    if cap_alert is not None:
        events.append(_event(
            timestamp=cap_alert.created_at,
            category="ingest",
            source=f"cap_poller / {cap_alert.source or 'CAP'}",
            summary=f"CAP alert ingested: {cap_alert.event or 'unknown event'}",
            details={
                "cap_alert_id": cap_alert.id,
                "status": cap_alert.status,
                "message_type": cap_alert.message_type,
                "scope": cap_alert.scope,
                "severity": cap_alert.severity,
                "urgency": cap_alert.urgency,
                "certainty": cap_alert.certainty,
                "headline": cap_alert.headline,
                "sent": cap_alert.sent.isoformat() if cap_alert.sent else None,
                "expires": cap_alert.expires.isoformat() if cap_alert.expires else None,
            },
        ))
        if (
            cap_alert.updated_at
            and cap_alert.created_at
            and cap_alert.updated_at > cap_alert.created_at
        ):
            events.append(_event(
                timestamp=cap_alert.updated_at,
                category="ingest",
                source="cap_poller",
                summary="CAP alert record updated",
                details={"cap_alert_id": cap_alert.id},
            ))
        if cap_alert.eas_forwarded is not None:
            forwarding_event = _forwarding_event(cap_alert)
            if forwarding_event is not None:
                events.append(forwarding_event)

    for src in received:
        events.append(_event(
            timestamp=src.received_at,
            category="decode",
            source=f"eas_monitor / {src.source_name or 'OTA'}",
            summary=(
                f"SAME decode: {src.event_code or '?'} "
                f"({src.originator_code or '?'}) — decision: "
                f"{(src.forwarding_decision or 'unknown').lower()}"
            ),
            details={
                "received_id": src.id,
                "raw_same_header": src.raw_same_header,
                "event_code": src.event_code,
                "event_name": src.event_name,
                "originator_code": src.originator_code,
                "callsign": src.callsign,
                "fips_codes": list(src.fips_codes or []),
                "forwarding_decision": src.forwarding_decision,
                "forwarding_reason": src.forwarding_reason,
                "decode_confidence": src.decode_confidence,
            },
        ))
        if src.forwarded_at:
            events.append(_event(
                timestamp=src.forwarded_at,
                category="forward",
                source="auto_forward",
                summary="OTA alert relayed to air chain",
                details={"received_id": src.id},
            ))

    for message in messages:
        events.append(_event(
            timestamp=message.created_at,
            category="broadcast",
            source="eas_storage",
            summary=f"EAS message #{message.id} built (SAME: {message.same_header})",
            details={
                "message_id": message.id,
                "cap_alert_id": message.cap_alert_id,
                "audio_filename": message.audio_filename,
                "tts_provider": message.tts_provider,
                "has_audio_blob": message.audio_data is not None,
                "has_tts_audio": message.tts_audio_data is not None,
            },
        ))

    for activation in manual:
        ts = activation.triggered_at or activation.sent_at or activation.created_at
        events.append(_event(
            timestamp=ts,
            category="manual",
            source=f"manual / {activation.triggered_by or activation.created_by or 'operator'}",
            summary=(
                f"Manual activation: {activation.event_name or activation.event_code} "
                f"({activation.status})"
            ),
            details={
                "activation_id": activation.id,
                "event_code": activation.event_code,
                "same_header": activation.same_header,
                "duration_minutes": activation.duration_minutes,
                "created_by": activation.created_by,
                "triggered_by": activation.triggered_by,
            },
        ))

    for gpio in gpio_logs:
        events.append(_event(
            timestamp=gpio.activated_at,
            category="gpio",
            source=f"gpio / pin {gpio.pin}",
            summary=(
                f"GPIO pin {gpio.pin} activated"
                + (f" by {gpio.operator}" if gpio.operator else "")
                + (
                    f" (duration: {gpio.duration_seconds:.1f}s)"
                    if gpio.duration_seconds
                    else ""
                )
            ),
            details={
                "gpio_log_id": gpio.id,
                "pin": gpio.pin,
                "activation_type": gpio.activation_type,
                "operator": gpio.operator,
                "reason": gpio.reason,
                "success": gpio.success,
                "deactivated_at": (
                    gpio.deactivated_at.isoformat() if gpio.deactivated_at else None
                ),
                "duration_seconds": gpio.duration_seconds,
            },
            level="ERROR" if gpio.success is False else "INFO",
        ))
        if gpio.deactivated_at and gpio.deactivated_at != gpio.activated_at:
            events.append(_event(
                timestamp=gpio.deactivated_at,
                category="gpio",
                source=f"gpio / pin {gpio.pin}",
                summary=f"GPIO pin {gpio.pin} deactivated",
                details={"gpio_log_id": gpio.id},
            ))

    for alert in audio_alerts:
        events.append(_event(
            timestamp=alert.created_at,
            category="audio",
            source=f"audio / {alert.source_name}",
            summary=f"{alert.alert_type}: {alert.message}",
            details={
                "audio_alert_id": alert.id,
                "alert_level": alert.alert_level,
                "alert_type": alert.alert_type,
                "acknowledged": alert.acknowledged,
                "resolved": alert.resolved,
                "threshold_value": alert.threshold_value,
                "actual_value": alert.actual_value,
            },
            level=(alert.alert_level or "INFO").upper(),
        ))

    for log in system_logs:
        events.append(_event(
            timestamp=log.timestamp,
            category="system",
            source=log.module or "system",
            summary=log.message,
            details=log.details if isinstance(log.details, dict) else None,
            level=(log.level or "INFO").upper(),
        ))

    # Drop dropped-Nones, sort ascending by timestamp.
    events = [e for e in events if e is not None]
    events.sort(key=lambda e: e["timestamp"])

    counts: Dict[str, int] = {key: 0 for key in CATEGORIES}
    for event in events:
        counts[event["category"]] = counts.get(event["category"], 0) + 1

    # Pre-build audio playback URLs for each EASMessage that has a blob.
    # Using url_for here keeps the route name authoritative (changes in
    # webapp/admin/audio.py propagate automatically).
    audio_urls: Dict[int, str] = {}
    try:
        from flask import url_for
        for message in messages:
            if message.audio_data is not None or message.audio_filename:
                audio_urls[message.id] = url_for(
                    "eas_message_audio", message_id=message.id
                )
    except Exception:
        # url_for can fail outside an app context; the template handles
        # missing URLs gracefully.
        audio_urls = {}

    return {
        "identifier": identifier,
        "alert": cap_alert,
        "messages": messages,
        "manual": manual,
        "received": received,
        "events": events,
        "counts": counts,
        "audio_urls": audio_urls,
        "category_labels": CATEGORIES,
    }
