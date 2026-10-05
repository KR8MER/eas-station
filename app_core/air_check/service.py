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

"""Off-air self-monitoring: match what we sent with what we heard.

Three entry points, each safe to call from any process and none of which
ever raises into its caller -- verification must never be able to break a
broadcast or the decoder:

``register_transmission``  called by every transmit path (automatic
                           broadcast, manual send, RWT) as playout starts.
``record_off_air_decode``  called by the audio service for every header an
                           ``air_check`` receiver decodes.
``sweep_overdue``          called periodically; turns pending records whose
                           deadline has passed into ``missed`` and raises an
                           error for each.

A decode can arrive before its transmission is registered (the manual-send
path only records its activation after playout), so matching works in both
directions: a decode with no pending record is kept as ``unexpected`` and a
later ``register_transmission`` adopts it if the headers line up.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from app_utils import utc_now

from .matching import compare_headers, describe_mismatch, is_candidate, normalize_header
from .roles import (
    MATCH_WINDOW,
    MAX_PLAYOUT_SECONDS,
    _aware,
    _default_session,
    _rollback,
    _system_log,
    air_check_receivers,
    get_grace_seconds,
)

logger = logging.getLogger(__name__)

def register_transmission(
    header: Optional[str],
    *,
    origin_type: str,
    origin_id: Optional[int] = None,
    alert_identifier: Optional[str] = None,
    event_code: Optional[str] = None,
    playout_seconds: float = 0.0,
    session=None,
) -> Optional[Any]:
    """Open a pending air-check for a transmission that is starting now.

    Does nothing (returns ``None``) when no enabled air-check receiver is
    configured -- without one there is nothing to verify against, and
    opening records would only produce false "missed" errors.
    """
    session = session or _default_session()
    expected = normalize_header(header)
    if not expected:
        return None
    try:
        if not air_check_receivers(session):
            return None

        from app_core.models import AirCheckRecord
        from app_core._models_air_check import (
            AIR_CHECK_STATUS_MISMATCH,
            AIR_CHECK_STATUS_PENDING,
            AIR_CHECK_STATUS_UNEXPECTED,
            AIR_CHECK_STATUS_VERIFIED,
        )
        from app_utils.eas.indicators import BROADCAST_LEAD_IN_SECONDS, BROADCAST_LEAD_OUT_SECONDS

        now = utc_now()
        playout = max(0.0, min(float(playout_seconds or 0.0), MAX_PLAYOUT_SECONDS))
        deadline = now + timedelta(
            seconds=BROADCAST_LEAD_IN_SECONDS + playout + BROADCAST_LEAD_OUT_SECONDS
            + get_grace_seconds(session)
        )

        record = AirCheckRecord(
            origin_type=origin_type,
            origin_id=origin_id,
            alert_identifier=(str(alert_identifier)[:255] if alert_identifier else None),
            expected_header=expected[:255],
            event_code=event_code or _event_code_of(expected),
            sent_at=now,
            deadline_at=deadline,
            status=AIR_CHECK_STATUS_PENDING,
        )

        # Adopt a decode that beat this registration to the database.
        earlier = (
            session.query(AirCheckRecord)
            .filter(
                AirCheckRecord.status == AIR_CHECK_STATUS_UNEXPECTED,
                AirCheckRecord.received_at >= now - MATCH_WINDOW,
            )
            .order_by(AirCheckRecord.received_at.desc())
            .all()
        )
        best = None
        best_cmp = None
        for row in earlier:
            cmp = compare_headers(expected, row.received_header)
            if is_candidate(cmp) and (best_cmp is None or len(cmp["matched"]) > len(best_cmp["matched"])):
                best, best_cmp = row, cmp
        if best is not None:
            record.received_header = best.received_header
            record.received_at = best.received_at
            record.receiver_source = best.receiver_source
            record.receiver_identifier = best.receiver_identifier
            record.decode_confidence = best.decode_confidence
            _apply_comparison(record, best_cmp)
            record.status = (
                AIR_CHECK_STATUS_VERIFIED if best_cmp["exact"] else AIR_CHECK_STATUS_MISMATCH
            )
            session.delete(best)

        session.add(record)
        session.commit()
        logger.info(
            "Air-check opened for %s transmission %s (deadline %s): %s",
            origin_type, origin_id, deadline.isoformat(), expected,
        )
        return record
    except Exception as exc:
        logger.error("Failed to register air-check for %s %s: %s", origin_type, origin_id, exc)
        _rollback(session)
        return None


#: Preference among equally good candidates: pending > mismatch > missed > verified.
_OPEN_RANK = {"pending": 3, "mismatch": 2, "missed": 1}


def _event_code_of(header: str) -> Optional[str]:
    parts = header.split("-")
    return parts[2][:8] if len(parts) > 2 and parts[2] else None


def _apply_comparison(record, comparison: Dict[str, Any]) -> None:
    mismatched = list(comparison.get("mismatched") or [])
    record.mismatch_fields = mismatched or None
    if mismatched:
        record.detail = f"Decoded header differs in: {describe_mismatch(mismatched)}"
    else:
        record.detail = None


def record_off_air_decode(
    alert: Dict[str, Any],
    *,
    receiver_identifier: Optional[str] = None,
    session=None,
) -> Optional[Any]:
    """Match one header decoded by an air-check receiver.

    Returns the record it updated or created, or ``None`` when the decode
    was a repeat of one already recorded (or could not be processed).
    """
    session = session or _default_session()
    received = normalize_header(alert.get("raw_header") or alert.get("raw_text"))
    if not received:
        logger.debug("Air-check decode without a usable SAME header ignored")
        return None
    source_name = alert.get("source_name")
    try:
        confidence = float(alert.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    try:
        from app_core.models import AirCheckRecord
        from app_core._models_air_check import (
            AIR_CHECK_STATUS_MISMATCH,
            AIR_CHECK_STATUS_MISSED,
            AIR_CHECK_STATUS_VERIFIED,
        )

        now = utc_now()
        recent = (
            session.query(AirCheckRecord)
            .filter(
                AirCheckRecord.expected_header.isnot(None),
                AirCheckRecord.sent_at >= now - MATCH_WINDOW,
            )
            .all()
        )

        best = None
        best_cmp = None
        best_key = None
        for row in recent:
            cmp = compare_headers(row.expected_header, received)
            if not is_candidate(cmp):
                continue
            sent = _aware(row.sent_at) or now
            # Exactness first, then prefer a record still waiting for its
            # decode: a resend of an identical header must close its own
            # pending record, not bounce off the original's verified one.
            key = (
                cmp["exact"],
                _OPEN_RANK.get(row.status, 0),
                len(cmp["matched"]),
                -(abs((now - sent).total_seconds())),
            )
            if best_key is None or key > best_key:
                best, best_cmp, best_key = row, cmp, key

        if best is None:
            return _record_unexpected(session, received, source_name, receiver_identifier,
                                      confidence, now)

        if best.status == AIR_CHECK_STATUS_VERIFIED:
            # Already confirmed; a later (possibly garbled) repeat changes nothing.
            return None
        if best.status == AIR_CHECK_STATUS_MISMATCH and not best_cmp["exact"]:
            previous = compare_headers(best.expected_header, best.received_header)
            if len(best_cmp["matched"]) <= len(previous["matched"]):
                return None

        was_missed = best.status == AIR_CHECK_STATUS_MISSED
        best.received_header = received[:255]
        best.received_at = now
        best.receiver_source = source_name
        best.receiver_identifier = receiver_identifier
        best.decode_confidence = confidence
        _apply_comparison(best, best_cmp)
        best.status = AIR_CHECK_STATUS_VERIFIED if best_cmp["exact"] else AIR_CHECK_STATUS_MISMATCH
        if was_missed:
            late = (now - (_aware(best.deadline_at) or now)).total_seconds()
            note = f"Heard {late:.0f}s after the deadline -- consider a longer grace period."
            best.detail = f"{best.detail} {note}" if best.detail else note

        details = {
            "record_id": best.id,
            "expected_header": best.expected_header,
            "received_header": best.received_header,
            "receiver": receiver_identifier or source_name,
            "mismatch_fields": best.mismatch_fields or [],
        }
        if best.status == AIR_CHECK_STATUS_VERIFIED:
            logger.info("Air-check VERIFIED on %s: %s", receiver_identifier or source_name, received)
            _system_log(session, "INFO", "Air-check verified: transmission heard on air", details)
        else:
            logger.error(
                "Air-check MISMATCH on %s: sent %s, heard %s (%s)",
                receiver_identifier or source_name, best.expected_header, received, best.detail,
            )
            _system_log(session, "ERROR", "Air-check mismatch: header heard on air differs "
                        "from header sent", details)
        session.commit()
        return best
    except Exception as exc:
        logger.error("Failed to record air-check decode %s: %s", received, exc)
        _rollback(session)
        return None


def _record_unexpected(session, received, source_name, receiver_identifier, confidence, now):
    from app_core.models import AirCheckRecord
    from app_core._models_air_check import AIR_CHECK_STATUS_UNEXPECTED

    duplicate = (
        session.query(AirCheckRecord)
        .filter(
            AirCheckRecord.status == AIR_CHECK_STATUS_UNEXPECTED,
            AirCheckRecord.received_header == received[:255],
            AirCheckRecord.received_at >= now - MATCH_WINDOW,
        )
        .first()
    )
    if duplicate is not None:
        return None

    record = AirCheckRecord(
        status=AIR_CHECK_STATUS_UNEXPECTED,
        event_code=_event_code_of(received),
        received_header=received[:255],
        received_at=now,
        receiver_source=source_name,
        receiver_identifier=receiver_identifier,
        decode_confidence=confidence,
        detail="Heard on the air-check receiver but no matching transmission was sent "
               "by this station.",
    )
    session.add(record)
    _system_log(session, "WARNING", "Air-check heard a header this station did not send", {
        "received_header": record.received_header,
        "receiver": receiver_identifier or source_name,
    })
    session.commit()
    logger.warning(
        "Air-check UNEXPECTED on %s: %s (no matching transmission)",
        receiver_identifier or source_name, received,
    )
    return record


def sweep_overdue(session=None) -> int:
    """Mark pending air-checks past their deadline as missed. Returns count."""
    session = session or _default_session()
    try:
        from app_core.models import AirCheckRecord
        from app_core._models_air_check import AIR_CHECK_STATUS_MISSED, AIR_CHECK_STATUS_PENDING

        now = utc_now()
        overdue = (
            session.query(AirCheckRecord)
            .filter(
                AirCheckRecord.status == AIR_CHECK_STATUS_PENDING,
                AirCheckRecord.deadline_at < now,
            )
            .all()
        )
        for record in overdue:
            record.status = AIR_CHECK_STATUS_MISSED
            record.detail = (
                "Not heard on any air-check receiver before the deadline. The alert may "
                "not have reached the air -- check the transmitter, STL and encoder."
            )
            logger.error(
                "Air-check MISSED: %s transmission %s was not heard on air: %s",
                record.origin_type, record.origin_id, record.expected_header,
            )
            _system_log(session, "ERROR", "Air-check missed: sent alert was not heard on air", {
                "record_id": record.id,
                "origin_type": record.origin_type,
                "origin_id": record.origin_id,
                "alert_identifier": record.alert_identifier,
                "expected_header": record.expected_header,
                "sent_at": record.sent_at.isoformat() if record.sent_at else None,
            })
        if overdue:
            session.commit()
        return len(overdue)
    except Exception as exc:
        logger.error("Air-check sweep failed: %s", exc)
        _rollback(session)
        return 0


__all__ = [
    "record_off_air_decode",
    "register_transmission",
    "sweep_overdue",
]
