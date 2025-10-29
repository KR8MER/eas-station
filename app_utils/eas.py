"""Helpers for generating and broadcasting EAS-compatible audio output."""

from __future__ import annotations

import audioop
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
from fractions import Fraction
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - GPIO hardware is optional and platform specific
    import RPi.GPIO as RPiGPIO  # type: ignore
except Exception:  # pragma: no cover - gracefully handle non-RPi environments
    RPiGPIO = None


try:  # pragma: no cover - optional dependency for Azure TTS
    import azure.cognitiveservices.speech as azure_speech  # type: ignore
except Exception:  # pragma: no cover - keep optional
    azure_speech = None

from app_utils.event_codes import resolve_event_code

MANUAL_FIPS_ENV_TOKENS = {'ALL', 'ANY', 'US', 'USA', '*'}

SAME_BAUD = Fraction(3125, 6)  # 520.83… baud (520 5/6 per §11.31)
SAME_MARK_FREQ = float(SAME_BAUD * 4)  # 2083 1/3 Hz
SAME_SPACE_FREQ = float(SAME_BAUD * 3)  # 1562.5 Hz
SAME_PREAMBLE_BYTE = 0xAB
SAME_PREAMBLE_REPETITIONS = 16


def _clean_identifier(value: str) -> str:
    value = value.strip().replace(' ', '_')
    value = re.sub(r'[^A-Za-z0-9_.-]+', '_', value)
    return value[:96] or 'alert'


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
        'sample_rate': int(os.getenv('EAS_SAMPLE_RATE', '44100') or 44100),
        'tts_provider': (os.getenv('EAS_TTS_PROVIDER') or '').strip().lower(),
        'azure_speech_key': os.getenv('AZURE_SPEECH_KEY'),
        'azure_speech_region': os.getenv('AZURE_SPEECH_REGION'),
        'azure_speech_voice': os.getenv('AZURE_SPEECH_VOICE', 'en-US-AriaNeural'),
        'azure_speech_sample_rate': int(os.getenv('AZURE_SPEECH_SAMPLE_RATE', '24000') or 24000),
    }

    if config['audio_player_cmd']:
        config['audio_player_cmd'] = config['audio_player_cmd'].split()

    return config


P_DIGIT_MEANINGS = {
    '0': 'Entire area',
    '1': 'Northwest portion',
    '2': 'North central portion',
    '3': 'Northeast portion',
    '4': 'West central portion',
    '5': 'Central portion',
    '6': 'East central portion',
    '7': 'Southwest portion',
    '8': 'South central portion',
    '9': 'Southeast portion',
}

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

    if not same_codes and location_settings:
        fallback_same = location_settings.get('same_codes') or []
        same_codes = [str(code).strip() for code in fallback_same if code]

    if not same_codes and location_settings:
        zone_codes = location_settings.get('zone_codes') or []
        same_codes = [code.replace('O', '').upper().replace(' ', '') for code in zone_codes]

    formatted_locations = []
    for code in same_codes:
        digits = ''.join(ch for ch in code if ch.isdigit())
        if digits:
            formatted_locations.append(digits.zfill(6))

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


def _same_preamble_bits(repeats: int = SAME_PREAMBLE_REPETITIONS) -> List[int]:
    """Encode the SAME preamble (0xAB) bytes with start/stop framing."""

    bits: List[int] = []
    repeats = max(1, int(repeats))
    for _ in range(repeats):
        bits.append(0)
        for i in range(8):
            bits.append((SAME_PREAMBLE_BYTE >> i) & 1)
        bits.append(1)

    return bits


def _encode_same_bits(message: str, *, include_preamble: bool = False) -> List[int]:
    """Encode an ASCII SAME header using NRZ AFSK framing.

    Section 11.31 specifies 520 5/6 baud transmission with one start bit (0),
    seven data bits sent least-significant-bit first, a null eighth bit, and a
    single stop bit (1). The payload terminates with a carriage return.
    """

    bits: List[int] = []
    if include_preamble:
        bits.extend(_same_preamble_bits())
    for char in message + '\r':
        ascii_code = ord(char) & 0x7F

        char_bits: List[int] = [0]
        for i in range(7):
            char_bits.append((ascii_code >> i) & 1)

        # Null eighth bit per §11.31(a)(1)
        char_bits.append(0)

        # Stop bit
        char_bits.append(1)

        bits.extend(char_bits)

    return bits


