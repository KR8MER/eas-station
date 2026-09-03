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

Tests for app_core.settings_search: the field-label + stored-value index
behind the Settings hub's search box. The overriding concern is that a
value from an EncryptedString column (or a plaintext-but-secret-shaped one
like a heartbeat ping URL) can NEVER appear here, searchable or not --
these tests assert its absence directly against the actual seeded secret
value, not just against a column-name heuristic.
"""

from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app_core.extensions import db


# SQLite cannot render the PostgreSQL JSONB columns HardwareSettings
# declares; map them to plain JSON for the test database (mirrors
# tests/test_hardware_settings_cache.py).
@compiles(JSONB, "sqlite")
def _render_jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


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
    app = _make_app(tmp_path, "settings-search-test")
    with app.app_context():
        # Scoped table creation (not db.create_all()) -- mirrors
        # tests/test_secret_encryption.py; the full shared metadata includes
        # a PostGIS Geometry column that SQLite/geoalchemy2 can't create.
        from app_core._models_settings import ApplicationSettings, HardwareSettings, IcecastSettings
        from app_core._models_heartbeat import HeartbeatSettings

        engine = db.engine
        for model in (IcecastSettings, ApplicationSettings, HardwareSettings, HeartbeatSettings):
            model.__table__.create(bind=engine)
        yield app


_ALL_PAGES = [
    {"label": "Icecast Streaming", "url": "/admin/icecast", "group": "Audio & Speech"},
    {"label": "Application Settings", "url": "/admin/application/", "group": "Configuration"},
    {"label": "Uptime Heartbeat", "url": "/admin/heartbeat/", "group": "Configuration"},
    {"label": "Hardware Settings", "url": "/admin/hardware", "group": "Hardware"},
    {"label": "GPIO & Relays", "url": "/admin/gpio", "group": "Hardware"},
    {"label": "Zigbee", "url": "/admin/zigbee", "group": "Hardware"},
]

_ICECAST_SOURCE_PASSWORD = "supersecret-source-pw-9f8e7d"
_ICECAST_ADMIN_PASSWORD = "supersecret-admin-pw-1a2b3c"
_HEARTBEAT_TOKEN_URL = "https://hc-ping.com/abcdef01-secret-token-2345"


def _seed_rows():
    from app_core._models_settings import ApplicationSettings, HardwareSettings, IcecastSettings
    from app_core._models_heartbeat import HeartbeatSettings

    icecast = IcecastSettings(
        id=1,
        enabled=True,
        server="easstation",
        port=8000,
        source_password=_ICECAST_SOURCE_PASSWORD,
        admin_password=_ICECAST_ADMIN_PASSWORD,
        admin_user="admin",
        stream_bitrate=128,
    )
    application = ApplicationSettings(id=1, log_level="INFO")
    heartbeat = HeartbeatSettings(id=1, ping_url=_HEARTBEAT_TOKEN_URL, interval_seconds=60)
    hardware = HardwareSettings(id=1, gpio_enabled=True, zigbee_enabled=True, oled_enabled=False)

    db.session.add_all([icecast, application, heartbeat, hardware])
    db.session.commit()


def _all_text(index: list[dict]) -> str:
    """Every string the index could possibly expose, concatenated for a
    single substring search -- the strongest possible "never leaked" check.
    """
    return "\n".join(f"{r['field_label']} {r['value_display']} {r['value_search']}" for r in index)


class TestNoSecretsLeak:
    def test_icecast_passwords_never_appear(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        text = _all_text(index)
        assert _ICECAST_SOURCE_PASSWORD not in text
        assert _ICECAST_ADMIN_PASSWORD not in text

    def test_encrypted_columns_are_never_indexed_by_label_either(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        labels = {r["field_label"] for r in index}
        assert "Source Password" not in labels
        assert "Admin Password" not in labels

    def test_heartbeat_ping_url_blocklisted_despite_not_being_encrypted(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        text = _all_text(index)
        assert _HEARTBEAT_TOKEN_URL not in text
        assert "hc-ping.com" not in text


class TestFieldIndexing:
    def test_known_field_appears_with_correct_label_value_and_page(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        hit = next(r for r in index if r["field_label"] == "Stream Bitrate")
        assert hit["value_display"] == "128"
        assert hit["page_url"] == "/admin/icecast"
        assert hit["page_label"] == "Icecast Streaming"

    def test_non_secret_icecast_fields_still_indexed(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        labels = {r["field_label"] for r in index if r["page_url"] == "/admin/icecast"}
        assert "Server" in labels
        assert "Port" in labels
        assert "Admin User" in labels

    def test_page_absent_from_input_contributes_no_fields(self, app_context):
        """Simulates a viewer without permission to a page: if it's missing
        from the (already permission-filtered) nav_settings_items passed in,
        none of its fields should appear -- same access boundary as the
        Settings hub and command palette.
        """
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        restricted_pages = [p for p in _ALL_PAGES if p["url"] != "/admin/icecast"]
        index = build_settings_search_index(restricted_pages)
        assert not any(r["page_url"] == "/admin/icecast" for r in index)

    def test_empty_input_returns_empty_index(self, app_context):
        from app_core.settings_search import build_settings_search_index
        assert build_settings_search_index([]) == []


class TestHardwareSettingsColumnRouting:
    def test_gpio_columns_route_to_gpio_page_not_hardware(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        hit = next(r for r in index if r["field_label"] == "GPIO Enabled")
        assert hit["page_url"] == "/admin/gpio"
        assert hit["value_display"] == "Yes"

    def test_zigbee_columns_route_to_zigbee_page_not_hardware(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        hit = next(r for r in index if r["field_label"] == "Zigbee Enabled")
        assert hit["page_url"] == "/admin/zigbee"

    def test_other_hardware_columns_stay_on_hardware_page(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        hit = next(r for r in index if r["field_label"] == "OLED Enabled")
        assert hit["page_url"] == "/admin/hardware"

    def test_json_dict_columns_are_skipped(self, app_context):
        """gpio_pin_map / gpio_behavior_matrix are JSONB dicts, not simple
        entered values -- out of scope, must not crash or appear."""
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        labels = {r["field_label"] for r in index}
        assert "GPIO Pin Map" not in labels
        assert "GPIO Behavior Matrix" not in labels


class TestValueFormatting:
    def test_unset_field_shown_as_not_set_but_still_indexed_by_label(self, app_context):
        from app_core.settings_search import build_settings_search_index
        _seed_rows()
        index = build_settings_search_index(_ALL_PAGES)
        # HardwareSettings.dead_air_buzzer_gpio_pin is nullable, not seeded.
        hit = next(r for r in index if r["field_label"] == "Dead Air Buzzer GPIO Pin")
        assert hit["value_display"] == "(not set)"
        assert hit["value_search"] == ""
