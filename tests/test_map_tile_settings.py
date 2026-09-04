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

Tests for app_core.map_tile_settings: the basemap tile provider settings
for the alert share-card map inset (Settings -> Map Tiles).

The overriding concern, given this session's earlier bug where the CAP
poller couldn't decrypt TTS's Azure OpenAI key (see
tests/test_secret_encryption.py's regression tests), is the exact same
shape here: app_utils.image_export.maps._render_map() reads
carto_api_key from both a Flask request (web app) and a standalone
sessionmaker() session with no Flask app context at all (the CAP poller,
via app_core.notifications.alert_image). get_map_tile_settings() must
decrypt correctly in both, and must never raise -- a settings read
failure degrades to ('osm', None), not a broken map.
"""

from __future__ import annotations

import pytest
from flask import Flask

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
    app = _make_app(tmp_path, "map-tile-settings-test")
    with app.app_context():
        from app_core._models_settings import MapTileSettings
        MapTileSettings.__table__.create(bind=db.engine)
        yield app


def test_default_provider_is_osm_with_no_row(app_context):
    from app_core.map_tile_settings import get_map_tile_settings

    provider, api_key = get_map_tile_settings()
    assert provider == 'osm'
    assert api_key is None


def test_get_returns_saved_provider_and_key(app_context):
    from app_core._models_settings import MapTileSettings
    from app_core.map_tile_settings import get_map_tile_settings

    db.session.add(MapTileSettings(id=1, provider='carto_dark', carto_api_key='real-carto-key'))
    db.session.commit()
    db.session.expunge_all()

    provider, api_key = get_map_tile_settings()
    assert provider == 'carto_dark'
    assert api_key == 'real-carto-key'


def test_update_leaves_key_unchanged_when_blank(app_context):
    from app_core.map_tile_settings import get_map_tile_settings, update_map_tile_settings

    update_map_tile_settings({'provider': 'carto_dark', 'carto_api_key': 'first-key'})
    # Blank carto_api_key on a later save -- the "leave blank to keep the
    # current key" convention shared with TTSSettings.azure_openai_key.
    update_map_tile_settings({'provider': 'carto_dark', 'carto_api_key': ''})

    provider, api_key = get_map_tile_settings()
    assert provider == 'carto_dark'
    assert api_key == 'first-key'


def test_update_rejects_unknown_provider_is_ignored(app_context):
    """update_map_tile_settings() itself only writes recognized providers --
    request-level validation (webapp/admin/map_tiles.py) rejects the rest
    before this is ever called, but the accessor stays defensive too."""
    from app_core.map_tile_settings import get_map_tile_settings, update_map_tile_settings

    update_map_tile_settings({'provider': 'not-a-real-provider'})

    provider, _ = get_map_tile_settings()
    assert provider == 'osm'


def test_get_never_raises_when_table_missing(tmp_path):
    """A settings read must never break map rendering -- even a completely
    missing table degrades to ('osm', None) rather than propagating."""
    app = _make_app(tmp_path, "map-tile-settings-no-table")
    with app.app_context():
        from app_core.map_tile_settings import get_map_tile_settings
        provider, api_key = get_map_tile_settings()
    assert provider == 'osm'
    assert api_key is None


# ── Outside a Flask app context (standalone CAP poller shape) ──────────────

def test_carto_api_key_readable_via_raw_session_outside_app_context(tmp_path, monkeypatch):
    """Regression test mirroring test_secret_encryption.py's
    test_encrypted_column_readable_via_raw_session_outside_app_context:
    the CAP poller reads this settings row through its own
    sessionmaker() session with no Flask app ever pushed in that
    process."""
    import app_core.crypto as crypto_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app_core._models_settings import MapTileSettings
    from app_core.map_tile_settings import get_map_tile_settings

    monkeypatch.setattr(crypto_module, "_fernet_cache", None)

    secret_key = "e" * 40
    app_name = "map-tile-poller-context-write"
    app = _make_app(tmp_path, app_name, secret_key=secret_key)
    database_path = tmp_path / f"{app_name}.db"
    with app.app_context():
        MapTileSettings.__table__.create(bind=db.engine)
        db.session.add(MapTileSettings(id=1, provider='carto_dark', carto_api_key='poller-visible-key'))
        db.session.commit()

    monkeypatch.setenv("SECRET_KEY", secret_key)
    engine = create_engine(f"sqlite:///{database_path}")
    raw_session = sessionmaker(bind=engine)()
    try:
        provider, api_key = get_map_tile_settings(raw_session)
        assert provider == 'carto_dark'
        assert api_key == 'poller-visible-key'
    finally:
        raw_session.close()
