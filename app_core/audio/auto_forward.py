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

# Deduplication windows.
#
# CROSS_SOURCE_DEDUP_WINDOW_MINUTES is the window used when we only have
# event code + FIPS to compare with (CAP path; no raw SAME header).  15
# minutes balances catching cross-source duplicates against over-
# suppressing legitimate re-issues of the same alert type.
#
# HEADER_KEY_DEDUP_WINDOW_MINUTES is the window used when we can match
# on the callsign-independent SAME-header key.  Because the header key
# already encodes the issuer's release time (JJJHHMM) — which is unique
# per alert issuance — an identical key means the *same alert*, not
# merely a similar one, and there is no reason to re-broadcast it
# regardless of when the second copy arrives.  24 hours comfortably
# covers any SAME purge time we will encounter in practice.
CROSS_SOURCE_DEDUP_WINDOW_MINUTES = 15
HEADER_KEY_DEDUP_WINDOW_MINUTES = 24 * 60


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


def _alert_dedupe_lock_key(
    event_code: Optional[str],
    fips_codes: Optional[List[str]],
) -> Optional[int]:
    """Compute a stable 63-bit signed-int advisory-lock key for *this
    specific alert*.

    Derived from ``event_code + sorted FIPS`` — the lowest common
    denominator that BOTH the CAP path (no raw SAME header) and the
    OTA path (raw SAME header) can compute.  Using a shared key is
    essential: if CAP and OTA arrivals of the same alert took
    *different* locks, they would not actually serialize against each
    other and the back-to-back-duplicate race would persist.
    """
    import hashlib
    if not event_code:
        return None
    fips_part = ",".join(sorted(fips_codes or []))
    if not fips_part:
        return None
    key_str = f"{event_code}|{fips_part}"
    digest = hashlib.sha256(key_str.encode("utf-8")).digest()
    # First 8 bytes -> signed int64; mask top bit to keep it positive so
    # we don't trip "out of range" checks in older drivers.
    return int.from_bytes(digest[:8], "big", signed=False) & 0x7FFFFFFFFFFFFFFF


def _acquire_dedupe_lock(db_session, lock_key: Optional[int]) -> None:
    """Take a transaction-scoped advisory lock on the given key.

    The lock is released automatically when the current transaction
    commits or rolls back.  A no-op when ``lock_key`` is None or the
    underlying engine is not PostgreSQL.
    """
    if lock_key is None:
        return
    try:
        from sqlalchemy import text
        # pg_advisory_xact_lock is PostgreSQL-specific.  On other
        # engines this will raise and we silently degrade (the prior
        # behaviour — race window present — is preserved).
        db_session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"),
            {"k": lock_key},
        )
    except Exception as exc:
        logger.debug("Advisory dedupe lock unavailable (%s); racing", exc)


def _same_header_dedupe_key(header: Optional[str]) -> Optional[str]:
    """Reduce a SAME header to a callsign-independent dedupe key.

    A SAME header looks like
        ``ZCZC-ORG-EVT-PSSCCC-...+TTTT-JJJHHMM-CCCCCCCC-``
    Two relays of the same NWS alert differ only in the trailing
    callsign field, so dropping it gives a key that identifies the alert
    itself regardless of which station relayed it.
    """
    if not header:
        return None
    header = header.strip()
    if not header.startswith("ZCZC"):
        return None
    parts = header.split("-")
    if len(parts) < 5:
        return None
    return "-".join(parts[:-2])


def _parse_same_header(header: Optional[str]):
    """Extract (originator, event_code, fips_set, issue_time) from a SAME
    header.  Returns ``None`` if the header does not parse.

    SAME header format:
        ``ZCZC-ORG-EVT-PSSCCC[-PSSCCC...]+TTTT-JJJHHMM-CCCCCCCC-``
    The first FIPS field through the last carry ``+TTTT`` on the last
    one; ``JJJHHMM`` (parts[-3]) is the issuer's release time and is the
    closest thing to a globally-unique alert identifier we get from the
    SAME header alone.
    """
    if not header:
        return None
    header = header.strip()
    if not header.startswith("ZCZC"):
        return None
    parts = header.split("-")
    if len(parts) < 6:
        return None
    try:
        originator = parts[1]
        event_code = parts[2]
        issue_time = parts[-3]
        # FIPS codes live between parts[3] and parts[-3], with the last
        # one of them carrying "+TTTT" purge-time suffix.
        fips_set = set()
        for raw in parts[3:-3] + [parts[-3 - 1]] if False else parts[3:-3]:
            # The +TTTT suffix lives on the final FIPS field; strip it.
            code = raw.split("+", 1)[0]
            code = "".join(ch for ch in code if ch.isdigit())
            if code:
                fips_set.add(code.zfill(6)[:6])
        # parts[3:-3] above ends before the "+TTTT-JJJHHMM" pair; the
        # last FIPS-bearing field is actually parts[-4] (because of the
        # "+" glued to it).  Pull it explicitly to be safe.
        last_fips_field = parts[-4]
        code = last_fips_field.split("+", 1)[0]
        code = "".join(ch for ch in code if ch.isdigit())
        if code:
            fips_set.add(code.zfill(6)[:6])
        return originator, event_code, fips_set, issue_time
    except (IndexError, ValueError):
        return None


