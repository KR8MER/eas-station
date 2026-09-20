"""Tests for the public, no-login /status page's data aggregator.

Deliberately does not go through app_client: every request runs
app.py's before_request -> initialize_database() -> db.create_all(), which
fails against the SQLite test database because unrelated tables elsewhere
in the schema use JSONB (not representable on SQLite) -- the same reason
tests/test_support_smoke.py and friends are already listed in
tests/known_failures.txt rather than exercised via the test client. Instead
this calls the aggregator functions directly inside an app context, only
creating the specific tables they touch, matching the pattern
tests/test_import_alert_batching.py already uses for the same reason.

Route registration and the public/no-login guarantee are covered
separately and cheaply (no DB, no app context) by
tests/test_public_route_audit.py and tests/test_public_pages_authz.py.
"""

from datetime import timedelta

from app_core.extensions import db
from app_core.auth.audit import AuditAction, AuditLog
from app_core.models import CAPAlert, EASMessage
from app_utils import utc_now
from webapp.public import status_page


def _create_tables(app):
    with app.app_context():
        db.metadata.create_all(
            bind=db.engine,
            tables=[CAPAlert.__table__, EASMessage.__table__, AuditLog.__table__],
        )


def test_collect_public_status_with_empty_database(app):
    _create_tables(app)
    with app.app_context():
        data = status_page._collect_public_status(app.logger)

    assert data["audit_chain"] == {"last_verified_at": None, "ok": None}
    assert data["compliance"]["rwt_status"] == "unknown"
    assert data["compliance"]["rmt_status"] == "unknown"
    assert data["alerts_monitored"] == 0
    assert "services" in data


def test_last_same_message_at_matches_event_code(app):
    _create_tables(app)
    now = utc_now()
    with app.app_context():
        db.session.add(
            EASMessage(
                same_header="ZCZC-WXR-RWT-039173+0015-2632000-KR8MER  -",
                audio_filename="a.wav",
                text_filename="a.txt",
                created_at=now,
            )
        )
        db.session.add(
            EASMessage(
                same_header="ZCZC-WXR-RMT-039173+0100-2632000-KR8MER  -",
                audio_filename="b.wav",
                text_filename="b.txt",
                created_at=now - timedelta(days=40),
            )
        )
        db.session.commit()

        rwt_at = status_page._last_same_message_at("RWT")
        rmt_at = status_page._last_same_message_at("RMT")
        assert rwt_at is not None
        assert rmt_at is not None

        data = status_page._collect_public_status(app.logger)
        assert data["compliance"]["rwt_status"] == "current"
        assert data["compliance"]["rmt_status"] == "overdue"


def test_audit_chain_summary_reflects_most_recent_verification(app):
    _create_tables(app)
    with app.app_context():
        db.session.add(
            AuditLog(
                action=AuditAction.AUDIT_CHAIN_VERIFIED.value,
                success=True,
                resource_type="audit_chain",
            )
        )
        db.session.commit()

        summary = status_page._audit_chain_summary()
        assert summary["ok"] is True
        assert summary["last_verified_at"] is not None
