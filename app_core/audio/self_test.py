"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Utility harness for replaying SAME audio and verifying alert handling."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence

from app_utils import utc_now
from app_utils.eas_decode import (
    AudioDecodeError,
    SAMEAudioDecodeResult,
)

from .eas_monitor import EASAlert, compute_alert_signature
from .fips_utils import determine_fips_matches


class AlertSelfTestStatus(str, Enum):
    """High-level disposition for a replayed alert."""

    FORWARDED = "forwarded"
    FILTERED = "filtered"
    SUPPRESSED_DUPLICATE = "duplicate_suppressed"
    DECODE_ERROR = "decode_error"


@dataclass
class AlertSelfTestResult:
    """Outcome of running an audio payload through the self-test harness."""

    audio_path: str
    status: AlertSelfTestStatus
    reason: str
    event_code: str
    originator: str
    alert_fips_codes: List[str]
    matched_fips_codes: List[str]
    confidence: float
    duration_seconds: float
    raw_text: str
    duplicate: bool = False
    error: Optional[str] = None
    timestamp: Optional[str] = None

    def passed(self) -> bool:
        return self.status == AlertSelfTestStatus.FORWARDED


class AlertSelfTestHarness:
    """Replay SAME headers and report whether they would activate the system."""

    def __init__(
        self,
        configured_fips_codes: Sequence[str],
        *,
        duplicate_cooldown_seconds: float = 30.0,
        source_name: str = "self-test",
    ) -> None:
        self.configured_fips_codes = self._normalise_fips_codes(configured_fips_codes)
        self.duplicate_cooldown_seconds = max(0.0, float(duplicate_cooldown_seconds))
        self.source_name = source_name
        self._recent_alert_signatures: OrderedDict[str, float] = OrderedDict()

    def run_audio_files(self, audio_paths: Sequence[Path]) -> List[AlertSelfTestResult]:
        results: List[AlertSelfTestResult] = []
        for path in audio_paths:
            results.append(self.run_audio_file(path))
        return results

    def run_audio_file(self, audio_path: Path) -> AlertSelfTestResult:
        resolved = str(Path(audio_path).expanduser())
        try:
            decode_result = decode_same_audio(resolved)
        except AudioDecodeError as exc:  # pragma: no cover - exercised via CLI
            return AlertSelfTestResult(
                audio_path=resolved,
                status=AlertSelfTestStatus.DECODE_ERROR,
                reason="Unable to decode audio",
                event_code="UNKNOWN",
                originator="UNKNOWN",
                alert_fips_codes=[],
                matched_fips_codes=[],
                confidence=0.0,
                duration_seconds=0.0,
                raw_text="",
                duplicate=False,
                error=str(exc),
                timestamp=None,
            )

        return self.process_decode_result(
            decode_result,
            source_name=self.source_name,
            audio_path=resolved,
        )

    def process_decode_result(
        self,
        result: SAMEAudioDecodeResult,
        *,
        source_name: Optional[str] = None,
        audio_path: Optional[str] = None,
    ) -> AlertSelfTestResult:
        alert = self._build_alert(result, source_name or self.source_name, audio_path)
        event_code, originator, alert_fips = self._extract_header_metadata(alert)

        signature = compute_alert_signature(alert)
        now = time.time()
        is_duplicate = self._check_duplicate(signature, now)

        matched_fips = determine_fips_matches(alert_fips, self.configured_fips_codes)
        matched_fips_sorted = sorted(matched_fips)

        if is_duplicate:
            status = AlertSelfTestStatus.SUPPRESSED_DUPLICATE
            reason = f"Duplicate within {self.duplicate_cooldown_seconds:.1f}s window"
        elif matched_fips_sorted:
            status = AlertSelfTestStatus.FORWARDED
            reason = f"Matched configured FIPS: {', '.join(matched_fips_sorted)}"
        else:
            status = AlertSelfTestStatus.FILTERED
            reason = "No configured FIPS overlap"

        return AlertSelfTestResult(
            audio_path=audio_path or "<memory>",
            status=status,
            reason=reason,
            event_code=event_code,
            originator=originator,
            alert_fips_codes=alert_fips,
            matched_fips_codes=matched_fips_sorted,
            confidence=result.bit_confidence,
            duration_seconds=result.duration_seconds,
            raw_text=result.raw_text,
            duplicate=is_duplicate,
            error=None,
            timestamp=alert.timestamp.isoformat(),
        )

    @staticmethod
    def _normalise_fips_codes(values: Sequence[str]) -> List[str]:
        cleaned: List[str] = []
        seen = set()
        for value in values or []:
            digits = ''.join(ch for ch in str(value) if ch.isdigit())
            if not digits:
                continue
            digits = digits.zfill(6)[:6]
            if digits in seen:
                continue
            seen.add(digits)
            cleaned.append(digits)
        return cleaned

    def _build_alert(
        self,
        result: SAMEAudioDecodeResult,
        source_name: str,
        audio_path: Optional[str],
    ) -> EASAlert:
        headers: List[dict] = []
        for header in result.headers:
            payload = header.to_dict()
            if 'raw_text' not in payload and 'header' in payload:
                payload['raw_text'] = payload['header']
            headers.append(payload)

        return EASAlert(
            timestamp=utc_now(),
            raw_text=result.raw_text,
            headers=headers,
            confidence=result.bit_confidence,
            duration_seconds=result.duration_seconds,
            source_name=source_name,
            audio_file_path=audio_path,
        )

    @staticmethod
    def _extract_header_metadata(alert: EASAlert) -> (str, str, List[str]):
        event_code = "UNKNOWN"
        originator = "UNKNOWN"
        codes: List[str] = []

        if alert.headers:
            first = alert.headers[0]
            fields = first.get('fields') if isinstance(first, dict) else None
            if isinstance(fields, dict):
                event_code = str(fields.get('event_code', 'UNKNOWN') or 'UNKNOWN').strip().upper() or 'UNKNOWN'
                originator = str(fields.get('originator', 'UNKNOWN') or 'UNKNOWN').strip().upper() or 'UNKNOWN'
                locations = fields.get('locations', [])
                if isinstance(locations, list):
                    for entry in locations:
                        if not isinstance(entry, dict):
                            continue
                        code = (entry.get('code') or '').strip()
                        if code:
                            digits = ''.join(ch for ch in code if ch.isdigit())
                            if digits:
                                codes.append(digits.zfill(6)[:6])

        if codes:
            codes = sorted({code for code in codes})

        return event_code, originator, codes

    def _check_duplicate(self, signature: str, current_time: float) -> bool:
        cutoff = current_time - self.duplicate_cooldown_seconds
        while self._recent_alert_signatures:
            oldest_signature, timestamp = next(iter(self._recent_alert_signatures.items()))
            if timestamp >= cutoff:
                break
            self._recent_alert_signatures.popitem(last=False)

        if signature in self._recent_alert_signatures:
            return True

        self._recent_alert_signatures[signature] = current_time
        return False


def decode_same_audio(path: str) -> SAMEAudioDecodeResult:
    """Shim for dependency injection in unit tests."""
    from app_utils.eas_decode import decode_same_audio as _decode

    return _decode(path)


__all__ = [
    'AlertSelfTestHarness',
    'AlertSelfTestResult',
    'AlertSelfTestStatus',
]
