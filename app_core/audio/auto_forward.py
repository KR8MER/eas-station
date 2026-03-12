"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""
Automatic Alert Forwarding Module

Handles automatic forwarding of received alerts (IPAWS, NOAA CAP, and OTA)
to the air chain for broadcast. This module:

1. Cross-source deduplication: Prevents the same alert from being broadcast
   multiple times when received via IPAWS + NOAA + OTA simultaneously.
2. Originator substitution: Replaces the original alert's originator with
   the station's configured originator when generating outgoing SAME headers.
3. Automatic broadcast: Generates SAME audio, activates GPIO relays, and
   plays audio without operator intervention.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Deduplication window: alerts with the same event code and overlapping
# FIPS codes within this window are considered duplicates across sources.
CROSS_SOURCE_DEDUP_WINDOW_MINUTES = 15


def _get_fips_from_cap_alert(alert, raw_json: Optional[Dict] = None) -> List[str]:
    """Extract FIPS/SAME codes from a CAP alert object or its raw_json."""
    codes: List[str] = []

    if raw_json and isinstance(raw_json, dict):
        props = raw_json.get('properties', {})
        if isinstance(props, dict):
            geocode = props.get('geocode', {})
            if isinstance(geocode, dict):
                for key in ('SAME', 'same', 'SAMEcodes'):
                    values = geocode.get(key)
                    if values:
                        if isinstance(values, (list, tuple)):
                            codes.extend(str(v).strip() for v in values if v)
                        elif values:
                            codes.append(str(values).strip())
                        break  # stop at first matching key; UGC zone codes are not FIPS codes

    return [c for c in codes if c and c != 'None']


def _resolve_event_code(alert) -> Optional[str]:
    """Try to resolve the 3-letter EAS event code from a CAP alert."""
    from app_utils.event_codes import EVENT_CODE_REGISTRY

    event_name = (getattr(alert, 'event', '') or '').strip()
    if not event_name:
        return None

    # Direct lookup by event name
    for code, info in EVENT_CODE_REGISTRY.items():
        name = info.get('name', '') if isinstance(info, dict) else str(info)
        if name.lower() == event_name.lower():
            return code

    return None


def is_duplicate_broadcast(
    event_code: str,
    fips_codes: List[str],
    db_session,
    window_minutes: int = CROSS_SOURCE_DEDUP_WINDOW_MINUTES,
) -> bool:
    """Check if an alert with the same event code and overlapping FIPS has
    already been broadcast within the deduplication window.

    Checks both EASMessage (CAP-sourced broadcasts) and ManualEASActivation
    (manual/RWT/auto-forwarded broadcasts) tables.
    """
    if not event_code or not fips_codes:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    fips_set = set(fips_codes)

    try:
        from app_core.models import EASMessage
        recent_messages = (
            db_session.query(EASMessage)
            .filter(EASMessage.created_at >= cutoff)
            .all()
        )
        for msg in recent_messages:
            meta = msg.metadata_payload or {}
            msg_event_code = meta.get('event_code', '')
            msg_locations = meta.get('locations', [])
            if msg_event_code == event_code and fips_set & set(msg_locations):
                logger.info(
                    "Cross-source duplicate detected in EASMessage: "
                    "event=%s, overlapping FIPS=%s (message_id=%s)",
                    event_code,
                    fips_set & set(msg_locations),
                    msg.id,
                )
                return True
    except Exception as exc:
        logger.warning("EASMessage dedup check failed: %s", exc)

    try:
        from app_core.models import ManualEASActivation
        recent_activations = (
            db_session.query(ManualEASActivation)
            .filter(ManualEASActivation.created_at >= cutoff)
            .filter(ManualEASActivation.event_code == event_code)
            .all()
        )
        for activation in recent_activations:
            activation_fips = set(activation.same_locations or [])
            if fips_set & activation_fips:
                logger.info(
                    "Cross-source duplicate detected in ManualEASActivation: "
                    "event=%s, overlapping FIPS=%s (activation_id=%s)",
                    event_code,
                    fips_set & activation_fips,
                    activation.id,
                )
                return True
    except Exception as exc:
        logger.warning("ManualEASActivation dedup check failed: %s", exc)

    return False


