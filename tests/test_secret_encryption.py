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

"""Tests for app_core.crypto: column-level encryption at rest and
server-side password peppering.

Guards the fix for stored credentials (Icecast/SMTP/Twilio/Tailscale/
Tickstem/Azure OpenAI secrets, TOTP secrets) sitting in the database as
plaintext -- a real gap distinct from the browser-exposure bugs fixed
separately (see test_tts_settings_key_masking.py). Also covers the
password/backup-code pepper added alongside it, including the
backward-compatible upgrade path for hashes written before peppering
existed.
"""

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from app_core.extensions import db


def _make_app(tmp_path, name, secret_key="a" * 40):
    database_path = tmp_path / f"{name}.db"
    app = Flask(name)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY=secret_key,
    )
    db.init_app(app)
    return app


@pytest.fixture
def app_context(tmp_path):
    app = _make_app(tmp_path, "secret-encryption-test")
    with app.app_context():
        # Create only the tables these tests touch, not db.create_all() --
        # the full shared metadata includes a PostGIS Geometry column
        # (boundaries.geom), and geoalchemy2 registers a SQLite DDL hook for
        # it that calls the real SpatiaLite RecoverGeometryColumn() function;
        # under plain sqlite3 (no mod_spatialite loaded) that errors with
        # "no such function". Mirrors the scoped Table.create() pattern in
        # tests/test_audit_config_changes.py.
        from app_core._models_admin import AdminUser
        from app_core._models_settings import TailscaleSettings, TTSSettings
        engine = db.engine
        TTSSettings.__table__.create(bind=engine)
        TailscaleSettings.__table__.create(bind=engine)
        AdminUser.__table__.create(bind=engine)
        yield app


# ---------------------------------------------------------------------------
# encrypt_secret / decrypt_secret
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip(app_context):
    from app_core.crypto import decrypt_secret, encrypt_secret

    ciphertext = encrypt_secret("my-real-secret-value")
    assert ciphertext != "my-real-secret-value"
    assert ciphertext.startswith("enc:v1:")
    assert decrypt_secret(ciphertext) == "my-real-secret-value"


def test_encrypt_secret_passes_through_empty(app_context):
    from app_core.crypto import encrypt_secret

    assert encrypt_secret(None) is None
    assert encrypt_secret("") == ""


def test_decrypt_secret_tolerates_legacy_plaintext(app_context):
    """Rows written before EncryptedString existed have no "enc:v1:" prefix
    and must keep working (and get encrypted automatically on next save)."""
    from app_core.crypto import decrypt_secret

    assert decrypt_secret("plain-old-value-from-before-this-feature") == \
        "plain-old-value-from-before-this-feature"


def test_decrypt_secret_handles_key_rotation_gracefully(tmp_path):
    from app_core.crypto import decrypt_secret, encrypt_secret

    app_a = _make_app(tmp_path, "rotation-a", secret_key="a" * 40)
    with app_a.app_context():
        ciphertext = encrypt_secret("rotated-away-secret")

    app_b = _make_app(tmp_path, "rotation-b", secret_key="b" * 40)
    with app_b.app_context():
        # Different SECRET_KEY -> different derived key -> can't decrypt.
        # Must fail closed (empty string), not raise, so a key rotation
        # degrades to "re-enter this value" instead of a 500.
        assert decrypt_secret(ciphertext) == ""


# ---------------------------------------------------------------------------
# EncryptedString column type, end to end through a real model
# ---------------------------------------------------------------------------


def test_encrypted_string_column_is_encrypted_at_rest(app_context):
    from app_core._models_settings import TTSSettings

    settings = TTSSettings(id=1, provider="azure_openai", azure_openai_key="raw-api-key-value")
    db.session.add(settings)
    db.session.commit()
    db.session.expunge_all()

    # Read back through the ORM: transparently decrypted.
    reloaded = db.session.get(TTSSettings, 1)
    assert reloaded.azure_openai_key == "raw-api-key-value"

    # Read the raw column value directly (bypassing the ORM type decorator,
    # the way a DB dump or an attacker with read access to the table would
    # see it): must not be the plaintext.
    raw_value = db.session.execute(
        db.text("SELECT azure_openai_key FROM tts_settings WHERE id = 1")
    ).scalar()
    assert raw_value != "raw-api-key-value"
    assert raw_value.startswith("enc:v1:")


