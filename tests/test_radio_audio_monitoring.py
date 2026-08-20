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

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
import numpy as np

from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.extensions import db
from app_core.models import AudioSourceConfigDB, RadioReceiver


from app_core.audio.ingest import AudioSourceStatus
from webapp.admin import audio_ingest as audio_admin
from webapp.admin.audio_ingest import controller as audio_controller_mod
from webapp.admin.audio_ingest import streaming as audio_streaming_mod
from webapp.admin.audio_ingest import serialization as audio_serialization_mod
import webapp.routes_settings_radio as radio_routes
import webapp.radio_settings.deps as radio_deps


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover - sqlalchemy hook
    return "TEXT"


@pytest.fixture(autouse=True)
def reset_audio_globals(monkeypatch):
    # Each global lives in the submodule that owns it. Patching the
    # re-exporting package instead would not change what the functions see in
    # their own module globals, and the reset would silently do nothing.
    monkeypatch.setattr(audio_controller_mod, "_audio_controller", None)
    monkeypatch.setattr(audio_controller_mod, "_initialization_started", True)
    monkeypatch.setattr(audio_controller_mod, "_audio_initialization_lock_file", None)
    monkeypatch.setattr(audio_controller_mod, "_start_audio_sources_background", lambda app: None)
    monkeypatch.setattr(audio_streaming_mod, "_auto_streaming_service", None)
    monkeypatch.setattr(audio_streaming_mod, "_streaming_lock_file", None)