def auto_forward_cap_alert(
    cap_alert,
    alert_data: Dict[str, Any],
    db_session,
    eas_message_cls,
    eas_config: Dict[str, Any],
    location_settings: Optional[Dict[str, Any]] = None,
    logger_instance: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Automatically forward a CAP alert (IPAWS/NOAA) to the air chain.

    This is called by the CAP poller after saving a new alert to the database.
    It generates a SAME header with the station's originator, creates the
    broadcast audio, and plays it through the configured audio chain + GPIO.

    Args:
        cap_alert: CAPAlert model instance (already saved to DB).
        alert_data: Original alert data dict (includes raw_json).
        db_session: SQLAlchemy database session.
        eas_message_cls: EASMessage model class.
        eas_config: EAS configuration dict (from load_eas_config).
        location_settings: Location settings dict.
        logger_instance: Optional logger.

    Returns:
        Dict with forwarding result (same_triggered, event_code, reason, etc.).
    """
    log = logger_instance or logger

    result: Dict[str, Any] = {
        'forwarded': False,
        'source': getattr(cap_alert, 'source', 'CAP'),
        'identifier': getattr(cap_alert, 'identifier', 'unknown'),
    }

    if not eas_config.get('enabled'):
        reason = "EAS broadcasting disabled"
        log.debug("Auto-forward skipped for %s: %s", result['identifier'], reason)
        result['reason'] = reason
        _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
        return result

    # Extract FIPS codes for cross-source dedup
    raw_json = alert_data.get('raw_json', {})
    fips_codes = _get_fips_from_cap_alert(cap_alert, raw_json)
    event_code = _resolve_event_code(cap_alert)

    # Cross-source deduplication
    if event_code and fips_codes:
        if is_duplicate_broadcast(event_code, fips_codes, db_session):
            reason = (
                f"Cross-source duplicate: {event_code} already broadcast "
                f"for overlapping FIPS within {CROSS_SOURCE_DEDUP_WINDOW_MINUTES}min"
            )
            log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
            result['reason'] = reason
            _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
            return result

    # Use EASBroadcaster for the full broadcast pipeline.
    # Reload config fresh from the database so TTS and other settings saved
    # via the web UI after the poller started are always picked up.
    from app_utils.eas import EASBroadcaster, load_eas_config

    try:
        broadcast_config = load_eas_config()
    except Exception as exc:
        log.warning("Could not reload EAS config, falling back to caller-supplied config: %s", exc)
        broadcast_config = eas_config

    try:
        broadcaster = EASBroadcaster(
            db_session=db_session,
            model_cls=eas_message_cls,
            config=broadcast_config,
            logger=log,
            location_settings=location_settings,
        )
    except Exception as exc:
        reason = f"Failed to initialize EASBroadcaster: {exc}"
        log.error("Auto-forward failed for %s: %s", result['identifier'], reason)
        result['reason'] = reason
        _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
        return result

    # Build payload for EASBroadcaster.handle_alert()
    payload = dict(alert_data)
    if 'raw_json' not in payload:
        payload['raw_json'] = raw_json

    # Preserve key fields the broadcaster expects
    for field in ('event', 'status', 'message_type', 'sent', 'expires'):
        if field not in payload:
            payload[field] = getattr(cap_alert, field, None)

    # Mark as forwarded in payload so GPIO behavior triggers forwarding mode
    payload['forwarding_decision'] = 'forwarded'
    payload['forwarded'] = True

    try:
        broadcast_result = broadcaster.handle_alert(cap_alert, payload)
    except Exception as exc:
        reason = f"EASBroadcaster.handle_alert() failed: {exc}"
        log.error("Auto-forward failed for %s: %s", result['identifier'], reason, exc_info=True)
        result['reason'] = reason
        _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
        return result

    if broadcast_result.get('same_triggered'):
        reason = f"Auto-forwarded: SAME {broadcast_result.get('same_header', '')}"
        log.info(
            "Auto-forwarded CAP alert %s to air chain: event=%s, header=%s",
            result['identifier'],
            broadcast_result.get('event_code'),
            broadcast_result.get('same_header'),
        )
        result['forwarded'] = True
        result['same_header'] = broadcast_result.get('same_header')
        result['event_code'] = broadcast_result.get('event_code')
        result['record_id'] = broadcast_result.get('record_id')
        _update_cap_forwarding_status(
            cap_alert, db_session, True, reason, log,
            audio_url=broadcast_result.get('audio_path'),
        )

        # Send email/SMS notifications for this broadcast
        try:
            from app_core.notifications import send_alert_notifications

            alert_info = {
                'event_code': broadcast_result.get('event_code') or event_code or '',
                'headline': getattr(cap_alert, 'headline', '') or '',
                'same_header': broadcast_result.get('same_header', ''),
                'location_codes': fips_codes,
                'source': getattr(cap_alert, 'source', 'CAP') or 'CAP',
                'timestamp': (
                    getattr(cap_alert, 'sent', None) or datetime.now(timezone.utc)
                ).isoformat(),
            }
            send_alert_notifications(
                record_id=broadcast_result.get('record_id'),
                alert_info=alert_info,
                db_session=db_session,
                logger_instance=log,
            )
        except Exception as _notif_exc:
            log.warning("Notification dispatch failed (non-fatal): %s", _notif_exc)

    else:
        reason = broadcast_result.get('reason', 'Broadcast not triggered')
        log.info("Auto-forward did not trigger broadcast for %s: %s", result['identifier'], reason)
        result['reason'] = reason
        _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)

    return result


def auto_forward_ota_alert(
    alert_dict: Dict[str, Any],
    db_session,
    eas_message_cls,
    eas_config: Dict[str, Any],
    location_settings: Optional[Dict[str, Any]] = None,
    logger_instance: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Automatically forward an OTA (over-the-air) received EAS alert to the
    air chain for rebroadcast.

    Converts the decoded OTA alert dict into a CAPAlert-like object and
    invokes the same EASBroadcaster pipeline used for CAP alerts.

    Args:
        alert_dict: Decoded OTA alert data (from EASMonitor callback).
        db_session: SQLAlchemy database session.
        eas_message_cls: EASMessage model class.
        eas_config: EAS configuration dict.
        location_settings: Location settings dict.
        logger_instance: Optional logger.

    Returns:
        Dict with forwarding result.
    """
    log = logger_instance or logger

    event_code = alert_dict.get('event_code', 'UNKNOWN')
    fips_codes = alert_dict.get('location_codes', [])
    source_name = alert_dict.get('source_name', 'OTA')

    result: Dict[str, Any] = {
        'forwarded': False,
        'source': source_name,
        'event_code': event_code,
    }

    if not eas_config.get('enabled'):
        result['reason'] = "EAS broadcasting disabled"
        return result

    # Cross-source deduplication
    if event_code and event_code != 'UNKNOWN' and fips_codes:
        if is_duplicate_broadcast(event_code, fips_codes, db_session):
            result['reason'] = (
                f"Cross-source duplicate: {event_code} already broadcast "
                f"for overlapping FIPS within {CROSS_SOURCE_DEDUP_WINDOW_MINUTES}min"
            )
            log.info("OTA auto-forward skipped: %s", result['reason'])
            return result

    # Build a CAPAlert-like object from OTA alert data
    now = datetime.now(timezone.utc)
    issue_time = alert_dict.get('issue_time')
    purge_time = alert_dict.get('purge_time')
    sent_dt = (
        datetime.fromisoformat(issue_time) if isinstance(issue_time, str) else issue_time
    ) if issue_time else now
    expires_dt = (
        datetime.fromisoformat(purge_time) if isinstance(purge_time, str) else purge_time
    ) if purge_time else now + timedelta(hours=1)

    from app_utils.event_codes import EVENT_CODE_REGISTRY
    event_info = EVENT_CODE_REGISTRY.get(event_code, {})
    event_name = event_info.get('name', event_code) if isinstance(event_info, dict) else event_code

    alert_object = SimpleNamespace(
        id=None,
        identifier=f"OTA-{source_name}-{now.strftime('%Y%m%d%H%M%S')}",
        event=event_name,
        headline=f"Received {event_name} from {source_name}",
        description=f"EAS alert received over the air from {source_name}.",
        instruction=None,
        sent=sent_dt,
        expires=expires_dt,
        status='Actual',
        message_type='Alert',
        severity=event_info.get('severity', 'Unknown') if isinstance(event_info, dict) else 'Unknown',
        urgency=event_info.get('urgency', 'Unknown') if isinstance(event_info, dict) else 'Unknown',
        certainty='Observed',
        raw_json=None,
    )

    # Build payload with SAME geocode from OTA FIPS codes
    payload = {
        'identifier': alert_object.identifier,
        'event': event_name,
        'status': 'Actual',
        'message_type': 'Alert',
        'sent': sent_dt,
        'expires': expires_dt,
        'raw_json': {
            'properties': {
                'geocode': {
                    'SAME': list(fips_codes),
                }
            }
        },
        'forwarding_decision': 'forwarded',
        'forwarded': True,
    }

    # Reload config fresh from the database so TTS and other settings saved
    # via the web UI after the poller started are always picked up.
    from app_utils.eas import EASBroadcaster, load_eas_config

    try:
        broadcast_config = load_eas_config()
    except Exception as exc:
        log.warning("Could not reload EAS config, falling back to caller-supplied config: %s", exc)
        broadcast_config = eas_config

    try:
        broadcaster = EASBroadcaster(
            db_session=db_session,
            model_cls=eas_message_cls,
            config=broadcast_config,
            logger=log,
            location_settings=location_settings,
        )
    except Exception as exc:
        result['reason'] = f"Failed to initialize EASBroadcaster: {exc}"
        log.error("OTA auto-forward failed: %s", result['reason'])
        return result

    try:
        broadcast_result = broadcaster.handle_alert(alert_object, payload)
    except Exception as exc:
        result['reason'] = f"EASBroadcaster.handle_alert() failed: {exc}"
        log.error("OTA auto-forward failed: %s", result['reason'], exc_info=True)
        return result

    if broadcast_result.get('same_triggered'):
        log.info(
            "Auto-forwarded OTA alert to air chain: source=%s, event=%s, header=%s",
            source_name,
            broadcast_result.get('event_code'),
            broadcast_result.get('same_header'),
        )
        result['forwarded'] = True
        result['same_header'] = broadcast_result.get('same_header')
        result['record_id'] = broadcast_result.get('record_id')

        # Send email/SMS notifications for this broadcast
        try:
            from app_core.notifications import send_alert_notifications

            alert_info = {
                'event_code': event_code,
                'headline': alert_object.headline,
                'same_header': broadcast_result.get('same_header', ''),
                'location_codes': list(fips_codes),
                'source': source_name,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            send_alert_notifications(
                record_id=broadcast_result.get('record_id'),
                alert_info=alert_info,
                db_session=db_session,
                logger_instance=log,
            )
        except Exception as _notif_exc:
            log.warning("Notification dispatch failed (non-fatal): %s", _notif_exc)

    else:
        result['reason'] = broadcast_result.get('reason', 'Broadcast not triggered')
        log.info("OTA auto-forward did not trigger broadcast: %s", result['reason'])

    return result


def _update_cap_forwarding_status(
    cap_alert,
    db_session,
    forwarded: bool,
    reason: str,
    log: logging.Logger,
    audio_url: Optional[str] = None,
) -> None:
    """Update the eas_forwarded tracking fields on a CAPAlert record."""
    try:
        cap_alert.eas_forwarded = forwarded
        cap_alert.eas_forwarding_reason = (reason or '')[:255]
        if audio_url:
            cap_alert.eas_audio_url = str(audio_url)[:512]
        db_session.add(cap_alert)
        db_session.commit()
    except Exception as exc:
        log.warning("Failed to update CAP forwarding status: %s", exc)
        try:
            db_session.rollback()
        except Exception:
            pass


__all__ = [
    'auto_forward_cap_alert',
    'auto_forward_ota_alert',
    'is_duplicate_broadcast',
    'CROSS_SOURCE_DEDUP_WINDOW_MINUTES',
]