def test_backfill_encrypts_legacy_plaintext_rows(app_context):
    """A row written before EncryptedString existed sits in the database as
    plaintext until something re-saves it. backfill_legacy_plaintext_secrets()
    is what makes that happen once, at startup, without operator action."""
    from app_core.crypto import backfill_legacy_plaintext_secrets
    from app_core._models_settings import TTSSettings, TailscaleSettings

    # Simulate two pre-existing plaintext rows via raw SQL, bypassing the ORM
    # (and therefore EncryptedString's encrypt-on-write) entirely -- exactly
    # how a row saved by last month's code would actually look today.
    db.session.add(TTSSettings(id=1, provider="azure_openai"))
    db.session.add(TailscaleSettings(id=1, enabled=True))
    db.session.commit()
    db.session.execute(db.text(
        "UPDATE tts_settings SET azure_openai_key = 'legacy-plaintext-key' WHERE id = 1"
    ))
    db.session.execute(db.text(
        "UPDATE tailscale_settings SET auth_key = 'legacy-plaintext-authkey' WHERE id = 1"
    ))
    db.session.commit()

    encrypted_count = backfill_legacy_plaintext_secrets(db.session)
    assert encrypted_count == 2

    raw_tts_key = db.session.execute(
        db.text("SELECT azure_openai_key FROM tts_settings WHERE id = 1")
    ).scalar()
    raw_auth_key = db.session.execute(
        db.text("SELECT auth_key FROM tailscale_settings WHERE id = 1")
    ).scalar()
    assert raw_tts_key.startswith("enc:v1:")
    assert raw_auth_key.startswith("enc:v1:")

    # Still reads back correctly through the ORM after the rewrite.
    db.session.expunge_all()
    assert db.session.get(TTSSettings, 1).azure_openai_key == "legacy-plaintext-key"
    assert db.session.get(TailscaleSettings, 1).auth_key == "legacy-plaintext-authkey"

    # Idempotent: a second pass finds nothing left to encrypt.
    assert backfill_legacy_plaintext_secrets(db.session) == 0


# ---------------------------------------------------------------------------
# EncryptedString outside a Flask app context (standalone CAP poller shape)
# ---------------------------------------------------------------------------


def test_encrypted_column_readable_via_raw_session_outside_app_context(tmp_path, monkeypatch):
    """Regression test for a real production bug: the standalone CAP poller
    reads TTSSettings (and every other EncryptedString-backed settings row)
    through its own ``sessionmaker(bind=engine)`` session with no Flask app
    ever pushed in that process. Before this fix, decrypting the column
    still called ``current_app.secret_key`` deep inside SQLAlchemy's row
    hydration, which raised "Working outside of application context" --
    silently swallowed by the poller's own error handling, so TTS narration
    (and Icecast/SMTP/Tailscale/Tickstem credentials read the same way) was
    treated as unconfigured even though it was fully set up in the web UI.
    """
    import app_core.crypto as crypto_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app_core._models_settings import TTSSettings

    monkeypatch.setattr(crypto_module, "_fernet_cache", None)

    secret_key = "c" * 40

    # Write the value the normal way, inside a real app context -- mirrors
    # the web UI's Settings save.
    app_name = "poller-context-write"
    app = _make_app(tmp_path, app_name, secret_key=secret_key)
    database_path = tmp_path / f"{app_name}.db"
    with app.app_context():
        TTSSettings.__table__.create(bind=db.engine)
        db.session.add(TTSSettings(
            id=1, provider="azure_openai", enabled=True,
            azure_openai_key="raw-api-key-value",
        ))
        db.session.commit()

    # Read it back the way the CAP poller actually does: a plain
    # sessionmaker() session bound directly to the engine, with zero Flask
    # app pushed anywhere in this process. systemd's EnvironmentFile is what
    # puts SECRET_KEY in that process's environment in production.
    monkeypatch.setenv("SECRET_KEY", secret_key)
    engine = create_engine(f"sqlite:///{database_path}")
    raw_session = sessionmaker(bind=engine)()
    try:
        reloaded = raw_session.get(TTSSettings, 1)
        assert reloaded.azure_openai_key == "raw-api-key-value"
    finally:
        raw_session.close()


