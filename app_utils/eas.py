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


def load_eas_config(base_path: Optional[str] = None) -> Dict[str, object]:
    """Build a runtime configuration dictionary for EAS broadcasting."""

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
    azure_speech_key = ''
    azure_speech_region = ''
    azure_speech_voice = 'en-US-AriaNeural'
    azure_speech_sample_rate = 24000

    try:
        tts_settings = get_tts_settings()

        # Always log TTS settings at INFO level for debugging
        load_logger.info(f"TTS settings from DB: enabled={tts_settings.enabled}, provider='{tts_settings.provider}'")

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

                load_logger.info(f"Azure OpenAI TTS config loaded: endpoint={'<set>' if azure_openai_endpoint else '<MISSING>'}, key={'<set>' if azure_openai_key else '<MISSING>'}")

                if not azure_openai_endpoint:
                    load_logger.error("Azure OpenAI TTS enabled but endpoint is empty!")
                if not azure_openai_key:
                    load_logger.error("Azure OpenAI TTS enabled but API key is empty!")

            # Load Azure Cognitive Services Speech settings if provider is azure
            elif tts_provider == 'azure':
                azure_speech_key = (tts_settings.azure_speech_key or '').strip()
                azure_speech_region = (tts_settings.azure_speech_region or '').strip()
                azure_speech_voice = (tts_settings.azure_speech_voice or 'en-US-AriaNeural').strip()
                azure_speech_sample_rate = int(tts_settings.azure_speech_sample_rate or 24000)

                load_logger.info(f"Azure Speech TTS config loaded: region={'<set>' if azure_speech_region else '<MISSING>'}, key={'<set>' if azure_speech_key else '<MISSING>'}")

                if not azure_speech_key:
                    load_logger.error("Azure Speech TTS enabled but subscription key is empty!")
                if not azure_speech_region:
                    load_logger.error("Azure Speech TTS enabled but region is empty!")
    except Exception as exc:
        load_logger.error(f"Failed to load TTS settings from database: {exc}")
        load_logger.exception("TTS settings load error details:")

    # Load station identity from database (EASSettings row 1), falling back to
    # environment variables for backwards compatibility, then to hardcoded defaults.
    db_originator = None
    db_station_id = None
    db_broadcast_enabled = None
    db_sample_rate = None
    db_attention_tone_seconds = None
    db_audio_player = None
    try:
        from app_core.models import EASSettings
        eas_settings = EASSettings.query.get(1)
        if eas_settings:
            db_originator = eas_settings.originator
            db_station_id = eas_settings.station_id
            db_broadcast_enabled = eas_settings.broadcast_enabled
            db_sample_rate = eas_settings.sample_rate
            db_attention_tone_seconds = eas_settings.attention_tone_seconds
            db_audio_player = eas_settings.audio_player
            load_logger.info(
                'EASSettings loaded from DB: originator=%s station_id=%s broadcast_enabled=%s',
                db_originator, db_station_id, db_broadcast_enabled,
            )
    except Exception as exc:
        load_logger.debug('Could not load EASSettings from database: %s', exc)

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
        )[:8].ljust(8),
        'output_dir': _ensure_directory(output_dir),
        'web_subdir': web_subdir,
        'audio_player_cmd': os.getenv('EAS_AUDIO_PLAYER', '').strip() or (db_audio_player or ''),
        'attention_tone_seconds': float(
            os.getenv('EAS_ATTENTION_TONE_SECONDS')
            or (db_attention_tone_seconds if db_attention_tone_seconds is not None else 8)
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
        'azure_speech_key': azure_speech_key or os.getenv('AZURE_SPEECH_KEY') or '',
        'azure_speech_region': azure_speech_region or os.getenv('AZURE_SPEECH_REGION') or '',
        'azure_speech_voice': azure_speech_voice,
        'azure_speech_sample_rate': azure_speech_sample_rate,
        'azure_openai_endpoint': azure_openai_endpoint,
        'azure_openai_key': azure_openai_key,
        'azure_openai_voice': azure_openai_voice,
        'azure_openai_model': azure_openai_model,
        'azure_openai_speed': azure_openai_speed,
        'pyttsx3_voice': os.getenv('PYTTSX3_VOICE'),
        'pyttsx3_rate': os.getenv('PYTTSX3_RATE'),
        'pyttsx3_volume': os.getenv('PYTTSX3_VOLUME'),
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


SAME_HEADER_FIELD_DESCRIPTIONS = [
    {
        'segment': 'Preamble',
        'label': '16 × 0xAB',
        'description': (
            'Binary 10101011 bytes transmitted sixteen times to calibrate and synchronise '
            'receivers before the ASCII header.'
        ),
    },
    {
        'segment': 'ZCZC',
        'label': 'Start code',
        'description': (
            'Marks the start of the SAME header, inherited from NAVTEX to trigger decoders.'
        ),
    },
    {
        'segment': 'ORG',
        'label': 'Originator code',
        'description': (
            'Three-character identifier for the sender such as PEP, WXR, CIV, or EAS.'
        ),
    },
    {
        'segment': 'EEE',
        'label': 'Event code',
        'description': 'Three-character SAME event describing the hazard (for example TOR or RWT).',
    },
    {
        'segment': 'PSSCCC',
        'label': 'Location codes',
        'description': (
            'One to thirty-one SAME/FIPS identifiers. P denotes the portion of the area, '
            'SS is the state FIPS, and CCC is the county (000 represents the entire state).'
        ),
    },
    {
        'segment': '+TTTT',
        'label': 'Purge time',
        'description': (
            'Duration code expressed in minutes using SAME rounding rules (15-minute increments '
            'up to an hour, 30-minute increments to six hours, then hourly).'
        ),
    },
    {
        'segment': '-JJJHHMM',
        'label': 'Issue time',
        'description': (
            'Julian day-of-year with UTC hour and minute indicating when the alert was issued.'
        ),
    },
    {
        'segment': '-LLLLLLLL-',
        'label': 'Station identifier',
        'description': (
            'Eight-character station, system, or call-sign identifier using “/” instead of “-”.'
        ),
    },
    {
        'segment': 'NNNN',
        'label': 'End of message',
        'description': 'Transmitted three times after audio content to terminate the activation.',
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
    purge_minutes = int(duration_digits) if duration_digits.isdigit() else None

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

    return {
        'preamble': parts[0] if parts else 'ZCZC',
        'preamble_description': (
            'SAME headers begin with a sixteen-byte 0xAB preamble for receiver synchronisation.'
        ),
        'start_code': parts[0] if parts else 'ZCZC',
        'originator': originator,
        'originator_description': ORIGINATOR_DESCRIPTIONS.get(originator),
        'event_code': event_code,
        'event_name': event_name,
        'location_count': len(detailed_locations),
        'locations': detailed_locations,
        'purge_code': duration_digits or None,
        'purge_minutes': purge_minutes,
        'purge_label': _format_duration(purge_minutes),
        'issue_code': julian_digits or None,
        'issue_time_label': issue_time_label,
        'issue_time_iso': issue_time_iso,
        'issue_components': issue_components,
        'station_identifier': station_identifier,
        'raw_locations': locations,
        'header_parts': parts,
    }


def _julian_time(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    julian_day = dt.timetuple().tm_yday
    return f"{julian_day:03d}{dt:%H%M}"


def _duration_code(sent: datetime, expires: Optional[datetime]) -> str:
    if not sent or not expires:
        return '0015'
    delta = max(expires - sent, datetime.resolution)
    minutes = max(int(math.ceil(delta.total_seconds() / 60.0 / 15.0) * 15), 15)
    minutes = min(minutes, 600)
    return f"{minutes:04d}"


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

    for key in ('SAME', 'same', 'SAMEcodes'):  # vendor spellings of SAME codes only
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

    originator = str(config.get('originator', 'WXR'))[:3].upper()
    station = str(config.get('station_id', 'EASNODES')).ljust(8)[:8]

    location_field = '-'.join(formatted_locations)
    header = f"ZCZC-{originator}-{event_code}-{location_field}+{duration_code}-{julian}-{station}-"

    return header, formatted_locations, event_code


def build_eom_header(config: Dict[str, object]) -> str:
    """Return the EOM payload per 47 CFR §11.31(c).

    The End Of Message burst is simply the ASCII string ``NNNN`` framed by the
    SAME preamble. No originator, location, or timing fields are transmitted.
    """

    return "NNNN"


def _compose_message_text(alert: object) -> str:
    parts: List[str] = []
    for attr in ('headline', 'description', 'instruction'):
        value = getattr(alert, attr, '') or ''
        if value:
            parts.append(str(value).strip())
    text = '\n\n'.join(parts).strip()
    return text or "A new emergency alert has been received."


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
    This function downloads the audio and converts it to PCM samples.
    
    Args:
        resources: List of resource dicts from CAP XML parsing
        target_sample_rate: Target sample rate for output
        logger: Logger instance
        timeout: Download timeout in seconds
        
    Returns:
        Tuple of (audio_samples, source_uri) or (None, None) if no audio found
    """
    import requests
    
    # Find audio resources - look for EAS Broadcast Content or audio mime types
    audio_resources = []
    for resource in resources:
        mime_type = (resource.get('mimeType') or '').lower()
        resource_desc = (resource.get('resourceDesc') or '').lower()
        uri = resource.get('uri', '')
        
        # Check for audio mime types or EAS broadcast content
        is_audio = (
            'audio' in mime_type or
            'eas broadcast' in resource_desc or
            uri.endswith(('.mp3', '.wav', '.ogg', '.m4a'))
        )
        
        if is_audio and uri:
            audio_resources.append(resource)
    
    if not audio_resources:
        return None, None
    
    # Try each audio resource until one works
    for resource in audio_resources:
        uri = resource.get('uri', '')
        mime_type = resource.get('mimeType', '')
        resource_desc = resource.get('resourceDesc', '')
        
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
            
            # Convert audio to PCM samples
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
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch audio from {uri}: {e}")
        except Exception as e:
            logger.error(f"Error processing audio from {uri}: {e}")
    
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
    
    # Try MP3 via pydub
    if 'mp3' in mime_lower or 'mpeg' in mime_lower or audio_data[:3] == b'ID3' or audio_data[:2] == b'\xff\xfb':
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
            logger.warning("pydub not available for MP3 conversion. Install with: pip install pydub")
        except Exception as e:
            logger.warning(f"Failed to convert MP3 audio: {e}")
    
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

        samples: List[int] = []
        segment_samples: Dict[str, List[int]] = {
            'same': [],
            'attention': [],
            'buffer': [],
        }

        for burst_index in range(3):
            samples.extend(header_samples)
            segment_samples['same'].extend(header_samples)
            silence = _generate_silence(1.0, self.sample_rate)
            samples.extend(silence)
            segment_samples['same'].extend(silence)

        tone_duration = float(self.config.get('attention_tone_seconds', 8) or 8)
        attention_samples = _generate_tone((853.0, 960.0), tone_duration, self.sample_rate, amplitude)
        samples.extend(attention_samples)
        segment_samples['attention'].extend(attention_samples)

        post_tone_silence = _generate_silence(1.0, self.sample_rate)
        samples.extend(post_tone_silence)
        segment_samples['buffer'].extend(post_tone_silence)

        message_text = _compose_message_text(alert)
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
            # Normalize audio to match SAME/AFSK amplitude
            # Reduced to 70% of SAME amplitude to prevent clipping/distortion
            normalized_voice_samples = _normalize_audio_amplitude(voice_samples, amplitude * 0.7)
            pre_voice_silence = _generate_silence(1.0, self.sample_rate)
            samples.extend(pre_voice_silence)
            segment_samples['buffer'].extend(pre_voice_silence)
            samples.extend(normalized_voice_samples)
            tts_segment = list(normalized_voice_samples)
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
        eom_bits = encode_same_bits(eom_header, include_preamble=True)
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
            if burst_index < 2:
                eom_raw_samples.extend(_generate_silence(1.0, self.sample_rate))
        eom_raw_samples.extend(_generate_silence(1.0, self.sample_rate))
        samples.extend(eom_raw_samples)

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

        samples: List[int] = []
        for burst_index in range(3):
            samples.extend(header_samples)
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

        repeats = max(1, int(repeats))
        same_samples: List[int] = []
        for burst_index in range(repeats):
            same_samples.extend(header_samples)
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
                    # Normalize TTS audio to match SAME/AFSK amplitude
                    # Reduced to 70% of SAME amplitude to prevent clipping/distortion
                    normalized_voiceover = _normalize_audio_amplitude(voiceover, amplitude * 0.7)
                    tts_samples.extend(normalized_voiceover)
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
        eom_bits = encode_same_bits(eom_header, include_preamble=True)
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
        composite_samples: List[int] = []
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

        (
            audio_filename,
            text_filename,
            message_text,
            audio_bytes,
            text_payload,
            segment_payload,
        ) = self.audio_generator.build_files(alert, payload, header, location_codes)

        # EOM is now embedded in audio_bytes (built inside build_files()).
        # Extract the EOM segment for separate database storage so it can be
        # displayed/downloaded individually from the audio detail page.
        eom_bytes = (segment_payload.get('eom') or {}).get('wav_bytes')

        audio_path = os.path.join(self.audio_generator.output_dir, audio_filename)

        result.update(
            {
                "same_triggered": True,
                "event_code": event_code,
                "same_header": header,
                "audio_path": audio_path,
                "location_codes": location_codes,
            }
        )

        alert_identifier = getattr(alert, 'identifier', None) or payload.get('identifier')
        behavior_manager = self.gpio_behavior_manager
        if behavior_manager:
            behavior_manager.trigger_incoming_alert(
                alert_id=str(alert_identifier) if alert_identifier else None,
                event_code=event_code,
            )

            forwarding_decision = str(payload.get('forwarding_decision', '') or '').lower()
            if forwarding_decision == 'forwarded' or bool(payload.get('forwarded', False)):
                behavior_manager.trigger_forwarding_alert(
                    alert_id=str(alert_identifier) if alert_identifier else None,
                    event_code=event_code,
                )

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
                        )
                    elif activated_any:
                        controller.deactivate_all()
                except Exception as exc:
                    self.logger.warning(f"GPIO release failed: {exc}")

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
]

