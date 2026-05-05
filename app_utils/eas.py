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

from __future__ import annotations

"""Helpers for generating and broadcasting EAS-compatible audio output."""

import io
import json
import math
import os
import re
import struct
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from flask import current_app, has_app_context

from app_utils.event_codes import EVENT_CODE_REGISTRY, resolve_event_code
from app_utils.fips_codes import P_DIGIT_LABELS
from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS

from .eas_fsk import (
    SAME_BAUD,
    SAME_MARK_FREQ,
    SAME_SPACE_FREQ,
    encode_same_bits,
    encode_terminator_bits,
    generate_fsk_samples,
)
from .eas_tts import TTSEngine
from .gpio import (
    GPIOActivationType,
    GPIOBehaviorManager,
    GPIOController,
    GPIOPinConfig,
    load_gpio_behavior_matrix_from_db,
    load_gpio_pin_configs_from_db,
)


def _get_oled_enabled_status():
    """Get OLED enabled status from database."""
    try:
        from app_core.hardware_settings import get_oled_settings
        oled_settings = get_oled_settings()
        return oled_settings.get('enabled', False)
    except Exception:
        return False


_BROADCAST_STATE_KEY = 'eas:broadcast_active'
_INCOMING_STATE_KEY = 'eas:incoming_alert'


def set_incoming_alert(event_code: str = '') -> None:
    """Record in Redis that an alert has been received but broadcast has not started.

    Called when an alert is first processed so hardware indicators (tower light)
    can show a pre-broadcast "incoming" state (e.g. yellow blink) while audio
    is being generated and the playout decision is being made.  The key carries
    a short TTL so stale entries self-expire if the broadcast never starts.
    """
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return
        payload = json.dumps({'incoming': True, 'event_code': event_code or '', 'ts': time.time()})
        client.set(_INCOMING_STATE_KEY, payload, ex=300)  # 5-minute safety TTL
    except Exception:
        pass


def clear_incoming_alert() -> None:
    """Remove the incoming alert marker from Redis."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return
        client.delete(_INCOMING_STATE_KEY)
    except Exception:
        pass


def get_incoming_alert_state() -> dict:
    """Return current incoming-alert state dict, or ``{'incoming': False}`` if none."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return {'incoming': False}
        raw = client.get(_INCOMING_STATE_KEY)
        if raw is None:
            return {'incoming': False}
        return json.loads(raw)
    except Exception:
        return {'incoming': False}


def set_broadcast_active(
    event_code: str,
    label: str,
    duration_seconds: float,
    source: str = 'manual',
) -> None:
    """Record in Redis that an EAS broadcast is in progress.

    Called just before audio playback begins so all connected clients can
    display a live countdown timer regardless of which page they are on.
    """
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return
        payload = json.dumps({
            'active': True,
            'start_ts': time.time(),
            'duration_seconds': float(duration_seconds),
            'event_code': event_code or '',
            'label': label or event_code or 'EAS Alert',
            'source': source,
        })
        # TTL = duration + 60 s safety margin so stale entries self-expire
        ttl = max(60, int(duration_seconds) + 60)
        client.set(_BROADCAST_STATE_KEY, payload, ex=ttl)
        # Broadcast starting supersedes the incoming-alert state
        client.delete(_INCOMING_STATE_KEY)
    except Exception:
        pass


def clear_broadcast_active() -> None:
    """Remove the active broadcast marker from Redis once playback ends."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return
        client.delete(_BROADCAST_STATE_KEY)
    except Exception:
        pass


def get_broadcast_state() -> dict:
    """Return current broadcast state dict, or ``{'active': False}`` if idle."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return {'active': False}
        raw = client.get(_BROADCAST_STATE_KEY)
        if raw is None:
            return {'active': False}
        return json.loads(raw)
    except Exception:
        return {'active': False}


MANUAL_FIPS_ENV_TOKENS = {'ALL', 'ANY', 'US', 'USA', '*'}


def _clean_identifier(value: str) -> str:
    value = value.strip().replace(' ', '_')
    value = re.sub(r'[^A-Za-z0-9_.-]+', '_', value)
    return value[:96] or 'alert'


def _normalise_same_codes(values: Iterable[str]) -> List[str]:
    normalised: List[str] = []
    for value in values:
        digits = ''.join(ch for ch in str(value) if ch.isdigit())
        if digits:
            normalised.append(digits.zfill(6))
    return normalised


