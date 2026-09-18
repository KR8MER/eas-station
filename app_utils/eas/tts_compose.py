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

"""Composing the final spoken message text from an alert and its NWS payload."""

import re
from datetime import datetime
from typing import Dict, List, Optional

from flask import current_app, has_app_context

from .same_header_constants import ORIGINATOR_DESCRIPTIONS
from .tts_normalize import _normalize_text_for_tts



def _strip_awips_identifier(description: str, parameters: Dict[str, object]) -> str:
    """Strip the leading AWIPS product identifier from an NWS description.

    NWS warning products begin the CAP ``<description>`` with the internal
    AWIPS product identifier on its own line (e.g. ``"SVRCLE"`` for a Severe
    Thunderstorm Warning from the Cleveland office), followed by a blank line
    and the human-readable text::

        SVRCLE

        The National Weather Service in Cleveland has issued a
        ...

    The identifier is an internal routing code, not narratable content, so it
    should not be spoken in the TTS voiceover.  This removes it when present.

    Stripping is driven solely by the exact value from the CAP
    ``AWIPSidentifier`` parameter, and only when the description actually
    begins with it on its own line.  Many alerts have no AWIPS identifier (and
    some legitimately begin with a short all-caps line), so no shape-based
    heuristic is applied — that would risk deleting real content from messages
    that never carried an identifier.  When the parameter is absent or does not
    match the start of the description, the text is returned unchanged.
    """
    if not description:
        return description

    if not isinstance(parameters, dict):
        return description

    awips_val = parameters.get('AWIPSidentifier')
    if isinstance(awips_val, list):
        awips_val = awips_val[0] if awips_val else None
    if not awips_val:
        return description

    awips = str(awips_val).strip()
    if not awips:
        return description

    import re as _re

    # Strip the identifier only when the description opens with it on its own
    # line (optional trailing spaces, then a newline).
    pattern = r'^\s*' + _re.escape(awips) + r'[ \t]*\r?\n'
    stripped = _re.sub(pattern, '', description, count=1, flags=_re.IGNORECASE)
    if stripped != description:
        return stripped.lstrip('\r\n')

    return description




