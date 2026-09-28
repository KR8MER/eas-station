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

"""Off-air self-monitoring (air-check): header matching and record lifecycle.

The lifecycle tests run the real queries against an in-memory SQLite
session holding just the tables the air-check touches.
"""

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app_core.air_check import (
    ROLE_AIR_CHECK,
    collect_air_check_issues,
    compare_headers,
    normalize_header,
    parse_header,
    record_off_air_decode,
    register_transmission,
    resolve_source_role,
    sweep_overdue,
)
from app_core.air_check import roles as air_check_roles
from app_core.air_check.matching import is_candidate
from app_core.models import AirCheckRecord, AirCheckSettings, RadioReceiver, SystemLog
from app_utils import utc_now

ROOT = Path(__file__).resolve().parents[1]

SENT = "ZCZC-WXR-TOR-039137-039041+0030-2711200-KR8MER  -"
SENT_NORMALIZED = "ZCZC-WXR-TOR-039137-039041+0030-2711200-KR8MER-"


# ---------------------------------------------------------------------------
# Header matching (pure)
# ---------------------------------------------------------------------------

class TestMatching:
    def test_normalize_strips_padding_and_keeps_one_trailing_dash(self):
        assert normalize_header(SENT) == SENT_NORMALIZED
        assert normalize_header(SENT_NORMALIZED.rstrip("-")) == SENT_NORMALIZED
        assert normalize_header("noise ZCZC-WXR-RWT-039137+0015-2711200-KR8MER-") == \
            "ZCZC-WXR-RWT-039137+0015-2711200-KR8MER-"
        assert normalize_header("NNNN") == ""
        assert normalize_header(None) == ""

    def test_parse_splits_every_field(self):
        assert parse_header(SENT) == {
            "originator": "WXR",
            "event_code": "TOR",
            "locations": ["039041", "039137"],
            "purge": "0030",
            "issue_time": "2711200",
            "station": "KR8MER",
        }

    def test_parse_rejects_malformed_headers(self):
        assert parse_header("ZCZC-WXR-TOR") is None
        assert parse_header("ZCZC-WXR-TOR-039137-2711200-KR8MER-") is None  # no +TTTT

    def test_identical_headers_are_exact(self):
        result = compare_headers(SENT, SENT_NORMALIZED)
        assert result["exact"] is True
        assert result["mismatched"] == []

    def test_location_order_does_not_matter(self):
        reordered = "ZCZC-WXR-TOR-039041-039137+0030-2711200-KR8MER-"
        assert compare_headers(SENT, reordered)["exact"] is True

    def test_changed_station_id_is_a_mismatch_on_that_field_only(self):
        heard = "ZCZC-WXR-TOR-039137-039041+0030-2711200-WXYZ-"
        result = compare_headers(SENT, heard)
        assert result["exact"] is False
        assert result["mismatched"] == ["station"]
        assert is_candidate(result)

    def test_unrelated_header_is_not_a_candidate(self):
        other = "ZCZC-CIV-CAE-048001+0100-2720000-OTHER-"
        assert not is_candidate(compare_headers(SENT, other))

    def test_unparseable_header_matches_nothing(self):
        result = compare_headers(SENT, "ZCZC-garbage")
        assert result["parsed"] is False
        assert not is_candidate(result)


# ---------------------------------------------------------------------------
# Record lifecycle (SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        RadioReceiver.__table__,
        AirCheckRecord.__table__,
        AirCheckSettings.__table__,
        SystemLog.__table__,
    ]
    RadioReceiver.metadata.create_all(engine, tables=tables)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()
    engine.dispose()


def _add_receiver(session, role=ROLE_AIR_CHECK, enabled=True, identifier="aircheck"):
    session.add(RadioReceiver(
        identifier=identifier, display_name=identifier, driver="rtlsdr",
        frequency_hz=162_550_000.0, sample_rate=2_400_000, role=role, enabled=enabled,
    ))
    session.commit()


def _decode(session, header, source="sdr-aircheck"):
    return record_off_air_decode(
        {"raw_header": header, "source_name": source, "confidence": 0.93},
        receiver_identifier="aircheck", session=session,
    )


def _levels(session):
    return [row.level for row in session.query(SystemLog).all()]


