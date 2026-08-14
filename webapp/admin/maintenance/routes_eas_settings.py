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

from __future__ import annotations

"""The EAS settings page and its write path."""

from flask import current_app, jsonify, request

from app_core.auth.roles import require_permission
from app_core.extensions import db

from .blueprint import maintenance_bp
from .eas_settings import _ensure_eas_settings_record


@maintenance_bp.route("/admin/eas_settings", methods=["GET", "PUT"])
@require_permission('system.configure')
def admin_eas_settings():
    """Get or update EAS broadcast settings."""
    try:
        if request.method == "GET":
            settings = _ensure_eas_settings_record()
            return jsonify({"settings": settings.to_dict()})

        # PUT - Update settings
        payload = request.get_json(silent=True) or {}

        settings = _ensure_eas_settings_record()

        # Update broadcast enabled
        if "broadcast_enabled" in payload:
            settings.broadcast_enabled = bool(payload["broadcast_enabled"])

        # Update originator
        if "originator" in payload:
            originator = str(payload["originator"]).strip().upper()[:8]
            if originator in ("WXR", "EAS", "PEP", "CIV"):
                settings.originator = originator

        # Update station ID
        if "station_id" in payload:
            station_id = str(payload["station_id"]).strip().upper()[:8]
            if station_id:
                settings.station_id = station_id

        # Update output directory
        if "output_dir" in payload:
            output_dir = str(payload["output_dir"]).strip()
            if output_dir:
                settings.output_dir = output_dir

        # Update attention tone seconds
        if "attention_tone_seconds" in payload:
            try:
                tone_sec = int(payload["attention_tone_seconds"])
                if 1 <= tone_sec <= 25:
                    settings.attention_tone_seconds = tone_sec
            except (TypeError, ValueError):
                pass

        # Update sample rate
        if "sample_rate" in payload:
            try:
                sample_rate = int(payload["sample_rate"])
                if sample_rate in (8000, 16000, 22050, 44100, 48000):
                    settings.sample_rate = sample_rate
            except (TypeError, ValueError):
                pass

        # Update audio player
        if "audio_player" in payload:
            audio_player = str(payload["audio_player"]).strip()
            if audio_player:
                settings.audio_player = audio_player

        # Update station fingerprint toggle
        if "endec_fingerprint" in payload:
            settings.endec_fingerprint = bool(payload["endec_fingerprint"])

        # Update relay narration source (OTA relay audio policy)
        if "relay_narration_source" in payload:
            _narration = str(payload["relay_narration_source"] or "auto").strip().lower()
            if _narration in ("auto", "captured", "tts"):
                settings.relay_narration_source = _narration

        # Update pre/post-alert chime profiles
        _ALLOWED_CHIMES = {"none", "bell", "beep", "three_tone", "qc2", "dtmf", "mdc1200"}
        for _field in ("pre_alert_chime", "post_alert_chime"):
            if _field in payload:
                _value = str(payload[_field] or "none").strip().lower()
                if _value in _ALLOWED_CHIMES:
                    setattr(settings, _field, _value)

        # Update pre/post-alert chime durations (clamped 0.1–10.0 seconds)
        for _field in ("pre_alert_chime_duration", "post_alert_chime_duration"):
            if _field in payload:
                try:
                    _dur = float(payload[_field])
                except (TypeError, ValueError):
                    continue
                if 0.1 <= _dur <= 10.0:
                    setattr(settings, _field, _dur)

        # Update QC-II Tone A / Tone B frequencies (clamped 50–4000 Hz)
        for _field in ("qc2_tone_a_freq", "qc2_tone_b_freq"):
            if _field in payload:
                try:
                    _freq = float(payload[_field])
                except (TypeError, ValueError):
                    continue
                if 50.0 <= _freq <= 4000.0:
                    setattr(settings, _field, _freq)

        # Update DTMF sequence: keep only valid digits (0-9, A-D, *, #).
        if "dtmf_sequence" in payload:
            _raw = str(payload["dtmf_sequence"] or "").upper()
            _filtered = "".join(c for c in _raw if c in "0123456789ABCD*#")
            settings.dtmf_sequence = _filtered[:32]

        # Update QC-II long-tone settings
        if "qc2_long_tone_enabled" in payload:
            settings.qc2_long_tone_enabled = bool(payload["qc2_long_tone_enabled"])
        if "qc2_long_tone_seconds" in payload:
            try:
                _lt_secs = float(payload["qc2_long_tone_seconds"])
            except (TypeError, ValueError):
                _lt_secs = None
            if _lt_secs is not None and 1.0 <= _lt_secs <= 120.0:
                settings.qc2_long_tone_seconds = _lt_secs

        # Update MDC1200 selective-calling settings
        if "mdc1200_unit_id" in payload:
            _raw_uid = payload["mdc1200_unit_id"]
            try:
                # Accept either decimal or "0x.." prefixed hex (Motorola CPS
                # commonly displays unit IDs in 4-digit hex).
                if isinstance(_raw_uid, str):
                    _uid = int(_raw_uid.strip(), 0)
                else:
                    _uid = int(_raw_uid)
            except (TypeError, ValueError):
                _uid = None
            if _uid is not None and 1 <= _uid <= 0xFFFF:
                settings.mdc1200_unit_id = _uid
        if "mdc1200_op_code" in payload:
            _allowed_ops = {
                "ptt_id_pre", "ptt_id_post", "emergency",
                "request_to_talk", "remote_monitor",
                "call_alert", "selective_call",
                "custom",
            }
            _op = str(payload["mdc1200_op_code"] or "ptt_id_pre").strip().lower()
            if _op in _allowed_ops:
                settings.mdc1200_op_code = _op
        if "mdc1200_target_unit_id" in payload:
            # Target ID for double-packet ops (Call Alert / Selective Call).
            # Empty string / None / 0 => clear the field, falling back to
            # single-packet emission with mdc1200_unit_id as the only ID
            # on the wire.
            _raw_tid = payload["mdc1200_target_unit_id"]
            if _raw_tid in (None, ""):
                settings.mdc1200_target_unit_id = None
            else:
                try:
                    if isinstance(_raw_tid, str):
                        _tid = int(_raw_tid.strip(), 0)
                    else:
                        _tid = int(_raw_tid)
                except (TypeError, ValueError):
                    _tid = None
                if _tid is not None:
                    if _tid == 0:
                        settings.mdc1200_target_unit_id = None
                    elif 1 <= _tid <= 0xFFFF:
                        settings.mdc1200_target_unit_id = _tid
        for _byte_field in ("mdc1200_op_code_raw", "mdc1200_arg_raw"):
            if _byte_field in payload:
                _val = payload[_byte_field]
                if _val is None or _val == "":
                    setattr(settings, _byte_field, None)
                else:
                    try:
                        # Accept either decimal or "0x.." prefixed hex.
                        if isinstance(_val, str):
                            _byte = int(_val, 0)
                        else:
                            _byte = int(_val)
                    except (TypeError, ValueError):
                        _byte = None
                    if _byte is not None and 0 <= _byte <= 0xFF:
                        setattr(settings, _byte_field, _byte)

        # Update authorized FIPS codes
        if "authorized_fips_codes" in payload:
            fips = payload["authorized_fips_codes"]
            if isinstance(fips, list):
                settings.authorized_fips_codes = [
                    str(code).strip() for code in fips if str(code).strip()
                ]
            elif isinstance(fips, str):
                settings.authorized_fips_codes = [
                    code.strip() for code in fips.split(",") if code.strip()
                ]

        # Update authorized event codes
        if "authorized_event_codes" in payload:
            events = payload["authorized_event_codes"]
            if isinstance(events, list):
                settings.authorized_event_codes = [
                    str(code).strip().upper() for code in events if str(code).strip()
                ]
            elif isinstance(events, str):
                settings.authorized_event_codes = [
                    code.strip().upper() for code in events.split(",") if code.strip()
                ]

        # Update cross-source dedup windows (minutes)
        if "cross_source_dedup_minutes" in payload:
            try:
                _cs_window = int(payload["cross_source_dedup_minutes"])
                if 1 <= _cs_window <= 1440:
                    settings.cross_source_dedup_minutes = _cs_window
            except (TypeError, ValueError):
                pass
        if "header_key_dedup_minutes" in payload:
            try:
                _hk_window = int(payload["header_key_dedup_minutes"])
                if 1 <= _hk_window <= 10080:  # up to 7 days
                    settings.header_key_dedup_minutes = _hk_window
            except (TypeError, ValueError):
                pass

        # Update the audio-ingest minimum-confidence-to-log floor (0-100;
        # 0 = disabled, log every detection regardless of confidence)
        if "min_log_confidence_percent" in payload:
            try:
                _min_conf = float(payload["min_log_confidence_percent"])
                if 0.0 <= _min_conf <= 100.0:
                    settings.min_log_confidence_percent = _min_conf
            except (TypeError, ValueError):
                pass

        # Update auto-forwarding event allowlist
        if "forwarded_event_codes" in payload:
            events = payload["forwarded_event_codes"]
            if isinstance(events, list):
                settings.forwarded_event_codes = [
                    str(code).strip().upper() for code in events if str(code).strip()
                ]
            elif isinstance(events, str):
                settings.forwarded_event_codes = [
                    code.strip().upper() for code in events.split(",") if code.strip()
                ]

        db.session.commit()

        current_app.logger.info("EAS settings updated")

        return jsonify({
            "success": True,
            "message": "EAS settings updated",
            "settings": settings.to_dict()
        })

    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Error processing EAS settings: %s", exc)
        return jsonify({"error": f"Failed to process EAS settings: {exc}"}), 500
