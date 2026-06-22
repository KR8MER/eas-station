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

"""Tests for the RBDS history API (/api/audio/sources/<name>/rbds/history).

The endpoint derives a BLER trend series and a field-change event log from
the AudioSourceMetrics snapshots the audio service persists once a second.
"""

import logging
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.extensions import db
from app_core.models import AudioSourceMetrics
from app_utils import utc_now
from webapp.admin import audio_ingest as audio_admin


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover - sqlalchemy hook
    return "TEXT"


@pytest.fixture(autouse=True)
def _quiet_audio_globals(monkeypatch):
    monkeypatch.setattr(audio_admin, "_initialization_started", True)
    monkeypatch.setattr(audio_admin, "_start_audio_sources_background", lambda app: None)


@pytest.fixture
def history_app(tmp_path: Path):
    database_path = tmp_path / "rbds_history.db"
    app = Flask("rbds-history-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    with app.app_context():
        AudioSourceMetrics.__table__.create(bind=db.engine)
        audio_admin.register_audio_ingest_routes(app, logging.getLogger("rbds-history-test"))
        yield app
        db.session.remove()
        AudioSourceMetrics.__table__.drop(bind=db.engine)


def _add_snapshot(ts, metadata, source_name="sdr-test"):
    db.session.add(AudioSourceMetrics(
        source_name=source_name,
        source_type="sdr",
        peak_level_db=-6.0,
        rms_level_db=-18.0,
        peak_level_linear=0.5,
        rms_level_linear=0.12,
        sample_rate=48000,
        channels=2,
        frames_captured=0,
        timestamp=ts,
        source_metadata=metadata,
    ))


def test_history_returns_points_and_events(history_app):
    with history_app.app_context():
        base = utc_now() - timedelta(minutes=10)
        for i in range(8):
            md = {
                'rbds_lock_state': 'LOCKED',
                'rbds_raw_bler': 0.01 * i,
                'rbds_net_bler': 0.001 * i,
                'rbds_glitches_rejected': i,
                'rbds_pi_code': '5862',
                'rbds_ta': i >= 4,                      # toggles at i=4
                'rbds_ps_name': 'WXTEST' if i < 6 else 'NEWPS',  # changes at i=6
            }
            _add_snapshot(base + timedelta(seconds=30 * i), md)
        db.session.commit()

        client = history_app.test_client()
        resp = client.get('/api/audio/sources/sdr-test/rbds/history?minutes=60')
        assert resp.status_code == 200
        data = resp.get_json()

        assert data['source'] == 'sdr-test'
        assert data['sample_count'] == 8
        assert len(data['points']) == 8
        assert data['points'][3]['raw_bler'] == pytest.approx(0.03)

        changes = [(ev['field'], ev['to']) for ev in data['events']]
        assert ('TA', True) in changes
        assert ('PS', 'NEWPS') in changes
        # PI never changed, so it must not appear as an event.
        assert not any(field == 'PI' for field, _ in changes)


def test_history_skips_non_rbds_snapshots_and_partial_gaps(history_app):
    with history_app.app_context():
        base = utc_now() - timedelta(minutes=5)
        _add_snapshot(base, {'rbds_lock_state': 'LOCKED', 'rbds_ta': False})
        # Snapshot with no RBDS keys at all — not an RBDS sample, skipped.
        _add_snapshot(base + timedelta(seconds=30), {'stereo_pilot_locked': True})
        # Snapshot where the publisher omitted rbds_ta — must not fabricate
        # a change event when the value reappears unchanged.
        _add_snapshot(base + timedelta(seconds=60), {'rbds_lock_state': 'LOCKED'})
        _add_snapshot(base + timedelta(seconds=90), {'rbds_lock_state': 'LOCKED', 'rbds_ta': False})
        db.session.commit()

        client = history_app.test_client()
        resp = client.get('/api/audio/sources/sdr-test/rbds/history')
        assert resp.status_code == 200
        data = resp.get_json()

        assert data['sample_count'] == 3
        assert data['events'] == []


def test_history_unknown_source_and_bad_minutes(history_app):
    with history_app.app_context():
        client = history_app.test_client()
        resp = client.get('/api/audio/sources/no-such-source/rbds/history?minutes=banana')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['minutes'] == 60  # malformed value falls back to default
        assert data['points'] == []
        assert data['events'] == []


def test_history_downsamples_long_series(history_app):
    with history_app.app_context():
        base = utc_now() - timedelta(minutes=30)
        for i in range(1000):
            _add_snapshot(
                base + timedelta(seconds=i),
                {'rbds_lock_state': 'LOCKED', 'rbds_raw_bler': 0.01},
            )
        db.session.commit()

        client = history_app.test_client()
        resp = client.get('/api/audio/sources/sdr-test/rbds/history?minutes=60')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['sample_count'] == 1000
        assert len(data['points']) <= 500
