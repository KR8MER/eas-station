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

"""The MPX (demodulated baseband) spectrum -- the FM-analyzer "MPX scope"
view showing the 19 kHz pilot / 38 kHz stereo / 57 kHz RDS subcarriers,
plus two raw time-domain "oscilloscope" traces (the composite multiplex
waveform, and the decoded L/R channels when stereo is locked) captured on
the same gate and bundled into the same payload.

Sibling of routes_signal.py's /api/radio/spectrum/<id> (the RF spectrum
around the tuned carrier), kept in its own file rather than added there --
that file is already at this package's ~400-line guideline, and the two
spectra have different sources (SDR hardware service vs. demod service),
different Redis keys, and no shared fallback logic to justify one route
function doing both. No command-queue fallback here (unlike RF spectrum):
the MPX spectrum only exists as something eas-station-demod.service
computes and publishes on its own ~2 Hz cadence (see
app_core/radio/demod/fm.py's _MPX_SPECTRUM_INTERVAL_S) -- there's no
synchronous "ask for one now" path to fall back to.
"""

import json
import time
from typing import Any

from flask import Flask, jsonify

from app_core.config.redis_config import RedisChannels
from app_core.models import RadioReceiver

from . import deps


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""

    @app.route("/api/radio/mpx_spectrum/<int:receiver_id>", methods=["GET"])
    def api_radio_mpx_spectrum(receiver_id: int) -> Any:
        """Return the most recently published demodulated-baseband (MPX)
        spectrum for one receiver.

        Unlike the RF spectrum, this signal only exists downstream of
        FM demodulation -- AM/IQ-passthrough receivers, or an FM receiver
        whose demod service hasn't published one yet, simply have no key
        in Redis. That's reported as ``status: "unavailable"`` with 200,
        not a 404/500, so the frontend can distinguish "nothing to show
        yet" from a real error the same way the RF spectrum route does
        for its own no-samples case.

        Returns:
            200 with {receiver_id, identifier, display_name, sample_rate,
            freq_min, freq_max, fft_size, spectrum, waveform, audio_left,
            audio_right, timestamp, status}. ``audio_left``/``audio_right``
            are omitted (not merely empty) when stereo isn't locked, so the
            frontend can distinguish "no stereo audio to show" from "an
            empty trace".
        """
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        try:
            redis_client = deps.get_redis_client()
            spectrum_key = f"{RedisChannels.MPX_SPECTRUM_PREFIX}{receiver.identifier}"
            raw = redis_client.get(spectrum_key)

            if not raw:
                return jsonify({
                    "receiver_id": receiver.id,
                    "identifier": receiver.identifier,
                    "display_name": receiver.display_name,
                    "sample_rate": 0,
                    "freq_min": 0,
                    "freq_max": 0,
                    "fft_size": 0,
                    "spectrum": [],
                    "timestamp": time.time(),
                    "status": "unavailable",
                })

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)

            sample_rate = int(payload.get("sample_rate", 0) or 0)
            response = {
                "receiver_id": receiver.id,
                "identifier": receiver.identifier,
                "display_name": receiver.display_name,
                "sample_rate": sample_rate,
                # One-sided spectrum (rfft): 0 Hz to Nyquist. multiplex is
                # at the receiver's full configured sample_rate, not the
                # early-decimated rate the RF spectrum uses -- demod runs
                # before that decimation stage.
                "freq_min": 0,
                "freq_max": sample_rate // 2,
                "fft_size": payload.get("fft_size", 0),
                "spectrum": payload.get("spectrum", []),
                "waveform": payload.get("waveform", []),
                "timestamp": payload.get("timestamp", time.time()),
                "status": "available",
            }
            if "audio_left" in payload and "audio_right" in payload:
                response["audio_left"] = payload["audio_left"]
                response["audio_right"] = payload["audio_right"]
            return jsonify(response)
        except Exception as exc:
            route_logger.error(
                "Failed to get MPX spectrum for receiver %s: %s", receiver_id, exc, exc_info=True,
            )
            deps._log_radio_event(
                "ERROR",
                f"Failed to get MPX spectrum: {exc}",
                module_suffix="mpx_spectrum",
                details={"receiver_id": receiver_id, "error": str(exc)},
            )
            return jsonify({"error": "Failed to get MPX spectrum data"}), 500


__all__ = ["register"]
