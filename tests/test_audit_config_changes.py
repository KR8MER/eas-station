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

from __future__ import annotations

"""Tests for configuration-change auditing (AuditLogger.log_config_change).

These guard the regression fixed when settings-save routes (environment,
application, hardware, TTS, poller, icecast) and the EAS send/purge actions
were wired into the tamper-evident audit ledger.  Previously a user could
change a setting or transmit an alert with no record of *who* did it.

The test exercises the cryptographic core over a SQLite-backed AuditLog,
mirroring tests/test_audit_chain.py -- no PostGIS or app factory required.
"""

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app_core.extensions import db
from app_core.auth import _audit_signing_key as signing_key_mod
from app_core.auth.audit import AuditAction, AuditLog, AuditLogger


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def app_context(tmp_path, monkeypatch):
    database_path = tmp_path / "audit_config.db"
    app = Flask("audit-config-test")
    app.secret_key = "test-secret-key-for-session"
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    key_path = tmp_path / "audit_signing.key"
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    pk = Ed25519PrivateKey.generate()
    key_path.write_bytes(
        pk.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("AUDIT_SIGNING_KEY_PATH", str(key_path))
    signing_key_mod.reset_signing_key_cache_for_tests()

    with app.app_context():
        engine = db.engine
        AuditLog.__table__.create(bind=engine)
        try:
            yield app
        finally:
            db.session.remove()
            AuditLog.__table__.drop(bind=engine)
            signing_key_mod.reset_signing_key_cache_for_tests()


def test_log_config_change_records_config_updated(app_context):
    """A settings save records a chained, signed config.updated row."""
    row = AuditLogger.log_config_change(
        resource_type="poller_settings",
        resource_id="1",
        details={"enabled": True, "poll_interval_sec": 120},
    )

    assert row.action == AuditAction.CONFIG_UPDATED.value
    assert row.resource_type == "poller_settings"
    assert row.resource_id == "1"
    assert row.details["enabled"] is True
    assert row.success is True
    # Chained + signed like every other audit row.
    assert row.entry_hash is not None and len(row.entry_hash) == 64
    assert row.signature is not None
    assert AuditLogger.verify_chain()["ok"] is True


def test_log_config_change_captures_session_user(app_context):
    """The acting user is auto-detected from the Flask session.

    This is the whole point of the change: answering "who changed this
    setting".  Inside a request context with session['user_id'] set, the
    audit row must carry that user_id.
    """
    with app_context.test_request_context("/admin/poller/update"):
        from flask import session
        session["user_id"] = 42

        row = AuditLogger.log_config_change(
            resource_type="application_settings",
            details={"changed_fields": ["log_level"]},
        )

    assert row.user_id == 42


def test_log_config_change_failure_is_recorded(app_context):
    """A failed config change can be recorded with success=False."""
    row = AuditLogger.log_config_change(
        resource_type="icecast_settings",
        details={"error": "bad port"},
        success=False,
    )
    assert row.action == AuditAction.CONFIG_UPDATED.value
    assert row.success is False


def test_secret_values_are_not_persisted_in_details(app_context):
    """Security invariant: secret values never land in the audit trail.

    The settings routes that touch credentials (TTS, Icecast) pass only the
    changed field *names* for secret-bearing keys, never the values. This
    mirrors that contract: a details dict built the way those routes build it
    must not contain the secret string anywhere in the persisted row.
    """
    # Simulate the redaction the TTS/Icecast routes perform before calling the
    # helper: secret-bearing keys contribute their name to changed_fields only.
    submitted = {
        "provider": "azure_openai",
        "azure_openai_api_key": "super-secret-value-123",
        "admin_password": "p@ssw0rd!",
    }
    sensitive = ("key", "password", "secret", "token")
    details = {"changed_fields": sorted(submitted.keys())}
    for k, v in submitted.items():
        if not any(s in k.lower() for s in sensitive):
            details[k] = v

    row = AuditLogger.log_config_change(resource_type="tts_settings", details=details)

    # Field names are recorded...
    assert "azure_openai_api_key" in row.details["changed_fields"]
    assert "admin_password" in row.details["changed_fields"]
    # ...but the secret values appear nowhere in the persisted row.
    import json
    serialized = json.dumps(row.details)
    assert "super-secret-value-123" not in serialized
    assert "p@ssw0rd!" not in serialized
    assert row.details.get("provider") == "azure_openai"


def test_raise_on_error_propagates_write_failure(app_context, monkeypatch):
    """raise_on_error=True surfaces a failed ledger write; default swallows it.

    This backs the fail-closed manual-EAS purge: if the tamper-evident row
    cannot be written, the caller must be able to abort instead of silently
    deleting compliance records with no audit trail.
    """
    def _boom(_entry):
        raise RuntimeError("simulated signing failure")

    monkeypatch.setattr(AuditLogger, "_chain_and_sign", staticmethod(_boom))

    # Default behavior: failure is logged and swallowed (returns the entry).
    AuditLogger.log(
        action=AuditAction.ALERT_DELETED,
        resource_type="manual_eas_activation",
        details={"deleted_ids": [1]},
    )

    # Fail-closed behavior: the failure propagates so the caller can abort.
    with pytest.raises(RuntimeError, match="simulated signing failure"):
        AuditLogger.log(
            action=AuditAction.ALERT_DELETED,
            resource_type="manual_eas_activation",
            details={"deleted_ids": [1]},
            raise_on_error=True,
        )


def test_eas_broadcast_and_delete_actions_chain(app_context):
    """EAS transmission and purge land in the tamper-evident ledger."""
    sent = AuditLogger.log(
        action=AuditAction.EAS_BROADCAST,
        resource_type="manual_eas_activation",
        resource_id="7",
        details={"event_code": "RWT", "triggered_by": "operator"},
    )
    purged = AuditLogger.log(
        action=AuditAction.ALERT_DELETED,
        resource_type="manual_eas_activation",
        details={"deleted_ids": [7], "deleted_count": 1},
    )

    assert sent.action == AuditAction.EAS_BROADCAST.value
    assert purged.action == AuditAction.ALERT_DELETED.value
    assert purged.prev_hash == sent.entry_hash
    assert AuditLogger.verify_chain()["ok"] is True