def _generate_fsk_samples(
    bits: Sequence[int],
    sample_rate: int,
    bit_rate: float,
    mark_freq: float,
    space_freq: float,
    amplitude: float,
) -> List[int]:
    """Render NRZ AFSK samples while preserving the fractional bit timing."""

    samples: List[int] = []
    phase = 0.0
    delta = math.tau / sample_rate
    samples_per_bit = sample_rate / bit_rate
    carry = 0.0

    for bit in bits:
        freq = mark_freq if bit else space_freq
        step = freq * delta
        total = samples_per_bit + carry
        sample_count = int(total)
        if sample_count <= 0:
            sample_count = 1
        carry = total - sample_count

        for _ in range(sample_count):
            samples.append(int(math.sin(phase) * amplitude))
            phase = (phase + step) % math.tau

    return samples


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


@dataclass
class GPIORelayController:
    pin: int
    active_high: bool
    hold_seconds: float
    activated_at: Optional[float] = field(default=None, init=False)

    def __post_init__(self) -> None:  # pragma: no cover - hardware specific
        if RPiGPIO is None:
            raise RuntimeError('RPi.GPIO not available')
        self._active_level = RPiGPIO.HIGH if self.active_high else RPiGPIO.LOW
        self._resting_level = RPiGPIO.LOW if self.active_high else RPiGPIO.HIGH
        RPiGPIO.setmode(RPiGPIO.BCM)
        RPiGPIO.setup(self.pin, RPiGPIO.OUT, initial=self._resting_level)

    def activate(self, logger) -> None:  # pragma: no cover - hardware specific
        if RPiGPIO is None:
            return
        RPiGPIO.output(self.pin, self._active_level)
        self.activated_at = time.monotonic()
        if logger:
            logger.debug('Activated GPIO relay on pin %s', self.pin)

    def deactivate(self, logger) -> None:  # pragma: no cover - hardware specific
        if RPiGPIO is None:
            return
        if self.activated_at is not None:
            elapsed = time.monotonic() - self.activated_at
            remaining = max(0.0, self.hold_seconds - elapsed)
            if remaining > 0:
                time.sleep(remaining)
        RPiGPIO.output(self.pin, self._resting_level)
        self.activated_at = None
        if logger:
            logger.debug('Released GPIO relay on pin %s', self.pin)


