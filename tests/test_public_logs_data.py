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

"""Characterization tests for the /logs query layer.

Written *before* ``_load_logs_data`` (1,057 lines in a single function) was
decomposed into the ``webapp/public/logs_sources/`` package, and it is the
safety net that makes that decomposition checkable. ``ast.dump()`` comparison is
useless for a restructure, so instead the loader is driven over every
``log_type`` it dispatches on and the **full** returned triple is asserted —
display name, every key of every log dict, and the report metadata.

The loader had no test coverage at all before this file, which is exactly the
situation the refactor plan's ground rule 5 says to discover *before* moving
code rather than after.

Each ``log_type`` branch shapes its rows differently — the ``details`` payloads
are per-category, and the ``level`` is derived by a different rule in almost
every branch — so the per-branch ``details``/``level`` assertions here are the
real content of the harness, not incidental detail.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

# Every branch under test reads a real table, and several of those tables carry
# PostgreSQL-specific column types (JSONB payloads, array columns), so these
# cannot run against the in-memory SQLite database the default `app` fixture
# builds. CI provides a PostgreSQL DATABASE_URL; see .github/workflows/tests.yml.
_DB_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _DB_URL.startswith(("postgresql", "postgres://")),
    reason="needs a PostgreSQL DATABASE_URL (the log tables use JSONB columns)",
)

from app_core.extensions import db  # noqa: E402
from app_core.models import (  # noqa: E402
    AudioAlert,
    AudioHealthStatus,
    AudioSourceMetrics,
    EASDecodedAudio,
    EASMessage,
    GPIOActivationLog,
    ManualEASActivation,
    PollDebugRecord,
    PollHistory,
    ReceivedEASAlert,
    SystemLog,
)

# A fixed instant so every assertion below can name exact timestamps. These
# columns are TIMESTAMP WITH TIME ZONE, so rows come back tz-aware and the
# loader passes the value through untouched — the sort key is the only place
# tzinfo gets stripped, and only for comparison.
T0 = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _t(minutes: int) -> datetime:
    """``T0`` offset by ``minutes``, for ordering rows deterministically."""
    return T0 + timedelta(minutes=minutes)


# The tables the loader reads. Emptied before and after every test so the
# ``.limit()`` windows are deterministic regardless of what else the suite left
# behind.
_LOG_MODELS = (
    SystemLog,
    PollHistory,
    PollDebugRecord,
    AudioAlert,
    AudioSourceMetrics,
    AudioHealthStatus,
    GPIOActivationLog,
    EASMessage,
    EASDecodedAudio,
    ManualEASActivation,
    ReceivedEASAlert,
)


@pytest.fixture(scope="module")
def app():
    """The real application object, bound to the configured PostgreSQL URL.

    Deliberately shadows the session-wide `app` fixture from conftest.py, which
    forces sqlite:///:memory: and therefore has none of these tables.
    """
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


def _wipe():
    from app_core.auth.audit import AuditLog

    for model in _LOG_MODELS:
        db.session.query(model).delete(synchronize_session=False)
    db.session.query(AuditLog).delete(synchronize_session=False)
    db.session.commit()


@pytest.fixture
def ctx(app):
    """An app context with every log table emptied, restored afterwards."""
    with app.app_context():
        _wipe()
        yield
        db.session.rollback()
        _wipe()
        db.session.remove()


@pytest.fixture
def loader():
    """The loader under test, bound to a quiet logger."""
    from webapp.public.logs_data import build_logs_loader

    return build_logs_loader(logging.getLogger("test-logs-data"))


def _add(row):
    db.session.add(row)
    db.session.commit()
    return row


# ---------------------------------------------------------------------------
# Row builders — one per model, with every field the loader reads populated.
# ---------------------------------------------------------------------------

def _system_log(**kw):
    return _add(SystemLog(**{
        "timestamp": _t(0),
        "level": "ERROR",
        "module": "poller",
        "message": "boom",
        "alert_identifier": "NWS-1",
        "details": {"trace": "x"},
        **kw,
    }))


def _poll_history(**kw):
    return _add(PollHistory(**{
        "timestamp": _t(0),
        "status": "success",
        "alerts_fetched": 7,
        "alerts_new": 2,
        "alerts_updated": 1,
        "execution_time_ms": 123,
        "error_message": None,
        "data_source": "NOAA",
        "details": {"alerts_accepted": 5, "alerts_filtered": 2},
        **kw,
    }))


def _poll_debug(**kw):
    return _add(PollDebugRecord(**{
        "created_at": _t(0),
        "poll_run_id": "run-1",
        "poll_started_at": _t(0),
        "poll_status": "ok",
        "data_source": "noaa",
        "alert_identifier": "NWS-9",
        "alert_event": "Tornado Warning",
        "alert_sent": _t(-5),
        "is_relevant": True,
        "relevance_reason": "fips match",
        "relevance_matches": ["039001"],
        "ugc_codes": ["OHC001"],
        "area_desc": "Allen County",
        "was_saved": True,
        "was_new": True,
        "alert_db_id": 42,
        "parse_success": True,
        "parse_error": None,
        "polygon_count": 1,
        "geometry_type": "Polygon",
        "raw_xml_present": True,
        "notes": "n",
        **kw,
    }))


def _audio_alert(**kw):
    return _add(AudioAlert(**{
        "created_at": _t(0),
        "updated_at": _t(1),
        "source_name": "stream-a",
        "alert_level": "warning",
        "alert_type": "silence",
        "message": "silence detected",
        "alert_identifier": "AA-1",
        "acknowledged": False,
        "resolved": False,
        **kw,
    }))


def _audio_metrics(**kw):
    return _add(AudioSourceMetrics(**{
        "timestamp": _t(0),
        "source_name": "stream-a",
        "source_type": "stream",
        "peak_level_db": -6.0,
        "rms_level_db": -18.0,
        "peak_level_linear": 0.5,
        "rms_level_linear": 0.12,
        "sample_rate": 48000,
        "channels": 2,
        "frames_captured": 1234,
        "silence_detected": False,
        "clipping_detected": False,
        "buffer_utilization": 0.25,
        "source_metadata": {"station": "WXYZ"},
        **kw,
    }))


def _audio_health(**kw):
    return _add(AudioHealthStatus(**{
        "timestamp": _t(0),
        "source_name": "stream-a",
        "health_score": 91.5,
        "is_healthy": True,
        "is_active": True,
        "error_detected": False,
        "uptime_seconds": 3600.0,
        "silence_detected": False,
        "silence_duration_seconds": 0.0,
        "time_since_last_signal_seconds": 1.0,
        "level_trend": "rising",
        "trend_value_db": 2.5,
        "health_metadata": {"k": "v"},
        **kw,
    }))


def _gpio_log(**kw):
    return _add(GPIOActivationLog(**{
        "activated_at": _t(0),
        "deactivated_at": _t(1),
        "pin": 17,
        "activation_type": "alert",
        "duration_seconds": 60.0,
        "alert_id": "GP-1",
        "reason": "tornado warning",
        "success": True,
        "error_message": None,
        **kw,
    }))


def _eas_message(**kw):
    return _add(EASMessage(**{
        "created_at": _t(0),
        "cap_alert_id": None,
        "alert_identifier": "EM-1",
        "same_header": "ZCZC-WXR-TOR",
        "audio_filename": "a.wav",
        "text_filename": "a.txt",
        "tts_provider": "azure",
        "tts_warning": None,
        "text_payload": "body",
        "metadata_payload": {"m": 1},
        "audio_data": b"\x00\x01",
        **kw,
    }))


def _decoded_audio(**kw):
    return _add(EASDecodedAudio(**{
        "created_at": _t(0),
        "original_filename": "cap.wav",
        "content_type": "audio/wav",
        "raw_text": "raw",
        "same_headers": ["ZCZC-WXR-TOR"],
        "quality_metrics": {"snr": 20},
        "segment_metadata": {"n": 3},
        "header_audio_data": b"\x00",
        "composite_audio_data": None,
        **kw,
    }))


def _manual_activation(**kw):
    return _add(ManualEASActivation(**{
        "created_at": _t(0),
        "identifier": "MA-1",
        "event_code": "RWT",
        "event_name": "Required Weekly Test",
        "status": "ALERT",
        "message_type": "Alert",
        "same_header": "ZCZC-EAS-RWT",
        "same_locations": ["039003"],
        "tone_profile": "attention",
        "tone_seconds": 8.0,
        "includes_tts": True,
        "tts_warning": None,
        "sent_at": _t(-1),
        "expires_at": _t(60),
        "headline": "Test",
        "message_text": "This is a test",
        "instruction_text": "No action",
        "duration_minutes": 30,
        "storage_path": "/srv/a",
        "archived_at": None,
        **kw,
    }))


def _received_alert(**kw):
    return _add(ReceivedEASAlert(**{
        "received_at": _t(0),
        "source_name": "monitor-1",
        "raw_same_header": "ZCZC-WXR-TOR",
        "event_code": "TOR",
        "event_name": "Tornado Warning",
        "originator_code": "WXR",
        "originator_name": "Weather Service",
        "fips_codes": ["039003"],
        "forwarding_decision": "forwarded",
        "forwarding_reason": "in area",
        "matched_fips_codes": ["039003"],
        "decode_confidence": 0.97,
        # generated_message_id is a real FK to eas_messages; left NULL so the
        # builder does not need a companion row.
        "generated_message_id": None,
        "callsign": "WXYZ",
        **kw,
    }))


def _audit(**kw):
    from app_core.auth.audit import AuditLog

    return _add(AuditLog(**{
        "timestamp": _t(0),
        "action": "config.updated",
        "success": True,
        "username": "alice",
        "user_id": 1,
        "resource_type": "setting",
        "resource_id": "TTS_PROVIDER",
        "ip_address": "10.0.0.1",
        "user_agent": "pytest",
        "details": {"old": "a", "new": "b"},
        "prev_hash": "p",
        "entry_hash": "e",
        "signature": "s",
        **kw,
    }))


# ---------------------------------------------------------------------------
# Per-category branches
# ---------------------------------------------------------------------------

def test_unknown_log_type_returns_the_defaults(ctx, loader):
    """A log_type nothing matches falls through to the initialised values."""
    name, rows, meta = loader("no-such-type", 50)
    assert (name, rows, meta) == ("System Logs", [], None)


def test_system_branch(ctx, loader):
    _system_log()
    name, rows, meta = loader("system", 50)

    assert name == "System Logs"
    assert meta is None
    assert rows == [{
        "timestamp": _t(0),
        "level": "ERROR",
        "module": "poller",
        "message": "boom",
        "alert_identifier": "NWS-1",
        "details": {"trace": "x"},
    }]


def test_system_branch_defaults_missing_module_to_system(ctx, loader):
    _system_log(module=None)
    _, rows, _ = loader("system", 50)
    assert rows[0]["module"] == "system"


def test_system_branch_orders_newest_first_and_honours_limit(ctx, loader):
    for i in range(5):
        _system_log(timestamp=_t(i), message=f"m{i}")
    _, rows, _ = loader("system", 3)
    assert [r["message"] for r in rows] == ["m4", "m3", "m2"]


def test_polling_branch_merges_details_and_builds_message(ctx, loader):
    _poll_history()
    name, rows, meta = loader("polling", 50)

    assert name == "CAP Polling Logs"
    assert meta is None
    assert rows == [{
        "timestamp": _t(0),
        "level": "SUCCESS",
        "module": "Alert Polling (NOAA)",
        "message": "Status: success | Fetched: 7 | Accepted: 5 | Filtered: 2 | New: 2 | Updated: 1",
        "details": {
            "execution_time_ms": 123,
            "error": None,
            "data_source": "NOAA",
            "alerts_fetched": 7,
            "alerts_new": 2,
            "alerts_updated": 1,
            "alerts_accepted": 5,
            "alerts_filtered": 2,
        },
    }]


def test_polling_branch_omits_accepted_filtered_without_details(ctx, loader):
    """No ``details`` JSON means no Accepted/Filtered segments in the message."""
    _poll_history(details=None)
    _, rows, _ = loader("polling", 50)
    assert rows[0]["message"] == "Status: success | Fetched: 7 | New: 2 | Updated: 1"


@pytest.mark.parametrize(
    "status,error_message,expected_level",
    [
        ("success", None, "SUCCESS"),
        ("SUCCESS", None, "SUCCESS"),   # the check lowercases
        ("partial", None, "INFO"),
        ("success", "kaboom", "ERROR"),  # an error outranks the status
        ("", None, "INFO"),              # `(log.status or '')` guards the empty case
    ],
)
def test_polling_branch_level_rules(ctx, loader, status, error_message, expected_level):
    _poll_history(status=status, error_message=error_message)
    _, rows, _ = loader("polling", 50)
    assert rows[0]["level"] == expected_level


def test_polling_branch_labels_unknown_data_source(ctx, loader):
    _poll_history(data_source=None)
    _, rows, _ = loader("polling", 50)
    assert rows[0]["module"] == "Alert Polling (UNKNOWN)"


def test_polling_debug_branch(ctx, loader):
    _poll_debug()
    name, rows, meta = loader("polling_debug", 50)

    assert name == "Polling Debug Logs"
    assert meta is None
    assert len(rows) == 1
    row = rows[0]
    assert row["timestamp"] == _t(0)
    assert row["level"] == "INFO"
    assert row["module"] == "Polling Debug (noaa)"
    assert row["message"] == (
        "Run run-1: NWS-9 | Status OK | Relevant: yes | Saved: yes"
    )
    assert row["details"] == {
        "poll_run_id": "run-1",
        "poll_status": "ok",
        "data_source": "noaa",
        "alert_identifier": "NWS-9",
        "alert_event": "Tornado Warning",
        "alert_sent": _t(-5).isoformat(),
        "created_at": _t(0).isoformat(),
        "is_relevant": True,
        "relevance_reason": "fips match",
        "relevance_matches": ["039001"],
        "ugc_codes": ["OHC001"],
        "area_desc": "Allen County",
        "was_saved": True,
        "was_new": True,
        "alert_db_id": 42,
        "parse_success": True,
        "parse_error": None,
        "polygon_count": 1,
        "geometry_type": "Polygon",
        "raw_xml_present": True,
        "notes": "n",
    }


@pytest.mark.parametrize(
    "parse_success,is_relevant,expected_level",
    [
        (False, True, "ERROR"),    # a parse failure outranks relevance
        (False, False, "ERROR"),
        (True, True, "INFO"),
        (True, False, "WARNING"),
    ],
)
def test_polling_debug_level_rules(ctx, loader, parse_success, is_relevant, expected_level):
    _poll_debug(parse_success=parse_success, is_relevant=is_relevant)
    _, rows, _ = loader("polling_debug", 50)
    assert rows[0]["level"] == expected_level


def test_polling_debug_falls_back_through_identifier_then_event(ctx, loader):
    _poll_debug(alert_identifier=None)
    _, rows, _ = loader("polling_debug", 50)
    assert "Tornado Warning" in rows[0]["message"]

    _wipe()
    _poll_debug(alert_identifier=None, alert_event=None)
    _, rows, _ = loader("polling_debug", 50)
    assert "Unknown alert" in rows[0]["message"]


def test_audio_branch(ctx, loader):
    _audio_alert()
    name, rows, meta = loader("audio", 50)

    assert name == "Audio System Logs"
    assert meta is None
    assert rows == [{
        "timestamp": _t(0),
        "level": "WARNING",  # alert_level upper-cased
        "module": "Audio Alert: stream-a",
        "message": "silence detected",
        "alert_identifier": "AA-1",
        "details": {
            "alert_type": "silence",
            "acknowledged": False,
            "resolved": False,
            "created_at": _t(0).isoformat(),
            "updated_at": _t(1).isoformat(),
        },
    }]


def test_audio_metrics_branch(ctx, loader):
    _audio_metrics()
    name, rows, meta = loader("audio_metrics", 50)

    assert name == "Audio Metrics Logs"
    assert meta is None
    assert rows == [{
        "timestamp": _t(0),
        "level": "INFO",
        "module": "Audio Metrics: stream-a",
        "message": "Peak: -6.0dB | RMS: -18.0dB | SR: 48000Hz",
        "details": {
            "source_type": "stream",
            "channels": 2,
            "frames": 1234,
            "silence": False,
            "clipping": False,
            "buffer_utilization": 0.25,
            "stream_info": {"station": "WXYZ"},
        },
    }]


@pytest.mark.parametrize(
    "silence,clipping,expected_level",
    [(False, False, "INFO"), (True, False, "WARNING"),
     (False, True, "WARNING"), (True, True, "WARNING")],
)
def test_audio_metrics_level_rules(ctx, loader, silence, clipping, expected_level):
    _audio_metrics(silence_detected=silence, clipping_detected=clipping)
    _, rows, _ = loader("audio_metrics", 50)
    assert rows[0]["level"] == expected_level


def test_audio_health_branch(ctx, loader):
    _audio_health()
    name, rows, meta = loader("audio_health", 50)

    assert name == "Audio Health Logs"
    assert meta is None
    assert rows == [{
        "timestamp": _t(0),
        "level": "INFO",
        "module": "Audio Health: stream-a",
        "message": "Health Score: 91.5/100 | Active: True | Uptime: 3600.0s",
        "details": {
            "healthy": True,
            "silence_detected": False,
            "silence_duration": 0.0,
            "time_since_signal": 1.0,
            "trend": "rising (2.5dB)",
            "metadata": {"k": "v"},
        },
    }]


def test_audio_health_trend_is_none_without_a_level_trend(ctx, loader):
    _audio_health(level_trend=None)
    _, rows, _ = loader("audio_health", 50)
    assert rows[0]["details"]["trend"] is None


@pytest.mark.parametrize(
    "error_detected,is_healthy,expected_level",
    [(True, True, "ERROR"),     # error_detected outranks is_healthy
     (True, False, "ERROR"),
     (False, False, "WARNING"),
     (False, True, "INFO")],
)
def test_audio_health_level_rules(ctx, loader, error_detected, is_healthy, expected_level):
    _audio_health(error_detected=error_detected, is_healthy=is_healthy)
    _, rows, _ = loader("audio_health", 50)
    assert rows[0]["level"] == expected_level


def test_gpio_branch_exposes_alert_id_under_the_canonical_name(ctx, loader):
    from app_utils.gpio_logs import gpio_log_level, gpio_log_message

    row = _gpio_log()
    name, rows, meta = loader("gpio", 50)

    assert name == "GPIO Activation Logs"
    assert meta is None
    assert rows == [{
        "timestamp": _t(0),
        "level": gpio_log_level(row),
        "module": "GPIO Pin 17",
        "message": gpio_log_message(row),
        # GPIOActivationLog stores it as ``alert_id``; the UI reads
        # ``alert_identifier``, and both appear in the payload.
        "alert_identifier": "GP-1",
        "details": {
            "pin": 17,
            "activation_type": "alert",
            "activated_at": _t(0).isoformat(),
            "deactivated_at": _t(1).isoformat(),
            "duration": 60.0,
            "alert_id": "GP-1",
            "reason": "tornado warning",
            "success": True,
            "error_message": None,
        },
    }]


def test_eas_messages_branch_reports_blob_presence_without_loading_blobs(ctx, loader):
    """The six audio columns are reduced to booleans in SQL, not transferred."""
    _eas_message()
    name, rows, meta = loader("eas_messages", 50)

    assert name == "EAS Messages Generated"
    assert meta is None
    assert rows == [{
        "timestamp": _t(0),
        "level": "INFO",
        "module": "EAS Message Generator",
        "message": "SAME: ZCZC-WXR-TOR | TTS Provider: azure | Audio: a.wav",
        "alert_identifier": "EM-1",
        "details": {
            "id": rows[0]["details"]["id"],
            "cap_alert_id": None,
            "alert_identifier": "EM-1",
            "same_header": "ZCZC-WXR-TOR",
            "audio_filename": "a.wav",
            "text_filename": "a.txt",
            "has_audio_data": True,      # populated above
            "has_eom_audio": False,      # left NULL
            "has_same_audio": False,
            "has_attention_audio": False,
            "has_tts_audio": False,
            "tts_provider": "azure",
            "tts_warning": None,
            "text_payload": "body",
            "metadata": {"m": 1},
        },
    }]


def test_eas_messages_branch_labels_a_missing_tts_provider(ctx, loader):
    _eas_message(tts_provider=None)
    _, rows, _ = loader("eas_messages", 50)
    assert "TTS Provider: None" in rows[0]["message"]


def test_decoded_audio_branch(ctx, loader):
    _decoded_audio()
    name, rows, meta = loader("decoded_audio", 50)

    assert name == "Decoded EAS Audio"
    assert meta is None
    assert rows[0]["message"] == "File: cap.wav | SAME Headers: 1 | Type: audio/wav"
    assert rows[0]["level"] == "INFO"
    assert rows[0]["module"] == "EAS Audio Decoder"
    assert rows[0]["details"] == {
        "id": rows[0]["details"]["id"],
        "original_filename": "cap.wav",
        "content_type": "audio/wav",
        "raw_text": "raw",
        "same_headers": ["ZCZC-WXR-TOR"],
        "quality_metrics": {"snr": 20},
        "segment_metadata": {"n": 3},
        "has_header_audio": True,
        "has_attention_tone": False,
        "has_narration": False,
        "has_eom_audio": False,
        "has_composite": False,
    }


def test_decoded_audio_branch_handles_empty_fields(ctx, loader):
    _decoded_audio(original_filename=None, content_type=None, same_headers=None)
    _, rows, _ = loader("decoded_audio", 50)
    assert rows[0]["message"] == "File: Unknown | SAME Headers: 0 | Type: N/A"
    assert rows[0]["details"]["same_headers"] == []


def test_manual_activations_branch(ctx, loader):
    _manual_activation()
    name, rows, meta = loader("manual_activations", 50)

    assert name == "Manual EAS Activations"
    assert meta is None
    assert rows[0]["timestamp"] == _t(0)
    assert rows[0]["level"] == "WARNING"  # status == 'ALERT'
    assert rows[0]["module"] == "Manual EAS Activation"
    assert rows[0]["message"] == (
        "Event: Required Weekly Test (RWT) | Status: ALERT | Type: Alert"
    )
    assert rows[0]["details"] == {
        "id": rows[0]["details"]["id"],
        "identifier": "MA-1",
        "event_code": "RWT",
        "event_name": "Required Weekly Test",
        "status": "ALERT",
        "message_type": "Alert",
        "same_header": "ZCZC-EAS-RWT",
        "same_locations": ["039003"],
        "tone_profile": "attention",
        "tone_seconds": 8.0,
        "includes_tts": True,
        "tts_warning": None,
        "sent_at": _t(-1).isoformat(),
        "expires_at": _t(60).isoformat(),
        "headline": "Test",
        "message_text": "This is a test",
        "instruction_text": "No action",
        "duration_minutes": 30,
        "storage_path": "/srv/a",
        "archived_at": None,
    }


def test_manual_activations_level_is_info_unless_status_is_alert(ctx, loader):
    _manual_activation(status="TEST")
    _, rows, _ = loader("manual_activations", 50)
    assert rows[0]["level"] == "INFO"


def test_received_alerts_branch(ctx, loader):
    _received_alert()
    name, rows, meta = loader("received_alerts", 50)

    assert name == "Received EAS Alerts"
    assert meta is None
    assert rows[0]["timestamp"] == _t(0)
    assert rows[0]["level"] == "INFO"
    assert rows[0]["module"] == "Audio Monitor: monitor-1"
    assert rows[0]["message"] == (
        "Event: TOR (Tornado Warning) | Decision: forwarded | Source: WXYZ"
    )
    assert rows[0]["details"] == {
        "id": rows[0]["details"]["id"],
        "source_name": "monitor-1",
        "raw_same_header": "ZCZC-WXR-TOR",
        "event_code": "TOR",
        "event_name": "Tornado Warning",
        "originator_code": "WXR",
        "originator_name": "Weather Service",
        "fips_codes": ["039003"],
        "forwarding_decision": "forwarded",
        "forwarding_reason": "in area",
        "matched_fips_codes": ["039003"],
        "decode_confidence": 0.97,
        "generated_message_id": None,
    }


@pytest.mark.parametrize(
    "decision,expected_level",
    [("forwarded", "INFO"), ("ignored", "WARNING"), ("error", "ERROR"), ("", "ERROR")],
)
def test_received_alerts_level_rules(ctx, loader, decision, expected_level):
    _received_alert(forwarding_decision=decision)
    _, rows, _ = loader("received_alerts", 50)
    assert rows[0]["level"] == expected_level


def test_received_alerts_falls_back_to_source_name_without_a_callsign(ctx, loader):
    _received_alert(callsign=None, event_name=None)
    _, rows, _ = loader("received_alerts", 50)
    assert rows[0]["message"] == (
        "Event: TOR (Unknown) | Decision: forwarded | Source: monitor-1"
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def test_audit_branch_surfaces_the_tamper_evidence_chain(ctx, loader):
    _audit()
    name, rows, meta = loader("audit", 50)

    assert name == "Audit Log"
    assert meta is None
    assert rows[0]["level"] == "INFO"
    assert rows[0]["module"] == "audit:config.updated"
    assert rows[0]["message"] == "config.updated by alice on setting#TTS_PROVIDER"
    assert rows[0]["alert_identifier"] is None
    # All three chain fields must be present — an operator cross-checks a row
    # against an exported copy with them (docs/security/AUDIT_LOG_INTEGRITY.md).
    assert rows[0]["details"]["prev_hash"] == "p"
    assert rows[0]["details"]["entry_hash"] == "e"
    assert rows[0]["details"]["signature"] == "s"
    assert rows[0]["details"]["ip_address"] == "10.0.0.1"


@pytest.mark.parametrize(
    "kw,expected_message,expected_level",
    [
        ({}, "config.updated by alice on setting#TTS_PROVIDER", "INFO"),
        ({"username": None}, "config.updated (anonymous) on setting#TTS_PROVIDER", "INFO"),
        ({"resource_type": None}, "config.updated by alice", "INFO"),
        ({"resource_id": None}, "config.updated by alice", "INFO"),
        ({"success": False}, "config.updated by alice on setting#TTS_PROVIDER — FAILED", "WARNING"),
    ],
)
def test_audit_message_assembly(ctx, loader, kw, expected_message, expected_level):
    _audit(**kw)
    _, rows, _ = loader("audit", 50)
    assert rows[0]["message"] == expected_message
    assert rows[0]["level"] == expected_level


def test_audit_action_filter_applies_at_the_database_level(ctx, loader):
    """The filter must run in SQL, not after the limit window."""
    _audit(action="login.failed", timestamp=_t(10))
    _audit(action="login.failed", timestamp=_t(9))
    _audit(action="config.updated", timestamp=_t(0))

    _, rows, _ = loader("audit", 2, action_filter="config.updated")
    assert [r["details"]["action"] for r in rows] == ["config.updated"]

    _, rows, _ = loader("audit", 2)
    assert [r["details"]["action"] for r in rows] == ["login.failed", "login.failed"]


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

def test_compliance_branch_maps_categories_to_levels(ctx, loader, monkeypatch):
    import app_core.eas_storage as eas_storage

    entries = [
        {"category": "received", "timestamp": _t(3), "event_label": "TOR",
         "status": "logged", "identifier": "R-1", "details": {"a": 1}},
        {"category": "relayed", "timestamp": _t(2), "event_label": "TOR",
         "status": "relayed", "identifier": "F-1", "details": {}},
        {"category": "manual", "timestamp": _t(1), "event_label": "RWT",
         "status": "sent", "identifier": "M-1", "details": None},
        {"category": "other", "timestamp": _t(0), "event_label": None,
         "status": None, "identifier": None},
    ]
    monkeypatch.setattr(
        eas_storage, "collect_compliance_log_entries",
        lambda window_days: (entries, None, None),
    )

    name, rows, meta = loader("compliance", 50)

    assert name == "Compliance Log"
    assert meta is None
    assert [r["level"] for r in rows] == ["INFO", "SUCCESS", "WARNING", "SECONDARY"]
    assert [r["module"] for r in rows] == [
        "compliance:received", "compliance:relayed",
        "compliance:manual", "compliance:other",
    ]
    assert rows[0]["message"] == "TOR — logged"
    assert rows[3]["message"] == "Unknown event — no status"
    assert rows[2]["details"] == {}   # None details normalise to {}
    assert rows[3]["alert_identifier"] is None


def test_compliance_branch_honours_the_limit(ctx, loader, monkeypatch):
    import app_core.eas_storage as eas_storage

    entries = [
        {"category": "received", "timestamp": _t(i), "event_label": f"E{i}",
         "status": "s", "identifier": f"I{i}", "details": {}}
        for i in range(5)
    ]
    monkeypatch.setattr(
        eas_storage, "collect_compliance_log_entries",
        lambda window_days: (entries, None, None),
    )
    _, rows, _ = loader("compliance", 2)
    assert len(rows) == 2


def test_compliance_branch_survives_a_failing_query(ctx, loader, monkeypatch):
    import app_core.eas_storage as eas_storage

    def _boom(window_days):
        raise RuntimeError("db down")

    monkeypatch.setattr(eas_storage, "collect_compliance_log_entries", _boom)

    name, rows, meta = loader("compliance", 50)
    assert (name, rows, meta) == ("Compliance Log", [], None)


def test_compliance_branch_uses_a_thirty_day_window(ctx, loader, monkeypatch):
    import app_core.eas_storage as eas_storage

    seen = {}

    def _capture(window_days):
        seen["window_days"] = window_days
        return ([], None, None)

    monkeypatch.setattr(eas_storage, "collect_compliance_log_entries", _capture)
    loader("compliance", 50)
    assert seen["window_days"] == 30


# ---------------------------------------------------------------------------
# FCC reports
# ---------------------------------------------------------------------------

def _install_report(monkeypatch, builder, kind="received"):
    import app_core.eas_storage as eas_storage

    monkeypatch.setitem(eas_storage.REPORT_BUILDERS, kind, builder)
    monkeypatch.setattr(
        eas_storage, "resolve_report_window",
        lambda days: (datetime(2026, 7, 8), datetime(2026, 8, 7)),
    )


def test_report_branch_mirrors_rows_and_builds_meta(ctx, loader, monkeypatch):
    def builder(window_start, window_end):
        return {
            "title": "Received Alerts",
            "subtitle": "last 30 days",
            "columns": [{"label": "When"}, {"label": "Event"}, {"label": "Note"}],
            "rows": [
                ["2026-08-07T12:00:00", "TOR", None],
                ["2026-08-06T12:00:00", "SVR", "note"],
            ],
            "summary_lines": ["2 alerts"],
            "window_start": window_start,
            "window_end": window_end,
            "row_count": 2,
        }

    _install_report(monkeypatch, builder)
    name, rows, meta = loader("report_received", 50)

    assert name == "Received Alerts (FCC report)"
    assert len(rows) == 2
    # A None cell renders as "" and is dropped from the readable fallback
    # message, but is still present as a key in ``details``.
    assert rows[0]["message"] == "When: 2026-08-07T12:00:00 · Event: TOR"
    assert rows[0]["details"] == {"When": "2026-08-07T12:00:00", "Event": "TOR", "Note": ""}
    assert rows[0]["timestamp"] == datetime(2026, 8, 7, 12, 0, 0)
    assert rows[0]["module"] == "report:received"
    assert rows[0]["alert_identifier"] is None
    assert rows[1]["message"] == "When: 2026-08-06T12:00:00 · Event: SVR · Note: note"

    assert meta == {
        "kind": "received",
        "title": "Received Alerts",
        "subtitle": "last 30 days",
        "columns": ["When", "Event", "Note"],
        "summary_lines": ["2 alerts"],
        "window_start": datetime(2026, 7, 8),
        "window_end": datetime(2026, 8, 7),
        "row_count": 2,
    }


def test_report_branch_recovers_a_timestamp_from_a_decorated_first_cell(ctx, loader, monkeypatch):
    """The builder formats timestamps as ``local / ISO UTC`` strings."""
    def builder(window_start, window_end):
        return {
            "columns": [{"label": "When"}],
            "rows": [["Aug 7 8:00 AM / 2026-08-07T12:00:00 UTC"]],
            "summary_lines": [],
            "window_start": None,
            "window_end": None,
        }

    _install_report(monkeypatch, builder)
    _, rows, _ = loader("report_received", 50)
    assert rows[0]["timestamp"] == datetime(2026, 8, 7, 12, 0, 0)


def test_report_branch_leaves_an_unparseable_timestamp_as_none(ctx, loader, monkeypatch):
    def builder(window_start, window_end):
        return {
            "columns": [{"label": "Event"}],
            "rows": [["not a date"]],
            "summary_lines": [],
            "window_start": None,
            "window_end": None,
        }

    _install_report(monkeypatch, builder)
    _, rows, _ = loader("report_received", 50)
    assert rows[0]["timestamp"] is None


def test_report_branch_honours_the_limit(ctx, loader, monkeypatch):
    def builder(window_start, window_end):
        return {
            "columns": [{"label": "Event"}],
            "rows": [[f"E{i}"] for i in range(10)],
            "summary_lines": [],
            "window_start": None,
            "window_end": None,
        }

    _install_report(monkeypatch, builder)
    _, rows, meta = loader("report_received", 3)
    assert len(rows) == 3
    # row_count is absent from the builder payload, so it falls back to the
    # number of rows actually mirrored (post-limit), not the builder's total.
    assert meta["row_count"] == 3


def test_report_branch_rejects_an_unknown_kind(ctx, loader):
    name, rows, meta = loader("report_nonsense", 50)
    assert (name, rows, meta) == ("Unknown report", [], None)


def test_report_branch_rolls_back_after_a_failing_builder(ctx, loader, monkeypatch):
    """A builder that raises leaves the session in an aborted transaction.

    Without the rollback every later query on this connection — including the
    per-request permission check — fails with InFailedSqlTransaction, so the
    page 500s well away from the actual fault.
    """
    rolled_back = []
    real_rollback = db.session.rollback

    def _tracking_rollback():
        rolled_back.append(True)
        return real_rollback()

    def builder(window_start, window_end):
        raise RuntimeError("query blew up")

    _install_report(monkeypatch, builder)
    monkeypatch.setattr(db.session, "rollback", _tracking_rollback)

    name, rows, meta = loader("report_received", 50)

    assert rolled_back, "a failing report builder must roll the session back"
    assert name == "Received Alerts (FCC report)"
    assert rows == []
    assert meta == {
        "kind": "received",
        "title": "Received Alerts (FCC report)",
        "subtitle": None,
        "columns": [],
        "summary_lines": [],
        "window_start": None,
        "window_end": None,
        "row_count": 0,
    }


def test_report_branch_titles_every_known_kind(ctx, loader, monkeypatch):
    def builder(window_start, window_end):
        return {"columns": [], "rows": [], "summary_lines": [],
                "window_start": None, "window_end": None}

    expected = {
        "received": "Received Alerts (FCC report)",
        "forwarded": "Forwarded Alerts (FCC report)",
        "ignored": "Ignored Alerts (FCC report)",
        "initiated": "Initiated Alerts (FCC report)",
        "weekly": "Weekly Summary (FCC report)",
        "monthly": "Monthly Summary (FCC report)",
    }
    for kind, title in expected.items():
        _install_report(monkeypatch, builder, kind=kind)
        name, _, _ = loader(f"report_{kind}", 50)
        assert name == title


# ---------------------------------------------------------------------------
# systemd service logs
# ---------------------------------------------------------------------------

def _journal(ts_us, message, priority="6", unit="eas-station-web.service"):
    return {"timestamp": str(ts_us), "message": message,
            "priority": priority, "unit": unit}


@pytest.fixture
def fake_journal(monkeypatch):
    """Replace the two systemd collaborators the ``services`` loader calls.

    Patched on ``logs_sources.services`` — the module that *calls* them — not
    on ``logs_data``, which merely dispatches. The ``all`` view has its own
    copy of both imports in ``logs_sources.aggregate`` and is patched
    separately below; rebinding one does not affect the other.
    """
    import webapp.public.logs_sources.services as target

    calls = []

    def _get_systemd_logs(service, lines, priority, since):
        calls.append({"service": service, "lines": lines,
                      "priority": priority, "since": since})
        return {"success": True, "logs": [
            _journal(1_754_568_000_000_000, f"{service} line 1"),
            _journal(1_754_567_000_000_000, f"{service} line 2"),
        ]}

    monkeypatch.setattr(target, "get_systemd_logs", _get_systemd_logs)
    monkeypatch.setattr(target, "get_all_log_services",
                        lambda: ["eas-station-web", "eas-station-poller"])
    return calls


def test_services_branch(ctx, loader, fake_journal):
    name, rows, meta = loader("services", 50)

    assert name == "Service Logs (systemd)"
    assert meta is None
    assert len(rows) == 4
    # Newest first across all services.
    assert rows[0]["timestamp"] == datetime.fromtimestamp(1_754_568_000_000_000 / 1_000_000)
    assert rows[0]["level"] == "INFO"
    assert rows[0]["details"] == {"service": "eas-station-web", "priority": "6"}
    assert rows[0]["module"] == "eas-station-web.service"
    # The limit is divided across the services, floored at 5.
    assert [c["lines"] for c in fake_journal] == [25, 25]
    assert [c["priority"] for c in fake_journal] == [None, None]
    assert [c["since"] for c in fake_journal] == [None, None]


def test_services_branch_floors_lines_per_service_at_five(ctx, loader, fake_journal):
    loader("services", 4)
    assert [c["lines"] for c in fake_journal] == [5, 5]


def test_services_branch_narrows_to_a_single_service(ctx, loader, fake_journal):
    _, rows, _ = loader("services", 50, service_filter="eas-station-poller")
    assert [c["service"] for c in fake_journal] == ["eas-station-poller"]
    # A single service gets the whole limit rather than a share of it.
    assert fake_journal[0]["lines"] == 50
    assert len(rows) == 2


def test_services_branch_ignores_an_unknown_service_filter(ctx, loader, fake_journal):
    """An unrecognised filter falls back to every service, not to none."""
    loader("services", 50, service_filter="not-a-service")
    assert [c["service"] for c in fake_journal] == ["eas-station-web", "eas-station-poller"]


@pytest.mark.parametrize(
    "syslog_priority,expected_level",
    [("0", "ERROR"), ("3", "ERROR"), ("4", "WARNING"), ("6", "INFO"), ("7", "INFO")],
)
def test_services_branch_maps_syslog_priority_to_level(
    ctx, loader, monkeypatch, syslog_priority, expected_level
):
    import webapp.public.logs_sources.services as target

    def _get(service, lines, priority, since):
        return {"success": True,
                "logs": [_journal(1_754_568_000_000_000, "m", priority=syslog_priority)]}

    monkeypatch.setattr(target, "get_all_log_services", lambda: ["eas-station-web"])
    monkeypatch.setattr(target, "get_systemd_logs", _get)

    _, rows, _ = loader("services", 10)
    assert rows[0]["level"] == expected_level


def test_services_branch_tolerates_a_failing_service(ctx, loader, monkeypatch):
    import webapp.public.logs_sources.services as target

    monkeypatch.setattr(target, "get_all_log_services",
                        lambda: ["good-service", "bad-service"])

    def _get(service, lines, priority, since):
        if service == "bad-service":
            return {"success": False, "error": "unit not found"}
        return {"success": True, "logs": [_journal(1_754_568_000_000_000, "ok")]}

    monkeypatch.setattr(target, "get_systemd_logs", _get)

    _, rows, _ = loader("services", 50)
    assert [r["message"] for r in rows] == ["ok"]


def test_services_branch_handles_a_missing_timestamp(ctx, loader, monkeypatch):
    import webapp.public.logs_sources.services as target

    monkeypatch.setattr(target, "get_all_log_services", lambda: ["svc"])
    monkeypatch.setattr(target, "get_systemd_logs", lambda service, lines, priority, since: {
        "success": True,
        "logs": [{"message": "no ts", "priority": "6", "unit": "svc"},
                 _journal(1_754_568_000_000_000, "has ts")],
    })

    _, rows, _ = loader("services", 50)
    # A row with no timestamp sorts to the bottom rather than raising.
    assert [r["message"] for r in rows] == ["has ts", "no ts"]
    assert rows[1]["timestamp"] is None


# ---------------------------------------------------------------------------
# The 'all' aggregate
# ---------------------------------------------------------------------------

@pytest.fixture
def no_journal(monkeypatch):
    """Silence the systemd collector so 'all' only sees database categories."""
    import webapp.public.logs_sources.aggregate as target

    monkeypatch.setattr(target, "get_all_log_services", lambda: [])
    monkeypatch.setattr(
        target, "get_systemd_logs",
        lambda *a, **k: {"success": False, "error": "no journal"},
    )


def test_all_branch_labels_every_category(ctx, loader, no_journal):
    _system_log(timestamp=_t(10))
    _poll_history(timestamp=_t(9))
    _audio_alert(created_at=_t(8))
    _gpio_log(activated_at=_t(7))
    _eas_message(created_at=_t(6))
    _manual_activation(created_at=_t(5))
    _received_alert(received_at=_t(4))
    _poll_debug(created_at=_t(3))
    _audio_metrics(timestamp=_t(2))
    _audio_health(timestamp=_t(1))
    _decoded_audio(created_at=_t(0))

    name, rows, meta = loader("all", 100)

    assert name == "All Logs"
    assert meta is None
    # Newest first, one row per category, each carrying its own label.
    assert [r["category"] for r in rows] == [
        "System", "Polling", "Audio", "GPIO", "EAS Messages",
        "Manual Activations", "Received EAS", "Polling Debug",
        "Audio Metrics", "Audio Health", "Decoded Audio",
    ]


def test_all_branch_gives_each_category_a_share_of_the_limit(ctx, loader, no_journal):
    """``logs_per_category`` is ``max(10, limit // 10)``."""
    for i in range(30):
        _system_log(timestamp=_t(i), message=f"m{i}")

    # limit // 10 == 2, but the floor of 10 wins.
    _, rows, _ = loader("all", 20)
    assert len(rows) == 10

    # limit // 10 == 15, which now exceeds the floor.
    _, rows, _ = loader("all", 150)
    assert len(rows) == 15


def test_all_branch_truncates_the_merged_list_to_the_limit(ctx, loader, no_journal):
    for i in range(20):
        _system_log(timestamp=_t(i), message=f"s{i}")
    for i in range(20):
        _audio_alert(created_at=_t(i), message=f"a{i}")

    _, rows, _ = loader("all", 100)
    # 10 per category by the floor, both categories present, merged and sorted.
    assert len(rows) == 20

    _, rows, _ = loader("all", 12)
    assert len(rows) == 12


def test_all_branch_rows_carry_the_compact_detail_shape(ctx, loader, no_journal):
    """'all' deliberately carries fewer detail keys than the focused views."""
    _poll_history()
    _, rows, _ = loader("all", 100)

    assert rows[0]["details"] == {
        "execution_time_ms": 123,
        "error": None,
        "data_source": "NOAA",
    }
    # No Accepted/Filtered segments here, unlike the focused 'polling' view.
    assert rows[0]["message"] == "Status: success | Fetched: 7 | New: 2 | Updated: 1"
    assert "alert_identifier" not in rows[0]


def test_all_branch_sorts_naive_and_aware_timestamps_together(ctx, loader, no_journal, monkeypatch):
    """Journal rows are naive, database rows may be aware — one sort key."""
    import webapp.public.logs_sources.aggregate as target

    _system_log(timestamp=_t(0), message="db row")
    monkeypatch.setattr(target, "get_all_log_services", lambda: ["svc"])
    monkeypatch.setattr(target, "get_systemd_logs", lambda service, lines, priority, since: {
        "success": True,
        # 2030-01-01, far enough ahead of the database row that the ordering
        # holds whatever local zone `datetime.fromtimestamp` renders it in.
        "logs": [_journal(1_893_456_000_000_000, "journal row")],
    })

    _, rows, _ = loader("all", 100)
    assert [r["message"] for r in rows] == ["journal row", "db row"]


def test_all_branch_survives_a_broken_category(ctx, loader, no_journal, monkeypatch):
    """One category raising must not take the whole page down."""
    _system_log(timestamp=_t(5))
    _audio_alert(created_at=_t(4))

    class _Boom:
        def order_by(self, *a, **k):
            raise RuntimeError("table gone")

    monkeypatch.setattr(GPIOActivationLog, "query", _Boom())

    _, rows, _ = loader("all", 100)
    categories = {r["category"] for r in rows}
    assert "System" in categories and "Audio" in categories
    assert "GPIO" not in categories


def test_all_branch_divides_journal_lines_across_services(ctx, loader, monkeypatch):
    import webapp.public.logs_sources.aggregate as target

    calls = []
    monkeypatch.setattr(target, "get_all_log_services", lambda: ["a", "b", "c"])

    def _get(service, lines, priority, since):
        calls.append(lines)
        return {"success": True, "logs": []}

    monkeypatch.setattr(target, "get_systemd_logs", _get)

    loader("all", 300)          # logs_per_category = 30, // 3 services = 10
    assert calls == [10, 10, 10]

    calls.clear()
    loader("all", 20)           # logs_per_category floors at 10, // 3 == 3
    assert calls == [3, 3, 3]
