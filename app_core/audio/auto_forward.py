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
2. CAP compliance gating: Enforces ECIG §3.1–§3.3 requirements — only alerts
   with status=Actual, scope=Public, and a future expiry are forwarded.
3. Originator preservation: Per ECIG §3.4.1.1, the EAS-ORG from the incoming
   CAP alert's parameters is used for the outgoing SAME header; the station's
   configured originator is used only as a fallback.
4. Automatic broadcast: Generates SAME audio, activates GPIO relays, and
   plays audio without operator intervention.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

from app_utils.vtec import VTEC_BROADCAST_ACTIONS, VTEC_SKIP_ACTIONS, VTEC_TERMINAL_ACTIONS

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
                # ECIG §3.10: FIPS6 geocodes are treated the same as SAME codes.
                for key in ('SAME', 'same', 'SAMEcodes', 'FIPS6', 'fips6'):
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

    # ── ECIG §3.1: status=Actual required for any on-air broadcast ────────
    alert_status = getattr(cap_alert, 'status', None) or alert_data.get('status', '')
    if str(alert_status).strip().lower() != 'actual':
        reason = f"Alert status '{alert_status}' is not 'Actual' — broadcast suppressed (ECIG §3.1)"
        log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
        result['reason'] = reason
        _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
        return result

    # ── ECIG §3.2: scope=Public required for broadcast ────────────────────
    alert_scope = getattr(cap_alert, 'scope', None) or alert_data.get('scope', '')
    if str(alert_scope).strip().lower() != 'public':
        reason = f"Alert scope '{alert_scope}' is not 'Public' — broadcast suppressed (ECIG §3.2)"
        log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
        result['reason'] = reason
        _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
        return result

    # ── ECIG §3.3: expired alerts shall not be broadcast ─────────────────
    sent_dt = getattr(cap_alert, 'sent', None) or alert_data.get('sent')
    expires_dt = getattr(cap_alert, 'expires', None) or alert_data.get('expires')
    if isinstance(expires_dt, datetime) and isinstance(sent_dt, datetime):
        if expires_dt <= sent_dt:
            reason = "Alert expires ≤ sent — alert is already expired (ECIG §3.3)"
            log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
            result['reason'] = reason
            _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
            return result
    now_utc = datetime.now(timezone.utc)
    if isinstance(expires_dt, datetime):
        exp = expires_dt if expires_dt.tzinfo else expires_dt.replace(tzinfo=timezone.utc)
        if exp <= now_utc:
            reason = f"Alert already expired at {expires_dt} — broadcast suppressed (ECIG §3.3)"
            log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
            result['reason'] = reason
            _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
            return result

    # Extract FIPS codes for cross-source dedup
    raw_json = alert_data.get('raw_json', {})
    fips_codes = _get_fips_from_cap_alert(cap_alert, raw_json)
    event_code = _resolve_event_code(cap_alert)

    # Event code filtering: forward only events the operator has selected.
    # An empty allowlist means "forward all event types" — except RWT, which is
    # always suppressed unless the operator explicitly opts in by adding 'RWT'
    # to forwarded_event_codes.  This keeps the CAP path consistent with the
    # OTA path (auto_forward_ota_alert) so test activations are not silently
    # rebroadcast just because the allowlist is empty.
    forwarded_event_codes = eas_config.get('forwarded_event_codes') or []
    allowed = {str(c).strip().upper() for c in forwarded_event_codes if str(c).strip()}
    event_code_upper = event_code.upper() if event_code else ''

    if event_code_upper == 'RWT' and 'RWT' not in allowed:
        reason = (
            "RWT not forwarded — add 'RWT' to forwarded_event_codes to relay test activations"
        )
        log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
        result['reason'] = reason
        _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
        return result

    if allowed and event_code_upper not in allowed:
        # An unresolved event code (event_code_upper == '') with a configured
        # allowlist must also be rejected: we cannot prove the alert is on the
        # allowlist, so refuse to forward rather than silently bypassing the
        # operator's filter.
        reason = (
            f"Event '{event_code or 'UNKNOWN'}' is not in the configured forwarding allowlist"
        )
        log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
        result['reason'] = reason
        _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
        return result

    # VTEC-aware action gating — only applies when VTEC was parsed at ingest
    vtec_action: Optional[str] = getattr(cap_alert, 'vtec_action', None)
    if vtec_action:
        if vtec_action in VTEC_SKIP_ACTIONS:
            # CON / ROU / COR: event is already on air, this is a non-VTEC text
            # update or routine placeholder — no new broadcast needed
            reason = (
                f"VTEC action '{vtec_action}' is a non-broadcast update "
                "— rebroadcast suppressed"
            )
            log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
            result['reason'] = reason
            _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
            return result

        if vtec_action in VTEC_TERMINAL_ACTIONS:
            # CAN / EXP: event is over; cancellation tones are not auto-generated
            reason = (
                f"VTEC action '{vtec_action}' indicates event termination "
                "— no broadcast triggered"
            )
            log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
            result['reason'] = reason
            _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
            return result

        if vtec_action in VTEC_BROADCAST_ACTIONS and vtec_action == 'UPG':
            # UPG: upgraded severity — always rebroadcast, skip dedup window
            log.info(
                "Auto-forward forced for %s: VTEC action 'UPG' bypasses dedup window",
                result['identifier'],
            )
            # Fall through directly to broadcaster — skip the FIPS dedup check below
            fips_codes_for_dedup: List[str] = []
        else:
            fips_codes_for_dedup = fips_codes
    else:
        fips_codes_for_dedup = fips_codes

    # Cross-source deduplication (skipped for UPG)
    if event_code and fips_codes_for_dedup:
        if is_duplicate_broadcast(event_code, fips_codes_for_dedup, db_session):
            reason = (
                f"Cross-source duplicate: {event_code} already broadcast "
                f"for overlapping FIPS within {CROSS_SOURCE_DEDUP_WINDOW_MINUTES}min"
            )
            log.info("Auto-forward skipped for %s: %s", result['identifier'], reason)
            result['reason'] = reason
            _update_cap_forwarding_status(cap_alert, db_session, False, reason, log)
            return result

    # Use EASBroadcaster for the full broadcast pipeline
    from app_utils.eas import EASBroadcaster

    try:
        broadcaster = EASBroadcaster(
            db_session=db_session,
            model_cls=eas_message_cls,
            config=eas_config,
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

    # Push the alert text onto every active Icecast stream while the broadcast
    # is on the air; clear it once handle_alert() returns so normal source
    # metadata (song titles, etc.) resumes.
    from app_core.audio.alert_metadata import (
        clear_alert_metadata,
        set_alert_metadata,
    )

    alert_title = (getattr(cap_alert, 'headline', '') or '').strip()
    if not alert_title:
        alert_title = (getattr(cap_alert, 'event', '') or '').strip()
    if alert_title:
        set_alert_metadata(alert_title)

    try:
        try:
            broadcast_result = broadcaster.handle_alert(cap_alert, payload)
        finally:
            if alert_title:
                clear_alert_metadata()
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
    relay_audio_wav = alert_dict.get('relay_audio_wav')
    relay_tone_profile = alert_dict.get('relay_tone_profile', 'attention')  # 853+960 Hz EAS dual-tone
    relay_tone_duration = alert_dict.get('relay_tone_duration', 8.0)         # always 8 s

    result: Dict[str, Any] = {
        'forwarded': False,
        'source': source_name,
        'event_code': event_code,
    }

    if not eas_config.get('enabled'):
        result['reason'] = "EAS broadcasting disabled"
        return result

    # Refuse to rebroadcast an alert whose event code could not be decoded.
    # An UNKNOWN code means the SAME header was either garbled or from an event
    # type not in the registry; broadcasting it would produce an illegal/
    # nonsensical SAME header.
    if not event_code or event_code == 'UNKNOWN':
        result['reason'] = "OTA alert has unresolvable event code; skipping rebroadcast"
        log.info(
            "OTA auto-forward skipped for source '%s': %s",
            source_name, result['reason'],
        )
        return result

    # Event code filtering.
    forwarded_event_codes = eas_config.get('forwarded_event_codes') or []
    allowed = {str(c).strip().upper() for c in forwarded_event_codes if str(c).strip()}

    # RWT is suppressed by default even when no allowlist is configured.
    # Operators must explicitly add 'RWT' to forwarded_event_codes to relay tests.
    if event_code.upper() == 'RWT' and 'RWT' not in allowed:
        result['reason'] = (
            "RWT not forwarded — add 'RWT' to forwarded_event_codes to relay test activations"
        )
        log.info("OTA auto-forward skipped: %s", result['reason'])
        return result

    # General allowlist: when configured, reject anything not on the list.
    if allowed and event_code.upper() not in allowed:
        result['reason'] = (
            f"Event '{event_code}' is not in the configured forwarding allowlist"
        )
        log.info("OTA auto-forward skipped: %s", result['reason'])
        return result

    # Cross-source deduplication: only check when we have enough information
    # to produce a meaningful key (UNKNOWN is already blocked above).
    if fips_codes:
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
        headline=f"{event_name} — {source_name}",
        description='',
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

    # Build human-readable area description from FIPS codes for TTS narration
    try:
        from app_utils.fips_codes import US_FIPS_LOOKUP as _FIPS_NAMES
        _area_parts = [
            _FIPS_NAMES[c] for c in fips_codes if c in _FIPS_NAMES
        ]
        area_desc = '; '.join(_area_parts) if _area_parts else 'the affected area'
    except Exception:
        area_desc = 'the affected area'

    # Originator code from the received SAME header (e.g. WXR, EAS, CIV, PEP)
    originator_code = (alert_dict.get('originator') or 'WXR').strip().upper()

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
                'event': event_name,
                'areaDesc': area_desc,
                'geocode': {
                    'SAME': list(fips_codes),
                },
                'parameters': {
                    'EAS-ORG': originator_code,
                },
            }
        },
        'forwarding_decision': 'forwarded',
        'forwarded': True,
    }

    # RWT must never carry an EBS attention tone — FCC §11.61 prohibits it.
    # When an RWT is forwarded, the relay is header × 3 + EOM only.
    if event_code.upper() == 'RWT':
        payload['relay_tone_profile'] = 'none'
        payload['relay_tone_duration'] = 0.0
        # Do NOT attach relay_audio_wav_bytes — no narration on RWT
    else:
        # Attach OTA narration audio captured between attention tone and EOM so
        # build_files() can relay it instead of synthesising new TTS.
        # Alerts with a 1050 Hz or EBS attention tone will always have narration.
        if relay_audio_wav:
            payload['relay_audio_wav_bytes'] = relay_audio_wav

        # Relay always uses the EAS dual-tone (853+960 Hz, 8 s).  Both the NOAA
        # 1050 Hz tone and any EBS dual-tone from the originating station are
        # stripped from the captured ring-buffer audio by _find_narration_start();
        # the broadcaster generates a fresh 8-second attention signal.
        payload['relay_tone_profile'] = relay_tone_profile
        payload['relay_tone_duration'] = relay_tone_duration

    from app_utils.eas import EASBroadcaster

    try:
        broadcaster = EASBroadcaster(
            db_session=db_session,
            model_cls=eas_message_cls,
            config=eas_config,
            logger=log,
            location_settings=location_settings,
        )
    except Exception as exc:
        result['reason'] = f"Failed to initialize EASBroadcaster: {exc}"
        log.error("OTA auto-forward failed: %s", result['reason'])
        return result

    # Push the alert text onto every active Icecast stream while the broadcast
    # is on the air; clear it once handle_alert() returns so normal source
    # metadata resumes.
    from app_core.audio.alert_metadata import (
        clear_alert_metadata,
        set_alert_metadata,
    )

    alert_title = (alert_object.headline or '').strip()
    if alert_title:
        set_alert_metadata(alert_title)

    try:
        try:
            broadcast_result = broadcaster.handle_alert(alert_object, payload)
        finally:
            if alert_title:
                clear_alert_metadata()
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