def _ensure_directory(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def load_eas_config(base_path: Optional[str] = None, db_session=None) -> Dict[str, object]:
    """Build a runtime configuration dictionary for EAS broadcasting.

    Args:
        base_path: Base filesystem path for locating static assets.
        db_session: Optional raw SQLAlchemy session.  When the caller runs
            outside a Flask application context (e.g. the standalone CAP
            poller process) the Flask-SQLAlchemy proxy cannot access the
            database.  Pass the caller's own session so TTS settings can
            still be read directly from the database.
    """

    base_path = base_path or os.getenv('EAS_BASE_PATH') or os.getcwd()
    static_dir = os.getenv('EAS_STATIC_DIR')
    if static_dir and not os.path.isabs(static_dir):
        static_dir = os.path.join(base_path, static_dir)
    static_dir = static_dir or os.path.join(base_path, 'static')

    default_output = os.path.join(static_dir, 'eas_messages')
    output_dir = os.getenv('EAS_OUTPUT_DIR', default_output)
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(base_path, output_dir)

    web_subdir = os.getenv('EAS_OUTPUT_WEB_PATH') or os.getenv('EAS_OUTPUT_WEB_SUBDIR')
    if web_subdir:
        web_subdir = web_subdir.strip('/')
    else:
        web_subdir = 'eas_messages'

    oled_enabled = _get_oled_enabled_status()
    gpio_configs = load_gpio_pin_configs_from_db(oled_enabled=oled_enabled)
    gpio_behavior_matrix = load_gpio_behavior_matrix_from_db(oled_enabled=oled_enabled)

    # Load TTS configuration from database only
    from app_core.tts_settings import get_tts_settings
    import logging
    load_logger = logging.getLogger('eas.config')

    tts_provider = ''
    azure_openai_endpoint = ''
    azure_openai_key = ''
    azure_openai_model = 'tts-1'
    azure_openai_voice = 'alloy'
    azure_openai_speed = 1.0

    tts_settings = None

    # When db_session is provided the caller runs outside a Flask app context
    # (e.g. the standalone CAP poller).  get_tts_settings() relies on
    # Flask-SQLAlchemy, which raises RuntimeError when there is no active
    # application context.  Critically, get_tts_settings() catches that
    # exception internally and returns a *fake* TTSSettings(id=1) object with
    # enabled=False — it never propagates the error.  That fake object is not
    # None, so the old "if tts_settings is None" guard below was permanently
    # short-circuited: the db_session fallback was never reached and TTS was
    # always treated as disabled for every CAP/IPAWS alert.
    #
    # Fix: when db_session is supplied, query it directly and skip
    # get_tts_settings() entirely.  This mirrors the pattern already used for
    # EASSettings further down this function (Bug 3 in test_airchain_fringe_cases).
    if db_session is not None:
        try:
            from app_core.models import TTSSettings as _TTSSettings
            tts_settings = db_session.get(_TTSSettings, 1)
            if tts_settings is not None:
                load_logger.info(
                    f"TTS settings from DB (direct session): enabled={tts_settings.enabled}, "
                    f"provider='{tts_settings.provider}'"
                )
            else:
                load_logger.info("TTS settings row not found via direct session (id=1); TTS disabled")
        except Exception as exc:
            load_logger.error(f"Failed to load TTS settings from direct session: {exc}")

    # Flask-SQLAlchemy path: only used when no db_session was provided, i.e.
    # we are running inside a Flask request handler or app context where
    # get_tts_settings() can reach the database normally.
    if tts_settings is None:
        try:
            tts_settings = get_tts_settings()
            load_logger.info(
                f"TTS settings from DB (Flask context): enabled={tts_settings.enabled}, "
                f"provider='{tts_settings.provider}'"
            )
        except Exception as exc:
            load_logger.warning(
                f"Could not load TTS settings via Flask context: {exc}."
            )

    if tts_settings is not None:
        if not tts_settings.enabled:
            load_logger.info("TTS is disabled in database settings")
        elif not tts_settings.provider:
            load_logger.warning("TTS is enabled but provider is empty in database settings")
        else:
            tts_provider = tts_settings.provider.strip().lower()
            load_logger.info(f"TTS enabled with provider: {tts_provider}")

            # Load Azure OpenAI settings if provider is azure_openai
            if tts_provider == 'azure_openai':
                azure_openai_endpoint = (tts_settings.azure_openai_endpoint or '').strip()
                azure_openai_key = (tts_settings.azure_openai_key or '').strip()
                azure_openai_model = (tts_settings.azure_openai_model or 'tts-1').strip()
                azure_openai_voice = (tts_settings.azure_openai_voice or 'alloy').strip()
                azure_openai_speed = tts_settings.azure_openai_speed or 1.0

                load_logger.info(
                    f"Azure OpenAI TTS config loaded: "
                    f"endpoint={'<set>' if azure_openai_endpoint else '<MISSING>'}, "
                    f"key={'<set>' if azure_openai_key else '<MISSING>'}"
                )

                if not azure_openai_endpoint:
                    load_logger.error("Azure OpenAI TTS enabled but endpoint is empty!")
                if not azure_openai_key:
                    load_logger.error("Azure OpenAI TTS enabled but API key is empty!")
    else:
        load_logger.warning("TTS settings could not be loaded from database; TTS will be disabled")

    # Load station identity from database (EASSettings row 1), falling back to
    # environment variables for backwards compatibility, then to hardcoded defaults.
    db_originator = None
    db_station_id = None
    db_broadcast_enabled = None
    db_sample_rate = None
    db_attention_tone_seconds = None
    db_max_activation_seconds = None
    db_audio_player = None
    db_endec_fingerprint = None
    db_pre_alert_chime = None
    db_post_alert_chime = None
    db_pre_alert_chime_duration = None
    db_post_alert_chime_duration = None
    db_qc2_tone_a_freq = None
    db_qc2_tone_b_freq = None
    db_qc2_long_tone_enabled = None
    db_qc2_long_tone_seconds = None
    db_dtmf_sequence = None
    db_forwarded_event_codes: List[str] = []
    try:
        from app_core.models import EASSettings
        eas_settings = EASSettings.query.get(1)
        if eas_settings:
            db_originator = eas_settings.originator
            db_station_id = eas_settings.station_id
            db_broadcast_enabled = eas_settings.broadcast_enabled
            db_sample_rate = eas_settings.sample_rate
            db_attention_tone_seconds = eas_settings.attention_tone_seconds
            db_max_activation_seconds = eas_settings.max_activation_seconds
            db_audio_player = eas_settings.audio_player
            db_endec_fingerprint = eas_settings.endec_fingerprint
            db_pre_alert_chime = getattr(eas_settings, 'pre_alert_chime', None)
            db_post_alert_chime = getattr(eas_settings, 'post_alert_chime', None)
            db_pre_alert_chime_duration = getattr(eas_settings, 'pre_alert_chime_duration', None)
            db_post_alert_chime_duration = getattr(eas_settings, 'post_alert_chime_duration', None)
            db_qc2_tone_a_freq = getattr(eas_settings, 'qc2_tone_a_freq', None)
            db_qc2_tone_b_freq = getattr(eas_settings, 'qc2_tone_b_freq', None)
            db_qc2_long_tone_enabled = getattr(eas_settings, 'qc2_long_tone_enabled', None)
            db_qc2_long_tone_seconds = getattr(eas_settings, 'qc2_long_tone_seconds', None)
            db_dtmf_sequence = getattr(eas_settings, 'dtmf_sequence', None)
            db_forwarded_event_codes = list(eas_settings.forwarded_event_codes or [])
            load_logger.info(
                'EASSettings loaded from DB: originator=%s station_id=%s broadcast_enabled=%s',
                db_originator, db_station_id, db_broadcast_enabled,
            )
    except Exception as exc:
        load_logger.debug('Could not load EASSettings from database: %s', exc)

    # Fallback: when called from a background process (e.g. the standalone CAP
    # poller) Flask-SQLAlchemy is unavailable.  Use the provided raw session
    # directly, mirroring the pattern already used for TTSSettings above.
    if db_broadcast_enabled is None and db_session is not None:
        try:
            from app_core.models import EASSettings as _EASSettings
            eas_settings = db_session.get(_EASSettings, 1)
            if eas_settings is not None:
                db_originator = eas_settings.originator
                db_station_id = eas_settings.station_id
                db_broadcast_enabled = eas_settings.broadcast_enabled
                db_sample_rate = eas_settings.sample_rate
                db_attention_tone_seconds = eas_settings.attention_tone_seconds
                db_max_activation_seconds = eas_settings.max_activation_seconds
                db_audio_player = eas_settings.audio_player
                db_endec_fingerprint = eas_settings.endec_fingerprint
                db_pre_alert_chime = getattr(eas_settings, 'pre_alert_chime', None)
                db_post_alert_chime = getattr(eas_settings, 'post_alert_chime', None)
                db_pre_alert_chime_duration = getattr(eas_settings, 'pre_alert_chime_duration', None)
                db_post_alert_chime_duration = getattr(eas_settings, 'post_alert_chime_duration', None)
                db_qc2_tone_a_freq = getattr(eas_settings, 'qc2_tone_a_freq', None)
                db_qc2_tone_b_freq = getattr(eas_settings, 'qc2_tone_b_freq', None)
                db_qc2_long_tone_enabled = getattr(eas_settings, 'qc2_long_tone_enabled', None)
                db_qc2_long_tone_seconds = getattr(eas_settings, 'qc2_long_tone_seconds', None)
                db_dtmf_sequence = getattr(eas_settings, 'dtmf_sequence', None)
                db_forwarded_event_codes = list(eas_settings.forwarded_event_codes or [])
                load_logger.info(
                    'EASSettings loaded from DB (direct session): originator=%s station_id=%s broadcast_enabled=%s',
                    db_originator, db_station_id, db_broadcast_enabled,
                )
            else:
                load_logger.info('EASSettings row not found via direct session (id=1)')
        except Exception as exc2:
            load_logger.error('Failed to load EASSettings from direct session: %s', exc2)

    config: Dict[str, object] = {
        'enabled': (
            db_broadcast_enabled if db_broadcast_enabled is not None
            else os.getenv('EAS_BROADCAST_ENABLED', 'false').lower() == 'true'
        ),
        'originator': (
            os.getenv('EAS_ORIGINATOR')
            or (db_originator if db_originator else None)
            or 'WXR'
        )[:3].upper(),
        'station_id': (
            os.getenv('EAS_STATION_ID')
            or (db_station_id if db_station_id else None)
            or 'EASNODES'
        ).strip()[:8],
        'output_dir': _ensure_directory(output_dir),
        'web_subdir': web_subdir,
        'audio_player_cmd': os.getenv('EAS_AUDIO_PLAYER', '').strip() or (db_audio_player or ''),
        'endec_fingerprint': (
            db_endec_fingerprint if db_endec_fingerprint is not None else True
        ),
        'pre_alert_chime': (
            os.getenv('EAS_PRE_ALERT_CHIME')
            or (db_pre_alert_chime if db_pre_alert_chime else 'none')
        ),
        'post_alert_chime': (
            os.getenv('EAS_POST_ALERT_CHIME')
            or (db_post_alert_chime if db_post_alert_chime else 'none')
        ),
        'pre_alert_chime_duration': float(
            os.getenv('EAS_PRE_ALERT_CHIME_DURATION')
            or (db_pre_alert_chime_duration if db_pre_alert_chime_duration is not None else 2.0)
        ),
        'post_alert_chime_duration': float(
            os.getenv('EAS_POST_ALERT_CHIME_DURATION')
            or (db_post_alert_chime_duration if db_post_alert_chime_duration is not None else 2.0)
        ),
        'qc2_tone_a_freq': float(
            os.getenv('EAS_QC2_TONE_A_FREQ')
            or (db_qc2_tone_a_freq if db_qc2_tone_a_freq is not None else 1000.0)
        ),
        'qc2_tone_b_freq': float(
            os.getenv('EAS_QC2_TONE_B_FREQ')
            or (db_qc2_tone_b_freq if db_qc2_tone_b_freq is not None else 1500.0)
        ),
        'qc2_long_tone_enabled': (
            os.getenv('EAS_QC2_LONG_TONE_ENABLED', '').lower() in ('1', 'true', 'yes')
            if os.getenv('EAS_QC2_LONG_TONE_ENABLED') is not None
            else bool(db_qc2_long_tone_enabled) if db_qc2_long_tone_enabled is not None else False
        ),
        'qc2_long_tone_seconds': float(
            os.getenv('EAS_QC2_LONG_TONE_SECONDS')
            or (db_qc2_long_tone_seconds if db_qc2_long_tone_seconds is not None else 10.0)
        ),
        'dtmf_sequence': (
            os.getenv('EAS_DTMF_SEQUENCE')
            or (db_dtmf_sequence if db_dtmf_sequence is not None else '')
        ),
        'attention_tone_seconds': float(
            os.getenv('EAS_ATTENTION_TONE_SECONDS')
            or (db_attention_tone_seconds if db_attention_tone_seconds is not None else 8)
        ),
        'max_activation_seconds': int(
            os.getenv('EAS_MAX_ACTIVATION_SECONDS')
            or (db_max_activation_seconds if db_max_activation_seconds is not None else 300)
        ),
        'gpio_pin_configs': [
            {
                'pin': cfg.pin,
                'name': cfg.name,
                'active_high': cfg.active_high,
                'hold_seconds': cfg.hold_seconds,
                'watchdog_seconds': cfg.watchdog_seconds,
            }
            for cfg in gpio_configs
        ],
        'gpio_behavior_matrix': {
            str(pin): [behavior.value for behavior in sorted(behaviors, key=lambda b: b.value)]
            for pin, behaviors in gpio_behavior_matrix.items()
        },
        'sample_rate': int(
            os.getenv('EAS_SAMPLE_RATE')
            or (db_sample_rate if db_sample_rate is not None else 16000)
        ),
        'tts_provider': tts_provider,
        'azure_speech_key': os.getenv('AZURE_SPEECH_KEY'),
        'azure_speech_region': os.getenv('AZURE_SPEECH_REGION'),
        'azure_speech_voice': os.getenv('AZURE_SPEECH_VOICE', 'en-US-AriaNeural'),
        'azure_speech_sample_rate': int(os.getenv('AZURE_SPEECH_SAMPLE_RATE', '24000') or 24000),
        'azure_openai_endpoint': azure_openai_endpoint,
        'azure_openai_key': azure_openai_key,
        'azure_openai_voice': azure_openai_voice,
        'azure_openai_model': azure_openai_model,
        'azure_openai_speed': azure_openai_speed,
        'pyttsx3_voice': os.getenv('PYTTSX3_VOICE'),
        'pyttsx3_rate': os.getenv('PYTTSX3_RATE'),
        'pyttsx3_volume': os.getenv('PYTTSX3_VOLUME'),
        'forwarded_event_codes': db_forwarded_event_codes,
    }

    if config['audio_player_cmd']:
        config['audio_player_cmd'] = config['audio_player_cmd'].split()

    return config


P_DIGIT_MEANINGS = dict(P_DIGIT_LABELS)

ORIGINATOR_DESCRIPTIONS = {
    'EAS': 'EAS Participant / broadcaster',
    'CIV': 'Civil authorities',
    'WXR': 'National Weather Service',
    'PEP': 'National Public Warning System (PEP)',
}

# County abbreviations for Lima Ohio EAS Operational Area
COUNTY_ABBREVIATIONS = {
    'ALLE': 'Allen',
    'AUGL': 'Auglaize',
    'HANC': 'Hancock',
    'HARD': 'Hardin',
    'MERC': 'Mercer',
    'PAUL': 'Paulding',
    'PUTN': 'Putnam',
    'VANW': 'Van Wert',
}

def decode_county_originator(originator_code: str) -> Optional[str]:
    """
    Decode county-based originator codes.

    Format: XXXXCOEM or XXXXCOSO
    Where:
    - XXXX = 4-letter county abbreviation
    - CO = County
    - EM = Emergency Management
    - SO = Sheriff's Office

    Examples:
    - PUTNCOSO = Putnam County Sheriff's Office
    - PUTNCOEM = Putnam County Emergency Management
    """
    code = originator_code.upper().strip()

    # Check if it matches the county pattern (8 characters)
    if len(code) != 8:
        return None

    # Extract components
    county_abbr = code[:4]
    middle = code[4:6]  # Should be 'CO'
    suffix = code[6:8]  # Either 'EM' or 'SO'

    # Validate the middle part
    if middle != 'CO':
        return None

    # Get county name
    county_name = COUNTY_ABBREVIATIONS.get(county_abbr)
    if not county_name:
        return None

    # Decode the suffix
    if suffix == 'EM':
        return f"{county_name} County Emergency Management"
    elif suffix == 'SO':
        return f"{county_name} County Sheriff's Office"

    return None

PRIMARY_ORIGINATORS: Tuple[str, ...] = ('EAS', 'CIV', 'WXR', 'PEP')

# NRSC-4-B §4.3.3.4 — exactly fourteen valid purge-time HHMM values.
# Times are encoded as HHMM (hours and minutes), not decimal minutes.
# 15-minute increments up to 0045; 30-minute increments from 0100 to 0600.
NRSC4B_VALID_PURGE_TIMES: Tuple[str, ...] = (
    '0015', '0030', '0045',
    '0100', '0130',
    '0200', '0230',
    '0300', '0330',
    '0400', '0430',
    '0500', '0530',
    '0600',
)

# NRSC-4-B §4.3.3.3 — maximum number of location codes in a single header.
NRSC4B_MAX_LOCATIONS: int = 31

# NRSC-4-B §4.3.3.2 — valid originator codes.
NRSC4B_VALID_ORIGINATORS: Tuple[str, ...] = PRIMARY_ORIGINATORS

# NRSC-4-B §4.3.3.7 — station identifier length (characters, excluding delimiters).
NRSC4B_STATION_ID_MAX_LEN: int = 8

# NRSC-4-B §4.2 — preamble byte value and repetition count.
NRSC4B_PREAMBLE_BYTE: int = 0xAB
NRSC4B_PREAMBLE_COUNT: int = 16

# NRSC-4-B §4.4 — FSK physical-layer constants.
# Baud rate: exactly 25000/48 = 520.833... symbols/second per NRSC-4-B §4.4.
NRSC4B_BAUD_RATE_FRAC: str = '25000/48'  # exact rational representation (≈ 520.83 baud)
NRSC4B_MARK_FREQ_HZ: float = 2083.0 + 1.0 / 3.0   # 2083 1/3 Hz
NRSC4B_SPACE_FREQ_HZ: float = 1562.5                # 1562.5 Hz
NRSC4B_CENTER_FREQ_HZ: float = 1822.916666          # midpoint (mark+space)/2

# NRSC-4-B §4.5 — triple-burst transmission count.
NRSC4B_BURST_COUNT: int = 3


SAME_HEADER_FIELD_DESCRIPTIONS = [
    {
        'segment': 'Preamble',
        'label': '16 × 0xAB',
        'nrsc4b_section': '§4.2',
        'description': (
            'Sixteen bytes of 0xAB (10101011 binary) transmitted before the ASCII header '
            'to calibrate and synchronise receivers.  Each byte is sent LSB-first with no '
            'start or stop framing, giving a 128-bit alternating mark/space pattern.'
        ),
    },
    {
        'segment': 'ZCZC',
        'label': 'Start code',
        'nrsc4b_section': '§4.3.2',
        'description': (
            'Four ASCII characters marking the start of the SAME header.  '
            'Inherited from NAVTEX to trigger automatic decoders.  '
            'Always the literal string "ZCZC" with no leading dash.'
        ),
    },
    {
        'segment': 'ORG',
        'label': 'Originator code',
        'nrsc4b_section': '§4.3.3.2',
        'description': (
            'Three-character code identifying who issued the alert.  '
            'Valid values: EAS (EAS Participant/broadcaster), CIV (Civil authorities), '
            'WXR (National Weather Service), PEP (National Public Warning System).'
        ),
        'valid_values': list(NRSC4B_VALID_ORIGINATORS),
    },
    {
        'segment': 'EEE',
        'label': 'Event code',
        'nrsc4b_section': '§4.3.3.3',
        'description': (
            'Three-character SAME event code describing the hazard (e.g. TOR, FFW, RWT).  '
            'Codes are maintained by FEMA/IPAWS and published in the FCC Part 11 rules.'
        ),
    },
    {
        'segment': 'PSSCCC',
        'label': 'Location codes',
        'nrsc4b_section': '§4.3.3.3',
        'description': (
            'One to thirty-one six-digit SAME/FIPS location identifiers separated by dashes.  '
            'P (1 digit) = geographic subset (0 = entire area, 1–9 = compass octant).  '
            'SS (2 digits) = state FIPS code.  '
            'CCC (3 digits) = county FIPS code (000 = entire state).'
        ),
        'max_count': NRSC4B_MAX_LOCATIONS,
    },
    {
        'segment': '+TTTT',
        'label': 'Purge time',
        'nrsc4b_section': '§4.3.3.4',
        'description': (
            'Four-digit HHMM duration code indicating how long the alert is valid.  '
            'Valid values are 0015 through 0600 in the increments defined by NRSC-4-B: '
            '15-minute steps up to 45 minutes, then 30-minute steps up to 6 hours.'
        ),
        'valid_values': list(NRSC4B_VALID_PURGE_TIMES),
    },
    {
        'segment': '-JJJHHMM',
        'label': 'Issue time',
        'nrsc4b_section': '§4.3.3.5',
        'description': (
            'Seven-digit UTC issue timestamp: JJJ = Julian day of year (001–366), '
            'HH = hour (00–23), MM = minute (00–59).  '
            'Year is not encoded; receivers infer it from the current calendar year.'
        ),
    },
    {
        'segment': '-LLLLLLLL-',
        'label': 'Station identifier',
        'nrsc4b_section': '§4.3.3.6',
        'description': (
            'Eight-character call-sign or system identifier for the originating station, '
            'padded with hyphens if shorter.  Slashes may substitute for hyphens inside '
            'the identifier.  Terminated by a trailing hyphen delimiter.'
        ),
        'max_length': NRSC4B_STATION_ID_MAX_LEN,
    },
    {
        'segment': 'NNNN',
        'label': 'End of message',
        'nrsc4b_section': '§4.3.4',
        'description': (
            'End Of Message marker transmitted three times after audio content to '
            'terminate the activation.  Each EOM burst consists of the standard '
            'preamble followed by the ASCII string "NNNN" with no trailing CR.'
        ),
    },
]

def describe_same_header(
    header: str,
    lookup: Optional[Dict[str, str]] = None,
    state_index: Optional[Dict[str, Dict[str, object]]] = None,
) -> Dict[str, object]:
    """Break a SAME header into its constituent fields for display."""

    if not header:
        return {}

    header = header.strip()
    if not header:
        return {}

    parts = header.split('-')
    if not parts or parts[0] != 'ZCZC':
        return {}

    originator = parts[1] if len(parts) > 1 else ''
    event_code = parts[2] if len(parts) > 2 else ''
    event_entry = EVENT_CODE_REGISTRY.get(event_code)
    event_name = event_entry.get('name') if event_entry else None

    locations: List[str] = []
    duration_fragment = ''
    index = 3

    while index < len(parts):
        fragment = parts[index]
        if '+' in fragment:
            loc_part, duration_fragment = fragment.split('+', 1)
            if loc_part:
                locations.append(loc_part)
            index += 1
            break
        if fragment:
            locations.append(fragment)
        index += 1

    julian_fragment = parts[index] if index < len(parts) else ''
    station_identifier = parts[index + 1] if index + 1 < len(parts) else ''

    duration_digits = ''.join(ch for ch in duration_fragment if ch.isdigit())[:4]
    # TTTT is HHMM, not decimal minutes (ECIG §3.4.1.4 / 47 CFR §11.31(b)(4)).
    # e.g. "0100" = 1 h 00 m = 60 min, not 100 min.
    if len(duration_digits) == 4:
        purge_minutes = int(duration_digits[:2]) * 60 + int(duration_digits[2:])
    elif duration_digits.isdigit():
        purge_minutes = int(duration_digits)
    else:
        purge_minutes = None

    def _format_duration(value: Optional[int]) -> Optional[str]:
        if value is None:
            return None
        if value == 0:
            return '0 minutes (immediate purge)'
        if value % 60 == 0:
            hours = value // 60
            return f"{hours} hour{'s' if hours != 1 else ''}"
        return f"{value} minute{'s' if value != 1 else ''}"

    julian_digits = ''.join(ch for ch in julian_fragment if ch.isdigit())[:7]
    issue_time_iso: Optional[str] = None
    issue_time_label: Optional[str] = None
    issue_components: Optional[Dict[str, int]] = None

    if len(julian_digits) == 7:
        try:
            ordinal = int(julian_digits[:3])
            hour = int(julian_digits[3:5])
            minute = int(julian_digits[5:7])
            base_year = datetime.now(timezone.utc).year
            issue_dt = datetime(base_year, 1, 1, tzinfo=timezone.utc) + timedelta(
                days=ordinal - 1,
                hours=hour,
                minutes=minute,
            )
            issue_time_iso = issue_dt.isoformat()
            issue_time_label = f"Day {ordinal:03d} at {hour:02d}:{minute:02d} UTC"
            issue_components = {'day_of_year': ordinal, 'hour': hour, 'minute': minute}
        except ValueError:
            issue_time_iso = None
            issue_time_label = None
            issue_components = None

    detailed_locations: List[Dict[str, object]] = []
    lookup = lookup or {}
    state_index = state_index or {}

    for entry in locations:
        digits = ''.join(ch for ch in entry if ch.isdigit()).zfill(6)[:6]
        if not digits:
            continue
        p_digit = digits[0]
        state_digits = digits[1:3]
        county_digits = digits[3:]
        state_info = state_index.get(state_digits) or {}
        state_name = state_info.get('name') or ''
        state_abbr = state_info.get('abbr') or state_digits
        description = lookup.get(digits)
        is_statewide = county_digits == '000'
        if is_statewide and not description:
            description = f"All Areas, {state_abbr}"

        detailed_locations.append({
            'code': digits,
            'p_digit': p_digit,
            'p_meaning': P_DIGIT_MEANINGS.get(p_digit),
            'state_fips': state_digits,
            'state_name': state_name or state_abbr,
            'state_abbr': state_abbr,
            'county_fips': county_digits,
            'is_statewide': is_statewide,
            'description': description or digits,
        })

    # ── NRSC-4-B compliance checks ────────────────────────────────────────
    # §4.3.3.2 — originator must be one of EAS, CIV, WXR, PEP.
    nrsc4b_valid_originator: bool = originator in NRSC4B_VALID_ORIGINATORS
    # §4.3.3.3 — event code must be a registered SAME code.
    nrsc4b_valid_event: bool = event_code in EVENT_CODE_REGISTRY
    # §4.3.3.4 — purge time must be one of the fourteen defined HHMM values.
    nrsc4b_valid_purge: bool = (duration_digits in NRSC4B_VALID_PURGE_TIMES)
    # §4.3.3.5 — issue time must be seven digits with valid JJJ/HH/MM ranges.
    _issue_valid = False
    if issue_components:
        try:
            _jjj = issue_components['day_of_year']
            _hh = issue_components['hour']
            _mm = issue_components['minute']
            _issue_valid = (1 <= _jjj <= 366) and (0 <= _hh <= 23) and (0 <= _mm <= 59)
        except (KeyError, TypeError, ValueError):
            pass
    nrsc4b_valid_issue_time: bool = _issue_valid
    # §4.3.3.3 — one to thirty-one location codes required.
    _loc_count = len(detailed_locations)
    nrsc4b_valid_location_count: bool = 1 <= _loc_count <= NRSC4B_MAX_LOCATIONS
    # §4.3.3.6 — station identifier must be 1–8 printable ASCII characters.
    _sid = station_identifier.strip('-')
    nrsc4b_valid_station_id: bool = bool(_sid) and len(_sid) <= NRSC4B_STATION_ID_MAX_LEN
    # Overall NRSC-4-B compliance flag.
    nrsc4b_compliant: bool = (
        nrsc4b_valid_originator
        and nrsc4b_valid_event
        and nrsc4b_valid_purge
        and nrsc4b_valid_issue_time
        and nrsc4b_valid_location_count
        and nrsc4b_valid_station_id
    )

    # ── Convenience decompositions ────────────────────────────────────────
    purge_hh: Optional[int] = int(duration_digits[:2]) if len(duration_digits) == 4 else None
    purge_mm: Optional[int] = int(duration_digits[2:]) if len(duration_digits) == 4 else None
    issue_day_of_year: Optional[int] = (
        issue_components['day_of_year'] if issue_components else None
    )
    issue_hour: Optional[int] = (
        issue_components['hour'] if issue_components else None
    )
    issue_minute: Optional[int] = (
        issue_components['minute'] if issue_components else None
    )
    # Raw station identifier as received (may include trailing dashes used as padding).
    station_identifier_raw: str = station_identifier

    return {
        # ── Structural fields ──────────────────────────────────────────────
        'preamble': parts[0] if parts else 'ZCZC',
        'preamble_description': (
            'SAME headers begin with a sixteen-byte 0xAB preamble for receiver synchronisation.'
        ),
        'start_code': parts[0] if parts else 'ZCZC',
        'header_length': len(header),
        'header_parts': parts,
        # ── Originator (NRSC-4-B §4.3.3.2) ───────────────────────────────
        'originator': originator,
        'originator_description': ORIGINATOR_DESCRIPTIONS.get(originator),
        'nrsc4b_valid_originator': nrsc4b_valid_originator,
        # ── Event code (NRSC-4-B §4.3.3.3) ───────────────────────────────
        'event_code': event_code,
        'event_name': event_name,
        'nrsc4b_valid_event': nrsc4b_valid_event,
        # ── Location codes (NRSC-4-B §4.3.3.3) ───────────────────────────
        'location_count': _loc_count,
        'location_count_valid': nrsc4b_valid_location_count,
        'locations': detailed_locations,
        'raw_locations': locations,
        # ── Purge time (NRSC-4-B §4.3.3.4) ───────────────────────────────
        'purge_code': duration_digits or None,
        'purge_hh': purge_hh,
        'purge_mm': purge_mm,
        'purge_minutes': purge_minutes,
        'purge_label': _format_duration(purge_minutes),
        'nrsc4b_valid_purge': nrsc4b_valid_purge,
        # ── Issue time (NRSC-4-B §4.3.3.5) ───────────────────────────────
        'issue_code': julian_digits or None,
        'issue_day_of_year': issue_day_of_year,
        'issue_hour': issue_hour,
        'issue_minute': issue_minute,
        'issue_time_label': issue_time_label,
        'issue_time_iso': issue_time_iso,
        'issue_components': issue_components,
        'nrsc4b_valid_issue_time': nrsc4b_valid_issue_time,
        # ── Station identifier (NRSC-4-B §4.3.3.6) ───────────────────────
        'station_identifier': station_identifier,
        'station_identifier_raw': station_identifier_raw,
        'nrsc4b_valid_station_id': nrsc4b_valid_station_id,
        # ── Overall NRSC-4-B compliance ────────────────────────────────────
        'nrsc4b_compliant': nrsc4b_compliant,
    }


def _julian_time(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    julian_day = dt.timetuple().tm_yday
    return f"{julian_day:03d}{dt:%H%M}"


def _duration_code(sent: datetime, expires: Optional[datetime]) -> str:
    """Return the SAME TTTT duration field as a 4-character HHMM string.

    Per ECIG §3.4.1.4 and 47 CFR §11.31(b)(4), the TTTT field is HHMM, NOT
    decimal minutes.  Valid values follow these rounding rules:
      • ≤45 min  → round up to the nearest 15-min increment (0015/0030/0045)
      • >45 min  → round up to the nearest 30-min increment, max 0600 (6 hours)
    """
    if not sent or not expires:
        return '0015'
    delta = expires - sent
    total_minutes = delta.total_seconds() / 60.0
    if total_minutes <= 0:
        return '0015'  # expired; caller should handle the rejection
    if total_minutes <= 45:
        rounded = max(int(math.ceil(total_minutes / 15.0)) * 15, 15)
        return f"{rounded:04d}"  # 0015, 0030, 0045
    else:
        rounded_minutes = int(math.ceil(total_minutes / 30.0)) * 30
        rounded_minutes = min(rounded_minutes, 360)  # cap at 6 hours (0600)
        hours = rounded_minutes // 60
        mins = rounded_minutes % 60
        return f"{hours:02d}{mins:02d}"  # 0100, 0130, 0200, …, 0600


def _collect_event_code_candidates(alert: object, payload: Dict[str, object]) -> List[str]:
    candidates: List[str] = []

    def _extend(value) -> None:
        if value is None:
            return
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if item is not None:
                    candidates.append(str(item))

    for key in ('event_code', 'eventCode', 'primary_event_code'):
        if key in payload:
            _extend(payload[key])
    for key in ('event_codes', 'eventCodes'):
        if key in payload:
            _extend(payload[key])

    raw_sources = []
    for container in (payload.get('raw_json'), getattr(alert, 'raw_json', None)):
        if isinstance(container, dict):
            props = container.get('properties') or {}
            raw_sources.append(props)
        else:
            raw_sources.append(None)

    for props in raw_sources:
        if not isinstance(props, dict):
            continue
        for key in ('event_code', 'eventCode', 'primary_event_code'):
            if key in props:
                _extend(props[key])
        for key in ('event_codes', 'eventCodes'):
            if key in props:
                _extend(props[key])

    ordered: List[str] = []
    seen = set()
    for candidate in candidates:
        text = str(candidate).strip()
        if not text:
            continue
        if text not in seen:
            seen.add(text)
            ordered.append(text)

    return ordered


def build_same_header(alert: object, payload: Dict[str, object], config: Dict[str, object],
                      location_settings: Optional[Dict[str, object]] = None) -> Tuple[str, List[str], str]:
    event_name = (getattr(alert, 'event', '') or '').strip()
    event_candidates = _collect_event_code_candidates(alert, payload)
    event_code = resolve_event_code(event_name, event_candidates)
    if not event_code:
        pretty_event = event_name or (payload.get('event') or '').strip() or 'unknown event'
        raise ValueError(f'No authorised SAME event code available for {pretty_event}.')
    if 'resolved_event_code' not in payload:
        payload['resolved_event_code'] = event_code

    geocode = (payload.get('raw_json', {}) or {}).get('properties', {}).get('geocode', {})
    same_codes = []

    # ECIG §3.10: FIPS6 geocodes shall be treated the same as SAME geocodes.
    for key in ('SAME', 'same', 'SAMEcodes', 'FIPS6', 'fips6'):
        values = geocode.get(key)
        if values:
            if isinstance(values, (list, tuple)):
                same_codes.extend(str(v).strip() for v in values)
            else:
                same_codes.append(str(values).strip())
            break  # stop at the first key that has data; don't accumulate across keys
    same_codes = [code for code in same_codes if code and code != 'None']

    zone_codes: List[str] = []
    if location_settings:
        zone_codes = location_settings.get('zone_codes') or []

    # Filter SAME codes to only those within the configured broadcast area.
    # Alerts may cover many counties; we only forward the codes that match our
    # area so the SAME header reflects our actual coverage, not the full alert area.
    if same_codes and location_settings:
        configured_raw = (
            location_settings.get('fips_codes')
            or location_settings.get('same_codes')
            or []
        )
        configured_normalised = set(
            _normalise_same_codes([str(c).strip() for c in configured_raw if str(c).strip()])
        )
        if configured_normalised:
            filtered: List[str] = []
            for code in same_codes:
                norm = ''.join(ch for ch in str(code) if ch.isdigit()).zfill(6)
                # Nationwide (000000) and statewide (SS000) wildcards are preserved
                # as-is — they must not be stripped by the per-county filter or the
                # fallback will replace them with all configured FIPS codes, producing
                # an incorrect broadcast header.
                if norm == '000000' or (norm.endswith('000') and norm != '000000'):
                    filtered.append(code)
                elif norm in configured_normalised:
                    filtered.append(code)
            # Use filtered list; if nothing matched fall through to fallback below.
            same_codes = filtered

    if not same_codes and location_settings:
        fallback_same_raw = (
            location_settings.get('same_codes')
            or location_settings.get('fips_codes')
            or []
        )
        fallback_same = [str(code).strip() for code in fallback_same_raw if str(code).strip()]
        default_fips = [
            str(code).strip()
            for code in DEFAULT_LOCATION_SETTINGS.get('fips_codes', [])
            if str(code).strip()
        ]
        fallback_normalised = _normalise_same_codes(fallback_same)
        default_normalised = _normalise_same_codes(default_fips)
        fallback_matches_default = (
            bool(fallback_normalised)
            and fallback_normalised == default_normalised
            and bool(zone_codes)
        )
        if fallback_same and not fallback_matches_default:
            same_codes = fallback_same

    if not same_codes and zone_codes:
        same_codes = [code.replace('O', '').upper().replace(' ', '') for code in zone_codes]

    formatted_locations = _normalise_same_codes(same_codes)
    # FCC 47 CFR §11.31 limits SAME headers to 31 location codes
    if len(formatted_locations) > 31:
        formatted_locations = formatted_locations[:31]

    if not formatted_locations:
        formatted_locations = ['000000']

    sent = getattr(alert, 'sent', None) or payload.get('sent')
    expires = getattr(alert, 'expires', None) or payload.get('expires')
    sent_dt = sent if isinstance(sent, datetime) else None
    expires_dt = expires if isinstance(expires, datetime) else None

    duration_code = _duration_code(sent_dt, expires_dt)
    julian = _julian_time(sent_dt or datetime.now(timezone.utc))

    # ECIG §3.4.1.1: originator SHALL come from the CAP alert's EAS-ORG parameter
    # when present and valid; fall back to station config only as a last resort.
    originator = None
    try:
        params = (payload.get('raw_json', {}) or {}).get('properties', {}).get('parameters', {})
        if isinstance(params, dict):
            eas_org_val = params.get('EAS-ORG')
            if isinstance(eas_org_val, list):
                eas_org_val = eas_org_val[0] if eas_org_val else None
            if eas_org_val:
                candidate = str(eas_org_val).strip().upper()
                if candidate in ORIGINATOR_DESCRIPTIONS:
                    originator = candidate
    except Exception:
        pass
    if not originator:
        originator = str(config.get('originator', 'WXR'))[:3].upper()
    station = str(config.get('station_id', 'EASNODES')).strip()[:8]

    location_field = '-'.join(formatted_locations)
    header = f"ZCZC-{originator}-{event_code}-{location_field}+{duration_code}-{julian}-{station}-"

    return header, formatted_locations, event_code


def build_eom_header(config: Dict[str, object]) -> str:
    """Return the EOM payload per 47 CFR §11.31(c).

    The End Of Message burst is simply the ASCII string ``NNNN`` framed by the
    SAME preamble. No originator, location, or timing fields are transmitted.
    """

    return "NNNN"


def _load_pronunciation_rules() -> List[tuple]:
    """Load user-defined pronunciation rules from the database.

    Returns a list of (original_text, replacement_text, match_case) tuples
    for all enabled rules, ordered so longer patterns are applied first
    (prevents shorter prefixes from masking longer tokens).

    Falls back gracefully to an empty list when the database is unavailable
    or the table does not yet exist (e.g. before the first migration run).
    """
    try:
        from flask import has_app_context
        if not has_app_context():
            return []
        from app_core.models import TTSPronunciationRule
        from app_core.extensions import db
        rules = (
            TTSPronunciationRule.query
            .filter_by(enabled=True)
            .order_by(
                # Longer originals first so "Bellefontaine" is matched before "Bell"
                db.func.length(TTSPronunciationRule.original_text).desc()
            )
            .all()
        )
        return [(r.original_text, r.replacement_text, r.match_case) for r in rules]
    except Exception:
        return []


def _normalize_text_for_tts(text: str) -> str:
    """Expand common emergency-management acronyms and apply user pronunciation
    rules so TTS engines read the text correctly.

    Five layers of replacement are applied in order:

    1. **Time expansion** – converts compact/digital time formats that TTS
       engines mispronounce into fully-spoken equivalents.
       e.g. "1100 PM" → "eleven o'clock PM", "11:30 AM" → "eleven thirty AM".

    2. **NWS-specific text normalizations** – cleans up formatting patterns
       unique to NOAA/NWS alert text before acronym expansion:
       - Alternate-timezone slash notation: "/5 PM CDT/" → "5 PM CDT" —
         stripped before time expansion so colon times inside slashes
         (e.g. "/5:00 PM CDT/") are intact when the time patterns run.
       - Whitespace/punctuation: "..." → ". ", double newlines → ". ",
         single newlines → ", " — applied before other steps so sentence
         structure is established early.
       - Multiple spaces/tabs → ", " — applied after Indiana disambiguation
         so county+state-code pairs ("CASS IN") are matched before their
         surrounding column padding is collapsed.
         NWS places the same deadline in a second timezone inside slashes;
         the slashes are stripped so TTS reads naturally.
       - "ST." abbreviation: "ST. JOSEPH" → "Saint JOSEPH" so TTS does not
         read it as "Street Joseph".
       - Indiana county disambiguation: NWS watches append the state code
         "IN" after a county name that appears in more than one watch state
         (e.g. "ALLEN IN" = Allen County, Indiana vs "ALLEN OH" = Allen
         County, Ohio).  "IN" is replaced with "Indiana" only when it is
         immediately preceded by a recognised Indiana county name AND is not
         followed by a directional word, state name, or common English word
         that would indicate it is acting as a preposition.

    3. **Built-in acronym table** – hard-coded, case-sensitive whole-word
       substitutions for uppercase tokens that TTS engines mispronounce
       (EAS → "Emergency Alert System", NWS → "National Weather Service",
       EDT → "Eastern Daylight Time", MI → "Michigan", OH → "Ohio", …).

    4. **Database pronunciation dictionary** – user-managed rows from the
       ``tts_pronunciation_rules`` table.  Each row supplies an
       ``original_text`` pattern, a ``replacement_text`` phonetic spelling,
       and a ``match_case`` flag.  Longer patterns are applied first so that
       multi-word entries (e.g. "Bellefontaine") are not accidentally masked
       by shorter ones (e.g. "Bell").

    5. **Lowercase normalisation** – converts the remaining all-caps NWS
       product text to lowercase so TTS engines treat tokens as words rather
       than as acronyms.  All acronym expansions have already been applied
       by this point.

    Only whole-word occurrences are replaced (regex ``\\b`` word boundaries).
    """
    if not text:
        return text

    import re

    # ── Layer 1: Time pronunciation expansion ────────────────────────────
    # TTS engines read "1100" as "eleven hundred" (military) and "11:00" can
    # also be mispronounced.  Convert to fully-spoken word form so that every
    # TTS backend gives a consistent, natural result.

    _ONES = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
             'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen',
             'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen',
             'nineteen']
    _TENS_WORDS = ['', '', 'twenty', 'thirty', 'forty', 'fifty']

    def _hour_word(h: int) -> str:
        h12 = h % 12 or 12
        return _ONES[h12]

    def _minute_phrase(m: int) -> str:
        """Return spoken minutes: 0→"o'clock", 1-9→"oh one", 10-19, 20+."""
        if m == 0:
            return "o'clock"
        if m < 10:
            return f"oh {_ONES[m]}"
        if m < 20:
            return _ONES[m]
        t, o = divmod(m, 10)
        return _TENS_WORDS[t] if o == 0 else f"{_TENS_WORDS[t]}-{_ONES[o]}"

    def _expand_time_match(mo) -> str:
        h = int(mo.group(1))
        m = int(mo.group(2))
        ampm = mo.group(3).upper()
        hw = _hour_word(h)
        mp = _minute_phrase(m)
        if mp == "o'clock":
            return f"{hw} o'clock {ampm}"
        return f"{hw} {mp} {ampm}"

    result = text

    # Slash alternate-timezone notation must be stripped BEFORE time expansion
    # so that colon-format times inside slashes (e.g. "/5:00 PM CDT/") are
    # intact when the time-expansion patterns run.  If time expansion ran first
    # it would convert "5:00 PM" to "five o'clock PM", leaving orphaned slashes
    # that the slash pattern can no longer match.
    result = re.sub(
        r'/\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s+[A-Z]{2,5})\s*/',
        r' \1 ',
        result,
    )

    # Pattern A: compact 4-digit time, e.g. "1100 PM", "0930 AM"
    # Matches HHMM immediately followed (possibly with space) by AM/PM.
    result = re.sub(
        r'\b([01]?\d|2[0-3])([0-5]\d)\s+(AM|PM)\b',
        _expand_time_match,
        result,
        flags=re.IGNORECASE,
    )

    # Pattern B: colon-separated time, e.g. "11:00 PM", "9:30 AM"
    result = re.sub(
        r'\b(\d{1,2}):([0-5]\d)\s*(AM|PM)\b',
        _expand_time_match,
        result,
        flags=re.IGNORECASE,
    )

    # ── Layer 2: NWS-specific text normalizations ────────────────────────
    # These clean up formatting conventions unique to NWS/NOAA alert text
    # before the acronym table runs.

    # Asterisk removal — NWS uses "* WHAT...", "* WHERE...", "* WHEN..." etc.
    # as bullet-point markers.  TTS engines read a bare asterisk as "asterisk"
    # which sounds unnatural.  Strip leading bullet asterisks first, then remove
    # any remaining asterisks so they are never spoken.
    result = re.sub(r'^\s*\*\s*', '', result, flags=re.MULTILINE)
    result = result.replace('*', '')

    # Whitespace / punctuation — convert structural whitespace to spoken
    # pauses so TTS does not read the whole alert as a run-on sentence.

    # Ellipsis → sentence break.  NWS uses "..." throughout product text as
    # a clause/sentence separator (e.g. "...TORNADO WARNING IN EFFECT...").
    result = re.sub(r'\.{3,}', '. ', result)

    # Double newline (paragraph break) → sentence pause.
    result = re.sub(r'\n{2,}', '. ', result)

    # Single newline → comma pause.
    result = re.sub(r'\n', ', ', result)

    # "ST." (Saint abbreviation): expand before the main acronym loop so
    # that the trailing period does not confuse word-boundary matching.
    # e.g. "ST. JOSEPH" → "Saint JOSEPH", "ST. LOUIS" → "Saint LOUIS".
    result = re.sub(r'\bST\.(?=\s)', 'Saint', result, flags=re.IGNORECASE)

    # Indiana county-name disambiguation: NWS watches append the two-letter
    # state code "IN" immediately after a county name that also appears in
    # another watch state (e.g. "ALLEN IN" = Allen County, Indiana vs
    # "ALLEN OH" = Allen County, Ohio).  TTS reads the bare code "IN" as the
    # preposition "in" which is ambiguous; expanding it to "Indiana" makes the
    # reading unambiguous and natural.
    #
    # Safety constraints applied together:
    #   • Positive match  — the preceding word must be a recognised Indiana
    #     county name (all 92 counties, single-word spellings as used by NWS).
    #   • Negative lookahead — the word that follows "IN" must NOT be a
    #     directional word, state name, or common English function word that
    #     would indicate "IN" is acting as a preposition rather than a state
    #     code.  This prevents "GRANT IN NORTHERN INDIANA" from becoming
    #     "GRANT Indiana NORTHERN INDIANA".
    _INDIANA_COUNTIES = (
        r'ADAMS|ALLEN|BARTHOLOMEW|BENTON|BLACKFORD|BOONE|BROWN|CARROLL|CASS|'
        r'CLARK|CLAY|CLINTON|CRAWFORD|DAVIESS|DEARBORN|DECATUR|DELAWARE|'
        r'DUBOIS|ELKHART|FAYETTE|FLOYD|FOUNTAIN|FRANKLIN|FULTON|GIBSON|'
        r'GRANT|GREENE|HAMILTON|HANCOCK|HARRISON|HENDRICKS|HENRY|HOWARD|'
        r'HUNTINGTON|JACKSON|JASPER|JAY|JEFFERSON|JENNINGS|JOHNSON|KNOX|'
        r'KOSCIUSKO|LAGRANGE|LAKE|LAPORTE|LAWRENCE|MADISON|MARION|MARSHALL|'
        r'MARTIN|MIAMI|MONROE|MONTGOMERY|MORGAN|NEWTON|NOBLE|OHIO|ORANGE|'
        r'OWEN|PARKE|PERRY|PIKE|PORTER|POSEY|PULASKI|PUTNAM|RANDOLPH|'
        r'RIPLEY|RUSH|SCOTT|SHELBY|SPENCER|STARKE|STEUBEN|SULLIVAN|'
        r'SWITZERLAND|TIPPECANOE|TIPTON|UNION|VANDERBURGH|VERMILLION|VIGO|'
        r'WABASH|WARREN|WARRICK|WASHINGTON|WAYNE|WELLS|WHITE|WHITLEY'
    )
    # Words that follow "IN" when it is a preposition, not a state code.
    _IN_PREPOSITION_AFTER = (
        r'NORTH|SOUTH|EAST|WEST|CENTRAL|NORTHERN|SOUTHERN|EASTERN|WESTERN|'
        r'NORTHWEST|SOUTHWEST|NORTHEAST|SOUTHEAST|'
        r'INDIANA|MICHIGAN|OHIO|ILLINOIS|KENTUCKY|WISCONSIN|MINNESOTA|'
        r'THE|A|AN|THIS|THAT|THESE|THOSE|EFFECT|WATCH|COUNTIES|COUNTY|'
        r'CITIES|CITY|AREAS|AREA|FOLLOWING|ALL|SOME|MANY|FEW|EACH|EVERY'
    )
    result = re.sub(
        r'\b(' + _INDIANA_COUNTIES + r')\s+IN\b'
        r'(?!\s+(?:' + _IN_PREPOSITION_AFTER + r'))',
        r'\1 Indiana',
        result,
    )

    # Two or more spaces, or any number of tabs → comma pause.
    # NWS formats county lists in fixed-width columns separated by multiple
    # spaces or tabs, e.g. "KOSCIUSKO             ST. JOSEPH".
    # A lone tab counts as a separator; two+ spaces do too.
    # This runs after Indiana disambiguation so that "CASS IN" (single space)
    # is recognised as a county+state-code pair before any spaces are replaced.
    result = re.sub(r'\t+|[ \t]{2,}', ', ', result)

    # ── Layer 3: hard-coded acronym expansions ────────────────────────────
    # Order matters: longer / more-specific entries first.
    _ACRONYM_MAP = [
        # Compound EAS parameter tokens
        ('EAS-ORG',    'E.A.S. originator'),
        ('EAS-STN-ID', 'E.A.S. station ID'),
        # Agency / system names
        ('IPAWS',  'I.P.A.W.S.'),
        ('NOAA',   'N.O.A.A.'),
        ('FEMA',   'F.E.M.A.'),
        ('NWS',    'National Weather Service'),
        ('EBS',    'Emergency Broadcast System'),
        ('EAS',    'Emergency Alert System'),
        # Event codes that appear verbatim in auto-generated message text
        ('RWT',    'Required Weekly Test'),
        ('RMT',    'Required Monthly Test'),
        ('EOM',    'end of message'),
        # US timezone abbreviations — daylight saving time
        ('EDT',    'Eastern Daylight Time'),
        ('CDT',    'Central Daylight Time'),
        ('MDT',    'Mountain Daylight Time'),
        ('PDT',    'Pacific Daylight Time'),
        # US timezone abbreviations — standard time
        ('EST',    'Eastern Standard Time'),
        ('CST',    'Central Standard Time'),
        ('MST',    'Mountain Standard Time'),
        ('PST',    'Pacific Standard Time'),
        # Other common timezone abbreviations
        ('UTC',    'Coordinated Universal Time'),
        ('GMT',    'Greenwich Mean Time'),
        ('AKDT',   'Alaska Daylight Time'),
        ('AKST',   'Alaska Standard Time'),
        ('HST',    'Hawaii Standard Time'),
        ('HAST',   'Hawaii-Aleutian Standard Time'),
        ('HADT',   'Hawaii-Aleutian Daylight Time'),
        # US state codes used as county-name disambiguation markers in NWS
        # watches (e.g. "CASS MI" = Cass County, Michigan; "ALLEN OH" =
        # Allen County, Ohio).  TTS engines mispronounce bare two-letter
        # codes ("MI" → "my", "OH" → "oh").
        ('MI',     'Michigan'),
        ('OH',     'Ohio'),
        # Military / civil facility abbreviations in NWS city lists.
        ('AFB',    'Air Force Base'),
        ('ARB',    'Air Reserve Base'),
        ('AFD',    'Air Force Base'),
    ]

    for token, expansion in _ACRONYM_MAP:
        result = re.sub(r'\b' + re.escape(token) + r'\b', expansion, result)

    # ── Layer 4: database pronunciation dictionary ────────────────────────
    for original, replacement, match_case in _load_pronunciation_rules():
        flags = 0 if match_case else re.IGNORECASE
        try:
            result = re.sub(
                r'\b' + re.escape(original) + r'\b',
                replacement,
                result,
                flags=flags,
            )
        except re.error:
            pass  # Malformed pattern — skip silently

    # ── Layer 5: lowercase normalisation ─────────────────────────────────
    # NWS product text is entirely uppercase.  All acronym and pronunciation
    # expansions have already run, so lowercasing now lets every TTS backend
    # treat the remaining tokens as plain words rather than abbreviations.
    result = result.lower()

    return result


def _compose_message_text(alert: object, payload: Optional[Dict[str, object]] = None) -> str:
    """Build the TTS narration text from the alert body.

    Structure (in order of preference):
    1. EASText CAP parameter — if present, use verbatim (§3.6.3).
    2. Otherwise: senderName + description + instruction (§3.6.2).
       NOTE: headline is metadata, not alert content, and is excluded.
    3. Fallback: generated FCC Required Text when no body text is available.

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
    # Originator description
    eas_org_val = parameters.get('EAS-ORG')
    if isinstance(eas_org_val, list):
        eas_org_val = eas_org_val[0] if eas_org_val else None
    originator_code = (str(eas_org_val).strip().upper() if eas_org_val else None) or 'WXR'
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
        for attr in ('description', 'instruction'):
            value = str(getattr(alert, attr, '') or '').strip()
            if value:
                body_parts.append(value)
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

    return _normalize_text_for_tts(full_text)


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


def _generate_tone(freqs: Iterable[float], duration: float, sample_rate: int, amplitude: float) -> List[int]:
    total_samples = max(1, int(duration * sample_rate))
    freqs = list(freqs)
    samples: List[int] = []
    for n in range(total_samples):
        t = n / sample_rate
        value = sum(math.sin(2 * math.pi * freq * t) for freq in freqs)
        value /= max(len(freqs), 1)
        samples.append(int(value * amplitude))
    return samples


def _generate_silence(duration: float, sample_rate: int) -> List[int]:
    return [0] * max(1, int(duration * sample_rate))


# Allowed chime profile values for pre/post-alert chimes.
ALERT_CHIME_PROFILES = ('none', 'bell', 'beep', 'three_tone', 'qc2', 'dtmf')


# Standard DTMF tone-pair frequency map: digit -> (low Hz, high Hz).
# Source: ITU-T Recommendation Q.23 / Q.24.
_DTMF_FREQUENCIES: Dict[str, Tuple[float, float]] = {
    '1': (697.0, 1209.0), '2': (697.0, 1336.0), '3': (697.0, 1477.0), 'A': (697.0, 1633.0),
    '4': (770.0, 1209.0), '5': (770.0, 1336.0), '6': (770.0, 1477.0), 'B': (770.0, 1633.0),
    '7': (852.0, 1209.0), '8': (852.0, 1336.0), '9': (852.0, 1477.0), 'C': (852.0, 1633.0),
    '*': (941.0, 1209.0), '0': (941.0, 1336.0), '#': (941.0, 1477.0), 'D': (941.0, 1633.0),
}


def _generate_chime(
    profile: Optional[str],
    duration: float,
    sample_rate: int,
    amplitude: float,
    qc2_tone_a_freq: float = 1000.0,
    qc2_tone_b_freq: float = 1500.0,
    dtmf_sequence: str = '',
    qc2_long_tone_enabled: bool = False,
    qc2_long_tone_seconds: float = 10.0,
) -> List[int]:
    """Generate a short attention chime to play before/after an EAS broadcast.

    The chime is *not* part of the SAME/FSK signaling and is purely cosmetic —
    it is inserted before the first SAME header burst (pre-alert) or after the
    final EOM sequence (post-alert) when the operator has configured one.

    Supported profiles:
        - 'none' / 'off' / falsy: returns an empty list (no audio).
        - 'bell':       single 880 Hz sine with exponential decay envelope.
        - 'beep':       sustained 1000 Hz sine for the full duration.
        - 'three_tone': three ascending tones (440, 880, 1320 Hz),
                        each occupying ~1/3 of the duration.
        - 'qc2':        Motorola Quick Call II two-tone paging — fixed
                        1 s Tone A (``qc2_tone_a_freq``) followed by
                        4 s Tone B (``qc2_tone_b_freq``), 5 s total.
                        ``duration`` is ignored to keep timing on-spec.
                        When ``qc2_long_tone_enabled`` is ``True``, an
                        additional steady tone at ``qc2_tone_b_freq`` is
                        appended for ``qc2_long_tone_seconds`` seconds.
        - 'dtmf':       Plays each character of ``dtmf_sequence`` (digits
                        0-9, letters A-D, * or #) as its standard DTMF
                        low+high tone pair, using ITU-T Q.24 timing
                        (100 ms tone, 50 ms gap).  ``duration`` is ignored.

    Args:
        profile: Chime profile name (case-insensitive).
        duration: Total duration in seconds (clamped to 0.1–10.0).
            Ignored when ``profile`` is ``'dtmf'`` or ``'qc2'`` — both use
            standardized fixed timings.
        sample_rate: Output sample rate in Hz.
        amplitude: Peak signed-int amplitude (e.g. 0.7 * 32767).
        qc2_tone_a_freq: Tone A frequency in Hz when ``profile == 'qc2'``.
        qc2_tone_b_freq: Tone B frequency in Hz when ``profile == 'qc2'``.
        dtmf_sequence: Digit string when ``profile == 'dtmf'``.  Unrecognised
            characters are ignored.  Limited to the first 32 valid digits.
        qc2_long_tone_enabled: When ``True`` and ``profile == 'qc2'``, a
            sustained tone at ``qc2_tone_b_freq`` is appended after the
            standard A + B sequence.
        qc2_long_tone_seconds: Duration in seconds for the optional QC-II
            long tone (clamped to 1.0–120.0).  Ignored when
            ``qc2_long_tone_enabled`` is ``False``.

    Returns:
        A list of int16-range PCM samples, or an empty list when disabled.
    """
    if not profile:
        return []
    name = str(profile).strip().lower()
    if name in ('', 'none', 'off', 'omit', 'disabled'):
        return []

    # DTMF has its own timing and ignores `duration`.
    if name == 'dtmf':
        digits = [c for c in str(dtmf_sequence or '').upper() if c in _DTMF_FREQUENCIES]
        if not digits:
            return []
        digits = digits[:32]
        # ITU-T Q.24 minimum: 70 ms tone / 65 ms gap.  We use the slightly
        # more conservative 100 ms tone / 50 ms gap commonly emitted by
        # commercial dialers for clean detection.
        tone_samples = max(1, int(0.10 * sample_rate))
        gap_samples = max(1, int(0.05 * sample_rate))
        # Sum of two unit-amplitude sines can reach 2.0; scale by 0.5 so the
        # combined waveform never exceeds the supplied peak amplitude.
        per_tone_amp = amplitude * 0.5
        out: List[int] = []
        for idx, digit in enumerate(digits):
            f_low, f_high = _DTMF_FREQUENCIES[digit]
            for n in range(tone_samples):
                t = n / sample_rate
                value = (
                    math.sin(2 * math.pi * f_low * t)
                    + math.sin(2 * math.pi * f_high * t)
                )
                out.append(int(value * per_tone_amp))
            if idx < len(digits) - 1:
                out.extend([0] * gap_samples)
        return out

    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = 2.0
    duration = max(0.1, min(10.0, duration))

    total_samples = max(1, int(duration * sample_rate))
    samples: List[int] = []

    if name == 'beep':
        freq = 1000.0
        for n in range(total_samples):
            t = n / sample_rate
            samples.append(int(math.sin(2 * math.pi * freq * t) * amplitude))
        return samples

    if name == 'bell':
        # 880 Hz sine with an exponential amplitude decay (-decay_rate * t).
        # Decay rate is tuned so a 2 s chime fades to ~5% of peak amplitude.
        freq = 880.0
        decay_rate = 3.0
        for n in range(total_samples):
            t = n / sample_rate
            envelope = math.exp(-decay_rate * t)
            samples.append(int(math.sin(2 * math.pi * freq * t) * envelope * amplitude))
        return samples

    if name in ('three_tone', 'threetone', '3tone', '3_tone'):
        freqs = (440.0, 880.0, 1320.0)
        per_tone = max(1, total_samples // len(freqs))
        for idx, freq in enumerate(freqs):
            # Last tone absorbs any rounding remainder so the total length matches.
            tone_len = per_tone if idx < len(freqs) - 1 else (total_samples - per_tone * (len(freqs) - 1))
            tone_len = max(1, tone_len)
            for n in range(tone_len):
                t = n / sample_rate
                samples.append(int(math.sin(2 * math.pi * freq * t) * amplitude))
        return samples

    if name in ('qc2', 'qcii', 'quickcall', 'quick_call', 'two_tone'):
        # Motorola Quick Call II is a standardized two-tone paging protocol
        # with fixed timing: 1 s Tone A followed by 4 s Tone B (5 s total).
        # `duration` is intentionally ignored — pagers time against the
        # absolute 1 s / 4 s segments, so any other ratio produces a
        # non-spec signal that real receivers may refuse to decode.
        try:
            freq_a = float(qc2_tone_a_freq)
        except (TypeError, ValueError):
            freq_a = 1000.0
        try:
            freq_b = float(qc2_tone_b_freq)
        except (TypeError, ValueError):
            freq_b = 1500.0
        freq_a = max(50.0, min(4000.0, freq_a))
        freq_b = max(50.0, min(4000.0, freq_b))

        a_samples = max(1, int(1.0 * sample_rate))
        b_samples = max(1, int(4.0 * sample_rate))
        out: List[int] = []
        for n in range(a_samples):
            t = n / sample_rate
            out.append(int(math.sin(2 * math.pi * freq_a * t) * amplitude))
        for n in range(b_samples):
            t = n / sample_rate
            out.append(int(math.sin(2 * math.pi * freq_b * t) * amplitude))

        # Optional long tone: a sustained steady tone at Tone B frequency
        # appended after the standard A + B sequence.
        if qc2_long_tone_enabled:
            try:
                long_secs = float(qc2_long_tone_seconds)
            except (TypeError, ValueError):
                long_secs = 10.0
            long_secs = max(1.0, min(120.0, long_secs))
            long_samples = max(1, int(long_secs * sample_rate))
            for n in range(long_samples):
                t = n / sample_rate
                out.append(int(math.sin(2 * math.pi * freq_b * t) * amplitude))

        return out

    # Unknown profile: be safe and emit no chime rather than raise.
    return []


def _generate_station_terminator_samples(amplitude: float, sample_rate: int) -> List[int]:
    """Generate the KR8MER EAS Station FSK fingerprint: 3 × 0xBB terminator bytes.

    0xBB (10111011 binary) is not used by any known ENDEC hardware.  EAS-Tools
    only recognises 0x00 and 0xFF, so third-party decoders gracefully exit
    post-message mode on the first 0xBB byte (the message is already fully
    decoded).  Our own decoder captures the run and reports ENDEC_MODE_EAS_STATION.
    """
    bits = encode_terminator_bits(0xBB, 3)
    return generate_fsk_samples(
        bits,
        sample_rate=sample_rate,
        bit_rate=float(SAME_BAUD),
        mark_freq=SAME_MARK_FREQ,
        space_freq=SAME_SPACE_FREQ,
        amplitude=amplitude,
    )


def _normalize_audio_amplitude(samples: List[int], target_amplitude: float) -> List[int]:
    """Normalize audio samples to match the target amplitude using RMS.

    This ensures TTS audio has the same perceived loudness as SAME/AFSK tones.
    Uses RMS (Root Mean Square) normalization which better represents perceived
    loudness compared to peak normalization.
    """
    if not samples:
        return samples

    # Calculate RMS (Root Mean Square) of the input samples
    sum_squares = sum(s * s for s in samples)
    rms = math.sqrt(sum_squares / len(samples))

    # Avoid division by zero
    if rms == 0:
        return samples

    # For sine wave tones (SAME/attention), RMS ≈ peak / sqrt(2)
    # So target RMS should be target_amplitude / sqrt(2)
    target_rms = target_amplitude / math.sqrt(2)

    # Calculate the scaling factor needed to reach target RMS
    scale = target_rms / rms

    # Apply scaling to all samples
    # Clamp to prevent overflow beyond int16 range
    return [max(-32768, min(32767, int(s * scale))) for s in samples]


def _write_wave_file(path: str, samples: Sequence[int], sample_rate: int) -> None:
    with wave.open(path, 'w') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = struct.pack('<' + 'h' * len(samples), *samples)
        wav.writeframes(frames)


def samples_to_wav_bytes(samples: Sequence[int], sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, 'w') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = struct.pack('<' + 'h' * len(samples), *samples)
        wav.writeframes(frames)
    buffer.seek(0)
    return buffer.getvalue()


def _wav_duration_seconds(wav_bytes: bytes) -> float:
    """Return the duration of a WAV file in seconds, or 0.0 on error."""
    try:
        with io.BytesIO(wav_bytes) as bio:
            with wave.open(bio, 'rb') as w:
                return w.getnframes() / w.getframerate()
    except Exception:
        return 0.0


def truncate_wav_to_max_seconds(
    composite_wav: bytes,
    eom_wav: Optional[bytes],
    max_seconds: float,
) -> bytes:
    """Enforce the hard activation time limit on composite EAS audio.

    If *composite_wav* is within *max_seconds* it is returned unchanged.
    Otherwise the audio is trimmed so that the total duration equals
    *max_seconds*, with the EOM segment (*eom_wav*) preserved at the end.
    This mirrors DASDEC behaviour: the narration is cut short when it would
    exceed the configured hard limit, and the EOM plays immediately after.
    """
    composite_duration = _wav_duration_seconds(composite_wav)
    if composite_duration <= max_seconds:
        return composite_wav

    # Read composite WAV parameters
    with io.BytesIO(composite_wav) as bio:
        with wave.open(bio, 'rb') as w:
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            framerate = w.getframerate()

    # Determine how many frames to keep from the composite (before EOM)
    eom_duration = _wav_duration_seconds(eom_wav) if eom_wav else 0.0
    pre_eom_limit = max(0.0, max_seconds - eom_duration)
    max_pre_eom_frames = int(pre_eom_limit * framerate)

    with io.BytesIO(composite_wav) as bio:
        with wave.open(bio, 'rb') as w:
            truncated_frames = w.readframes(max_pre_eom_frames)

    # Append the EOM frames from the isolated EOM WAV
    eom_raw_frames = b''
    if eom_wav:
        try:
            with io.BytesIO(eom_wav) as bio:
                with wave.open(bio, 'rb') as w:
                    eom_raw_frames = w.readframes(w.getnframes())
        except Exception:
            pass

    output = io.BytesIO()
    with wave.open(output, 'w') as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(truncated_frames)
        if eom_raw_frames:
            w.writeframes(eom_raw_frames)
    output.seek(0)
    return output.getvalue()


def _run_command(command: Sequence[str], logger) -> None:
    try:
        subprocess.run(list(command), check=False)
    except Exception as exc:  # pragma: no cover - subprocess errors are logged
        if logger:
            logger.warning(f"Failed to run command {' '.join(command)}: {exc}")


def _fetch_embedded_audio(
    resources: List[Dict[str, str]],
    target_sample_rate: int,
    logger,
    timeout: int = 30,
) -> Tuple[Optional[List[int]], Optional[str]]:
    """Fetch and convert embedded audio from CAP resources.

    IPAWS alerts can contain pre-recorded audio in <resource> elements.
    Audio may be provided as an external URL (``uri``) to download or as
    inline base64-encoded content (``derefUri``).  Both cases are handled.
    When a resource carries ``derefUri`` but no ``mimeType`` the format is
    inferred from the decoded bytes so that alerts that omit MIME metadata
    still produce valid audio.

    Args:
        resources: List of resource dicts from CAP XML parsing
        target_sample_rate: Target sample rate for output
        logger: Logger instance
        timeout: Download timeout in seconds

    Returns:
        Tuple of (audio_samples, source_description) or (None, None) if no
        usable audio resource was found.
    """
    import base64
    import binascii
    import requests

    # Collect candidate audio resources.
    # A resource is a candidate when:
    #  - its mimeType or resourceDesc explicitly indicates audio, OR
    #  - it carries a derefUri with no conflicting (non-audio) MIME type.
    # Resources that advertise a non-audio MIME type are excluded even if
    # they have a derefUri, to avoid treating e.g. image attachments as audio.
    audio_resources = []
    for resource in resources:
        mime_type = (resource.get('mimeType') or '').lower()
        resource_desc = (resource.get('resourceDesc') or '').lower()
        uri = resource.get('uri', '')
        deref_uri = resource.get('derefUri', '')

        has_audio_hint = (
            'audio' in mime_type or
            'eas broadcast' in resource_desc or
            uri.endswith(('.mp3', '.wav', '.ogg', '.m4a'))
        )
        # A MIME type present but NOT containing 'audio' is a conflict.
        has_non_audio_mime = bool(mime_type) and 'audio' not in mime_type

        has_content = bool(uri) or bool(deref_uri)
        is_candidate = has_content and (has_audio_hint or (bool(deref_uri) and not has_non_audio_mime))

        if is_candidate:
            audio_resources.append(resource)

    if not audio_resources:
        return None, None

    # Try each candidate until one produces valid PCM samples.
    # Prefer inline derefUri (already available locally) over downloading.
    for resource in audio_resources:
        uri = resource.get('uri', '')
        deref_uri = resource.get('derefUri', '')
        mime_type = resource.get('mimeType', '')
        resource_desc = resource.get('resourceDesc', '')

        # --- inline base64 audio ---
        if deref_uri:
            logger.info(
                f"Decoding inline IPAWS audio: {resource_desc or 'unnamed'} "
                f"({mime_type or 'auto-detect'}, {len(deref_uri)} base64 chars)"
            )
            try:
                audio_data = base64.b64decode(deref_uri, validate=False)
                logger.info(f"Decoded {len(audio_data)} bytes of inline IPAWS audio")

                samples = _convert_audio_to_samples(audio_data, mime_type, target_sample_rate, logger)
                if samples:
                    logger.info(
                        f"Successfully converted inline IPAWS audio: {len(samples)} samples "
                        f"({len(samples) / target_sample_rate:.1f}s at {target_sample_rate}Hz)"
                    )
                    return samples, f"derefUri:{resource_desc or 'inline'}"
                else:
                    logger.warning("Failed to convert inline IPAWS audio; will try URI if available")
            except (binascii.Error, ValueError) as exc:
                logger.warning(f"Failed to base64-decode inline IPAWS audio: {exc}")
            except Exception as exc:
                logger.error(f"Error processing inline IPAWS audio: {exc}")

        # --- external URI audio ---
        if uri:
            logger.info(
                f"Fetching embedded audio from IPAWS: {resource_desc or 'unnamed'} "
                f"({mime_type}) from {uri[:80]}..."
            )
            try:
                # Disable proxy to allow direct download from IPAWS
                response = requests.get(uri, timeout=timeout, stream=True, proxies={'http': None, 'https': None})
                response.raise_for_status()

                audio_data = response.content
                logger.info(f"Downloaded {len(audio_data)} bytes of audio from IPAWS")

                samples = _convert_audio_to_samples(audio_data, mime_type, target_sample_rate, logger)
                if samples:
                    logger.info(
                        f"Successfully converted IPAWS audio: {len(samples)} samples "
                        f"({len(samples) / target_sample_rate:.1f}s at {target_sample_rate}Hz)"
                    )
                    return samples, uri
                else:
                    logger.warning(f"Failed to convert audio from {uri}")

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout fetching audio from {uri}")
            except requests.exceptions.RequestException as exc:
                logger.warning(f"Failed to fetch audio from {uri}: {exc}")
            except Exception as exc:
                logger.error(f"Error processing audio from {uri}: {exc}")

    return None, None


def _convert_audio_to_samples(
    audio_data: bytes,
    mime_type: str,
    target_sample_rate: int,
    logger,
) -> Optional[List[int]]:
    """Convert audio bytes to PCM samples at target sample rate.
    
    Supports WAV, MP3 (via pydub if available), and other formats.
    """
    mime_lower = mime_type.lower()
    
    # Try WAV first
    if 'wav' in mime_lower or audio_data[:4] == b'RIFF':
        try:
            with io.BytesIO(audio_data) as audio_io:
                with wave.open(audio_io, 'rb') as wav:
                    channels = wav.getnchannels()
                    sample_width = wav.getsampwidth()
                    frame_rate = wav.getframerate()
                    frames = wav.readframes(wav.getnframes())
                    
                    # Convert to mono if stereo
                    if channels == 2:
                        if sample_width == 2:
                            samples = struct.unpack(f'<{len(frames)//2}h', frames)
                            mono_samples = [(samples[i] + samples[i+1]) // 2 
                                          for i in range(0, len(samples), 2)]
                        else:
                            mono_samples = list(frames[::2])
                    else:
                        if sample_width == 2:
                            mono_samples = list(struct.unpack(f'<{len(frames)//2}h', frames))
                        elif sample_width == 1:
                            mono_samples = [(b - 128) * 256 for b in frames]
                        else:
                            logger.warning(f"Unsupported WAV sample width: {sample_width}")
                            return None
                    
                    # Resample if needed
                    if frame_rate != target_sample_rate:
                        mono_samples = _resample_audio(mono_samples, frame_rate, target_sample_rate)
                    
                    return mono_samples
        except Exception as e:
            logger.warning(f"Failed to parse WAV audio: {e}")
    
    # MPEG audio frame sync: first byte 0xFF, second byte high-nibble 0xE or 0xF
    # This covers MPEG-1/2/2.5 Layers 1-3 (e.g. 0xFB=MPEG1-L3, 0xF3=MPEG2-L3, 0xE2=MPEG2.5-L3)
    _is_mpeg_sync = len(audio_data) >= 2 and audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0
    if 'mp3' in mime_lower or 'mpeg' in mime_lower or audio_data[:3] == b'ID3' or _is_mpeg_sync:
        # Try pydub first (no subprocess overhead)
        try:
            from pydub import AudioSegment

            audio_io = io.BytesIO(audio_data)
            audio = AudioSegment.from_mp3(audio_io)

            # Convert to mono
            audio = audio.set_channels(1)

            # Resample to target rate
            audio = audio.set_frame_rate(target_sample_rate)

            # Get raw samples
            raw_data = audio.raw_data
            samples = list(struct.unpack(f'<{len(raw_data)//2}h', raw_data))

            return samples

        except ImportError:
            logger.warning("pydub not available for MP3 conversion; trying ffmpeg directly")
        except Exception as e:
            logger.warning(f"pydub MP3 conversion failed ({e}); trying ffmpeg directly")

        # Fallback: pipe raw MP3 bytes into ffmpeg and get back s16le PCM
        try:
            import shutil
            if shutil.which("ffmpeg"):
                result = subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", "pipe:0",
                        "-ar", str(target_sample_rate),
                        "-ac", "1",
                        "-f", "s16le",
                        "pipe:1",
                    ],
                    input=audio_data,
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout:
                    samples = list(struct.unpack(f'<{len(result.stdout)//2}h', result.stdout))
                    logger.info(f"Converted MP3 via ffmpeg subprocess: {len(samples)} samples")
                    return samples
                else:
                    stderr = result.stderr.decode("utf-8", "ignore").strip()
                    logger.warning(f"ffmpeg MP3 decode failed: {stderr}")
            else:
                logger.warning("ffmpeg not found; cannot decode MP3 audio for TTS narration")
        except Exception as e:
            logger.warning(f"ffmpeg MP3 fallback failed: {e}")

    # Last-resort: try pydub auto-format detection for any unrecognised format
    if mime_type == '' or ('audio' in mime_lower and not any(k in mime_lower for k in ('wav', 'mp3', 'mpeg'))):
        try:
            from pydub import AudioSegment

            audio_io = io.BytesIO(audio_data)
            audio = AudioSegment.from_file(audio_io)
            audio = audio.set_channels(1)
            audio = audio.set_frame_rate(target_sample_rate)
            raw_data = audio.raw_data
            samples = list(struct.unpack(f'<{len(raw_data)//2}h', raw_data))
            logger.info("Converted audio via pydub auto-detection")
            return samples
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"pydub auto-detection failed: {e}")

    logger.warning(f"Unsupported audio format: {mime_type}")
    return None


def _resample_audio(samples: List[int], source_rate: int, target_rate: int) -> List[int]:
    """Simple linear interpolation resampling."""
    if source_rate == target_rate:
        return samples
    
    ratio = target_rate / source_rate
    new_length = int(len(samples) * ratio)
    
    if new_length < 1:
        return samples
    
    result = []
    for i in range(new_length):
        src_idx = i / ratio
        idx_low = int(src_idx)
        idx_high = min(idx_low + 1, len(samples) - 1)
        frac = src_idx - idx_low
        
        value = int(samples[idx_low] * (1 - frac) + samples[idx_high] * frac)
        result.append(value)
    
    return result


class EASAudioGenerator:
    def __init__(self, config: Dict[str, object], logger) -> None:
        self.config = config
        self.logger = logger
        self.sample_rate = int(config.get('sample_rate', 16000))
        self.output_dir = str(config.get('output_dir'))
        _ensure_directory(self.output_dir)
        
        # Log TTS configuration for debugging
        tts_provider = config.get('tts_provider', '')
        if tts_provider:
            logger.info(f"EASAudioGenerator: TTS provider '{tts_provider}' configured")
            if tts_provider == 'azure_openai':
                endpoint = config.get('azure_openai_endpoint', '')
                key = config.get('azure_openai_key', '')
                logger.info(f"Azure OpenAI config: endpoint={'<set>' if endpoint else '<MISSING>'}, key={'<set>' if key else '<MISSING>'}")
        else:
            logger.info("EASAudioGenerator: No TTS provider configured")
        
        self.tts_engine = TTSEngine(config, logger, self.sample_rate)
        # Opt-out flag: set config key 'endec_fingerprint' to False to suppress
        # the 3 × 0xAA trill appended after each SAME burst.  Defaults to True.
        self._fingerprint_enabled = bool(config.get('endec_fingerprint', True))

    def _terminator_samples(self, amplitude: float) -> List[int]:
        """Return the station fingerprint samples, or [] when fingerprinting is disabled."""
        if not self._fingerprint_enabled:
            return []
        return _generate_station_terminator_samples(amplitude, self.sample_rate)

    def build_files(
        self,
        alert: object,
        payload: Dict[str, object],
        header: str,
        location_codes: List[str],
    ) -> Tuple[str, str, str, bytes, Dict[str, object], Dict[str, Dict[str, object]]]:
        identifier = getattr(alert, 'identifier', None) or payload.get('identifier') or 'alert'
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        base_name = _clean_identifier(f"{identifier}_{timestamp}")
        audio_filename = f"{base_name}.wav"
        text_filename = f"{base_name}.txt"

        audio_path = os.path.join(self.output_dir, audio_filename)
        text_path = os.path.join(self.output_dir, text_filename)

        same_bits = encode_same_bits(header, include_preamble=True)
        amplitude = 0.7 * 32767
        header_samples = generate_fsk_samples(
            same_bits,
            sample_rate=self.sample_rate,
            bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=amplitude,
        )
        terminator_samples = self._terminator_samples(amplitude)

        samples: List[int] = []
        segment_samples: Dict[str, List[int]] = {
            'same': [],
            'attention': [],
            'buffer': [],
        }

        # Pre-alert chime (system-level, configured per-station): plays
        # BEFORE the first SAME header burst.  See _generate_chime() for
        # supported profiles ('none', 'bell', 'beep', 'three_tone', 'qc2').
        pre_chime_profile = self.config.get('pre_alert_chime', 'none')
        pre_chime_duration = float(self.config.get('pre_alert_chime_duration', 2.0) or 2.0)
        qc2_freq_a = float(self.config.get('qc2_tone_a_freq', 1000.0) or 1000.0)
        qc2_freq_b = float(self.config.get('qc2_tone_b_freq', 1500.0) or 1500.0)
        qc2_long_tone = bool(self.config.get('qc2_long_tone_enabled', False))
        qc2_long_secs = float(self.config.get('qc2_long_tone_seconds', 10.0) or 10.0)
        dtmf_seq = str(self.config.get('dtmf_sequence', '') or '')
        pre_chime_samples = _generate_chime(
            pre_chime_profile, pre_chime_duration, self.sample_rate, amplitude,
            qc2_tone_a_freq=qc2_freq_a, qc2_tone_b_freq=qc2_freq_b,
            dtmf_sequence=dtmf_seq,
            qc2_long_tone_enabled=qc2_long_tone, qc2_long_tone_seconds=qc2_long_secs,
        )
        if pre_chime_samples:
            samples.extend(pre_chime_samples)
            samples.extend(_generate_silence(0.5, self.sample_rate))

        for burst_index in range(3):
            samples.extend(header_samples)
            segment_samples['same'].extend(header_samples)
            samples.extend(terminator_samples)
            segment_samples['same'].extend(terminator_samples)
            silence = _generate_silence(1.0, self.sample_rate)
            samples.extend(silence)
            segment_samples['same'].extend(silence)

        # relay_tone_duration overrides the configured value for OTA relays so
        # the attention signal is always exactly 8 s regardless of station config.
        if 'relay_tone_duration' in payload:
            tone_duration = float(payload['relay_tone_duration'])
        else:
            tone_duration = float(self.config.get('attention_tone_seconds', 8) or 8)
        _tone_profile = str(payload.get('relay_tone_profile', 'attention')).strip().lower()
        # 'none' is used for RWT relays: FCC §11.61 forbids sending EBS tones
        # with a Required Weekly Test.  RWT relay = header × 3 + EOM only.
        _omit_tone = _tone_profile in ('none', 'omit', 'off', 'disabled')
        attention_samples: List[int] = []
        if not _omit_tone:
            if _tone_profile in ('1050', '1050hz', 'single'):
                _tone_freqs: tuple = (1050.0,)
            else:
                _tone_freqs = (853.0, 960.0)   # standard EAS dual-tone
            attention_samples = _generate_tone(_tone_freqs, tone_duration, self.sample_rate, amplitude)
        samples.extend(attention_samples)
        segment_samples['attention'].extend(attention_samples)

        if not _omit_tone:
            post_tone_silence = _generate_silence(1.0, self.sample_rate)
            samples.extend(post_tone_silence)
            segment_samples['buffer'].extend(post_tone_silence)

        message_text = _compose_message_text(alert, payload)
        if message_text:
            preview = message_text.replace('\n', ' ')
            self.logger.debug('Alert narration preview: %s', preview[:240])
        else:
            self.logger.warning('No message text for TTS narration - message_text is empty or None')

        # Check for embedded audio from IPAWS CAP resources FIRST
        # This allows originators to provide pre-recorded audio messages
        embedded_audio_samples: Optional[List[int]] = None
        embedded_audio_source: Optional[str] = None
        
        raw_json = payload.get('raw_json', {})
        if isinstance(raw_json, dict):
            properties = raw_json.get('properties', {})
            resources = properties.get('resources', [])
            if resources:
                self.logger.info(f"Found {len(resources)} CAP resources, checking for embedded audio...")
                embedded_audio_samples, embedded_audio_source = _fetch_embedded_audio(
                    resources, self.sample_rate, self.logger
                )
        
        voice_samples: Optional[List[int]] = None
        tts_segment: List[int] = []
        tts_warning: Optional[str] = None
        provider = self.tts_engine.provider
        
        # If no embedded audio found in resources, try the saved IPAWS audio file on disk.
        # This handles cases where raw_json resources are unavailable or derefUri decoding
        # failed but the poller already extracted and saved the audio to EAS_OUTPUT_DIR.
        if not embedded_audio_samples:
            _ipaws_saved = getattr(alert, 'ipaws_audio_url', None)
            if _ipaws_saved:
                _eas_out = os.getenv('EAS_OUTPUT_DIR') or os.path.join(
                    os.getenv('EAS_STATIC_DIR', os.path.join(os.getcwd(), 'static')),
                    'eas_messages',
                )
                _safe_fn = os.path.basename(str(_ipaws_saved))
                _disk_path = os.path.join(_eas_out, _safe_fn)
                if _safe_fn and os.path.isfile(_disk_path):
                    try:
                        with open(_disk_path, 'rb') as _fh:
                            _file_bytes = _fh.read()
                        _mime = (
                            'audio/mpeg'
                            if _file_bytes[:3] == b'ID3' or _file_bytes[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2')
                            else ''
                        )
                        _disk_samples = _convert_audio_to_samples(_file_bytes, _mime, self.sample_rate, self.logger)
                        if _disk_samples:
                            embedded_audio_samples = _disk_samples
                            embedded_audio_source = f"ipaws_saved:{_safe_fn}"
                            self.logger.info(
                                "Using saved IPAWS audio from disk: %s (%d samples)",
                                _safe_fn, len(_disk_samples),
                            )
                    except Exception as _exc:
                        self.logger.warning("Failed to load saved IPAWS audio %s: %s", _disk_path, _exc)

        # OTA relay audio takes highest priority: use the narration captured from
        # the received broadcast (between attention tone and EOM) instead of any
        # IPAWS embedded audio or synthesised TTS.
        # Exception: when the tone is omitted (e.g. RWT) there is no narration.
        relay_audio_wav_bytes = None if _omit_tone else payload.get('relay_audio_wav_bytes')
        if relay_audio_wav_bytes:
            relay_samples = _convert_audio_to_samples(
                relay_audio_wav_bytes, 'audio/wav', self.sample_rate, self.logger
            )
            if relay_samples:
                self.logger.info(
                    "Using OTA relay audio (%d samples) instead of TTS/IPAWS",
                    len(relay_samples),
                )
                voice_samples = relay_samples
                provider = 'ota_relay'
            else:
                self.logger.warning(
                    "relay_audio_wav_bytes present but failed to decode — falling back to IPAWS/TTS"
                )

        if _omit_tone:
            # No-tone mode (e.g. RWT): header + EOM only — skip all narration.
            voice_samples = None
        elif voice_samples is None:
            if embedded_audio_samples:
                # Use embedded audio from IPAWS instead of TTS
                self.logger.info(
                    f"Using embedded IPAWS audio ({len(embedded_audio_samples)} samples) "
                    f"instead of TTS synthesis"
                )
                voice_samples = embedded_audio_samples
                provider = 'ipaws_embedded'
            else:
                # Fall back to TTS generation
                if message_text:
                    self.logger.info(f"Attempting TTS generation with provider '{provider}' for {len(message_text)} characters of text")
                    voice_samples = self.tts_engine.generate(message_text)
                    if not voice_samples:
                        self.logger.error(f"TTS engine returned no samples. Provider: '{provider}', Last error: {self.tts_engine.last_error}")
                else:
                    self.logger.warning("Skipping TTS generation - no message text available")
                    voice_samples = None

        if voice_samples:
            pre_voice_silence = _generate_silence(1.0, self.sample_rate)
            samples.extend(pre_voice_silence)
            segment_samples['buffer'].extend(pre_voice_silence)
            samples.extend(voice_samples)
            tts_segment = list(voice_samples)
        else:
            # Capture TTS failure for database storage and logging
            error_detail = self.tts_engine.last_error
            if provider == 'azure':
                base_message = 'Azure Speech is configured but synthesis failed.'
                tts_warning = f"{base_message} {error_detail}" if error_detail else base_message
            elif provider == 'azure_openai':
                base_message = 'Azure OpenAI TTS is configured but synthesis failed.'
                tts_warning = f"{base_message} {error_detail}" if error_detail else base_message
            elif provider == 'pyttsx3':
                base_message = 'pyttsx3 is configured but synthesis failed.'
                tts_warning = f"{base_message} {error_detail}" if error_detail else base_message
            elif provider:
                base_message = f'TTS provider "{provider}" is configured but synthesis failed.'
                tts_warning = f"{base_message} {error_detail}" if error_detail else base_message
            else:
                tts_warning = 'No TTS provider configured.'

            # Log the TTS failure for debugging
            if provider and error_detail:
                self.logger.error(f"TTS synthesis failed with provider '{provider}': {error_detail}")
            elif provider:
                self.logger.warning(f"TTS provider '{provider}' is configured but produced no audio")
            else:
                self.logger.info("TTS is not configured for this alert")

        trailing_silence = _generate_silence(1.0, self.sample_rate)
        samples.extend(trailing_silence)
        segment_samples['buffer'].extend(trailing_silence)

        # Generate EOM (End of Message) and append it to the complete audio sequence.
        # This ensures the broadcast sequence (SAME + attention + narration + EOM) is
        # contained in one uninterrupted audio file, matching the behavior of
        # build_manual_components() and satisfying FCC 47 CFR §11.31.
        eom_header = build_eom_header(self.config)
        eom_bits = encode_same_bits(eom_header, include_preamble=True, include_cr=False)
        eom_header_samples = generate_fsk_samples(
            eom_bits,
            sample_rate=self.sample_rate,
            bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=amplitude,
        )
        eom_raw_samples: List[int] = []
        for burst_index in range(3):
            eom_raw_samples.extend(eom_header_samples)
            eom_raw_samples.extend(terminator_samples)
            if burst_index < 2:
                eom_raw_samples.extend(_generate_silence(1.0, self.sample_rate))
        eom_raw_samples.extend(_generate_silence(1.0, self.sample_rate))
        samples.extend(eom_raw_samples)

        # Post-alert chime (system-level, configured per-station): plays
        # AFTER the EOM sequence.  See _generate_chime() for supported
        # profiles ('none', 'bell', 'beep', 'three_tone', 'qc2').
        post_chime_profile = self.config.get('post_alert_chime', 'none')
        post_chime_duration = float(self.config.get('post_alert_chime_duration', 2.0) or 2.0)
        post_chime_samples = _generate_chime(
            post_chime_profile, post_chime_duration, self.sample_rate, amplitude,
            qc2_tone_a_freq=qc2_freq_a, qc2_tone_b_freq=qc2_freq_b,
            dtmf_sequence=dtmf_seq,
            qc2_long_tone_enabled=qc2_long_tone, qc2_long_tone_seconds=qc2_long_secs,
        )
        if post_chime_samples:
            samples.extend(_generate_silence(0.5, self.sample_rate))
            samples.extend(post_chime_samples)

        wav_bytes = samples_to_wav_bytes(samples, self.sample_rate)
        try:
            with open(audio_path, 'wb') as handle:
                handle.write(wav_bytes)
            self.logger.info(f"Generated SAME audio at {audio_path}")
        except OSError as exc:
            self.logger.warning(
                "Could not write audio file to disk (audio stored in database only): %s", exc
            )

        segment_payload: Dict[str, Dict[str, object]] = {}

        for key, segment in segment_samples.items():
            if not segment:
                continue
            segment_wav = samples_to_wav_bytes(segment, self.sample_rate)
            segment_payload[key] = {
                'wav_bytes': segment_wav,
                'duration_seconds': round(len(segment) / self.sample_rate, 6),
                'size_bytes': len(segment_wav),
            }

        if tts_segment:
            tts_wav = samples_to_wav_bytes(tts_segment, self.sample_rate)
            segment_payload['tts'] = {
                'wav_bytes': tts_wav,
                'duration_seconds': round(len(tts_segment) / self.sample_rate, 6),
                'size_bytes': len(tts_wav),
            }

        eom_wav = samples_to_wav_bytes(eom_raw_samples, self.sample_rate)
        segment_payload['eom'] = {
            'wav_bytes': eom_wav,
            'duration_seconds': round(len(eom_raw_samples) / self.sample_rate, 6),
            'size_bytes': len(eom_wav),
        }

        if pre_chime_samples:
            pre_chime_wav = samples_to_wav_bytes(pre_chime_samples, self.sample_rate)
            segment_payload['pre_chime'] = {
                'wav_bytes': pre_chime_wav,
                'duration_seconds': round(len(pre_chime_samples) / self.sample_rate, 6),
                'size_bytes': len(pre_chime_wav),
                'profile': str(pre_chime_profile or 'none').lower(),
            }

        if post_chime_samples:
            post_chime_wav = samples_to_wav_bytes(post_chime_samples, self.sample_rate)
            segment_payload['post_chime'] = {
                'wav_bytes': post_chime_wav,
                'duration_seconds': round(len(post_chime_samples) / self.sample_rate, 6),
                'size_bytes': len(post_chime_wav),
                'profile': str(post_chime_profile or 'none').lower(),
            }

        # Record composite metrics (bytes already stored as audio_data; no duplication)
        segment_payload['composite'] = {
            'duration_seconds': round(len(samples) / self.sample_rate, 6),
            'size_bytes': len(wav_bytes),
        }

        text_body = {
            'identifier': identifier,
            'event': getattr(alert, 'event', ''),
            'sent': getattr(alert, 'sent', None).isoformat() if getattr(alert, 'sent', None) else None,
            'expires': getattr(alert, 'expires', None).isoformat() if getattr(alert, 'expires', None) else None,
            'same_header': header,
            'location_codes': location_codes,
            'headline': getattr(alert, 'headline', ''),
            'description': getattr(alert, 'description', ''),
            'instruction': getattr(alert, 'instruction', ''),
            'message_text': message_text,
        }
        text_body['voiceover_provider'] = provider or None
        text_body['tts_warning'] = tts_warning
        if embedded_audio_source:
            text_body['embedded_audio_source'] = embedded_audio_source

        try:
            with open(text_path, 'w', encoding='utf-8') as handle:
                json.dump(text_body, handle, indent=2)
            self.logger.info(f"Wrote alert summary at {text_path}")
        except OSError as exc:
            self.logger.warning(
                "Could not write text summary to disk (payload stored in database only): %s", exc
            )

        return audio_filename, text_filename, message_text, wav_bytes, text_body, segment_payload

    def build_eom_file(self) -> Tuple[str, bytes]:
        header = build_eom_header(self.config)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        base_name = _clean_identifier(f"eom_{timestamp}")
        audio_filename = f"{base_name}.wav"
        audio_path = os.path.join(self.output_dir, audio_filename)

        same_bits = encode_same_bits(header, include_preamble=True, include_cr=False)
        amplitude = 0.7 * 32767
        header_samples = generate_fsk_samples(
            same_bits,
            sample_rate=self.sample_rate,
            bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=amplitude,
        )
        terminator_samples = self._terminator_samples(amplitude)

        samples: List[int] = []
        for burst_index in range(3):
            samples.extend(header_samples)
            samples.extend(terminator_samples)
            if burst_index < 2:
                samples.extend(_generate_silence(1.0, self.sample_rate))

        samples.extend(_generate_silence(1.0, self.sample_rate))

        wav_bytes = samples_to_wav_bytes(samples, self.sample_rate)
        try:
            with open(audio_path, 'wb') as handle:
                handle.write(wav_bytes)
            if self.logger:
                self.logger.debug('Generated EOM audio at %s', audio_path)
        except OSError as exc:
            if self.logger:
                self.logger.warning(
                    "Could not write EOM audio file to disk (audio stored in database only): %s",
                    exc,
                )

        return audio_filename, wav_bytes

    def build_manual_components(
        self,
        alert: object,
        header: str,
        *,
        repeats: int = 3,
        tone_profile: str = 'attention',
        tone_duration: Optional[float] = None,
        include_tts: bool = True,
        silence_between_headers: float = 1.0,
        silence_after_header: float = 1.0,
        force_rwt_defaults: bool = True,
        narration_upload_samples: Optional[List[int]] = None,
        pre_alert_samples: Optional[List[int]] = None,
        post_alert_samples: Optional[List[int]] = None,
    ) -> Dict[str, object]:
        # Extract event code from SAME header to detect RWT (Required Weekly Test)
        # Header format: ZCZC-ORG-EEE-PSSCCC-... where EEE is the event code
        event_code = None
        if header:
            parts = header.split('-')
            if len(parts) > 2:
                event_code = parts[2].strip().upper()

        # For RWT (Required Weekly Test), optionally disable TTS and attention tones
        # By default (force_rwt_defaults=True), RWT only has SAME header and EOM tones
        # Set force_rwt_defaults=False to allow TTS and attention tones for RWT
        if event_code == 'RWT' and force_rwt_defaults:
            include_tts = False
            tone_profile = 'none'
            if self.logger:
                self.logger.info("RWT detected: disabling TTS narration and attention tones (use force_rwt_defaults=False to override)")

        amplitude = 0.7 * 32767
        same_bits = encode_same_bits(header, include_preamble=True)
        header_samples = generate_fsk_samples(
            same_bits,
            sample_rate=self.sample_rate,
            bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=amplitude,
        )
        terminator_samples = self._terminator_samples(amplitude)

        repeats = max(1, int(repeats))
        same_samples: List[int] = []
        for burst_index in range(repeats):
            same_samples.extend(header_samples)
            same_samples.extend(terminator_samples)
            if burst_index < repeats - 1:
                same_samples.extend(_generate_silence(silence_between_headers, self.sample_rate))

        profile = (tone_profile or 'attention').strip().lower()
        omit_tone = profile in {'none', 'omit', 'off', 'disabled'}

        tone_seconds = tone_duration
        if tone_seconds in (None, ''):
            tone_seconds = float(self.config.get('attention_tone_seconds', 8) or 8)

        attention_samples: List[int] = []
        if omit_tone:
            tone_seconds = 0.0
            tone_freqs: Iterable[float] = ()
            profile_label = 'none'
        else:
            tone_seconds = max(0.25, float(tone_seconds))
            if profile in {'1050', '1050hz', 'single'}:
                tone_freqs = (1050.0,)
                profile_label = '1050hz'
            else:
                tone_freqs = (853.0, 960.0)
                profile_label = 'attention'

            attention_samples = _generate_tone(tone_freqs, tone_seconds, self.sample_rate, amplitude)

        message_text = _compose_message_text(alert)
        tts_samples: List[int] = []
        tts_warning: Optional[str] = None
        provider = self.tts_engine.provider

        # If narration audio was uploaded, use it instead of TTS
        if narration_upload_samples:
            normalized_narration = _normalize_audio_amplitude(narration_upload_samples, amplitude * 0.7)
            tts_samples.extend(normalized_narration)
            if self.logger:
                self.logger.info(f"Using uploaded narration audio: {len(tts_samples)} samples")
        elif include_tts:
            if not message_text:
                if self.logger:
                    self.logger.warning("TTS requested but no message text available for narration")
                tts_warning = 'No message text available for TTS narration.'
            else:
                if self.logger:
                    self.logger.info(f"Generating TTS with provider '{provider}' for {len(message_text)} characters")
                    
                voiceover = self.tts_engine.generate(message_text)
                
                if voiceover:
                    tts_samples.extend(voiceover)
                    if self.logger:
                        self.logger.info(f"TTS generation successful: {len(tts_samples)} samples generated")
                else:
                    error_detail = self.tts_engine.last_error
                    if provider == 'azure':
                        base_message = 'Azure Speech is configured but synthesis failed.'
                        tts_warning = f"{base_message} {error_detail}" if error_detail else base_message
                    elif provider == 'azure_openai':
                        base_message = 'Azure OpenAI TTS is configured but synthesis failed.'
                        tts_warning = f"{base_message} {error_detail}" if error_detail else base_message
                    elif provider == 'pyttsx3':
                        base_message = 'pyttsx3 is configured but synthesis failed.'
                        tts_warning = f"{base_message} {error_detail}" if error_detail else base_message
                    elif provider:
                        base_message = f'TTS provider "{provider}" is configured but synthesis failed.'
                        tts_warning = f"{base_message} {error_detail}" if error_detail else base_message
                    else:
                        tts_warning = 'No TTS provider configured; supply narration manually.'

                    # Log the TTS failure for debugging - ALWAYS log, not just when error_detail exists
                    if self.logger:
                        if provider:
                            if error_detail:
                                self.logger.error(f"TTS synthesis failed with provider '{provider}': {error_detail}")
                            else:
                                self.logger.error(f"TTS synthesis failed with provider '{provider}': No error details available")
                        else:
                            self.logger.warning("TTS synthesis skipped: No TTS provider configured")
        else:
            if self.logger:
                self.logger.info("TTS narration disabled for this broadcast (include_tts=False)")

        eom_header = build_eom_header(self.config)
        eom_bits = encode_same_bits(eom_header, include_preamble=True, include_cr=False)
        eom_header_samples = generate_fsk_samples(
            eom_bits,
            sample_rate=self.sample_rate,
            bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=amplitude,
        )

        eom_samples: List[int] = []
        for burst_index in range(3):
            eom_samples.extend(eom_header_samples)
            eom_samples.extend(terminator_samples)
            if burst_index < 2:
                eom_samples.extend(_generate_silence(1.0, self.sample_rate))

        eom_samples.extend(_generate_silence(1.0, self.sample_rate))

        # Normalize uploaded pre/post alert audio
        norm_pre_alert = (
            _normalize_audio_amplitude(pre_alert_samples, amplitude * 0.7)
            if pre_alert_samples else []
        )
        norm_post_alert = (
            _normalize_audio_amplitude(post_alert_samples, amplitude * 0.7)
            if post_alert_samples else []
        )

        trailing_silence = _generate_silence(silence_after_header, self.sample_rate)

        # System-level chimes (configured per-station via EASSettings).
        # The pre-chime plays BEFORE the first SAME header burst, and the
        # post-chime plays AFTER the EOM sequence.  These are distinct from
        # the per-broadcast pre_alert_samples/post_alert_samples uploads,
        # which bracket the narration segment.
        pre_chime_profile = self.config.get('pre_alert_chime', 'none')
        pre_chime_duration = float(self.config.get('pre_alert_chime_duration', 2.0) or 2.0)
        qc2_freq_a = float(self.config.get('qc2_tone_a_freq', 1000.0) or 1000.0)
        qc2_freq_b = float(self.config.get('qc2_tone_b_freq', 1500.0) or 1500.0)
        qc2_long_tone = bool(self.config.get('qc2_long_tone_enabled', False))
        qc2_long_secs = float(self.config.get('qc2_long_tone_seconds', 10.0) or 10.0)
        dtmf_seq = str(self.config.get('dtmf_sequence', '') or '')
        pre_chime_samples_list = _generate_chime(
            pre_chime_profile, pre_chime_duration, self.sample_rate, amplitude,
            qc2_tone_a_freq=qc2_freq_a, qc2_tone_b_freq=qc2_freq_b,
            dtmf_sequence=dtmf_seq,
            qc2_long_tone_enabled=qc2_long_tone, qc2_long_tone_seconds=qc2_long_secs,
        )
        post_chime_profile = self.config.get('post_alert_chime', 'none')
        post_chime_duration = float(self.config.get('post_alert_chime_duration', 2.0) or 2.0)
        post_chime_samples_list = _generate_chime(
            post_chime_profile, post_chime_duration, self.sample_rate, amplitude,
            qc2_tone_a_freq=qc2_freq_a, qc2_tone_b_freq=qc2_freq_b,
            dtmf_sequence=dtmf_seq,
            qc2_long_tone_enabled=qc2_long_tone, qc2_long_tone_seconds=qc2_long_secs,
        )
        chime_separator = _generate_silence(0.5, self.sample_rate)

        composite_samples: List[int] = []
        if pre_chime_samples_list:
            composite_samples.extend(pre_chime_samples_list)
            composite_samples.extend(chime_separator)
        composite_samples.extend(same_samples)
        composite_samples.extend(trailing_silence)
        composite_samples.extend(attention_samples)
        if norm_pre_alert:
            composite_samples.extend(trailing_silence)
            composite_samples.extend(norm_pre_alert)
        if tts_samples:
            composite_samples.extend(trailing_silence)
            composite_samples.extend(tts_samples)
        if norm_post_alert:
            composite_samples.extend(trailing_silence)
            composite_samples.extend(norm_post_alert)
        composite_samples.extend(trailing_silence)
        composite_samples.extend(eom_samples)
        if post_chime_samples_list:
            composite_samples.extend(chime_separator)
            composite_samples.extend(post_chime_samples_list)

        return {
            'header': header,
            'message_text': message_text,
            'tone_profile': profile_label,
            'tone_seconds': float(tone_seconds),
            'same_samples': same_samples,
            'attention_samples': attention_samples,
            'tts_samples': tts_samples,
            'tts_warning': tts_warning,
            'tts_provider': provider or None,
            'tts_enabled': include_tts,  # Actual TTS state (may differ from request if RWT)
            'eom_header': eom_header,
            'eom_samples': eom_samples,
            'pre_alert_samples': norm_pre_alert,
            'post_alert_samples': norm_post_alert,
            'pre_chime_samples': pre_chime_samples_list,
            'post_chime_samples': post_chime_samples_list,
            'pre_chime_profile': str(pre_chime_profile or 'none').lower(),
            'post_chime_profile': str(post_chime_profile or 'none').lower(),
            'composite_samples': composite_samples,
            'sample_rate': self.sample_rate,
        }


class EASBroadcaster:
    def __init__(
        self,
        db_session,
        model_cls,
        config: Dict[str, object],
        logger,
        location_settings: Optional[Dict[str, object]] = None,
    ) -> None:
        self.db_session = db_session
        self.model_cls = model_cls
        self.config = config
        self.logger = logger
        self.location_settings = location_settings or {}
        self.enabled = bool(config.get('enabled'))
        self.audio_generator = EASAudioGenerator(config, logger)
        self.gpio_controller: Optional[GPIOController] = None
        self.gpio_pin_configs: List[GPIOPinConfig] = []
        self.gpio_behavior_manager: Optional[GPIOBehaviorManager] = None

        if not self.enabled:
            self.logger.info('EAS broadcasting is disabled via configuration.')
        else:
            self.logger.info(
                'EAS broadcasting enabled with output directory %s',
                self.audio_generator.output_dir,
            )

        if self.enabled:
            oled_enabled = _get_oled_enabled_status()
            gpio_configs = load_gpio_pin_configs_from_db(self.logger, oled_enabled=oled_enabled)
            if gpio_configs:
                try:
                    gpio_logger = (
                        self.logger.getChild('gpio')
                        if hasattr(self.logger, 'getChild')
                        else self.logger
                    )
                    controller = GPIOController(
                        db_session=self.db_session,
                        logger=gpio_logger,
                    )
                    for config_entry in gpio_configs:
                        controller.add_pin(config_entry)

                    self.gpio_controller = controller
                    self.gpio_pin_configs = gpio_configs
                    behavior_matrix = load_gpio_behavior_matrix_from_db(self.logger)
                    self.gpio_behavior_manager = GPIOBehaviorManager(
                        controller=controller,
                        pin_configs=gpio_configs,
                        behavior_matrix=behavior_matrix,
                        logger=gpio_logger.getChild('behavior')
                        if hasattr(gpio_logger, 'getChild')
                        else gpio_logger,
                    )
                    controller.behavior_manager = self.gpio_behavior_manager
                    self.logger.info(
                        'Configured GPIO controller with %s pin(s)',
                        len(gpio_configs),
                    )
                except Exception as exc:  # pragma: no cover - hardware setup
                    self.logger.warning(f"GPIO controller unavailable: {exc}")
                    self.gpio_controller = None

    def _play_audio(self, audio_path: str) -> None:
        cmd = self.config.get('audio_player_cmd')
        if not cmd:
            self.logger.debug('No audio player configured; skipping playback.')
            return
        command = list(cmd) + [audio_path]
        self.logger.info('Playing alert audio using %s', ' '.join(command))
        _run_command(command, self.logger)

    def _play_audio_or_bytes(
        self, audio_path: Optional[str], fallback_bytes: Optional[bytes]
    ) -> None:
        """Play audio from ``audio_path`` if it exists, otherwise write
        ``fallback_bytes`` to a temporary file and play from there."""
        if audio_path and os.path.exists(audio_path):
            self._play_audio(audio_path)
            return
        if fallback_bytes:
            if audio_path:
                self.logger.warning(
                    "Audio file not on disk, playing from memory: %s", audio_path
                )
            fd, tmp_path = tempfile.mkstemp(suffix='.wav')
            try:
                os.write(fd, fallback_bytes)
                os.close(fd)
                self._play_audio(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        elif audio_path:
            self.logger.warning('Audio file not available for playback: %s', audio_path)

    def _get_blockchannel(self, alert: object, payload: Dict[str, object]) -> set:
        """Extract BLOCKCHANNEL values from alert/payload.
        
        BLOCKCHANNEL is a CAP/IPAWS parameter that specifies which distribution
        channels should NOT be used for an alert. Common values include:
        - EAS: Emergency Alert System (broadcast)
        - NWEM: Non-Weather Emergency Message
        - CMAS: Commercial Mobile Alert System (Wireless Emergency Alerts)
        
        The parameter can appear in:
        - payload['raw_json']['properties']['parameters']['BLOCKCHANNEL']
        - payload['parameters']['BLOCKCHANNEL']
        - alert.raw_json['properties']['parameters']['BLOCKCHANNEL']
        
        Returns:
            Set of blocked channel names (uppercase), empty set if none blocked
        """
        blocked: set = set()
        
        def _extract_from_parameters(params: dict) -> None:
            if not isinstance(params, dict):
                return
            # Check uppercase first, then lowercase - use explicit None check to avoid
            # issues with empty lists being falsy
            blockchannel = params.get('BLOCKCHANNEL')
            if blockchannel is None:
                blockchannel = params.get('blockchannel', [])
            if isinstance(blockchannel, str):
                blocked.add(blockchannel.strip().upper())
            elif isinstance(blockchannel, (list, tuple)):
                for item in blockchannel:
                    if item:
                        blocked.add(str(item).strip().upper())
        
        # Check payload['parameters']
        if isinstance(payload.get('parameters'), dict):
            _extract_from_parameters(payload['parameters'])
        
        # Check payload['raw_json']['properties']['parameters']
        raw_json = payload.get('raw_json', {})
        if isinstance(raw_json, dict):
            props = raw_json.get('properties', {})
            if isinstance(props, dict):
                _extract_from_parameters(props.get('parameters', {}))
        
        # Check alert.raw_json['properties']['parameters']
        alert_raw_json = getattr(alert, 'raw_json', None)
        if isinstance(alert_raw_json, dict):
            props = alert_raw_json.get('properties', {})
            if isinstance(props, dict):
                _extract_from_parameters(props.get('parameters', {}))
        
        return blocked

    def handle_alert(self, alert: object, payload: Dict[str, object]) -> Dict[str, object]:
        result: Dict[str, object] = {"same_triggered": False}
        if not self.enabled or not alert:
            result["reason"] = "Broadcasting disabled"
            return result

        status = (getattr(alert, 'status', '') or '').lower()
        message_type = (payload.get('message_type') or getattr(alert, 'message_type', '') or '').lower()
        event_name = (getattr(alert, 'event', '') or payload.get('event') or '').strip().lower()

        suppressed_events = {
            'special weather statement',
            'dense fog advisory',
        }

        # Note: BLOCKCHANNEL in IPAWS/CAP applies to automated IPAWS distribution
        # systems, not to local EAS stations monitoring the NWS API directly.
        # Local EAS stations must make their own broadcast decisions based on
        # event type and geographic coverage, not the BLOCKCHANNEL parameter.

        if status not in {'actual', 'test'}:
            self.logger.debug('Skipping EAS generation for status %s', status)
            result['reason'] = f"Unsupported status: {status}"
            return result
        if message_type not in {'alert', 'update', 'test'}:
            self.logger.debug('Skipping EAS generation for message type %s', message_type)
            result['reason'] = f"Unsupported message type: {message_type}"
            return result
        if event_name in suppressed_events:
            pretty_event = getattr(alert, 'event', '') or payload.get('event') or event_name
            self.logger.info('Skipping EAS generation for event %s', pretty_event)
            result['reason'] = f"Suppressed event {pretty_event}"
            return result

        try:
            header, location_codes, event_code = build_same_header(
                alert,
                payload,
                self.config,
                self.location_settings,
            )
        except ValueError as exc:
            self.logger.info('Skipping EAS generation: %s', exc)
            result['reason'] = str(exc)
            return result

        try:
            (
                audio_filename,
                text_filename,
                message_text,
                audio_bytes,
                text_payload,
                segment_payload,
            ) = self.audio_generator.build_files(alert, payload, header, location_codes)
        except Exception as exc:
            self.logger.error('Audio generation failed for alert %s: %s',
                              getattr(alert, 'identifier', 'unknown'), exc)
            result['reason'] = f"Audio generation failed: {exc}"
            return result

        # EOM is now embedded in audio_bytes (built inside build_files()).
        # Extract the EOM segment for separate database storage so it can be
        # displayed/downloaded individually from the audio detail page.
        eom_bytes = (segment_payload.get('eom') or {}).get('wav_bytes')

        audio_path = os.path.join(self.audio_generator.output_dir, audio_filename)

        # Populate result fields that are known at this point, but defer
        # setting same_triggered=True until the database commit succeeds so
        # callers never see a "triggered" status when the record was not saved
        # and audio was never played.
        result.update(
            {
                "event_code": event_code,
                "same_header": header,
                "audio_path": audio_path,
                "location_codes": location_codes,
            }
        )

        alert_identifier = getattr(alert, 'identifier', None) or payload.get('identifier')
        forwarding_decision = str(payload.get('forwarding_decision', '') or '').lower()
        is_forwarded = forwarding_decision == 'forwarded' or bool(payload.get('forwarded', False))

        # Signal hardware indicators (tower light) that an alert has arrived but
        # broadcast has not started yet.  The hardware service polls this key and
        # calls start_incoming_alert() on the tower light controller.
        set_incoming_alert(event_code=event_code or '')

        behavior_manager = self.gpio_behavior_manager
        if behavior_manager:
            behavior_manager.trigger_incoming_alert(
                alert_id=str(alert_identifier) if alert_identifier else None,
                event_code=event_code,
            )
            # FORWARDING_ALERT pins are held for the full broadcast duration via
            # start_alert(forwarded=True) below instead of a short pulse here.

        # Create and persist database record BEFORE queue/immediate mode split
        # This ensures both modes have consistent database tracking
        segment_metadata = {
            key: {
                'duration_seconds': value.get('duration_seconds'),
                'size_bytes': value.get('size_bytes'),
            }
            for key, value in segment_payload.items()
            if value
        }

        record = self.model_cls(
            cap_alert_id=getattr(alert, 'id', None),
            same_header=header,
            audio_filename=audio_filename,
            text_filename=text_filename,
            audio_data=audio_bytes,
            eom_audio_data=eom_bytes,
            same_audio_data=(segment_payload.get('same') or {}).get('wav_bytes'),
            attention_audio_data=(segment_payload.get('attention') or {}).get('wav_bytes'),
            tts_audio_data=(segment_payload.get('tts') or {}).get('wav_bytes'),
            buffer_audio_data=(segment_payload.get('buffer') or {}).get('wav_bytes'),
            tts_warning=text_payload.get('tts_warning'),
            tts_provider=text_payload.get('voiceover_provider'),
            text_payload=text_payload,
            created_at=datetime.now(timezone.utc),
            metadata_payload={
                'event': getattr(alert, 'event', ''),
                'event_code': event_code,
                'severity': getattr(alert, 'severity', ''),
                'status': getattr(alert, 'status', ''),
                'message_type': getattr(alert, 'message_type', ''),
                'locations': location_codes,
                'segments': segment_metadata,
                'has_tts': bool(segment_payload.get('tts')),
                'has_eom': bool(segment_payload.get('eom')),
            },
        )

        try:
            self.db_session.add(record)
            self.db_session.commit()
            self.logger.info('Stored EAS message metadata for alert %s', getattr(alert, 'identifier', 'unknown'))
            result['record_id'] = getattr(record, 'id', None)
            # Only mark as triggered after the record is safely persisted.
            # If the commit fails the caller will see same_triggered=False and
            # an 'error' key rather than a false-positive success status.
            result['same_triggered'] = True
        except Exception as exc:
            self.logger.error(f"Failed to persist EAS message record: {exc}")
            self.db_session.rollback()
            result['error'] = str(exc)
            # If database persistence fails, we can't continue
            return result

        # Play audio synchronously
        controller = self.gpio_controller
        behavior_manager = self.gpio_behavior_manager
        activated_any = False
        manager_handled = False
        if controller:
            try:  # pragma: no cover - hardware specific
                activation_reason = f"Automatic alert playout ({event_code or 'unknown'})"
                if behavior_manager:
                    manager_handled = behavior_manager.start_alert(
                        alert_id=str(alert_identifier) if alert_identifier else None,
                        event_code=event_code,
                        reason=activation_reason,
                        forwarded=is_forwarded,
                    )
                    activated_any = activated_any or manager_handled

                if not activated_any:
                    activation_results = controller.activate_all(
                        activation_type=GPIOActivationType.AUTOMATIC,
                        operator=None,
                        alert_id=str(alert_identifier) if alert_identifier else None,
                        reason=activation_reason,
                    )
                    activated_any = any(activation_results.values())
                    if not activated_any:
                        self.logger.warning('GPIO controller configured but no pins activated')
            except Exception as exc:
                self.logger.warning(f"GPIO activation failed: {exc}")
                activated_any = False
                manager_handled = False

        try:
            # Inject into Icecast FIRST so stream listeners hear the alert
            # in sync with local playback.  inject_eas_audio() queues all
            # audio chunks into the BroadcastQueue immediately (no blocking),
            # then _play_audio_or_bytes() plays locally while the
            # IcecastStreamer drains those chunks to FFmpeg in real time.
            # Previously injection happened AFTER _play_audio_or_bytes()
            # returned, meaning Icecast listeners missed the entire alert.
            try:
                from app_core.audio.eas_stream_injector import inject_eas_audio
                _wav_data = audio_bytes
                if _wav_data is None and audio_path and os.path.exists(audio_path):
                    with open(audio_path, 'rb') as _f:
                        _wav_data = _f.read()
                if _wav_data:
                    inject_eas_audio(_wav_data)
            except Exception as _inj_exc:
                self.logger.warning("EAS stream injection failed (non-fatal): %s", _inj_exc)

            # Publish broadcast state to Redis so all connected browser clients
            # can display the global countdown timer overlay.
            _duration_hint = _wav_duration_seconds(audio_bytes) if audio_bytes else 0.0
            _event_info = EVENT_CODE_REGISTRY.get(event_code or '', {})
            _event_label = (
                _event_info.get('name', event_code) if isinstance(_event_info, dict) else event_code
            ) or 'EAS Alert'
            _bcast_source = 'forwarded' if is_forwarded else 'auto'
            set_broadcast_active(
                event_code=event_code or '',
                label=_event_label,
                duration_seconds=_duration_hint,
                source=_bcast_source,
            )

            # audio_bytes contains the complete broadcast sequence:
            # SAME header (3x) → attention tone → TTS narration → EOM.
            # All segments are in a single uninterrupted audio file, so no
            # gap can appear between the narration and the EOM burst.
            self._play_audio_or_bytes(audio_path, audio_bytes)
        finally:
            if controller and activated_any:
                try:  # pragma: no cover - hardware specific
                    if manager_handled and behavior_manager:
                        behavior_manager.end_alert(
                            alert_id=str(alert_identifier) if alert_identifier else None,
                            event_code=event_code,
                            forwarded=is_forwarded,
                        )
                    elif activated_any:
                        controller.deactivate_all()
                except Exception as exc:
                    self.logger.warning(f"GPIO release failed: {exc}")
            clear_broadcast_active()

        return result


def convert_audio_to_samples(
    audio_data: bytes,
    mime_type: str,
    target_sample_rate: int,
    logger,
) -> Optional[List[int]]:
    """Public wrapper for audio conversion. See :func:`_convert_audio_to_samples`."""
    return _convert_audio_to_samples(audio_data, mime_type, target_sample_rate, logger)


__all__ = [
    'load_eas_config',
    'EASBroadcaster',
    'EASAudioGenerator',
    'build_same_header',
    'build_eom_header',
    'samples_to_wav_bytes',
    'manual_default_same_codes',
    'convert_audio_to_samples',
    'PRIMARY_ORIGINATORS',
    'set_broadcast_active',
    'clear_broadcast_active',
    'get_broadcast_state',
]