def is_duplicate_broadcast(
    event_code: str,
    fips_codes: List[str],
    db_session,
    window_minutes: int = CROSS_SOURCE_DEDUP_WINDOW_MINUTES,
    raw_same_header: Optional[str] = None,
) -> bool:
    """Check whether *this specific alert* has already been broadcast
    within the deduplication window.

    Matching rules (in priority order):

    1. **Header-key match.**  When ``raw_same_header`` is supplied and
       contains a usable SAME header, compute its callsign-independent
       dedupe key (see :func:`_same_header_dedupe_key`) and look for any
       broadcast within ``HEADER_KEY_DEDUP_WINDOW_MINUTES`` whose
       ``same_header`` reduces to the same key.  The header key already
       encodes the issuer's release time (JJJHHMM), so two messages
       with the same key are the *same alert issuance* and should never
       both broadcast regardless of how far apart they arrive.  A long
       window is necessary because relay broadcasts of the same alert
       routinely arrive 15–30 minutes after the CAP feed.

    2. **Full-FIPS match.**  When no header is available (CAP alerts
       carry only structured fields), use ``window_minutes`` (default
       15) and require the recent broadcast to have the *same event
       code* AND the *same FIPS set* (sorted-equal, not "any overlap").
       Requiring full-set match prevents two distinct SVRs — one for
       Williams+Steuben (039125, 039161) and one for Defiance+Williams+
       Henry (039039, 039125, 039137) — from suppressing each other
       just because they share Williams.

    Checks both ``EASMessage`` (CAP and OTA broadcasts) and
    ``ManualEASActivation`` (manual/RWT/auto-forwarded broadcasts).
    """
    if not event_code:
        return False

    fips_set = set(fips_codes or [])
    header_key = _same_header_dedupe_key(raw_same_header)

    if not header_key and not fips_set:
        # Without either signal, we cannot tell duplicates from distinct
        # alerts.  Don't suppress.
        return False

    now = datetime.now(timezone.utc)
    fips_cutoff = now - timedelta(minutes=window_minutes)
    # Header-key matches use a 24h window because the key includes the
    # unique issue time and so cannot produce false positives.
    header_cutoff = now - timedelta(minutes=HEADER_KEY_DEDUP_WINDOW_MINUTES)
    cutoff = header_cutoff if header_key else fips_cutoff

    # Parse the incoming raw header once if available.  This gives us the
    # issuer-identity triple (originator, event, issue_time) which is the
    # strongest cross-source identity signal we have.
    incoming = _parse_same_header(raw_same_header)

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
            if msg_event_code != event_code:
                continue

            # 1) Header-key match (preferred when available — strongest signal)
            if header_key:
                msg_key = _same_header_dedupe_key(msg.same_header)
                if msg_key and msg_key == header_key:
                    logger.info(
                        "Cross-source duplicate detected in EASMessage (header "
                        "key match): event=%s, key=%s (message_id=%s)",
                        event_code, header_key, msg.id,
                    )
                    return True

            # 2) Issuer-identity match: same originator + event + issue
            # time, with overlapping FIPS.  Catches the case where a
            # relay station's incoming raw_header has a broader FIPS set
            # than the local outgoing broadcast (we filter to our
            # configured coverage area before transmitting), so the
            # header keys legitimately differ but the alert is the same
            # NWS issuance.  Example from 2026-05-18: 16:11 CAP
            # broadcast SVR-039173, then 16:29 DON/JKZ relay arrived
            # with incoming FIPS 039095-039173 — same originator
            # (WXR), event (SVR) and issue time (1382009), overlapping
            # on 039173 — same alert.
            if incoming is not None:
                msg_parsed = _parse_same_header(msg.same_header)
                if msg_parsed is not None:
                    m_orig, m_evt, m_fips, m_issue = msg_parsed
                    i_orig, i_evt, i_fips, i_issue = incoming
                    if (
                        m_orig == i_orig
                        and m_evt == i_evt
                        and m_issue == i_issue
                        and (m_fips & i_fips)
                    ):
                        logger.info(
                            "Cross-source duplicate detected in EASMessage "
                            "(issuer-identity match): event=%s, originator=%s, "
                            "issue_time=%s, FIPS overlap=%s (message_id=%s)",
                            event_code, i_orig, i_issue,
                            sorted(m_fips & i_fips), msg.id,
                        )
                        return True
                # If header_key was provided and matched nothing above,
                # don't fall through to the lossy FIPS-set check — we
                # have enough signal already.
                if header_key:
                    continue

            # 3) Full-FIPS-set match (only when no header at all)
            if not header_key:
                msg_locations = set(meta.get('locations', []) or [])
                if msg_locations and msg_locations == fips_set:
                    logger.info(
                        "Cross-source duplicate detected in EASMessage (full-FIPS "
                        "match): event=%s, FIPS=%s (message_id=%s)",
                        event_code, sorted(fips_set), msg.id,
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
            # 1) Header-key match
            if header_key:
                act_key = _same_header_dedupe_key(activation.same_header)
                if act_key and act_key == header_key:
                    logger.info(
                        "Cross-source duplicate detected in ManualEASActivation "
                        "(header key match): event=%s, key=%s (activation_id=%s)",
                        event_code, header_key, activation.id,
                    )
                    return True
            # 2) Issuer-identity match
            if incoming is not None:
                act_parsed = _parse_same_header(activation.same_header)
                if act_parsed is not None:
                    m_orig, m_evt, m_fips, m_issue = act_parsed
                    i_orig, i_evt, i_fips, i_issue = incoming
                    if (
                        m_orig == i_orig
                        and m_evt == i_evt
                        and m_issue == i_issue
                        and (m_fips & i_fips)
                    ):
                        logger.info(
                            "Cross-source duplicate detected in ManualEASActivation "
                            "(issuer-identity match): event=%s, originator=%s, "
                            "issue_time=%s, FIPS overlap=%s (activation_id=%s)",
                            event_code, i_orig, i_issue,
                            sorted(m_fips & i_fips), activation.id,
                        )
                        return True
                if header_key:
                    continue
            # 3) Full-FIPS-set match (only when no header at all)
            if not header_key:
                activation_fips = set(activation.same_locations or [])
                if activation_fips and activation_fips == fips_set:
                    logger.info(
                        "Cross-source duplicate detected in ManualEASActivation "
                        "(full-FIPS match): event=%s, FIPS=%s (activation_id=%s)",
                        event_code, sorted(fips_set), activation.id,
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

    # Cross-source deduplication (skipped for UPG).  Take a per-alert
    # advisory lock so concurrent CAP/OTA arrivals for the same alert
    # serialize through the check-then-commit sequence.
    if event_code and fips_codes_for_dedup:
        _acquire_dedupe_lock(
            db_session,
            _alert_dedupe_lock_key(event_code, fips_codes_for_dedup),
        )
        if is_duplicate_broadcast(event_code, fips_codes_for_dedup, db_session):
            reason = (
                f"Cross-source duplicate: {event_code} already broadcast "
                f"for the same FIPS set within {CROSS_SOURCE_DEDUP_WINDOW_MINUTES}min"
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

    # Cross-source deduplication.  Prefer the raw SAME header as the
    # dedupe key (it identifies the alert regardless of which station
    # relayed it); fall back to event code + full-FIPS-set match when
    # no header is available.
    raw_same_header = alert_dict.get('raw_header') or alert_dict.get('raw_text')
    if fips_codes or raw_same_header:
        # Serialize concurrent broadcasts of the SAME alert across
        # workers/processes.  Without this, two simultaneous arrivals
        # (CAP + OTA relay within ~1 s) can both pass the dedupe check
        # before either commits — the failure mode that produced two
        # back-to-back broadcasts of the same SVR at 16:54 EDT on
        # 2026-05-19.  The lock is keyed on the alert (not global) so
        # broadcasts of distinct alerts proceed in parallel.
        _acquire_dedupe_lock(
            db_session,
            _alert_dedupe_lock_key(event_code, fips_codes),
        )
        if is_duplicate_broadcast(
            event_code,
            fips_codes,
            db_session,
            raw_same_header=raw_same_header,
        ):
            result['reason'] = (
                f"Cross-source duplicate: {event_code} already broadcast "
                f"for the same alert within {HEADER_KEY_DEDUP_WINDOW_MINUTES}min"
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
