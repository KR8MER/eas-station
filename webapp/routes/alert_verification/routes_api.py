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

"""The small JSON endpoints: progress, header decode, decode audio."""

from flask import Flask, abort, jsonify, request, send_file

from app_core.auth.decorators import require_auth, require_role
from app_core.models import EASDecodedAudio
import io
from app_utils.eas_decode import build_plain_language_summary
from app_utils.eas import describe_same_header
from app_utils.fips_codes import get_extended_same_lookup

from .progress import ProgressTracker


def register(app: Flask, logger):
    """Attach this module's routes, recreating register's closure.

    ``route_logger`` is rebuilt here rather than passed in, so each
    handler closes over exactly what it closed over in the single-file
    module.
    """
    route_logger = logger.getChild('alert_verification')

    @app.route("/admin/alert-verification/progress/<operation_id>")
    @require_auth
    @require_role("Admin", "Operator")
    def alert_verification_progress(operation_id: str):
        """Get progress status for a long-running operation."""
        progress_data = ProgressTracker.get(operation_id)

        if not progress_data:
            route_logger.debug(f"Progress not found for operation_id: {operation_id}")
            return jsonify({
                "status": "not_found",
                "message": "No progress data found for this operation"
            }), 404

        route_logger.debug(f"Progress for {operation_id}: {progress_data.get('percent')}% - {progress_data.get('message')}")
        return jsonify({
            "status": "ok",
            "progress": progress_data
        })

    @app.route("/api/decode-same-header", methods=["POST"])
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def decode_same_header_api():
        """Parse a raw ZCZC SAME header string and return structured field data.

        Accepts JSON ``{"header": "ZCZC-WXR-TOR-039137+0015-3042020-KR8MER-"}``
        and returns the full parsed representation without requiring audio.
        """
        payload = request.get_json(force=True, silent=True) or {}
        raw_header = str(payload.get("header") or "").strip()

        if not raw_header:
            return jsonify({"error": "No header provided."}), 400

        # Normalise: strip leading/trailing whitespace and ensure one ZCZC prefix
        if "ZCZC" in raw_header:
            raw_header = raw_header[raw_header.find("ZCZC"):]

        if not raw_header.startswith("ZCZC-"):
            return jsonify({"error": "Header must begin with ZCZC-."}), 400

        try:
            fips_lookup = get_extended_same_lookup()
            fields = describe_same_header(raw_header, lookup=fips_lookup)
            summary = build_plain_language_summary(raw_header, fields)
            return jsonify({
                "header": raw_header,
                "fields": fields,
                "summary": summary,
            })
        except Exception as exc:
            route_logger.warning("Failed to parse raw SAME header: %s", exc)
            return jsonify({"error": f"Unable to parse header: {exc}"}), 422

    @app.route("/admin/alert-verification/decodes/<int:decode_id>/audio/<string:segment>")
    @require_auth
    @require_role("Admin", "Operator")
    def alert_verification_decode_audio(decode_id: int, segment: str):
        segment_key = (segment or "").strip().lower()
        column_map = {
            "header": "header_audio_data",
            "attention_tone": "attention_tone_audio_data",
            "tone": "attention_tone_audio_data",  # Alias
            "narration": "narration_audio_data",
            "eom": "eom_audio_data",
            "buffer": "buffer_audio_data",
            "composite": "composite_audio_data",
            "message": "message_audio_data",  # Deprecated, for backward compatibility
        }

        if segment_key not in column_map:
            abort(400, description="Unsupported audio segment.")

        record = EASDecodedAudio.query.get_or_404(decode_id)
        payload = getattr(record, column_map[segment_key])
        if not payload:
            abort(404, description="Audio segment not available.")

        download = (request.args.get("download") or "").strip().lower()
        as_attachment = download in {"1", "true", "yes", "download"}

        filename = f"decoded_{decode_id}_{segment_key}.wav"
        file_obj = io.BytesIO(payload)
        file_obj.seek(0)

        response = send_file(
            file_obj,
            mimetype="audio/wav",
            as_attachment=as_attachment,
            download_name=filename,
            max_age=0,
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