def test_encrypted_column_raises_without_app_context_or_env_secret_key(tmp_path, monkeypatch):
    """Without a Flask app context AND without SECRET_KEY in the
    environment, there's genuinely no key material available -- must still
    fail loudly (RuntimeError) rather than silently return garbage."""
    import app_core.crypto as crypto_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app_core._models_settings import TTSSettings

    monkeypatch.setattr(crypto_module, "_fernet_cache", None)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    secret_key = "d" * 40

    app_name = "poller-no-secret-write"
    app = _make_app(tmp_path, app_name, secret_key=secret_key)
    database_path = tmp_path / f"{app_name}.db"
    with app.app_context():
        TTSSettings.__table__.create(bind=db.engine)
        db.session.add(TTSSettings(
            id=1, provider="azure_openai", enabled=True,
            azure_openai_key="raw-api-key-value",
        ))
        db.session.commit()

    engine = create_engine(f"sqlite:///{database_path}")
    raw_session = sessionmaker(bind=engine)()
    try:
        with pytest.raises(RuntimeError, match="SECRET_KEY is not configured"):
            raw_session.get(TTSSettings, 1)
    finally:
        raw_session.close()


# ---------------------------------------------------------------------------
# Password peppering (AdminUser)
# ---------------------------------------------------------------------------


def test_password_set_and_check_roundtrip(app_context):
    from app_core._models_admin import AdminUser

    user = AdminUser(username="alice")
    user.set_password("correct horse battery staple")

    assert user.check_password("correct horse battery staple") is True
    assert user.check_password("wrong password") is False


def test_password_hash_is_peppered_not_bare_werkzeug_hash(app_context):
    """A peppered hash must NOT verify against the raw password via plain
    werkzeug check -- proves the pepper is actually being mixed in, not a
    no-op."""
    from app_core._models_admin import AdminUser
    from werkzeug.security import check_password_hash

    user = AdminUser(username="bob")
    user.set_password("hunter2")

    assert check_password_hash(user.password_hash, "hunter2") is False


def test_pre_pepper_hash_still_verifies_and_upgrades(app_context):
    """Simulates an account whose password_hash was written before server-
    side peppering existed (plain werkzeug hash of the raw password). Must
    still authenticate, and must transparently upgrade in place."""
    from app_core._models_admin import AdminUser

    user = AdminUser(username="carol")
    user.password_hash = generate_password_hash("legacy-password")
    user.salt = "pbkdf2"

    assert user.check_password("legacy-password") is True

    # Upgraded in place (pending commit, per the method's contract) --
    # the old bare hash no longer matches the raw password directly.
    from werkzeug.security import check_password_hash
    assert check_password_hash(user.password_hash, "legacy-password") is False
    # But check_password still authenticates on the new peppered hash.
    assert user.check_password("legacy-password") is True


# ---------------------------------------------------------------------------
# MFA backup codes
# ---------------------------------------------------------------------------


def test_backup_codes_hash_and_verify_roundtrip(app_context):
    from app_core.auth.mfa import MFAManager

    codes = MFAManager.generate_backup_codes(count=3)
    hashed_json = MFAManager.hash_backup_codes(codes)

    is_valid, remaining_json = MFAManager.verify_backup_code(codes[0], hashed_json)
    assert is_valid is True

    import json
    assert len(json.loads(remaining_json)) == 2

    # Used code cannot be replayed.
    is_valid_again, _ = MFAManager.verify_backup_code(codes[0], remaining_json)
    assert is_valid_again is False


def test_legacy_unpeppered_backup_code_still_verifies(app_context):
    """A backup code hashed before peppering existed (plain werkzeug hash of
    the raw code, no pepper) must still be accepted."""
    from app_core.auth.mfa import MFAManager
    import json

    legacy_hashed_json = json.dumps([generate_password_hash("ABCD1234")])

    is_valid, remaining_json = MFAManager.verify_backup_code("ABCD1234", legacy_hashed_json)
    assert is_valid is True
    assert json.loads(remaining_json) == []
