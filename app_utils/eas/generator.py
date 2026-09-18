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

"""EASAudioGenerator: composes SAME header, attention tone, spoken message and
EOM burst into the final broadcast WAV."""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..eas_fsk import SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ, encode_same_bits, generate_fsk_samples
from ..eas_tts import TTSEngine

from .audio_conversion import _convert_audio_to_samples, _fetch_embedded_audio
from .chime import _generate_chime
from .config import _ensure_directory
from .same_header_build import build_eom_header
from .tone_generation import (
    POST_ALERT_SIGNAL_GAP_SECONDS,
    _generate_silence,
    _generate_station_terminator_samples,
    _generate_tone,
    _mdc1200_meta_target_unit_id,
    _normalize_audio_amplitude,
    _resolve_mdc1200_op_for_position,
)
from .tts_compose import _compose_message_text
from .wav_io import samples_to_wav_bytes



def _clean_identifier(value: str) -> str:
    value = value.strip().replace(' ', '_')
    value = re.sub(r'[^A-Za-z0-9_.-]+', '_', value)
    return value[:96] or 'alert'




class EASAudioGenerator:
    def __init__(self, config: Dict[str, object], logger, db_session=None) -> None:
        self.config = config
        self.logger = logger
        # Raw SQLAlchemy session for callers outside a Flask app context
        # (CAP poller / OTA monitor) so the TTS pronunciation dictionary
        # can still be read from the database.
        self.db_session = db_session
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
        # the 3 × 0xA9 trill appended after each SAME burst.  Defaults to True.
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
        mdc1200_unit_id = int(self.config.get('mdc1200_unit_id', 1) or 1)
        mdc1200_op_code = str(self.config.get('mdc1200_op_code', 'ptt_id_pre') or 'ptt_id_pre')
        mdc1200_op_code_raw = self.config.get('mdc1200_op_code_raw', None)
        mdc1200_arg_raw = self.config.get('mdc1200_arg_raw', None)
        mdc1200_target_unit_id = self.config.get('mdc1200_target_unit_id', None)
        pre_chime_samples = _generate_chime(
            pre_chime_profile, pre_chime_duration, self.sample_rate, amplitude,
            qc2_tone_a_freq=qc2_freq_a, qc2_tone_b_freq=qc2_freq_b,
            dtmf_sequence=dtmf_seq,
            qc2_long_tone_enabled=qc2_long_tone, qc2_long_tone_seconds=qc2_long_secs,
            mdc1200_op_code=_resolve_mdc1200_op_for_position(mdc1200_op_code, 'pre'),
            mdc1200_op_code_raw=mdc1200_op_code_raw,
            mdc1200_arg_raw=mdc1200_arg_raw,
            mdc1200_unit_id=mdc1200_unit_id,
            mdc1200_target_unit_id=mdc1200_target_unit_id,
        )
        if pre_chime_samples:
            samples.extend(_generate_silence(1.0, self.sample_rate))
            samples.extend(pre_chime_samples)
            samples.extend(_generate_silence(1.0, self.sample_rate))

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

        message_text = _compose_message_text(alert, payload, db_session=self.db_session)
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
            # Narration comes from wildly different sources (cloud TTS, IPAWS-
            # embedded audio, OTA relay capture) each with its own native level
            # — none of them are mastered against the SAME/attention tone
            # amplitude above. Without this, narration can sit 15+ dB below the
            # tones (matches the RMS target build_manual_components() already
            # uses for uploaded narration, so automatic and manual broadcasts
            # are leveled the same way).
            voice_samples = _normalize_audio_amplitude(voice_samples, amplitude * 0.7)
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
            mdc1200_op_code=_resolve_mdc1200_op_for_position(mdc1200_op_code, 'post'),
            mdc1200_op_code_raw=mdc1200_op_code_raw,
            mdc1200_arg_raw=mdc1200_arg_raw,
            mdc1200_unit_id=mdc1200_unit_id,
            mdc1200_target_unit_id=mdc1200_target_unit_id,
        )
        if post_chime_samples:
            samples.extend(_generate_silence(POST_ALERT_SIGNAL_GAP_SECONDS, self.sample_rate))
            samples.extend(post_chime_samples)
            # Trailing gap after the post-chime/MDC1200 burst itself, mirroring
            # the leading gap before the pre-chime burst above. Without this,
            # a receiver's squelch/decoder tail (or a repeater's own MDC1200
            # handling) has no dead-air margin after the burst before whatever
            # comes next -- reported as "still not getting the second of dead
            # air ... after the mdc1200 after the EOM."
            samples.extend(_generate_silence(POST_ALERT_SIGNAL_GAP_SECONDS, self.sample_rate))
        # No unconditional trailing silence tail when NO post-chime is
        # configured: the composite audio ends at the true end of content
        # (EOM). The 1-second post-broadcast relay hold is a program-level
        # GPIO timing concern, not audio content -- see
        # BROADCAST_LEAD_OUT_SECONDS and EASBroadcaster.handle_alert().
        # Baking it into the audio would freeze it into every stored/
        # archived/resent copy (including Icecast listeners and FCC-report
        # exports) and make it impossible to change without regenerating
        # every alert's audio.

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
        narration_upload_samples: Optional[List[int]] = None,
        pre_alert_samples: Optional[List[int]] = None,
        post_alert_samples: Optional[List[int]] = None,
        lead_announcement_samples: Optional[List[int]] = None,
        trail_announcement_samples: Optional[List[int]] = None,
    ) -> Dict[str, object]:
        # Extract event code from SAME header to detect RWT (Required Weekly Test)
        # Header format: ZCZC-ORG-EEE-PSSCCC-... where EEE is the event code
        event_code = None
        if header:
            parts = header.split('-')
            if len(parts) > 2:
                event_code = parts[2].strip().upper()

        # FCC 47 CFR §11.61(a)(1)(ii): the Required Weekly Test does not carry
        # the two-tone Attention Signal and does not include voice narration.
        # The RWT is SAME header + EOM only — no exceptions, no override.
        if event_code == 'RWT':
            include_tts = False
            tone_profile = 'none'

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

        message_text = _compose_message_text(alert, db_session=self.db_session)
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

        # Normalize uploaded pre/post alert audio
        norm_pre_alert = (
            _normalize_audio_amplitude(pre_alert_samples, amplitude * 0.7)
            if pre_alert_samples else []
        )
        norm_post_alert = (
            _normalize_audio_amplitude(post_alert_samples, amplitude * 0.7)
            if post_alert_samples else []
        )

        # Station announcements that bracket the *entire* test transmission
        # (e.g. "This station is conducting a test of the Emergency Alert
        # System" / "This concludes this test"). Unlike pre_alert_samples /
        # post_alert_samples above -- which sit between the SAME header and
        # the EOM, bracketing the narration segment -- these play outside the
        # encoded SAME burst entirely: before the lead-in silence and after
        # the EOM's trailing silence. That keeps them clear of the actual
        # FSK-encoded portion of the test per FCC 47 CFR §11.61(a)(1)(ii).
        norm_lead_announcement = (
            _normalize_audio_amplitude(lead_announcement_samples, amplitude * 0.7)
            if lead_announcement_samples else []
        )
        norm_trail_announcement = (
            _normalize_audio_amplitude(trail_announcement_samples, amplitude * 0.7)
            if trail_announcement_samples else []
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
        mdc1200_unit_id = int(self.config.get('mdc1200_unit_id', 1) or 1)
        mdc1200_op_code = str(self.config.get('mdc1200_op_code', 'ptt_id_pre') or 'ptt_id_pre')
        mdc1200_op_code_raw = self.config.get('mdc1200_op_code_raw', None)
        mdc1200_arg_raw = self.config.get('mdc1200_arg_raw', None)
        mdc1200_target_unit_id = self.config.get('mdc1200_target_unit_id', None)
        pre_chime_samples_list = _generate_chime(
            pre_chime_profile, pre_chime_duration, self.sample_rate, amplitude,
            qc2_tone_a_freq=qc2_freq_a, qc2_tone_b_freq=qc2_freq_b,
            dtmf_sequence=dtmf_seq,
            qc2_long_tone_enabled=qc2_long_tone, qc2_long_tone_seconds=qc2_long_secs,
            mdc1200_op_code=_resolve_mdc1200_op_for_position(mdc1200_op_code, 'pre'),
            mdc1200_op_code_raw=mdc1200_op_code_raw,
            mdc1200_arg_raw=mdc1200_arg_raw,
            mdc1200_unit_id=mdc1200_unit_id,
            mdc1200_target_unit_id=mdc1200_target_unit_id,
        )
        post_chime_profile = self.config.get('post_alert_chime', 'none')
        post_chime_duration = float(self.config.get('post_alert_chime_duration', 2.0) or 2.0)
        post_chime_samples_list = _generate_chime(
            post_chime_profile, post_chime_duration, self.sample_rate, amplitude,
            qc2_tone_a_freq=qc2_freq_a, qc2_tone_b_freq=qc2_freq_b,
            dtmf_sequence=dtmf_seq,
            qc2_long_tone_enabled=qc2_long_tone, qc2_long_tone_seconds=qc2_long_secs,
            mdc1200_op_code=_resolve_mdc1200_op_for_position(mdc1200_op_code, 'post'),
            mdc1200_op_code_raw=mdc1200_op_code_raw,
            mdc1200_arg_raw=mdc1200_arg_raw,
            mdc1200_unit_id=mdc1200_unit_id,
            mdc1200_target_unit_id=mdc1200_target_unit_id,
        )
        chime_separator = _generate_silence(1.0, self.sample_rate)

        composite_samples: List[int] = []
        if norm_lead_announcement:
            composite_samples.extend(norm_lead_announcement)
        if pre_chime_samples_list:
            composite_samples.extend(chime_separator)
            composite_samples.extend(pre_chime_samples_list)
            composite_samples.extend(chime_separator)
        # No unconditional lead-in silence here when no pre-chime is
        # configured: the 1-second relay pre-roll is a program-level GPIO
        # timing concern (BROADCAST_LEAD_IN_SECONDS, applied by every
        # caller that drives the airchain), not audio content -- baking it
        # into the WAV would freeze it into every stored/archived/resent
        # copy and make it impossible to adjust without regenerating audio.
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
            composite_samples.extend(_generate_silence(POST_ALERT_SIGNAL_GAP_SECONDS, self.sample_rate))
            composite_samples.extend(post_chime_samples_list)
            # Trailing gap after the post-chime/MDC1200 burst itself, mirroring
            # the leading gap before the pre-chime burst above -- see the
            # matching comment in build_files().
            composite_samples.extend(_generate_silence(POST_ALERT_SIGNAL_GAP_SECONDS, self.sample_rate))
        # No unconditional trailing silence tail here when no post-chime is
        # configured: the 1-second relay hold past end-of-message is a
        # program-level GPIO timing concern (BROADCAST_LEAD_OUT_SECONDS),
        # not audio content -- see the note above the lead-in silence removal.
        if norm_trail_announcement:
            composite_samples.extend(norm_trail_announcement)

        pre_chime_profile_norm = str(pre_chime_profile or 'none').lower()
        post_chime_profile_norm = str(post_chime_profile or 'none').lower()

        signaling_meta: Dict[str, Any] = {
            'pre_chime': {
                'profile': pre_chime_profile_norm,
                'duration_seconds': float(pre_chime_duration) if pre_chime_profile_norm != 'none' else 0.0,
                'used': bool(pre_chime_samples_list),
            },
            'post_chime': {
                'profile': post_chime_profile_norm,
                'duration_seconds': float(post_chime_duration) if post_chime_profile_norm != 'none' else 0.0,
                'used': bool(post_chime_samples_list),
            },
        }
        if pre_chime_profile_norm == 'mdc1200' or post_chime_profile_norm == 'mdc1200':
            signaling_meta['mdc1200'] = {
                'unit_id': int(mdc1200_unit_id or 0),
                'target_unit_id': _mdc1200_meta_target_unit_id(
                    mdc1200_op_code,
                    mdc1200_op_code_raw,
                    mdc1200_arg_raw,
                    mdc1200_target_unit_id,
                ),
                'op_code': mdc1200_op_code,
                'op_code_raw': (
                    int(mdc1200_op_code_raw)
                    if mdc1200_op_code_raw is not None else None
                ),
                'arg_raw': (
                    int(mdc1200_arg_raw)
                    if mdc1200_arg_raw is not None else None
                ),
                'pre_op_code': _resolve_mdc1200_op_for_position(mdc1200_op_code, 'pre'),
                'post_op_code': _resolve_mdc1200_op_for_position(mdc1200_op_code, 'post'),
            }
        if pre_chime_profile_norm == 'dtmf' or post_chime_profile_norm == 'dtmf':
            signaling_meta['dtmf_sequence'] = dtmf_seq
        if pre_chime_profile_norm == 'qc2' or post_chime_profile_norm == 'qc2':
            signaling_meta['qc2'] = {
                'tone_a_freq': qc2_freq_a,
                'tone_b_freq': qc2_freq_b,
                'long_tone_enabled': bool(qc2_long_tone),
                'long_tone_seconds': float(qc2_long_secs),
            }

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
            'lead_announcement_samples': norm_lead_announcement,
            'trail_announcement_samples': norm_trail_announcement,
            'pre_chime_samples': pre_chime_samples_list,
            'post_chime_samples': post_chime_samples_list,
            'pre_chime_profile': pre_chime_profile_norm,
            'post_chime_profile': post_chime_profile_norm,
            'signaling': signaling_meta,
            'composite_samples': composite_samples,
            'sample_rate': self.sample_rate,
        }
