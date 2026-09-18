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

"""Helpers for generating and broadcasting EAS-compatible audio output.

This package was a single 4,246-line ``app_utils/eas.py``. This ``__init__``
is the compatibility shim: every name the module exposed to the rest of the
tree keeps resolving from ``app_utils.eas``.

Layout::

    indicators             Redis-backed broadcast/incoming-alert indicator state
    config                 load_eas_config()
    same_header_constants  static SAME/NRSC-4-B lookup tables
    same_header_decode     decode_county_originator, describe_same_header, score_decode_confidence
    same_header_build      build_same_header, build_eom_header
    tts_normalize          ALL-CAPS CAP text -> sentence-case TTS text
    tts_compose            the final spoken message text
    tone_generation        attention tones, MDC1200 bursts (not the chime -- see chime)
    chime                  the alert-attention chime (bell/beep/three-tone/QC-II/DTMF/MDC1200)
    wav_io                 PCM samples <-> WAV bytes
    broadcast_pid          the in-flight playback subprocess's PID/EOM markers
    audio_conversion       embedded/IPAWS audio -> PCM samples
    generator              EASAudioGenerator
    broadcaster            EASBroadcaster

Dependencies run one way::

    indicators, same_header_constants, wav_io, broadcast_pid, chime  leaves
    config                 -> indicators
    same_header_decode     -> same_header_constants
    same_header_build      -> same_header_constants
    tts_compose            -> same_header_constants, tts_normalize
    generator              -> audio_conversion, chime, config, same_header_build,
                              tone_generation, tts_compose, wav_io
    broadcaster            -> broadcast_pid, generator, indicators,
                              same_header_build, wav_io

**`generator.py` (848) and `broadcaster.py` (489) are known exceptions** to
the 400-line guidance -- each is one god-class (`EASAudioGenerator`,
`EASBroadcaster`). Module-level splitting cannot shrink a single class;
bringing them under the cap needs collaborators extracted from the class
bodies, which is a behavioural change requiring its own characterization
pass. Tracked as a follow-up in
``docs/development/LARGE_FILE_REFACTOR_PLAN.md``. `config.py` (408) is
dominated by one 369-line function (`load_eas_config`) for the same reason.
"""

import subprocess  # noqa: F401 - re-exported so tests can patch app_utils.eas.subprocess
import time  # noqa: F401 - re-exported so tests can patch app_utils.eas.time.sleep

from .indicators import (
    BROADCAST_LEAD_IN_SECONDS,
    BROADCAST_LEAD_OUT_SECONDS,
    _BROADCAST_STATE_GRACE_SECONDS,
    _BROADCAST_STATE_KEY,
    _INCOMING_STATE_KEY,
    _INDICATOR_CHANNEL,
    _get_oled_enabled_status,
    _notify_indicator_change,
    clear_broadcast_active,
    clear_incoming_alert,
    get_broadcast_state,
    get_incoming_alert_state,
    set_broadcast_active,
    set_incoming_alert,
)
from .config import (
    MANUAL_FIPS_ENV_TOKENS,
    _ensure_directory,
    load_eas_config,
)
from .same_header_constants import (
    COUNTY_ABBREVIATIONS,
    NRSC4B_BAUD_RATE_FRAC,
    NRSC4B_BURST_COUNT,
    NRSC4B_CENTER_FREQ_HZ,
    NRSC4B_MARK_FREQ_HZ,
    NRSC4B_MAX_LOCATIONS,
    NRSC4B_PREAMBLE_BYTE,
    NRSC4B_PREAMBLE_COUNT,
    NRSC4B_SPACE_FREQ_HZ,
    NRSC4B_STATION_ID_MAX_LEN,
    NRSC4B_VALID_ORIGINATORS,
    NRSC4B_VALID_PURGE_TIMES,
    ORIGINATOR_DESCRIPTIONS,
    PRIMARY_ORIGINATORS,
    P_DIGIT_MEANINGS,
    SAME_HEADER_FIELD_DESCRIPTIONS,
    _NRSC4B_FIELD_FLAGS,
)
from .same_header_decode import (
    decode_county_originator,
    describe_same_header,
    score_decode_confidence,
)
from .same_header_build import (
    _collect_event_code_candidates,
    _duration_code,
    _julian_time,
    _normalise_same_codes,
    build_eom_header,
    build_same_header,
)
from .tts_normalize import (
    _load_pronunciation_rules,
    _normalize_text_for_tts,
)
from .tts_compose import (
    _compose_message_text,
    _strip_awips_identifier,
    manual_default_same_codes,
)
from .chime import _DTMF_FREQUENCIES, _generate_chime
from .tone_generation import (
    ALERT_CHIME_PROFILES,
    POST_ALERT_SIGNAL_GAP_SECONDS,
    _generate_silence,
    _generate_station_terminator_samples,
    _generate_tone,
    _mdc1200_meta_target_unit_id,
    _normalize_audio_amplitude,
    _resolve_mdc1200_op_for_position,
)
from .wav_io import (
    _wav_duration_seconds,
    _write_wave_file,
    samples_to_wav_bytes,
    truncate_wav_to_max_seconds,
)
from .broadcast_pid import (
    _BROADCAST_EOM_KEY,
    _BROADCAST_PID_KEY,
    _BROADCAST_PID_TTL,
    _clear_broadcast_pid,
    _publish_broadcast_pid,
    _run_command,
    get_broadcast_eom_audio,
    get_broadcast_pid,
    play_broadcast_audio,
)
from .audio_conversion import (
    EMBEDDED_AUDIO_DOWNLOAD_TIMEOUT,
    EMBEDDED_AUDIO_STREAMING_TIMEOUT,
    _convert_audio_to_samples,
    _fetch_embedded_audio,
    _resample_audio,
    convert_audio_to_samples,
)
from .generator import (
    EASAudioGenerator,
    _clean_identifier,
)
from .broadcaster import (
    EASBroadcaster,
)

__all__ = [
    'load_eas_config',
    'EASBroadcaster',
    'EASAudioGenerator',
    'build_same_header',
    'build_eom_header',
    'describe_same_header',
    'score_decode_confidence',
    'samples_to_wav_bytes',
    'manual_default_same_codes',
    'convert_audio_to_samples',
    'PRIMARY_ORIGINATORS',
    'set_broadcast_active',
    'clear_broadcast_active',
    'get_broadcast_state',
    'get_broadcast_pid',
    'get_broadcast_eom_audio',
    'play_broadcast_audio',
]
