"""Helpers for generating and broadcasting EAS-compatible audio output."""

from __future__ import annotations

import io
import json
import math
import os
import re
import struct
import subprocess
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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
from .gpio import GPIORelayController  # Import from unified GPIO module

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

    config: Dict[str, object] = {
        'enabled': os.getenv('EAS_BROADCAST_ENABLED', 'false').lower() == 'true',
        'originator': (os.getenv('EAS_ORIGINATOR') or 'WXR')[:3].upper(),
        'station_id': (os.getenv('EAS_STATION_ID') or 'EASNODES')[:8].ljust(8),
        'output_dir': _ensure_directory(output_dir),
        'web_subdir': web_subdir,
        'audio_player_cmd': os.getenv('EAS_AUDIO_PLAYER', '').strip(),
        'attention_tone_seconds': float(os.getenv('EAS_ATTENTION_TONE_SECONDS', '8') or 8),
        'gpio_pin': os.getenv('EAS_GPIO_PIN'),
        'gpio_active_state': os.getenv('EAS_GPIO_ACTIVE_STATE', 'HIGH').upper(),
        'gpio_hold_seconds': float(os.getenv('EAS_GPIO_HOLD_SECONDS', '5') or 5),
        'sample_rate': int(os.getenv('EAS_SAMPLE_RATE', '16000') or 16000),
        'tts_provider': (os.getenv('EAS_TTS_PROVIDER') or '').strip().lower(),
        'azure_speech_key': os.getenv('AZURE_SPEECH_KEY'),
        'azure_speech_region': os.getenv('AZURE_SPEECH_REGION'),
        'azure_speech_voice': os.getenv('AZURE_SPEECH_VOICE', 'en-US-AriaNeural'),
        'azure_speech_sample_rate': int(os.getenv('AZURE_SPEECH_SAMPLE_RATE', '24000') or 24000),
        'azure_openai_endpoint': os.getenv('AZURE_OPENAI_ENDPOINT'),
        'azure_openai_key': os.getenv('AZURE_OPENAI_KEY'),
        'azure_openai_voice': os.getenv('AZURE_OPENAI_VOICE', 'alloy'),
        'azure_openai_model': os.getenv('AZURE_OPENAI_MODEL', 'tts-1-hd'),
        'azure_openai_speed': float(os.getenv('AZURE_OPENAI_SPEED', '1.0') or 1.0),
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

    for key in ('SAME', 'same', 'SAMEcodes', 'UGC'):  # allow a few vendor spellings
        values = geocode.get(key)
        if values:
            if isinstance(values, (list, tuple)):
                same_codes.extend(str(v).strip() for v in values)
            else:
                same_codes.append(str(values).strip())
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
    """Return the default SAME/FIPS codes for manual generation templates."""

    raw = os.getenv('EAS_MANUAL_FIPS_CODES', '')
    codes: List[str] = []
    if raw:
        for token in re.split(r'[\s,]+', raw.upper()):
            token = token.strip()
            if not token or token in MANUAL_FIPS_ENV_TOKENS:
                continue
            digits = re.sub(r'[^0-9]', '', token)
            if digits:
                codes.append(digits.zfill(6)[:6])

    if not codes:
        codes = ['039137']

    return codes[:31]


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
    """Normalize audio samples to match the target amplitude.

    This ensures TTS audio has the same volume level as SAME/AFSK tones.
    """
    if not samples:
        return samples

    # Calculate peak amplitude of the input samples
    peak = max(abs(s) for s in samples)

    # Avoid division by zero
    if peak == 0:
        return samples

    # Calculate the scaling factor needed to reach target amplitude
    # Use 0.95 safety factor to prevent clipping
    scale = (target_amplitude * 0.95) / peak

    # Apply scaling to all samples
    return [int(s * scale) for s in samples]


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


# GPIORelayController is now imported from app_utils.gpio module


class EASAudioGenerator:
    def __init__(self, config: Dict[str, object], logger) -> None:
        self.config = config
        self.logger = logger
        self.sample_rate = int(config.get('sample_rate', 16000))
        self.output_dir = str(config.get('output_dir'))
        _ensure_directory(self.output_dir)
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

        voice_samples = self.tts_engine.generate(message_text)
        tts_segment: List[int] = []
        if voice_samples:
            # Normalize TTS audio to match SAME/AFSK amplitude
            normalized_voice_samples = _normalize_audio_amplitude(voice_samples, amplitude)
            pre_voice_silence = _generate_silence(1.0, self.sample_rate)
            samples.extend(pre_voice_silence)
            segment_samples['buffer'].extend(pre_voice_silence)
            samples.extend(normalized_voice_samples)
            tts_segment = list(normalized_voice_samples)
        else:
            # Log TTS failure for debugging
            provider = self.tts_engine.provider
            error_detail = self.tts_engine.last_error
            if provider and error_detail:
                self.logger.error(f"TTS synthesis failed with provider '{provider}': {error_detail}")
            elif provider:
                self.logger.warning(f"TTS provider '{provider}' is configured but produced no audio")

        trailing_silence = _generate_silence(1.0, self.sample_rate)
        samples.extend(trailing_silence)
        segment_samples['buffer'].extend(trailing_silence)

        wav_bytes = samples_to_wav_bytes(samples, self.sample_rate)
        with open(audio_path, 'wb') as handle:
            handle.write(wav_bytes)
        self.logger.info(f"Generated SAME audio at {audio_path}")

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
        text_body['voiceover_provider'] = self.config.get('tts_provider') or None

        with open(text_path, 'w', encoding='utf-8') as handle:
            json.dump(text_body, handle, indent=2)
        self.logger.info(f"Wrote alert summary at {text_path}")

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
        with open(audio_path, 'wb') as handle:
            handle.write(wav_bytes)
        if self.logger:
            self.logger.debug('Generated EOM audio at %s', audio_path)

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
    ) -> Dict[str, object]:
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
        if include_tts:
            voiceover = self.tts_engine.generate(message_text)
            if voiceover:
                # Normalize TTS audio to match SAME/AFSK amplitude
                normalized_voiceover = _normalize_audio_amplitude(voiceover, amplitude)
                tts_samples.extend(normalized_voiceover)
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

                # Log the TTS failure for debugging
                if self.logger and error_detail:
                    self.logger.error(f"TTS synthesis failed with provider '{provider}': {error_detail}")

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

        trailing_silence = _generate_silence(silence_after_header, self.sample_rate)
        composite_samples: List[int] = []
        composite_samples.extend(same_samples)
        composite_samples.extend(trailing_silence)
        composite_samples.extend(attention_samples)
        if tts_samples:
            composite_samples.extend(trailing_silence)
            composite_samples.extend(tts_samples)
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
            'eom_header': eom_header,
            'eom_samples': eom_samples,
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
        playout_queue: Optional[object] = None,
    ) -> None:
        self.db_session = db_session
        self.model_cls = model_cls
        self.config = config
        self.logger = logger
        self.location_settings = location_settings or {}
        self.enabled = bool(config.get('enabled'))
        self.audio_generator = EASAudioGenerator(config, logger)
        self.gpio_controller: Optional[GPIORelayController] = None
        self.playout_queue = playout_queue  # Optional AudioPlayoutQueue for queued playback

        if not self.enabled:
            self.logger.info('EAS broadcasting is disabled via configuration.')
        else:
            mode = 'with queue' if self.playout_queue else 'immediate'
            self.logger.info(
                'EAS broadcasting enabled (%s mode) with output directory %s',
                mode,
                self.audio_generator.output_dir,
            )

        gpio_pin = config.get('gpio_pin')
        if gpio_pin and self.enabled:
            try:
                pin_number = int(str(gpio_pin))
                active_high = str(config.get('gpio_active_state', 'HIGH')).upper() != 'LOW'
                hold = float(config.get('gpio_hold_seconds', 5))
                self.gpio_controller = GPIORelayController(pin=pin_number, active_high=active_high, hold_seconds=hold)
                self.logger.info('Configured GPIO relay on pin %s', pin_number)
            except Exception as exc:  # pragma: no cover - hardware setup
                self.logger.warning(f"GPIO relay unavailable: {exc}")
                self.gpio_controller = None

    def _play_audio(self, audio_path: str) -> None:
        cmd = self.config.get('audio_player_cmd')
        if not cmd:
            self.logger.debug('No audio player configured; skipping playback.')
            return
        command = list(cmd) + [audio_path]
        self.logger.info('Playing alert audio using %s', ' '.join(command))
        _run_command(command, self.logger)

    def _enqueue_alert(
        self,
        alert: object,
        eas_message: object,
        broadcast_result: Dict[str, object],
    ) -> Dict[str, object]:
        """
        Enqueue an alert for priority-based playback via AudioPlayoutQueue.

        This method is called when playout_queue is configured. It creates a
        PlayoutItem from the alert and EAS message record, then adds it to the
        queue with FCC-compliant precedence.

        Args:
            alert: CAPAlert database model instance
            eas_message: EASMessage database record (already persisted)
            broadcast_result: Result dictionary from audio generation

        Returns:
            Updated broadcast_result with queue information
        """
        try:
            # Import here to avoid circular dependency
            from app_core.audio import PlayoutItem

            # Get next queue ID
            queue_id = self.playout_queue.get_next_queue_id()

            # Create playout item using the real database record
            item = PlayoutItem.from_alert(
                alert=alert,
                eas_message=eas_message,
                broadcast_result=broadcast_result,
                queue_id=queue_id,
            )

            # Enqueue the item
            should_interrupt = self.playout_queue.enqueue(item, check_preemption=True)

            # Update result with queue information
            broadcast_result['queued'] = True
            broadcast_result['queue_id'] = queue_id
            broadcast_result['should_interrupt'] = should_interrupt

            self.logger.info(
                'Enqueued alert %s (event=%s, precedence=%s) with queue_id=%s',
                getattr(alert, 'id', None),
                broadcast_result.get('event_code'),
                item.precedence_level,
                queue_id,
            )

            if should_interrupt:
                self.logger.warning(
                    'High-priority alert should interrupt current playback'
                )

        except Exception as exc:
            self.logger.error(f'Failed to enqueue alert: {exc}', exc_info=True)
            broadcast_result['queue_error'] = str(exc)

        return broadcast_result

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

        try:
            eom_filename, eom_bytes = self.audio_generator.build_eom_file()
        except Exception as exc:
            self.logger.warning(f"Failed to generate EOM audio: {exc}")
            eom_filename = None
            eom_bytes = None

        audio_path = os.path.join(self.audio_generator.output_dir, audio_filename)
        eom_path = os.path.join(self.audio_generator.output_dir, eom_filename) if eom_filename else None

        result.update(
            {
                "same_triggered": True,
                "event_code": event_code,
                "same_header": header,
                "audio_path": audio_path,
                "eom_path": eom_path,
                "location_codes": location_codes,
            }
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
            text_payload=text_payload,
            created_at=datetime.now(timezone.utc),
            metadata_payload={
                'event': getattr(alert, 'event', ''),
                'event_code': event_code,
                'severity': getattr(alert, 'severity', ''),
                'status': getattr(alert, 'status', ''),
                'message_type': getattr(alert, 'message_type', ''),
                'locations': location_codes,
                'eom_filename': eom_filename,
                'segments': segment_metadata,
                'has_tts': bool(segment_payload.get('tts')),
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

        # Queue mode: enqueue for later playback by AudioOutputService
        if self.playout_queue:
            return self._enqueue_alert(alert, record, result)

        # Immediate mode: play synchronously (legacy behavior)
        controller = self.gpio_controller
        if controller:
            try:  # pragma: no cover - hardware specific
                controller.activate(self.logger)
            except Exception as exc:
                self.logger.warning(f"GPIO activation failed: {exc}")
                controller = None

        try:
            self._play_audio(audio_path)
            if eom_path:
                self._play_audio(eom_path)
        finally:
            if controller:
                try:  # pragma: no cover - hardware specific
                    controller.deactivate(self.logger)
                except Exception as exc:
                    self.logger.warning(f"GPIO release failed: {exc}")

        return result


__all__ = [
    'load_eas_config',
    'EASBroadcaster',
    'EASAudioGenerator',
    'build_same_header',
    'build_eom_header',
    'samples_to_wav_bytes',
    'manual_default_same_codes',
    'PRIMARY_ORIGINATORS',
]

