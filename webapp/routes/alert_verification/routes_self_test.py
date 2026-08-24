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

"""``POST /api/alert-self-test/run`` — the end-to-end self test."""

from pathlib import Path
from typing import List, Sequence

from flask import Flask, jsonify, request

from app_core.auth.decorators import require_auth, require_role
from app_core.auth.roles import get_current_user
from app_core.audio.self_test import AlertSelfTestHarness, AlertSelfTestStatus
from app_utils import utc_now

from .errors import AlertSelfTestError
from .helpers import _load_configured_fips, _result_to_dict
from .samples import DEFAULT_SAMPLE_FILES


def register(app: Flask, logger):
    """Attach this module's routes, recreating register's closure.

    ``route_logger`` and ``repo_root`` are rebuilt here rather than passed in, so each
    handler closes over exactly what it closed over in the single-file
    module.
    """
    route_logger = logger.getChild('alert_verification')
    repo_root = Path(app.root_path).resolve()

    def _resolve_audio_paths(paths: Sequence[str], include_defaults: bool) -> List[Path]:
        resolved: List[Path] = []
        seen: set[Path] = set()

        def _add(candidate: Path) -> None:
            target = candidate.resolve()
            if target in seen:
                return
            if not target.exists():
                raise AlertSelfTestError(f"Audio sample not found: {target}")
            seen.add(target)
            resolved.append(target)

        for raw_value in paths or []:
            if not raw_value:
                continue
            candidate = Path(str(raw_value)).expanduser()
            if not candidate.is_absolute():
                candidate = repo_root / candidate
            _add(candidate)

        if include_defaults or not resolved:
            for rel_path in DEFAULT_SAMPLE_FILES:
                candidate = (repo_root / rel_path).resolve()
                if candidate.exists():
                    _add(candidate)

        if not resolved:
            raise AlertSelfTestError("No audio samples were provided or available.")

        return resolved

    @app.route("/api/alert-self-test/run", methods=["POST"])
    @require_auth
    @require_role("Admin", "Operator")
    def run_alert_self_test():
        """Decode a batch of sample SAME audio through the live alert pipeline.

        Runs each given audio file through the same decode/duplicate/FIPS-
        filter logic a real received alert goes through, without touching
        the live air-chain -- useful for verifying the SAME decoder after a
        configuration change.

        Body:
            audio_paths (list[str], optional): Server-side paths to WAV
                samples to test. Defaults to the built-in sample set when
                omitted.
            use_default_samples (bool, optional): Force the built-in sample
                set even if audio_paths is given. Defaults to true only
                when audio_paths is empty.
            duplicate_cooldown (number, optional): Seconds before an
                identical header is treated as a fresh alert rather than a
                duplicate. Default 30.
            source_name (str, optional): Label attached to results, for
                distinguishing concurrent self-test runs. Default
                "self-test".
            require_match (bool, optional): Fail the run if no sample
                matches the configured FIPS codes. Default false.
            fips_codes (list[str], optional): FIPS codes to filter against,
                overriding the station's configured set for this run only.

        Returns:
            200 with {success, error, configured_fips, audio_samples,
            duplicate_cooldown, source_name, results, forwarded_count,
            decode_error_count, default_samples_used, timestamp}.
            400 if duplicate_cooldown is non-numeric or an audio path is
            invalid.
        """
        payload = request.get_json(force=True, silent=True) or {}

        user_audio_paths = payload.get("audio_paths") or []
        use_default_samples = bool(payload.get("use_default_samples", not user_audio_paths))
        cooldown = payload.get("duplicate_cooldown", 30.0)
        source_name = str(payload.get("source_name") or "self-test").strip() or "self-test"
        require_match = bool(payload.get("require_match", False))
        fips_override = payload.get("fips_codes") or []

        try:
            cooldown_value = max(0.0, float(cooldown))
        except (TypeError, ValueError):
            return (
                jsonify({"success": False, "error": "Duplicate cooldown must be numeric."}),
                400,
            )

        try:
            resolved_paths = _resolve_audio_paths(user_audio_paths, use_default_samples)
        except AlertSelfTestError as exc:
            route_logger.warning("Alert self-test rejected: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 400

        configured_fips = _load_configured_fips(fips_override)

        harness = AlertSelfTestHarness(
            configured_fips,
            duplicate_cooldown_seconds=cooldown_value,
            source_name=source_name,
        )

        route_logger.info(
            "Running alert self-test by user '%s': audio=%s fips=%s cooldown=%s source=%s",
            getattr(get_current_user(), 'username', 'unknown'),
            ",".join(str(path) for path in resolved_paths),
            ",".join(harness.configured_fips_codes) or "<none>",
            cooldown_value,
            source_name,
        )

        results = harness.run_audio_files(resolved_paths)
        forwarded = sum(1 for item in results if item.status == AlertSelfTestStatus.FORWARDED)
        decode_errors = sum(1 for item in results if item.status == AlertSelfTestStatus.DECODE_ERROR)

        # A self-test that cannot fail is not a test. `decode_errors` was
        # counted and reported in its own tile, but never consulted here, so
        # the verdict was `True` on every run unless the caller opted into
        # `require_match` — a run where every sample failed to decode still
        # rendered a green PASS. A decode error means the SAME header could
        # not be recovered from the audio, which is exactly the pipeline
        # failure this test exists to catch. FILTERED and SUPPRESSED_DUPLICATE
        # stay passing: those are correct outcomes, not faults.
        if not results:
            success = False
            error = "No audio samples were processed."
        elif decode_errors:
            success = False
            error = (
                f"{decode_errors} of {len(results)} sample(s) failed to decode a "
                "SAME header."
            )
        elif require_match and forwarded == 0:
            success = False
            error = "No alerts matched the configured FIPS codes."
        else:
            success = True
            error = None

        response = {
            "success": success,
            "error": error,
            "configured_fips": harness.configured_fips_codes,
            "audio_samples": [
                {"path": str(path), "name": path.name}
                for path in resolved_paths
            ],
            "duplicate_cooldown": cooldown_value,
            "source_name": source_name,
            "results": [_result_to_dict(item) for item in results],
            "forwarded_count": forwarded,
            "decode_error_count": decode_errors,
            "default_samples_used": use_default_samples and not user_audio_paths,
            "timestamp": utc_now().isoformat(),
        }

        return jsonify(response)
