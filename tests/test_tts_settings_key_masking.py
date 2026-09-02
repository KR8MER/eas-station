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

"""Regression tests for the Azure OpenAI TTS API key never reaching the
browser in plaintext.

Guards the fix for a real key leak: TTSSettings.to_dict() used to return the
raw azure_openai_key, and templates/admin/tts.html pre-filled a plain text
input with it -- so the secret rendered into every page load of /admin/tts
and every /admin/api/tts/settings response, and showed up verbatim in a
user-submitted screenshot. Fixed by masking the key in to_dict() and by
making update_tts_settings() treat a blank/masked submission as "no change"
rather than nulling out the stored key (the form field is no longer
pre-filled with the real value, so most saves submit it blank).
"""

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app_core.extensions import db
from app_core.tts_settings import update_tts_settings


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    # db.create_all() registers every model on the shared metadata, including
    # ones using Postgres-only JSONB columns unrelated to TTSSettings; this
    # mirrors the shim in tests/test_audit_config_changes.py so the full
    # schema can still be created against SQLite for this focused test.
    return "TEXT"


@pytest.fixture
def app_context(tmp_path):
    database_path = tmp_path / "tts_key_masking.db"
    app = Flask("tts-key-masking-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # azure_openai_key is now an EncryptedString column (app_core.crypto),
        # which derives its key from the app's SECRET_KEY.
        SECRET_KEY="test-secret-key-for-tts-masking-tests-32chars-min",
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app


def test_to_dict_masks_key_when_set(app_context):
    from app_core._models_settings import TTSSettings

    settings = update_tts_settings({
        "provider": "azure_openai",
        "azure_openai_key": "super-secret-real-key-value",
    })
    data = settings.to_dict()

    assert data["azure_openai_key"] == "••••••••"
    assert "super-secret-real-key-value" not in data["azure_openai_key"]
    assert data["azure_openai_key_set"] is True


def test_to_dict_reports_no_key_when_unset(app_context):
    settings = update_tts_settings({"provider": "azure_openai"})
    data = settings.to_dict()

    assert data["azure_openai_key"] == ""
    assert data["azure_openai_key_set"] is False


def test_blank_submission_preserves_existing_key(app_context):
    update_tts_settings({
        "provider": "azure_openai",
        "azure_openai_key": "original-secret-key",
    })

    # Simulates saving the form with the (never pre-filled) key field left
    # blank, e.g. after only changing the voice.
    settings = update_tts_settings({
        "provider": "azure_openai",
        "azure_openai_voice": "onyx",
        "azure_openai_key": "",
    })

    assert settings.azure_openai_key == "original-secret-key"
    assert settings.azure_openai_voice == "onyx"


def test_masked_placeholder_submission_preserves_existing_key(app_context):
    update_tts_settings({
        "provider": "azure_openai",
        "azure_openai_key": "original-secret-key",
    })

    settings = update_tts_settings({
        "provider": "azure_openai",
        "azure_openai_key": "••••••••",
    })

    assert settings.azure_openai_key == "original-secret-key"


def test_new_value_overwrites_existing_key(app_context):
    update_tts_settings({
        "provider": "azure_openai",
        "azure_openai_key": "original-secret-key",
    })

    settings = update_tts_settings({
        "provider": "azure_openai",
        "azure_openai_key": "rotated-new-key",
    })

    assert settings.azure_openai_key == "rotated-new-key"
