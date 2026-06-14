"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Tests for the received-alert purge service (app_core/alert_purge.py)."""

from datetime import timedelta

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app_core import alert_purge
from app_core._models_admin import SystemLog
from app_core._models_alerts import EASMessage, ReceivedEASAlert
from app_core._models_settings import AutoPurgeSettings
from app_core.extensions import db
from app_utils import utc_now


# SQLite cannot render the PostgreSQL JSONB columns some models declare;
# map them to plain JSON for the in-memory test database.
@compiles(JSONB, "sqlite")
def _render_jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def app():
    """Minimal Flask app bound to an in-memory SQLite database."""
    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["TESTING"] = True
    db.init_app(flask_app)

    with flask_app.app_context():
        db.metadata.create_all(
            bind=db.engine,
            tables=[
                ReceivedEASAlert.__table__,
                EASMessage.__table__,
                AutoPurgeSettings.__table__,
                SystemLog.__table__,
            ],
        )
        yield flask_app
        db.session.remove()


def _seed(now):
    """Seed a mix of old/new, forwarded/ignored alerts and return the count."""
    old = now - timedelta(days=120)
    recent = now - timedelta(days=1)

    msg = EASMessage(
        same_header="ZCZC-EAS-RWT-000000+0015-1000000-TEST-",
        audio_filename="msg.wav",
        text_filename="msg.json",
    )
    db.session.add(msg)
    db.session.flush()

    db.session.add_all([
        # old + ignored + audio (the noisy stream captures)
        ReceivedEASAlert(
            received_at=old, source_name="ERN/DON", alert_source="EAS-STREAM",
            event_code="SVR", forwarding_decision="ignored", raw_audio_data=b"X" * 100,
        ),
        ReceivedEASAlert(
            received_at=old, source_name="ERN/DON", alert_source="EAS-STREAM",
            event_code="RWT", forwarding_decision="ignored", raw_audio_data=b"X" * 50,
        ),
        # old + error + audio
        ReceivedEASAlert(
            received_at=old, source_name="SDR-1", alert_source="EAS-RF",
            event_code="SVR", forwarding_decision="error", raw_audio_data=b"X" * 25,
        ),
        # old + forwarded + audio + linked message
        ReceivedEASAlert(
            received_at=old, source_name="SDR-1", alert_source="EAS-RF",
            event_code="TOR", forwarding_decision="forwarded", raw_audio_data=b"X" * 200,
            generated_message_id=msg.id,
        ),
        # recent + ignored + audio (should survive an age purge)
        ReceivedEASAlert(
            received_at=recent, source_name="ERN/DON", alert_source="EAS-STREAM",
            event_code="SVR", forwarding_decision="ignored", raw_audio_data=b"X" * 10,
        ),
    ])
    db.session.commit()
    return msg.id


# ---------------------------------------------------------------------------
# Criteria normalisation
# ---------------------------------------------------------------------------

class TestNormalizeCriteria:
    def test_defaults(self):
        c = alert_purge.normalize_criteria({})
        assert c["older_than_days"] is None
        assert c["source"] is None
        assert c["decision"] == "any"
        assert c["scope"] == "full"
        assert c["delete_generated_messages"] is False

    def test_parses_and_uppercases_event(self):
        c = alert_purge.normalize_criteria(
            {"older_than_days": "30", "source": "ERN/DON",
             "decision": "ignored", "event_code": "svr", "scope": "audio",
             "delete_generated_messages": "true"}
        )
        assert c["older_than_days"] == 30
        assert c["source"] == "ERN/DON"
        assert c["decision"] == "ignored"
        assert c["event_code"] == "SVR"
        assert c["scope"] == "audio"
        assert c["delete_generated_messages"] is True

    def test_zero_days_becomes_none(self):
        assert alert_purge.normalize_criteria({"older_than_days": "0"})["older_than_days"] is None

    def test_rejects_bad_values(self):
        with pytest.raises(ValueError):
            alert_purge.normalize_criteria({"older_than_days": "abc"})
        with pytest.raises(ValueError):
            alert_purge.normalize_criteria({"decision": "nonsense"})
        with pytest.raises(ValueError):
            alert_purge.normalize_criteria({"scope": "nuke"})
        with pytest.raises(ValueError):
            alert_purge.normalize_criteria({"older_than_days": "99999"})


# ---------------------------------------------------------------------------
# Preview / stats
# ---------------------------------------------------------------------------

