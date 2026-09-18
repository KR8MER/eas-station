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

"""Loading app_config.json and .env into the EAS runtime config dict."""

import os
from typing import Dict, List, Optional

from ..gpio import load_gpio_behavior_matrix_from_db, load_gpio_pin_configs_from_db
from .indicators import _get_oled_enabled_status



MANUAL_FIPS_ENV_TOKENS = {'ALL', 'ANY', 'US', 'USA', '*'}




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
    db_mdc1200_unit_id = None
    db_mdc1200_op_code = None
    db_mdc1200_op_code_raw = None
    db_mdc1200_arg_raw = None
    db_mdc1200_target_unit_id = None
    db_forwarded_event_codes: List[str] = []
    db_cross_source_dedup_minutes = None
    db_header_key_dedup_minutes = None
    db_min_log_confidence_percent = None
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
            db_mdc1200_unit_id = getattr(eas_settings, 'mdc1200_unit_id', None)
            db_mdc1200_op_code = getattr(eas_settings, 'mdc1200_op_code', None)
            db_mdc1200_op_code_raw = getattr(eas_settings, 'mdc1200_op_code_raw', None)
            db_mdc1200_arg_raw = getattr(eas_settings, 'mdc1200_arg_raw', None)
            db_mdc1200_target_unit_id = getattr(eas_settings, 'mdc1200_target_unit_id', None)
            db_forwarded_event_codes = list(eas_settings.forwarded_event_codes or [])
            db_cross_source_dedup_minutes = getattr(eas_settings, 'cross_source_dedup_minutes', None)
            db_header_key_dedup_minutes = getattr(eas_settings, 'header_key_dedup_minutes', None)
            db_min_log_confidence_percent = getattr(eas_settings, 'min_log_confidence_percent', None)
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
                db_mdc1200_unit_id = getattr(eas_settings, 'mdc1200_unit_id', None)
                db_mdc1200_op_code = getattr(eas_settings, 'mdc1200_op_code', None)
                db_mdc1200_op_code_raw = getattr(eas_settings, 'mdc1200_op_code_raw', None)
                db_mdc1200_arg_raw = getattr(eas_settings, 'mdc1200_arg_raw', None)
                db_mdc1200_target_unit_id = getattr(eas_settings, 'mdc1200_target_unit_id', None)
                db_forwarded_event_codes = list(eas_settings.forwarded_event_codes or [])
                db_cross_source_dedup_minutes = getattr(eas_settings, 'cross_source_dedup_minutes', None)
                db_header_key_dedup_minutes = getattr(eas_settings, 'header_key_dedup_minutes', None)
                db_min_log_confidence_percent = getattr(eas_settings, 'min_log_confidence_percent', None)
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
        'mdc1200_unit_id': (
            int(os.getenv('EAS_MDC1200_UNIT_ID'), 0)
            if os.getenv('EAS_MDC1200_UNIT_ID')
            else int(db_mdc1200_unit_id if db_mdc1200_unit_id is not None else 1)
        ),
        'mdc1200_op_code': (
            os.getenv('EAS_MDC1200_OP_CODE')
            or (db_mdc1200_op_code if db_mdc1200_op_code else 'ptt_id_pre')
        ),
        'mdc1200_op_code_raw': (
            int(os.getenv('EAS_MDC1200_OP_CODE_RAW'), 0)
            if os.getenv('EAS_MDC1200_OP_CODE_RAW')
            else (db_mdc1200_op_code_raw if db_mdc1200_op_code_raw is not None else None)
        ),
        'mdc1200_arg_raw': (
            int(os.getenv('EAS_MDC1200_ARG_RAW'), 0)
            if os.getenv('EAS_MDC1200_ARG_RAW')
            else (db_mdc1200_arg_raw if db_mdc1200_arg_raw is not None else None)
        ),
        'mdc1200_target_unit_id': (
            int(os.getenv('EAS_MDC1200_TARGET_UNIT_ID'), 0)
            if os.getenv('EAS_MDC1200_TARGET_UNIT_ID')
            else (
                int(db_mdc1200_target_unit_id)
                if db_mdc1200_target_unit_id is not None else None
            )
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
        'cross_source_dedup_minutes': (
            int(db_cross_source_dedup_minutes) if db_cross_source_dedup_minutes is not None else 15
        ),
        'header_key_dedup_minutes': (
            int(db_header_key_dedup_minutes) if db_header_key_dedup_minutes is not None else 24 * 60
        ),
        'min_log_confidence_percent': (
            float(db_min_log_confidence_percent) if db_min_log_confidence_percent is not None else 0.0
        ),
    }

    if config['audio_player_cmd']:
        config['audio_player_cmd'] = config['audio_player_cmd'].split()

    return config
