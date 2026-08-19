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

"""Tests for eas_monitoring_service._make_audio_metrics_snapshot_writer.

Nothing in production ever wrote to the audio_source_metrics table -- only
tests instantiated AudioSourceMetrics directly -- so the RBDS History modal
always reported "No stored RBDS snapshots" regardless of uptime. These tests
cover the writer added to close that gap.
"""

import sys
import threading
import time
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


def _run_writer_and_wait(app, sources, monkeypatch):
    monkeypatch.setattr(svc, "_audio_controller", _FakeController(sources))
    trigger = svc._make_audio_metrics_snapshot_writer(app)

    # The writer dispatches its DB work onto a daemon thread so it can never
    # stall the caller. Wrap threading.Thread to capture that thread so the
    # test can join it instead of racing it.
    started = []
    real_thread = threading.Thread

    def _capturing_thread(*args, **kwargs):
        t = real_thread(*args, **kwargs)
        started.append(t)
        return t

    monkeypatch.setattr(threading, "Thread", _capturing_thread)
    trigger()
    assert started, "writer did not spawn a thread"
    started[0].join(timeout=5)


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
    _run_writer_and_wait(snapshot_app, sources, monkeypatch)

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
    _run_writer_and_wait(snapshot_app, sources, monkeypatch)

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
    _run_writer_and_wait(snapshot_app, sources, monkeypatch)

    with snapshot_app.app_context():
        row = AudioSourceMetrics.query.one()
        assert row.peak_level_linear == 0.0
        assert row.rms_level_linear == 0.0


def test_no_controller_does_not_raise(snapshot_app, monkeypatch):
    monkeypatch.setattr(svc, "_audio_controller", None)
    trigger = svc._make_audio_metrics_snapshot_writer(snapshot_app)
    trigger()
    time.sleep(0.2)

    with snapshot_app.app_context():
        assert AudioSourceMetrics.query.count() == 0