def _compose_message_text(
    alert: object,
    payload: Optional[Dict[str, object]] = None,
    db_session=None,
) -> str:
    """Build the TTS narration text from the alert body.

    Structure (in order of preference):
    1. EASText CAP parameter — if present, use verbatim (§3.6.3).
    2. Otherwise: senderName + description + instruction (§3.6.2).
       NOTE: headline is metadata, not alert content, and is excluded.
    3. IPAWS/WEA fallback when description AND instruction are empty:
       senderName + CMAMlongtext, then CMAMtext, then headline.  Many
       IPAWS-only senders (e.g. OHDOT) place the narratable text only in
       CMAMlongtext; without this fallback the audio would be limited to
       "Message from <senderName>".
    4. Fallback: generated FCC Required Text when no body text is available.

    Total text is hard-capped at 1800 characters (§3.6.5).
    All text is passed through _normalize_text_for_tts before returning.
    """
    import re as _re

    payload = payload or {}
    raw_json = payload.get('raw_json') or {}
    properties = raw_json.get('properties', {}) if isinstance(raw_json, dict) else {}
    parameters = properties.get('parameters', {}) if isinstance(properties, dict) else {}
    if not isinstance(parameters, dict):
        parameters = {}

    # ── FCC Required Text ───────────────────────────────────────────────
    # Originator description.
    #
    # ECIG §3.10: when a CAP 1.1 message arrives with no originator, assume
    # CIV.  In practice CAP 1.2 IPAWS messages always carry EAS-ORG; the
    # fallback below only fires for non-NOAA sources missing the parameter.
    # NOAA / NWS alerts default to WXR because their CAP feeds typically
    # omit EAS-ORG and the National Weather Service is the implicit
    # originator.
    eas_org_val = parameters.get('EAS-ORG')
    if isinstance(eas_org_val, list):
        eas_org_val = eas_org_val[0] if eas_org_val else None
    if eas_org_val:
        originator_code = str(eas_org_val).strip().upper()
    else:
        alert_source = (
            getattr(alert, 'source', None)
            or payload.get('source')
            or ''
        )
        if str(alert_source).strip().upper() in ('NOAA', 'NWS'):
            originator_code = 'WXR'
        else:
            originator_code = 'CIV'  # ECIG §3.10
    originator_desc = ORIGINATOR_DESCRIPTIONS.get(originator_code, originator_code)

    # Event name
    event_name = (
        (getattr(alert, 'event', '') or '')
        or str(properties.get('event', '') or payload.get('event', '') or '')
    ).strip() or 'Emergency Alert'

    # Area description
    area_desc = str(properties.get('areaDesc', '') or '').strip()
    if not area_desc:
        area_desc = 'the affected area'

    # Sent / expires times — prefer datetime objects for formatting
    sent_dt = getattr(alert, 'sent', None) or payload.get('sent')
    expires_dt = getattr(alert, 'expires', None) or payload.get('expires')

    def _fmt_time(dt) -> str:
        """Format a datetime for FCC Required Text (12-hour with timezone abbrev)."""
        if isinstance(dt, datetime):
            try:
                local_dt = dt.astimezone()  # system local timezone
                tz_name = local_dt.strftime('%Z') or 'UTC'
                return local_dt.strftime(f'%I:%M %p {tz_name}').lstrip('0')
            except Exception:
                return dt.strftime('%I:%M %p UTC').lstrip('0')
        if isinstance(dt, str):
            return dt
        return 'an unspecified time'

    sent_str = _fmt_time(sent_dt)
    expires_str = _fmt_time(expires_dt)

    fcc_required = (
        f"A {originator_desc} HAS ISSUED A {event_name} FOR THE FOLLOWING "
        f"COUNTIES/AREAS: {area_desc}; AT {sent_str} EFFECTIVE UNTIL {expires_str}."
    )

    # ── Body text: EASText or description/instruction ────────────────────
    # ECIG §3.6.3: if EASText parameter is present, use it verbatim
    eas_text_val = parameters.get('EASText')
    if isinstance(eas_text_val, list):
        eas_text_val = eas_text_val[0] if eas_text_val else None

    if eas_text_val:
        body = str(eas_text_val).strip()
    else:
        body_parts: List[str] = []
        sender = str(properties.get('senderName', '') or '').strip()
        if sender:
            body_parts.append(f"Message from {sender}.")

        description = str(getattr(alert, 'description', '') or '').strip()
        instruction = str(getattr(alert, 'instruction', '') or '').strip()

        # Strip the leading AWIPS product identifier (e.g. "SVRCLE") that NWS
        # places on the first line of warning descriptions — it is an internal
        # routing code, not narratable content.
        description = _strip_awips_identifier(description, parameters)

        if description:
            body_parts.append(description)
        if instruction:
            body_parts.append(instruction)

        # IPAWS / WEA fallback: when an alert lacks a CAP <description> and
        # <instruction> (common for IPAWS-only senders such as OHDOT), the
        # narratable text lives in the WEA-specific CAP parameters.  Prefer
        # CMAMlongtext (≤360 chars), then CMAMtext (≤90 chars), then the
        # CAP <headline>.  Without this fallback the only audio rendered
        # from such alerts would be "Message from <senderName>", which omits
        # the actual emergency content.
        if not description and not instruction:
            def _first_str(value):
                if isinstance(value, list):
                    value = value[0] if value else None
                if value is None:
                    return ''
                return str(value).strip()

            cmam_long = _first_str(parameters.get('CMAMlongtext'))
            cmam_short = _first_str(parameters.get('CMAMtext'))
            headline = str(properties.get('headline', '') or '').strip()

            fallback_text = cmam_long or cmam_short or headline
            if fallback_text:
                body_parts.append(fallback_text)

        body = '\n\n'.join(body_parts).strip()

    # Use only the body for TTS narration — the SAME header already encodes the
    # event/area/time metadata, and NWR plays only the description text, not a
    # generated headline sentence.  Fall back to fcc_required only when there is
    # no body at all.
    if body:
        full_text = body
    else:
        full_text = fcc_required

    # Cap TTS narration at 4096 characters.  The SAME header data field is a
    # separate 255-character field; TTS narration has no FCC length mandate and
    # 4096 chars comfortably fits within all major TTS provider API limits
    # (Azure OpenAI TTS: 4096; Azure Speech SDK: no hard per-call limit).
    # Long NWS alerts with multi-county boilerplate preamble previously hit
    # the old 1800-char limit before the specific * WHAT / * WHERE detail
    # lines, cutting off the most actionable parts of the message.
    if len(full_text) > 4096:
        full_text = full_text[:4093] + '...'

    return _normalize_text_for_tts(full_text, db_session=db_session)




def manual_default_same_codes() -> List[str]:
    """Return the default SAME/FIPS codes for manual broadcast generation.
    
    Returns codes for WHERE TO BROADCAST (RWT, manual activations).
    These are loaded from RWTScheduleConfig.same_codes (broadcast coverage area).
    
    Note: These codes are for BROADCASTING, not for filtering incoming alerts.
    LocationSettings.fips_codes are for filtering (can include nationwide/statewide),
    while RWT broadcast codes should only include local coverage area counties.
    """

    # Use RWTScheduleConfig.same_codes (broadcast coverage area)
    codes: List[str] = []
    if has_app_context():
        try:
            from app_core.models import RWTScheduleConfig
            from app_core.extensions import db

            config = RWTScheduleConfig.query.first()
            if config and config.same_codes:
                stored_codes = config.same_codes or []
                for value in stored_codes:
                    digits = re.sub(r'[^0-9]', '', str(value))
                    if digits:
                        codes.append(digits.zfill(6)[:6])
                return codes[:31]
        except Exception as exc:
            if current_app:
                current_app.logger.warning(
                    "Failed to load RWT broadcast SAME codes: %s", exc
                )

    # Return empty list - user should configure RWT broadcast codes
    return []
