import numpy as np
from unittest.mock import MagicMock

from app_core.audio.eas_monitor import ContinuousEASMonitor
from app_utils.eas_decode import SAMEAudioDecodeResult, SAMEHeaderDetails


class DummyAudioManager:
    def get_active_source(self):
        return "test-source"


def _build_decode_result(raw_text: str) -> SAMEAudioDecodeResult:
    header_fields = {
        "event_code": "RWT",
        "originator": "WXR",
        "locations": [{"code": "039137"}],
    }
    header = SAMEHeaderDetails(header=raw_text, fields=header_fields, confidence=0.99)
    return SAMEAudioDecodeResult(
        raw_text=raw_text,
        headers=[header],
        bit_count=1,
        frame_count=1,
        frame_errors=0,
        duration_seconds=8.0,
        sample_rate=22050,
        bit_confidence=0.99,
        min_bit_confidence=0.95,
    )


def _create_monitor() -> ContinuousEASMonitor:
    monitor = ContinuousEASMonitor(
        audio_manager=DummyAudioManager(),
        buffer_duration=1.0,
        scan_interval=1.0,
        save_audio_files=False,
    )
    monitor.alert_callback = MagicMock()
    return monitor


def test_duplicate_alerts_suppressed_within_window():
    monitor = _create_monitor()
    result = _build_decode_result("ZCZC-TEST-ALERT-1")
    samples = np.zeros(1, dtype=np.float32)

    monitor._handle_alert_detected(result, samples, "unused.wav")
    monitor._handle_alert_detected(result, samples, "unused.wav")

    assert monitor.alert_callback.call_count == 1


def test_distinct_alerts_within_window_both_forwarded():
    monitor = _create_monitor()
    first = _build_decode_result("ZCZC-TEST-ALERT-1")
    second = _build_decode_result("ZCZC-TEST-ALERT-2")
    samples = np.zeros(1, dtype=np.float32)

    monitor._handle_alert_detected(first, samples, "unused.wav")
    monitor._handle_alert_detected(second, samples, "unused.wav")

    assert monitor.alert_callback.call_count == 2


def test_duplicate_allowed_after_cooldown(monkeypatch):
    monitor = _create_monitor()
    result = _build_decode_result("ZCZC-TEST-ALERT-1")
    samples = np.zeros(1, dtype=np.float32)

    current_time = {"value": 1000.0}

    def fake_time():
        return current_time["value"]

    monkeypatch.setattr("app_core.audio.eas_monitor.time.time", fake_time)

    monitor._handle_alert_detected(result, samples, "unused.wav")
    assert monitor.alert_callback.call_count == 1

    current_time["value"] = 1000.0 + monitor._duplicate_cooldown_seconds + 0.1
    monitor._handle_alert_detected(result, samples, "unused.wav")

    assert monitor.alert_callback.call_count == 2