class TestLifecycle:
    def test_nothing_is_opened_without_an_air_check_receiver(self, session):
        _add_receiver(session, role="monitor")
        _add_receiver(session, identifier="disabled", enabled=False)
        assert register_transmission(SENT, origin_type="broadcast", session=session) is None
        assert session.query(AirCheckRecord).count() == 0

    def test_heard_exactly_is_verified(self, session):
        _add_receiver(session)
        record = register_transmission(SENT, origin_type="broadcast", origin_id=7,
                                       playout_seconds=30, session=session)
        assert record.status == "pending"
        assert record.expected_header == SENT_NORMALIZED
        assert record.event_code == "TOR"

        _decode(session, SENT_NORMALIZED)
        session.refresh(record)
        assert record.status == "verified"
        assert record.receiver_identifier == "aircheck"
        assert record.decode_confidence == pytest.approx(0.93)
        assert "INFO" in _levels(session)

    def test_heard_with_a_different_field_is_a_mismatch_error(self, session):
        _add_receiver(session)
        record = register_transmission(SENT, origin_type="manual", session=session)
        _decode(session, "ZCZC-WXR-TOR-039137-039041+0030-2711200-WXYZ-")
        session.refresh(record)
        assert record.status == "mismatch"
        assert record.mismatch_fields == ["station"]
        assert "Station ID" in record.detail
        assert "ERROR" in _levels(session)

    def test_not_heard_by_the_deadline_is_missed_and_raises_an_error(self, session):
        _add_receiver(session)
        record = register_transmission(SENT, origin_type="rwt", session=session)
        record.deadline_at = utc_now() - timedelta(seconds=1)
        session.commit()

        assert sweep_overdue(session) == 1
        session.refresh(record)
        assert record.status == "missed"
        assert "ERROR" in _levels(session)
        assert any("NOT heard" in issue for issue in collect_air_check_issues(session))

        record.acknowledged_at = utc_now()
        session.commit()
        assert collect_air_check_issues(session) == []

    def test_pending_within_deadline_is_not_swept(self, session):
        _add_receiver(session)
        register_transmission(SENT, origin_type="broadcast", playout_seconds=60, session=session)
        assert sweep_overdue(session) == 0

    def test_late_decode_after_missed_is_verified_with_a_note(self, session):
        _add_receiver(session)
        record = register_transmission(SENT, origin_type="broadcast", session=session)
        record.deadline_at = utc_now() - timedelta(seconds=30)
        session.commit()
        sweep_overdue(session)

        _decode(session, SENT)
        session.refresh(record)
        assert record.status == "verified"
        assert "after the deadline" in record.detail

    def test_header_we_did_not_send_is_unexpected_once(self, session):
        _add_receiver(session)
        other = "ZCZC-CIV-CAE-048001+0100-2720000-OTHER-"
        first = _decode(session, other)
        assert first.status == "unexpected"
        assert _decode(session, other) is None  # repeat is not recorded twice
        assert session.query(AirCheckRecord).count() == 1
        assert "WARNING" in _levels(session)

    def test_decode_that_arrives_before_registration_is_adopted(self, session):
        _add_receiver(session)
        _decode(session, SENT)
        assert session.query(AirCheckRecord).one().status == "unexpected"

        record = register_transmission(SENT, origin_type="manual", origin_id=3, session=session)
        assert record.status == "verified"
        assert session.query(AirCheckRecord).count() == 1

    def test_resend_of_same_header_closes_its_own_record(self, session):
        _add_receiver(session)
        original = register_transmission(SENT, origin_type="broadcast", session=session)
        _decode(session, SENT)
        resend = register_transmission(SENT, origin_type="resend", session=session)
        _decode(session, SENT)
        session.refresh(original)
        session.refresh(resend)
        assert original.status == "verified"
        assert resend.status == "verified"

    def test_garbled_repeat_does_not_downgrade_a_verified_record(self, session):
        _add_receiver(session)
        record = register_transmission(SENT, origin_type="broadcast", session=session)
        _decode(session, SENT)
        _decode(session, "ZCZC-WXR-TOR-039137-039041+0030-2711200-KR8MEX-")
        session.refresh(record)
        assert record.status == "verified"

    def test_grace_period_setting_extends_the_deadline(self, session):
        _add_receiver(session)
        session.add(AirCheckSettings(id=1, grace_seconds=300))
        session.commit()
        before = utc_now()
        record = register_transmission(SENT, origin_type="broadcast", playout_seconds=10,
                                       session=session)
        deadline = record.deadline_at.replace(tzinfo=before.tzinfo)
        assert deadline - before >= timedelta(seconds=310)


# ---------------------------------------------------------------------------
# Source -> receiver role resolution
# ---------------------------------------------------------------------------

def test_resolve_source_role_follows_audio_source_to_receiver():
    air_check_roles.clear_role_cache()
    cfg = MagicMock(config_params={"device_params": {"receiver_id": "aircheck"}})
    receiver = MagicMock(role=ROLE_AIR_CHECK)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.side_effect = [cfg, receiver]

    assert resolve_source_role("sdr-aircheck", session=session) == (ROLE_AIR_CHECK, "aircheck")
    # Cached: a second lookup does not hit the database.
    assert resolve_source_role("sdr-aircheck", session=session) == (ROLE_AIR_CHECK, "aircheck")
    assert session.query.call_count == 2
    air_check_roles.clear_role_cache()


def test_non_sdr_source_has_no_role():
    air_check_roles.clear_role_cache()
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    assert resolve_source_role("http-stream", session=session) == (None, None)
    air_check_roles.clear_role_cache()


# ---------------------------------------------------------------------------
# Receiver payload validation
# ---------------------------------------------------------------------------

def test_receiver_payload_accepts_known_roles_and_rejects_others():
    from webapp.radio_settings.payload import _parse_receiver_payload

    data, error = _parse_receiver_payload({"role": "AIR_CHECK"}, partial=True)
    assert error is None and data["role"] == "air_check"

    _, error = _parse_receiver_payload({"role": "transmitter"}, partial=True)
    assert error == "Invalid receiver role."

    data, _ = _parse_receiver_payload({"frequency_hz": 1}, partial=True)
    assert "role" not in data  # partial update leaves the role alone


# ---------------------------------------------------------------------------
# Wiring: every transmit path registers, and air-check decodes never relay
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path, origin", [
    ("app_utils/eas/broadcaster.py", "origin_type='broadcast'"),
    ("webapp/eas/workflow.py", "origin_type='manual'"),
    ("app_core/rwt_scheduler.py", "origin_type='rwt'"),
    ("scripts/resend_eas_broadcast.py", "origin_type='resend'"),
])
def test_every_transmit_path_opens_an_air_check(path, origin):
    source = (ROOT / path).read_text()
    assert "register_transmission(" in source
    assert origin in source


def test_air_check_decodes_are_diverted_before_relay_filtering():
    source = (ROOT / "eas_monitoring_service.py").read_text()
    divert = source.index("if role == ROLE_AIR_CHECK:")
    relay = source.index("return _alert_callback_inner(alert)")
    assert divert < relay