class TestPreview:
    def test_age_filter_counts(self, app):
        now = utc_now()
        _seed(now)
        crit = alert_purge.normalize_criteria({"older_than_days": "30"})
        preview = alert_purge.preview_purge(crit, now=now)
        # 4 of 5 are older than 30 days
        assert preview["matching_count"] == 4
        assert preview["audio_count"] == 4
        assert preview["audio_bytes"] == 100 + 50 + 25 + 200

    def test_not_forwarded_filter(self, app):
        now = utc_now()
        _seed(now)
        crit = alert_purge.normalize_criteria({"decision": "not_forwarded"})
        preview = alert_purge.preview_purge(crit, now=now)
        # 4 not-forwarded (2 old ignored, 1 error, 1 recent ignored)
        assert preview["matching_count"] == 4

    def test_source_filter(self, app):
        now = utc_now()
        _seed(now)
        crit = alert_purge.normalize_criteria({"source": "ERN/DON"})
        preview = alert_purge.preview_purge(crit, now=now)
        assert preview["matching_count"] == 3

    def test_storage_stats(self, app):
        now = utc_now()
        _seed(now)
        stats = alert_purge.get_storage_stats()
        assert stats["total"] == 5
        assert stats["with_audio"] == 5
        assert stats["forwarded"] == 1
        assert stats["ignored"] == 3
        assert stats["error"] == 1


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class TestExecutePurge:
    def test_full_purge_deletes_rows_and_logs(self, app):
        now = utc_now()
        _seed(now)
        crit = alert_purge.normalize_criteria({"older_than_days": "30", "scope": "full"})
        summary = alert_purge.execute_purge(crit, actor="tester", now=now)

        assert summary["rows_deleted"] == 4
        assert summary["audio_bytes_freed"] == 375
        assert db.session.query(ReceivedEASAlert).count() == 1  # the recent one

        # An audit entry was written (logs are never purged).
        audit = db.session.query(SystemLog).filter_by(module="alert_purge").all()
        assert len(audit) == 1
        assert audit[0].details["rows_deleted"] == 4

    def test_audio_scope_strips_blob_keeps_rows(self, app):
        now = utc_now()
        _seed(now)
        crit = alert_purge.normalize_criteria({"older_than_days": "30", "scope": "audio"})
        summary = alert_purge.execute_purge(crit, actor="tester", now=now)

        assert summary["audio_stripped"] == 4
        assert summary["rows_deleted"] == 0
        # No rows deleted; 4 blobs nulled, recent one still has audio.
        assert db.session.query(ReceivedEASAlert).count() == 5
        remaining_audio = (
            db.session.query(ReceivedEASAlert)
            .filter(ReceivedEASAlert.raw_audio_data.isnot(None))
            .count()
        )
        assert remaining_audio == 1

    def test_full_purge_deletes_generated_message(self, app):
        now = utc_now()
        msg_id = _seed(now)
        crit = alert_purge.normalize_criteria({
            "decision": "forwarded", "scope": "full",
            "delete_generated_messages": "true",
        })
        summary = alert_purge.execute_purge(crit, actor="tester", now=now)

        assert summary["rows_deleted"] == 1
        assert summary["messages_deleted"] == 1
        assert db.session.get(EASMessage, msg_id) is None

    def test_full_purge_keeps_message_when_not_requested(self, app):
        now = utc_now()
        msg_id = _seed(now)
        crit = alert_purge.normalize_criteria({"decision": "forwarded", "scope": "full"})
        summary = alert_purge.execute_purge(crit, actor="tester", now=now)

        assert summary["rows_deleted"] == 1
        assert summary["messages_deleted"] == 0
        assert db.session.get(EASMessage, msg_id) is not None

    def test_refuses_empty_criteria(self, app):
        now = utc_now()
        _seed(now)
        crit = alert_purge.normalize_criteria({})
        with pytest.raises(ValueError):
            alert_purge.execute_purge(crit, actor="tester", now=now)
        # Nothing was deleted.
        assert db.session.query(ReceivedEASAlert).count() == 5


# ---------------------------------------------------------------------------
# Auto-purge settings + run
# ---------------------------------------------------------------------------

class TestAutoPurge:
    def test_get_creates_defaults(self, app):
        settings = alert_purge.get_auto_purge_settings()
        assert settings.id == 1
        assert settings.enabled is False
        assert settings.max_age_days == 30
        assert settings.scope == "full"
        assert settings.decision_filter == "not_forwarded"

    def test_update_validates(self, app):
        updated = alert_purge.update_auto_purge_settings(
            {"enabled": "true", "max_age_days": "7", "scope": "audio"}
        )
        assert updated["enabled"] is True
        assert updated["max_age_days"] == 7
        assert updated["scope"] == "audio"

        with pytest.raises(ValueError):
            alert_purge.update_auto_purge_settings({"max_age_days": "-1"})
        with pytest.raises(ValueError):
            alert_purge.update_auto_purge_settings({"decision_filter": "bogus"})

    def test_run_skipped_when_disabled(self, app):
        now = utc_now()
        _seed(now)
        result = alert_purge.run_auto_purge(now=now)
        assert result.get("skipped") is True
        assert db.session.query(ReceivedEASAlert).count() == 5

    def test_run_purges_not_forwarded_old(self, app):
        now = utc_now()
        _seed(now)
        alert_purge.update_auto_purge_settings({
            "enabled": "true", "max_age_days": "30",
            "scope": "full", "decision_filter": "not_forwarded",
        })
        summary = alert_purge.run_auto_purge(now=now)

        # old ignored (2) + old error (1) = 3 removed; forwarded + recent survive
        assert summary["rows_deleted"] == 3
        assert db.session.query(ReceivedEASAlert).count() == 2

        settings = alert_purge.get_auto_purge_settings()
        assert settings.last_run_at is not None
        assert settings.last_run_summary["rows_deleted"] == 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHumanBytes:
    def test_formats(self):
        assert alert_purge.human_bytes(512) == "512 B"
        assert alert_purge.human_bytes(2048) == "2.0 KB"
        assert alert_purge.human_bytes(5 * 1024 * 1024) == "5.0 MB"
