"""Helpers for generating and broadcasting EAS-compatible audio output."""

from __future__ import annotations

import json
import math
import os
import re
import struct
import subprocess
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - GPIO hardware is optional and platform specific
    import RPi.GPIO as RPiGPIO  # type: ignore
except Exception:  # pragma: no cover - gracefully handle non-RPi environments
    RPiGPIO = None


SAME_EVENT_CODES: Dict[str, str] = {
    'tornado warning': 'TOR',
    'tornado watch': 'TOA',
    'severe thunderstorm warning': 'SVR',
    'severe thunderstorm watch': 'SVA',
    'flash flood warning': 'FFW',
    'flash flood watch': 'FFA',
    'flood warning': 'FLW',
    'flood watch': 'FLA',
    'amber alert': 'CAE',
    'child abduction emergency': 'CAE',
    'civil danger warning': 'CDW',
    'civil emergency message': 'CEM',
    'fire warning': 'FRW',
    'hurricane warning': 'HWW',
    'hurricane watch': 'HUA',
    'blizzard warning': 'BZW',
    'winter storm warning': 'WSW',
    'high wind warning': 'HWW',
    'ice storm warning': 'ISW',
    'snow squall warning': 'SQW',
    'dust storm warning': 'DSW',
    'radiological hazard warning': 'RHW',
    'hazardous materials warning': 'HMW',
}


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
        'call_sign': os.getenv('EAS_CALL_SIGN', 'EASNODES'),
        'output_dir': _ensure_directory(output_dir),
        'web_subdir': web_subdir,
        'audio_player_cmd': os.getenv('EAS_AUDIO_PLAYER', '').strip(),
        'attention_tone_seconds': float(os.getenv('EAS_ATTENTION_TONE_SECONDS', '8') or 8),
        'gpio_pin': os.getenv('EAS_GPIO_PIN'),
        'gpio_active_state': os.getenv('EAS_GPIO_ACTIVE_STATE', 'HIGH').upper(),
        'gpio_hold_seconds': float(os.getenv('EAS_GPIO_HOLD_SECONDS', '5') or 5),
        'sample_rate': int(os.getenv('EAS_SAMPLE_RATE', '44100') or 44100),
    }

    if config['audio_player_cmd']:
        config['audio_player_cmd'] = config['audio_player_cmd'].split()

    return config


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


def build_same_header(alert: object, payload: Dict[str, object], config: Dict[str, object],
                      location_settings: Optional[Dict[str, object]] = None) -> Tuple[str, List[str]]:
    event_name = (getattr(alert, 'event', '') or '').strip()
    event_code = SAME_EVENT_CODES.get(event_name.lower(), 'EAS')

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

    return header, formatted_locations


def _compose_message_text(alert: object) -> str:
    parts: List[str] = []
    for attr in ('headline', 'description', 'instruction'):
        value = getattr(alert, attr, '') or ''
        if value:
            parts.append(str(value).strip())
    text = '\n\n'.join(parts).strip()
    return text or "A new emergency alert has been received."


def _encode_same_bits(message: str) -> List[int]:
    bits: List[int] = []
    for char in message + '\r':
        ascii_code = ord(char)
        char_bits = [0]
        for i in range(8):
            char_bits.append((ascii_code >> i) & 1)
        char_bits.extend([1, 1])
        bits.extend(char_bits)
    return bits


def _generate_fsk_samples(bits: Sequence[int], sample_rate: int, bit_rate: float,
                          mark_freq: float, space_freq: float, amplitude: float) -> List[int]:
    samples: List[int] = []
    phase = 0.0
    delta = math.tau / sample_rate
    samples_per_bit = max(1, int(round(sample_rate / bit_rate)))

    for bit in bits:
        freq = mark_freq if bit else space_freq
        step = freq * delta
        for _ in range(samples_per_bit):
            samples.append(int(math.sin(phase) * amplitude))
            phase = (phase + step) % math.tau
    return samples


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

    def __post_init__(self) -> None:  # pragma: no cover - hardware specific
        if RPiGPIO is None:
            raise RuntimeError('RPi.GPIO not available')
        RPiGPIO.setmode(RPiGPIO.BCM)
        RPiGPIO.setup(self.pin, RPiGPIO.OUT, initial=RPiGPIO.LOW if self.active_high else RPiGPIO.HIGH)

    def activate(self, logger) -> None:  # pragma: no cover - hardware specific
        if RPiGPIO is None:
            return
        try:
            RPiGPIO.output(self.pin, RPiGPIO.HIGH if self.active_high else RPiGPIO.LOW)
            time.sleep(self.hold_seconds)
        finally:
            RPiGPIO.output(self.pin, RPiGPIO.LOW if self.active_high else RPiGPIO.HIGH)


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

        same_bits = _encode_same_bits(header)
        amplitude = 0.7 * 32767
        header_samples = _generate_fsk_samples(
            same_bits,
            sample_rate=self.sample_rate,
            bit_rate=520.83,
            mark_freq=2083.3,
            space_freq=1562.5,
            amplitude=amplitude,
        )

        samples: List[int] = []
        for _ in range(3):
            samples.extend(header_samples)
            samples.extend(_generate_silence(1.0, self.sample_rate))

        tone_duration = float(self.config.get('attention_tone_seconds', 8) or 8)
        samples.extend(_generate_tone((853.0, 960.0), tone_duration, self.sample_rate, amplitude))
        samples.extend(_generate_silence(0.5, self.sample_rate))

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
        }
        with open(text_path, 'w', encoding='utf-8') as handle:
            json.dump(text_body, handle, indent=2)
        self.logger.info(f"Wrote alert summary at {text_path}")

        message_text = _compose_message_text(alert)
        if message_text:
            preview = message_text.replace('\n', ' ')
            self.logger.debug('Alert narration preview: %s', preview[:240])

        return audio_filename, text_filename, message_text


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
        if status not in {'actual', 'test'}:
            self.logger.debug('Skipping EAS generation for status %s', status)
            return
        if message_type not in {'alert', 'update', 'test'}:
            self.logger.debug('Skipping EAS generation for message type %s', message_type)
            return

        header, location_codes = build_same_header(alert, payload, self.config, self.location_settings)
        audio_filename, text_filename, message_text = self.audio_generator.build_files(alert, payload, header, location_codes)

        audio_path = os.path.join(self.audio_generator.output_dir, audio_filename)

        if self.gpio_controller:
            try:  # pragma: no cover - hardware specific
                self.gpio_controller.activate(self.logger)
            except Exception as exc:
                self.logger.warning(f"GPIO activation failed: {exc}")

        self._play_audio(audio_path)

        record = self.model_cls(
            cap_alert_id=getattr(alert, 'id', None),
            same_header=header,
            audio_filename=audio_filename,
            text_filename=text_filename,
            created_at=datetime.now(timezone.utc),
            metadata={
                'event': getattr(alert, 'event', ''),
                'severity': getattr(alert, 'severity', ''),
                'status': getattr(alert, 'status', ''),
                'message_type': getattr(alert, 'message_type', ''),
                'locations': location_codes,
            },
        )

        try:
            self.db_session.add(record)
            self.db_session.commit()
            self.logger.info('Stored EAS message metadata for alert %s', getattr(alert, 'identifier', 'unknown'))
        except Exception as exc:
            self.logger.error(f"Failed to persist EAS message record: {exc}")
            self.db_session.rollback()


__all__ = ['load_eas_config', 'EASBroadcaster', 'build_same_header']