@pytest.fixture
def audio_app(tmp_path: Path):
    database_path = tmp_path / "radio_audio.db"
    app = Flask("radio-audio-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    with app.app_context():
        engine = db.engine
        RadioReceiver.__table__.create(bind=engine)
        AudioSourceConfigDB.__table__.create(bind=engine)
        audio_admin.register_audio_ingest_routes(app, logging.getLogger("audio-test"))
        radio_routes.register(app, logging.getLogger("radio-test"))
        yield app
        db.session.remove()
        AudioSourceConfigDB.__table__.drop(bind=engine)
        RadioReceiver.__table__.drop(bind=engine, checkfirst=True)


def _create_receiver(**overrides) -> RadioReceiver:
    data = {
        "identifier": "WX42",
        "display_name": "Weather 42",
        "driver": "rtlsdr",
        "frequency_hz": 162_550_000,
        "sample_rate": 2_400_000,
        "gain": None,
        "channel": None,
        "serial": None,
        "auto_start": False,
        "enabled": True,
        "notes": None,
        "modulation_type": "WFM",
        "audio_output": True,
        "stereo_enabled": False,
        "deemphasis_us": 75.0,
        "enable_rbds": False,
    }
    data.update(overrides)
    return RadioReceiver(**data)


def test_ensure_sdr_audio_monitor_source_creates_config(audio_app, authenticated_user):
    with audio_app.app_context():
        receiver = _create_receiver()
        db.session.add(receiver)
        db.session.commit()

        result = audio_admin.ensure_sdr_audio_monitor_source(
            receiver,
            start_immediately=False,
            commit=True,
        )

        assert result["source_name"] == "sdr-wx42"
        assert result["created"] is True
        assert result["removed"] is False

        config = AudioSourceConfigDB.query.filter_by(name="sdr-wx42").first()
        assert config is not None
        assert config.config_params["device_params"]["receiver_id"] == "WX42"
        assert config.config_params["device_params"]["iq_sample_rate"] == 2_400_000
        assert config.description.startswith("SDR monitor for Weather 42")

        controller = audio_admin._get_audio_controller()
        assert "sdr-wx42" in controller._sources
        adapter = controller._sources["sdr-wx42"]
        assert adapter.config.sample_rate == 32000
        assert adapter.metrics.metadata["receiver_identifier"] == "WX42"
        assert adapter.metrics.metadata["icecast_mount"] == "/sdr-wx42"


def test_remove_radio_managed_audio_source_cleans_up(audio_app, authenticated_user):
    with audio_app.app_context():
        receiver = _create_receiver()
        db.session.add(receiver)
        db.session.commit()

        audio_admin.ensure_sdr_audio_monitor_source(receiver, start_immediately=False, commit=True)

        removed = audio_admin.remove_radio_managed_audio_source("sdr-wx42")
        assert removed is True
        assert AudioSourceConfigDB.query.filter_by(name="sdr-wx42").first() is None

        controller = audio_admin._get_audio_controller()
        assert "sdr-wx42" not in controller._sources


def test_sync_radio_manager_state_updates_audio_sources(audio_app, monkeypatch, authenticated_user):
    class DummyReceiverInstance:
        def __init__(self, identifier: str) -> None:
            self.identifier = identifier
            self.started = 0

        def start(self) -> None:
            self.started += 1

        def get_status(self):  # pragma: no cover - simple struct
            from app_core.radio.manager import ReceiverStatus

            return ReceiverStatus(identifier=self.identifier, locked=True)

    class DummyRadioManager:
        def __init__(self) -> None:
            self.instances: dict[str, DummyReceiverInstance] = {}

        def configure_from_records(self, records):
            self.instances = {
                record.identifier: DummyReceiverInstance(record.identifier)
                for record in records
            }

        def get_receiver(self, identifier: str):
            return self.instances.get(identifier)

        def log_event(self, *args, **kwargs):  # pragma: no cover - noop for tests
            return None

    dummy_manager = DummyRadioManager()
    monkeypatch.setattr(radio_deps, "get_radio_manager", lambda: dummy_manager)
    monkeypatch.setattr(radio_deps, "_log_radio_event", lambda *args, **kwargs: None)

    with audio_app.app_context():
        active = _create_receiver(identifier="WXACTIVE", display_name="Active NOAA")
        stale = _create_receiver(identifier="WXSTALE", display_name="Stale NOAA")
        db.session.add_all([active, stale])
        db.session.commit()

        audio_admin.ensure_sdr_audio_monitor_source(stale, start_immediately=False, commit=True)

        stale.audio_output = False
        db.session.commit()

        summary = radio_routes._sync_radio_manager_state(logging.getLogger("radio-test"))
        assert summary["configured"] == 2

        configs = {cfg.name for cfg in AudioSourceConfigDB.query.all()}
        assert "sdr-wxactive" in configs
        assert "sdr-wxstale" not in configs

        controller = audio_admin._get_audio_controller()
        assert "sdr-wxactive" in controller._sources
        assert "sdr-wxstale" not in controller._sources


def test_api_ensure_audio_monitor_endpoint(audio_app, authenticated_user):
    with audio_app.app_context():
        receiver = _create_receiver(identifier="WXMON", display_name="Monitor NOAA")
        db.session.add(receiver)
        db.session.commit()
        receiver_id = receiver.id

        client = audio_app.test_client()

        response = client.post(f"/api/radio/receivers/{receiver_id}/audio-monitor", json={})
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["success"] is True
        assert payload["source_name"] == "sdr-wxmon"
        assert payload["receiver_enabled"] is True
        assert payload["audio_output"] is True

        response_start = client.post(
            f"/api/radio/receivers/{receiver_id}/audio-monitor",
            json={"start": True},
        )
        assert response_start.status_code == 200
        payload_start = response_start.get_json()
        assert payload_start["success"] is True
        assert payload_start["source_name"] == "sdr-wxmon"
        assert "message" in payload_start


def test_audio_source_endpoint_restores_missing_adapter(audio_app, authenticated_user):
    with audio_app.app_context():
        receiver = _create_receiver(identifier="WXRESTORE", display_name="Restore NOAA")
        db.session.add(receiver)
        db.session.commit()

        audio_admin.ensure_sdr_audio_monitor_source(receiver, start_immediately=False, commit=True)

        controller = audio_admin._get_audio_controller()
        assert "sdr-wxrestore" in controller._sources

        controller.remove_source("sdr-wxrestore")
        assert "sdr-wxrestore" not in controller._sources

        client = audio_app.test_client()
        response = client.get("/api/audio/sources/sdr-wxrestore")

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["name"] == "sdr-wxrestore"
        assert "sdr-wxrestore" in controller._sources


def test_audio_start_endpoint_restores_missing_adapter(audio_app, monkeypatch, authenticated_user):
    with audio_app.app_context():
        receiver = _create_receiver(identifier="WXSTART", display_name="Start NOAA")
        db.session.add(receiver)
        db.session.commit()

        audio_admin.ensure_sdr_audio_monitor_source(receiver, start_immediately=False, commit=True)

        controller = audio_admin._get_audio_controller()
        assert "sdr-wxstart" in controller._sources

        controller.remove_source("sdr-wxstart")
        assert "sdr-wxstart" not in controller._sources

        dummy_adapter = SimpleNamespace(
            config=SimpleNamespace(
                name="sdr-wxstart",
                sample_rate=32000,
                channels=1,
                buffer_size=4096,
                enabled=True,
                priority=10,
            ),
            status=AudioSourceStatus.STOPPED,
            error_message=None,
            metrics=SimpleNamespace(metadata={}),
        )

        def _dummy_start():
            dummy_adapter.status = AudioSourceStatus.RUNNING
            return True

        def _dummy_stop():
            dummy_adapter.status = AudioSourceStatus.STOPPED

        def _dummy_chunk(timeout: float = 0.2):  # pragma: no cover - not used in this test
            return np.zeros(1024, dtype=np.float32)

        dummy_adapter.start = _dummy_start  # type: ignore[attr-defined]
        dummy_adapter.stop = _dummy_stop  # type: ignore[attr-defined]
        dummy_adapter.get_audio_chunk = _dummy_chunk  # type: ignore[attr-defined]

        def _fake_restore(controller_obj, db_config):
            controller_obj.add_source(dummy_adapter)
            return dummy_adapter

        # _get_controller_and_adapter calls this through its own module global, so
        # webapp.admin.audio_ingest.serialization is the object to patch.
        monkeypatch.setattr(
            audio_serialization_mod, "_restore_audio_source_from_db_config", _fake_restore
        )

        client = audio_app.test_client()
        response = client.post("/api/audio/sources/sdr-wxstart/start")

        assert response.status_code == 200
        assert dummy_adapter.status == AudioSourceStatus.RUNNING
        assert "sdr-wxstart" in controller._sources


def test_audio_stream_endpoint_uses_wav_mimetype(audio_app, authenticated_user):
    with audio_app.app_context():
        controller = audio_admin._get_audio_controller()

        class DummyAdapter:
            def __init__(self) -> None:
                self.config = SimpleNamespace(
                    name="monitor-dummy",
                    sample_rate=48000,
                    channels=1,
                    buffer_size=1024,
                    enabled=True,
                    priority=5,
                )
                self.status = AudioSourceStatus.RUNNING
                self.error_message = None

            def start(self):  # pragma: no cover - not used in this test
                self.status = AudioSourceStatus.RUNNING
                return True

            def stop(self):  # pragma: no cover - invoked during cleanup
                self.status = AudioSourceStatus.STOPPED

            def get_audio_chunk(self, timeout: float = 0.2):
                return np.zeros(1024, dtype=np.float32)

        adapter = DummyAdapter()
        controller.add_source(adapter)

        client = audio_app.test_client()
        response = client.get("/api/audio/stream/monitor-dummy", buffered=False)

        assert response.status_code == 200
        assert response.mimetype == "audio/wav"

        # First chunk should be the WAV header beginning with RIFF
        first_chunk = next(response.response)
        assert first_chunk.startswith(b"RIFF")

        response.close()
        controller.remove_source("monitor-dummy")


def test_ensure_sdr_audio_monitor_source_preserves_archive_settings(audio_app, authenticated_user):
    """Re-syncing a receiver must not wipe the Audio Archives settings.

    ``ensure_sdr_audio_monitor_source`` used to assign a freshly-built
    ``config_params`` dict, which deleted the user-owned ``archive`` block
    stored alongside the receiver-derived keys.  Because the sync runs on every
    service start, archiving silently reverted to off after every upgrade.
    """
    with audio_app.app_context():
        receiver = _create_receiver()
        db.session.add(receiver)
        db.session.commit()

        audio_admin.ensure_sdr_audio_monitor_source(receiver, start_immediately=False, commit=True)

        # The user turns archiving on from /admin/audio/archives.
        config = AudioSourceConfigDB.query.filter_by(name="sdr-wx42").first()
        params = dict(config.config_params)
        params["archive"] = {
            "enabled": True,
            "output_dir": "archives",
            "segment_duration_seconds": 1800,
            "retention_days": 30,
            "max_disk_bytes": 0,
            "format": "mp3",
            "bitrate": 192,
            "silence_threshold": 0.005,
        }
        config.config_params = params
        db.session.commit()

        # An upgrade restarts the services, which re-syncs every receiver — and
        # this time the receiver's own settings changed too.
        receiver.frequency_hz = 99_500_000.0
        db.session.commit()
        audio_admin.ensure_sdr_audio_monitor_source(receiver, start_immediately=False, commit=True)

        config = AudioSourceConfigDB.query.filter_by(name="sdr-wx42").first()
        assert config.config_params["archive"]["enabled"] is True
        assert config.config_params["archive"]["retention_days"] == 30
        assert config.config_params["archive"]["format"] == "mp3"
        assert config.config_params["archive"]["bitrate"] == 192

        # ...while the receiver-derived keys still track the receiver.
        assert config.config_params["device_params"][
            "receiver_frequency_hz"
        ] == pytest.approx(99_500_000.0)
