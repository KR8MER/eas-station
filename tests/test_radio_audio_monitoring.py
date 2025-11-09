import logging
import sys
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.extensions import db
from app_core.models import AudioSourceConfigDB, RadioReceiver
from webapp.admin import audio_ingest as audio_admin
import webapp.routes_settings_radio as radio_routes


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover - sqlalchemy hook
    return "TEXT"


@pytest.fixture(autouse=True)
def reset_audio_globals(monkeypatch):
    monkeypatch.setattr(audio_admin, "_audio_controller", None)
    monkeypatch.setattr(audio_admin, "_auto_streaming_service", None)
    monkeypatch.setattr(audio_admin, "_initialization_started", True)
    monkeypatch.setattr(audio_admin, "_streaming_lock_file", None)
    monkeypatch.setattr(audio_admin, "_audio_initialization_lock_file", None)
    monkeypatch.setattr(audio_admin, "_start_audio_sources_background", lambda app: None)


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
        yield app
        db.session.remove()
        AudioSourceConfigDB.__table__.drop(bind=engine)
        RadioReceiver.__table__.drop(bind=engine)


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


def test_ensure_sdr_audio_monitor_source_creates_config(audio_app):
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
        assert config.description.startswith("SDR monitor for Weather 42")

        controller = audio_admin._get_audio_controller()
        assert "sdr-wx42" in controller._sources
        adapter = controller._sources["sdr-wx42"]
        assert adapter.config.sample_rate == 32000
        assert adapter.metrics.metadata["receiver_identifier"] == "WX42"
        assert adapter.metrics.metadata["icecast_mount"] == "/sdr-wx42"


def test_remove_radio_managed_audio_source_cleans_up(audio_app):
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


def test_sync_radio_manager_state_updates_audio_sources(audio_app, monkeypatch):
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
    monkeypatch.setattr(radio_routes, "get_radio_manager", lambda: dummy_manager)
    monkeypatch.setattr(radio_routes, "_log_radio_event", lambda *args, **kwargs: None)

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