class EASAudioGenerator:
    def __init__(self, config: Dict[str, object], logger) -> None:
        self.config = config
        self.logger = logger
        self.sample_rate = int(config.get('sample_rate', 44100))
        self.output_dir = str(config.get('output_dir'))
        _ensure_directory(self.output_dir)

    def build_files(self, alert: object, payload: Dict[str, object], header: str,
                    location_codes: List[str]) -> Tuple[str, str, str]:
        identifier = getattr(alert, 'identifier', None) or payload.get('identifier') or 'alert'
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        base_name = _clean_identifier(f"{identifier}_{timestamp}")
        audio_filename = f"{base_name}.wav"
        text_filename = f"{base_name}.txt"

        audio_path = os.path.join(self.output_dir, audio_filename)
        text_path = os.path.join(self.output_dir, text_filename)

        same_bits = _encode_same_bits(header, include_preamble=True)
        amplitude = 0.7 * 32767
        header_samples = _generate_fsk_samples(
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
            samples.extend(_generate_silence(1.0, self.sample_rate))

        tone_duration = float(self.config.get('attention_tone_seconds', 8) or 8)
        samples.extend(_generate_tone((853.0, 960.0), tone_duration, self.sample_rate, amplitude))
        samples.extend(_generate_silence(1.0, self.sample_rate))

        message_text = _compose_message_text(alert)
        if message_text:
            preview = message_text.replace('\n', ' ')
            self.logger.debug('Alert narration preview: %s', preview[:240])

        voice_samples = self._maybe_generate_voiceover(message_text)
        if voice_samples:
            samples.extend(_generate_silence(1.0, self.sample_rate))
            samples.extend(voice_samples)

        samples.extend(_generate_silence(1.0, self.sample_rate))

        _write_wave_file(audio_path, samples, self.sample_rate)
        self.logger.info(f"Generated SAME audio at {audio_path}")

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

        return audio_filename, text_filename, message_text

    def build_eom_file(self) -> str:
        header = build_eom_header(self.config)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        base_name = _clean_identifier(f"eom_{timestamp}")
        audio_filename = f"{base_name}.wav"
        audio_path = os.path.join(self.output_dir, audio_filename)

        same_bits = _encode_same_bits(header, include_preamble=True)
        amplitude = 0.7 * 32767
        header_samples = _generate_fsk_samples(
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

        _write_wave_file(audio_path, samples, self.sample_rate)
        if self.logger:
            self.logger.debug('Generated EOM audio at %s', audio_path)

        return audio_filename

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
        same_bits = _encode_same_bits(header, include_preamble=True)
        header_samples = _generate_fsk_samples(
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
        provider = (self.config.get('tts_provider') or '').strip().lower()
        if include_tts:
            voiceover = self._maybe_generate_voiceover(message_text)
            if voiceover:
                tts_samples.extend(voiceover)
            else:
                if provider == 'azure':
                    tts_warning = 'Azure Speech is configured but synthesis failed.'
                else:
                    tts_warning = 'No TTS provider configured; supply narration manually.'

        eom_header = build_eom_header(self.config)
        eom_bits = _encode_same_bits(eom_header, include_preamble=True)
        eom_header_samples = _generate_fsk_samples(
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

    def _maybe_generate_voiceover(self, text: str) -> Optional[List[int]]:
        provider = (self.config.get('tts_provider') or '').strip().lower()
        if provider != 'azure':
            return None

        if not text.strip():
            return None

        if azure_speech is None:
            if self.logger:
                self.logger.warning('Azure Speech SDK not installed; skipping TTS voiceover.')
            return None

        key = (self.config.get('azure_speech_key') or '').strip()
        region = (self.config.get('azure_speech_region') or '').strip()
        if not key or not region:
            if self.logger:
                self.logger.warning('Azure Speech credentials not configured; skipping TTS voiceover.')
            return None

        voice = (self.config.get('azure_speech_voice') or 'en-US-AriaNeural').strip()
        target_rate = int(self.config.get('sample_rate', 44100) or 44100)
        desired_source_rate = int(self.config.get('azure_speech_sample_rate', target_rate) or target_rate)

        try:
            speech_config = azure_speech.SpeechConfig(subscription=key, region=region)
            speech_config.speech_synthesis_voice_name = voice
            format_map = {
                16000: azure_speech.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm,
                22050: azure_speech.SpeechSynthesisOutputFormat.Riff22050Hz16BitMonoPcm,
                24000: azure_speech.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm,
                44100: azure_speech.SpeechSynthesisOutputFormat.Riff44100Hz16BitMonoPcm,
            }
            selected_format = format_map.get(desired_source_rate, azure_speech.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
            speech_config.set_speech_synthesis_output_format(selected_format)

            audio_config = azure_speech.audio.AudioOutputConfig(use_default_speaker=False)
            synthesizer = azure_speech.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
            result = synthesizer.speak_text(text)
        except Exception as exc:  # pragma: no cover - network/service specific
            if self.logger:
                self.logger.error(f"Azure speech synthesis failed: {exc}")
            return None

        reason = getattr(azure_speech, 'ResultReason', None)
        if reason and result.reason != reason.SynthesizingAudioCompleted:
            if self.logger:
                self.logger.error('Azure speech synthesis did not complete successfully: %s', result.reason)
            return None

        audio_bytes = getattr(result, 'audio_data', None)
        if not audio_bytes:
            if self.logger:
                self.logger.warning('Azure speech synthesis returned no audio data.')
            return None

        try:
            with wave.open(io.BytesIO(audio_bytes), 'rb') as wav_data:
                raw_frames = wav_data.readframes(wav_data.getnframes())
                sample_width = wav_data.getsampwidth()
                channels = wav_data.getnchannels()
                source_rate = wav_data.getframerate()

            if sample_width != 2:
                raw_frames = audioop.lin2lin(raw_frames, sample_width, 2)
            if channels != 1:
                raw_frames = audioop.tomono(raw_frames, 2, 0.5, 0.5)
            if source_rate != target_rate:
                raw_frames, _ = audioop.ratecv(raw_frames, 2, 1, source_rate, target_rate, None)

            sample_count = len(raw_frames) // 2
            samples = struct.unpack('<' + 'h' * sample_count, raw_frames[: sample_count * 2])
            if self.logger:
                self.logger.info('Appended Azure voiceover using voice %s', voice)
            return list(samples)
        except Exception as exc:  # pragma: no cover - audio decoding errors
            if self.logger:
                self.logger.error(f"Failed to decode Azure speech audio: {exc}")
            return None


class EASBroadcaster:
    def __init__(self, db_session, model_cls, config: Dict[str, object], logger, location_settings: Optional[Dict[str, object]] = None) -> None:
        self.db_session = db_session
        self.model_cls = model_cls
        self.config = config
        self.logger = logger
        self.location_settings = location_settings or {}
        self.enabled = bool(config.get('enabled'))
        self.audio_generator = EASAudioGenerator(config, logger)
        self.gpio_controller: Optional[GPIORelayController] = None

        if not self.enabled:
            self.logger.info('EAS broadcasting is disabled via configuration.')
        else:
            self.logger.info('EAS broadcasting enabled with output directory %s', self.audio_generator.output_dir)

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

    def handle_alert(self, alert: object, payload: Dict[str, object]) -> None:
        if not self.enabled or not alert:
            return

        status = (getattr(alert, 'status', '') or '').lower()
        message_type = (payload.get('message_type') or getattr(alert, 'message_type', '') or '').lower()
        event_name = (getattr(alert, 'event', '') or payload.get('event') or '').strip().lower()

        suppressed_events = {
            'special weather statement',
            'dense fog advisory',
        }

        if status not in {'actual', 'test'}:
            self.logger.debug('Skipping EAS generation for status %s', status)
            return
        if message_type not in {'alert', 'update', 'test'}:
            self.logger.debug('Skipping EAS generation for message type %s', message_type)
            return
        if event_name in suppressed_events:
            pretty_event = getattr(alert, 'event', '') or payload.get('event') or event_name
            self.logger.info('Skipping EAS generation for event %s', pretty_event)
            return

        try:
            header, location_codes, event_code = build_same_header(
                alert,
                payload,
                self.config,
                self.location_settings,
            )
        except ValueError as exc:
            self.logger.info('Skipping EAS generation: %s', exc)
            return

        audio_filename, text_filename, message_text = self.audio_generator.build_files(alert, payload, header, location_codes)

        try:
            eom_filename = self.audio_generator.build_eom_file()
        except Exception as exc:
            self.logger.warning(f"Failed to generate EOM audio: {exc}")
            eom_filename = None

        audio_path = os.path.join(self.audio_generator.output_dir, audio_filename)
        eom_path = os.path.join(self.audio_generator.output_dir, eom_filename) if eom_filename else None

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

        record = self.model_cls(
            cap_alert_id=getattr(alert, 'id', None),
            same_header=header,
            audio_filename=audio_filename,
            text_filename=text_filename,
            created_at=datetime.now(timezone.utc),
            metadata_payload={
                'event': getattr(alert, 'event', ''),
                'event_code': event_code,
                'severity': getattr(alert, 'severity', ''),
                'status': getattr(alert, 'status', ''),
                'message_type': getattr(alert, 'message_type', ''),
                'locations': location_codes,
                'eom_filename': eom_filename,
            },
        )

        try:
            self.db_session.add(record)
            self.db_session.commit()
            self.logger.info('Stored EAS message metadata for alert %s', getattr(alert, 'identifier', 'unknown'))
        except Exception as exc:
            self.logger.error(f"Failed to persist EAS message record: {exc}")
            self.db_session.rollback()


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

