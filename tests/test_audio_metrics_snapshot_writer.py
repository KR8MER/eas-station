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

"""Tests for eas_monitoring_service._snapshot_audio_metrics_once.

Nothing in production ever wrote to the audio_source_metrics table -- only
tests instantiated AudioSourceMetrics directly -- so the RBDS History modal
always reported "No stored RBDS snapshots" regardless of uptime. These tests
cover the writer added to close that gap. _snapshot_audio_metrics_once() is
tested directly (synchronously) rather than through the thread-dispatching
_make_audio_metrics_snapshot_writer() wrapper, so there is nothing to race
or mock -- production only adds a `threading.Thread(...).start()` around it.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.extensions import db  # noqa: E402
from app_core.models import AudioSourceMetrics  # noqa: E402
from app_core.audio.ingest import AudioSourceStatus, AudioSourceType  # noqa: E402
import eas_monitoring_service as svc  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover - sqlalchemy hook
    return "TEXT"


@dataclass
class _FakeMetrics:
    peak_level_db: Optional[float]
    rms_level_db: Optional[float]
    sample_rate: int = 44100
    channels: int = 1
    frames_captured: int = 12345
    silence_detected: bool = False
    buffer_utilization: float = 0.5
    metadata: Dict = field(default_factory=dict)


@dataclass
class _FakeConfig:
    source_type: AudioSourceType


@dataclass
class _FakeSource:
    status: AudioSourceStatus
    metrics: Optional[_FakeMetrics]
    config: _FakeConfig


class _FakeController:
    def __init__(self, sources: Dict[str, _FakeSource]):
        self._sources = sources

    def get_all_sources(self):
        return self._sources


@pytest.fixture
def snapshot_app(tmp_path: Path):
    database_path = tmp_path / "snapshot_writer.db"
    app = Flask("snapshot-writer-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        AudioSourceMetrics.__table__.create(bind=db.engine)
        yield app
        db.session.remove()
        AudioSourceMetrics.__table__.drop(bind=db.engine)


def _run_snapshot(app, sources, monkeypatch):
    controller = None if sources is None else _FakeController(sources)
    monkeypatch.setattr(svc, "_audio_controller", controller)
    svc._snapshot_audio_metrics_once(app)


def test_writes_one_row_per_running_source(snapshot_app, monkeypatch):
    sources = {
        "sdr-wbks": _FakeSource(
            status=AudioSourceStatus.RUNNING,
            metrics=_FakeMetrics(peak_level_db=-6.0, rms_level_db=-18.0, metadata={"rbds_lock_state": "LOCKED"}),
            config=_FakeConfig(source_type=AudioSourceType.SDR),
        ),
        "wnci": _FakeSource(
            status=AudioSourceStatus.RUNNING,
            metrics=_FakeMetrics(peak_level_db=-3.0, rms_level_db=-12.0),
            config=_FakeConfig(source_type=AudioSourceType.STREAM),
        ),
    }
    _run_snapshot(snapshot_app, sources, monkeypatch)

    with snapshot_app.app_context():
        rows = AudioSourceMetrics.query.order_by(AudioSourceMetrics.source_name).all()
        assert [r.source_name for r in rows] == ["sdr-wbks", "wnci"]

        sdr_row = rows[0]
        assert sdr_row.source_type == "sdr"
        assert sdr_row.peak_level_db == pytest.approx(-6.0)
        assert sdr_row.peak_level_linear == pytest.approx(10 ** (-6.0 / 20.0))
        assert sdr_row.rms_level_linear == pytest.approx(10 ** (-18.0 / 20.0))
        assert sdr_row.source_metadata == {"rbds_lock_state": "LOCKED"}

        stream_row = rows[1]
        assert stream_row.source_type == "stream"


def test_skips_non_running_and_metrics_less_sources(snapshot_app, monkeypatch):
    sources = {
        "stopped-source": _FakeSource(
            status=AudioSourceStatus.STOPPED,
            metrics=_FakeMetrics(peak_level_db=-6.0, rms_level_db=-18.0),
            config=_FakeConfig(source_type=AudioSourceType.SDR),
        ),
        "no-metrics-yet": _FakeSource(
            status=AudioSourceStatus.RUNNING,
            metrics=None,
            config=_FakeConfig(source_type=AudioSourceType.SDR),
        ),
    }
    _run_snapshot(snapshot_app, sources, monkeypatch)

    with snapshot_app.app_context():
        assert AudioSourceMetrics.query.count() == 0


def test_digital_silence_negative_infinity_does_not_crash(snapshot_app, monkeypatch):
    sources = {
        "silent": _FakeSource(
            status=AudioSourceStatus.RUNNING,
            metrics=_FakeMetrics(peak_level_db=float("-inf"), rms_level_db=float("-inf")),
            config=_FakeConfig(source_type=AudioSourceType.SDR),
        ),
    }
    _run_snapshot(snapshot_app, sources, monkeypatch)

    with snapshot_app.app_context():
        row = AudioSourceMetrics.query.one()
        assert row.peak_level_linear == 0.0
        assert row.rms_level_linear == 0.0


def test_no_controller_does_not_raise(snapshot_app, monkeypatch):
    _run_snapshot(snapshot_app, None, monkeypatch)

    with snapshot_app.app_context():
        assert AudioSourceMetrics.query.count() == 0


def test_numpy_scalar_metrics_are_coerced_to_native_types(snapshot_app, monkeypatch):
    """Regression test: production always feeds this writer numpy scalars.

    AudioSourceAdapter._update_metrics (app_core/audio/ingest.py) computes
    peak/rms dB via ``20 * np.log10(...)`` and defaults them to ``-np.inf``,
    so every field on the real ``AudioMetrics`` object is a numpy scalar
    (np.float32/np.float64/np.int64), never a plain Python ``float``/``int``
    like the fixtures above use. SQLite's loose typing let that slide
    silently, but psycopg2 raises ``can't adapt type 'numpy.float32'`` and
    the whole commit -- therefore the whole snapshot, every source, every
    second -- was silently failing in production. This reproduces that
    exact input shape and asserts both that the write succeeds and that
    what lands in the DB is a native Python type, not a numpy one.
    """
    np = pytest.importorskip("numpy")

    sources = {
        "sdr-wbks": _FakeSource(
            status=AudioSourceStatus.RUNNING,
            metrics=_FakeMetrics(
                peak_level_db=np.float32(-6.0),
                rms_level_db=np.float32(-18.0),
                sample_rate=np.int64(44100),
                channels=np.int64(1),
                frames_captured=np.int64(12345),
                buffer_utilization=np.float64(0.5),
            ),
            config=_FakeConfig(source_type=AudioSourceType.SDR),
        ),
    }
    _run_snapshot(snapshot_app, sources, monkeypatch)

    with snapshot_app.app_context():
        row = AudioSourceMetrics.query.one()
        assert row.peak_level_db == pytest.approx(-6.0)
        assert type(row.peak_level_linear) is float
        assert type(row.rms_level_linear) is float
        assert type(row.sample_rate) is int
        assert type(row.buffer_utilization) is float
