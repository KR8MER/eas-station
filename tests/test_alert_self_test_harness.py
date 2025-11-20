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

from app_core.audio.self_test import (
    AlertSelfTestHarness,
    AlertSelfTestStatus,
)
from app_utils.eas_decode import SAMEAudioDecodeResult, SAMEHeaderDetails


def _build_decode_result(fips_codes):
    locations = [{"code": code} for code in fips_codes]
    header_fields = {
        "event_code": "RWT",
        "originator": "WXR",
        "locations": locations,
    }
    header = SAMEHeaderDetails(header="ZCZC-TEST", fields=header_fields, confidence=0.99)
    return SAMEAudioDecodeResult(
        raw_text="ZCZC-TEST",
        headers=[header],
        bit_count=1,
        frame_count=1,
        frame_errors=0,
        duration_seconds=8.0,
        sample_rate=22050,
        bit_confidence=0.99,
        min_bit_confidence=0.95,
    )


def test_alert_forwarded_when_fips_match():
    harness = AlertSelfTestHarness(["039137"])
    decode_result = _build_decode_result(["039137"])

    result = harness.process_decode_result(decode_result, source_name="demo", audio_path="sample.wav")

    assert result.status == AlertSelfTestStatus.FORWARDED
    assert result.matched_fips_codes == ["039137"]


def test_alert_filtered_when_fips_do_not_match():
    harness = AlertSelfTestHarness(["039137"])
    decode_result = _build_decode_result(["018001"])

    result = harness.process_decode_result(decode_result, source_name="demo", audio_path="sample.wav")

    assert result.status == AlertSelfTestStatus.FILTERED
    assert result.matched_fips_codes == []


def test_duplicate_detection_respected(monkeypatch):
    harness = AlertSelfTestHarness(["039137"], duplicate_cooldown_seconds=30.0)
    decode_result = _build_decode_result(["039137"])

    current_time = {"value": 1000.0}

    def fake_time():
        return current_time["value"]

    monkeypatch.setattr("app_core.audio.self_test.time.time", fake_time)

    first = harness.process_decode_result(decode_result, source_name="demo", audio_path="sample.wav")
    assert first.status == AlertSelfTestStatus.FORWARDED

    current_time["value"] += 1.0
    second = harness.process_decode_result(decode_result, source_name="demo", audio_path="sample.wav")

    assert second.status == AlertSelfTestStatus.SUPPRESSED_DUPLICATE
