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

"""Tests for the tamper-evident audit-log chain.

These exercise the cryptographic core (chain linkage, content hashing,
Ed25519 signing/verification) over a SQLite-backed AuditLog model -- the
same approach used by ``test_location_reference.py`` for the location
settings tables.  No PostGIS or full app factory is required.
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
    # Use an explicit on-disk SQLite file so each test gets a fresh
    # AuditLog table without leaking rows between tests.
    database_path = tmp_path / "audit_chain.db"
    app = Flask("audit-chain-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    # Ensure each test starts with a freshly-resolved keypair.  Use a
    # deterministic key file rather than the process-wide ephemeral so
    # tampering tests can rely on a stable public key.
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


def _make_row(action=AuditAction.LOGIN_SUCCESS, **overrides):
    """Helper: insert a row via AuditLogger.log and return the persisted instance."""
    details = overrides.pop("details", {"k": "v"})
    return AuditLogger.log(action=action, details=details, **overrides)


# ---------------------------------------------------------------------------
# Happy path: chain links + verifier accepts the result
# ---------------------------------------------------------------------------

def test_chain_links_consecutive_rows(app_context):
    r1 = _make_row()
    r2 = _make_row()
    r3 = _make_row()

    assert r1.entry_hash is not None and len(r1.entry_hash) == 64
    assert r2.entry_hash is not None and r2.prev_hash == r1.entry_hash
    assert r3.entry_hash is not None and r3.prev_hash == r2.entry_hash
    # Genesis row has the 64-zero sentinel
    assert r1.prev_hash == "0" * 64


def test_verify_chain_accepts_unmodified_chain(app_context):
    for _ in range(5):
        _make_row()

    result = AuditLogger.verify_chain()
    assert result["ok"] is True, result
    assert result["checked"] == 5
    assert result["unsigned"] == 0
    assert result["first_bad_id"] is None
    assert result["reason"] is None


def test_signature_is_valid_ed25519(app_context):
    row = _make_row(details={"sample": True})
    assert row.signature is not None

    # Manually verify against the public half of the configured key.
    _pri, pub, source = signing_key_mod.get_signing_keypair()
    assert source == "env"  # we set AUDIT_SIGNING_KEY_PATH in the fixture

    import hashlib
    payload = row.canonical_content()
    payload["prev_hash"] = row.prev_hash
    digest = hashlib.sha256(AuditLogger._canonical_json(payload)).digest()
    pub.verify(bytes.fromhex(row.signature), digest)  # raises if bad


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------

def test_tamper_in_details_is_detected(app_context):
    r1 = _make_row(details={"original": True})
    _make_row(details={"original": True})

    # Mutate the persisted row's details to simulate a DB-level edit by
    # someone with shell access to Postgres.  This is exactly the threat
    # tamper-evidence is supposed to catch.
    r1.details = {"tampered": True}
    db.session.commit()

    result = AuditLogger.verify_chain()
    assert result["ok"] is False
    assert result["first_bad_id"] == r1.id
    assert "entry_hash mismatch" in result["reason"]


def test_tamper_at_prev_hash_is_detected(app_context):
    _make_row()
    r2 = _make_row()
    _make_row()

    # Edit r2's prev_hash to point at a different (non-existent) predecessor.
    r2.prev_hash = "f" * 64
    db.session.commit()

    result = AuditLogger.verify_chain()
    assert result["ok"] is False
    assert result["first_bad_id"] == r2.id
    assert "prev_hash mismatch" in result["reason"]


def test_signature_forgery_is_detected(app_context):
    r1 = _make_row()
    # Flip one byte of the signature.  Anything that isn't a real signature
    # over the same digest will fail Ed25519 verify.
    bad = bytearray.fromhex(r1.signature)
    bad[0] ^= 0xFF
    r1.signature = bad.hex()
    db.session.commit()

    result = AuditLogger.verify_chain()
    assert result["ok"] is False
    assert result["first_bad_id"] == r1.id
    assert "signature invalid" in result["reason"]


def test_deleted_row_in_middle_breaks_chain(app_context):
    r1 = _make_row()
    r2 = _make_row()
    r3 = _make_row()
    # Deleting r2 should make r3's prev_hash point to a row that no longer
    # exists -- but more importantly, the verifier walks ids ascending, so
    # after r1 it expects r1.entry_hash as prev, but r3 has r2's hash.
    db.session.delete(r2)
    db.session.commit()

    result = AuditLogger.verify_chain()
    assert result["ok"] is False
    assert result["first_bad_id"] == r3.id
    # First failure point is the prev_hash linkage from r1 -> r3.
    assert "prev_hash mismatch" in result["reason"]
    # Sanity: r1 was unaffected
    assert result["checked"] == 1


# ---------------------------------------------------------------------------
# Ephemeral-key fallback
# ---------------------------------------------------------------------------

def test_ephemeral_key_bootstrap(tmp_path, monkeypatch):
    # No env var set, no repo-secrets file -> ephemeral.  This test runs
    # OUTSIDE the app_context fixture because that fixture pins a real key.
    monkeypatch.delenv("AUDIT_SIGNING_KEY_PATH", raising=False)
    # Point the "repo root" lookup at a directory with no secrets/ dir.
    # The signing-key module computes parents[2] of its own location; we
    # can't easily redirect that, but we can simply ensure the secrets dir
    # under the real repo isn't present.  In the test sandbox it isn't.
    signing_key_mod.reset_signing_key_cache_for_tests()
    _pri, _pub, source = signing_key_mod.get_signing_keypair()
    assert source == "ephemeral"
    assert signing_key_mod.is_ephemeral_key() is True
    signing_key_mod.reset_signing_key_cache_for_tests()


# ---------------------------------------------------------------------------
# Canonical JSON determinism
# ---------------------------------------------------------------------------

def test_canonical_json_is_key_order_independent():
    a = AuditLogger._canonical_json({"x": 1, "y": [1, 2], "z": None})
    b = AuditLogger._canonical_json({"z": None, "y": [1, 2], "x": 1})
    assert a == b


def test_canonical_json_handles_datetime_in_details():
    # Datetimes inside `details` are coerced to ISO strings via default=str;
    # the important property is that the encoding is total -- no crash.
    from datetime import datetime, timezone
    blob = AuditLogger._canonical_json(
        {"when": datetime(2026, 5, 15, tzinfo=timezone.utc), "k": "v"}
    )
    assert b"2026-05-15" in blob
