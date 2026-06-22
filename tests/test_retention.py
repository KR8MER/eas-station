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

"""Tests for the automated data-retention sweeper (app_core/retention.py)."""

import os
from datetime import timedelta

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app_core import retention
from app_core._models_alerts import ReceivedEASAlert
from app_core._models_audio import (
    AudioAlert,
    AudioSourceMetrics,
    StreamMetadataLog,
)
from app_core._models_settings import RetentionSettings
from app_core.extensions import db
from app_utils import utc_now


# SQLite cannot render the PostgreSQL JSONB columns some models declare;
# map them to plain JSON for the in-memory test database.
@compiles(JSONB, "sqlite")
def _render_jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def app():
    """Minimal Flask app bound to an in-memory SQLite database.

    Only the tables the retention sweeper touches are created.
    """
    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["TESTING"] = True
    db.init_app(flask_app)

    with flask_app.app_context():
        db.metadata.create_all(
            bind=db.engine,
            tables=[
                RetentionSettings.__table__,
                StreamMetadataLog.__table__,
                AudioAlert.__table__,
                AudioSourceMetrics.__table__,
                ReceivedEASAlert.__table__,
            ],
        )
        yield flask_app
        db.session.remove()


# ---------------------------------------------------------------------------
# Cutoff math and disabled (0) semantics
# ---------------------------------------------------------------------------

class TestComputeCutoff:
    def test_zero_means_keep_forever(self):
        assert retention.compute_cutoff(0) is None

    def test_negative_means_keep_forever(self):
        assert retention.compute_cutoff(-5) is None

    def test_none_and_garbage_mean_keep_forever(self):
        assert retention.compute_cutoff(None) is None
        assert retention.compute_cutoff("not-a-number") is None

    def test_positive_days_produce_cutoff(self):
        now = utc_now()
        cutoff = retention.compute_cutoff(7, now=now)
        assert cutoff == now - timedelta(days=7)

    def test_string_days_accepted(self):
        now = utc_now()
        assert retention.compute_cutoff("14", now=now) == now - timedelta(days=14)


# ---------------------------------------------------------------------------
# File pruning
# ---------------------------------------------------------------------------

def _make_file(path, age_days, size=16):
    path.write_bytes(b"x" * size)
    old = (utc_now() - timedelta(days=age_days)).timestamp()
    os.utime(path, (old, old))


class TestPruneDirectory:
    def test_removes_only_old_matching_files(self, tmp_path):
        _make_file(tmp_path / "old.npy", age_days=30)
        _make_file(tmp_path / "new.npy", age_days=1)
        _make_file(tmp_path / "old.wav", age_days=30)

        files, bytes_removed = retention.prune_directory(
            str(tmp_path), 14, pattern="*.npy"
        )

        assert files == 1
        assert bytes_removed == 16
        assert not (tmp_path / "old.npy").exists()
        assert (tmp_path / "new.npy").exists()
        # Non-matching pattern untouched
        assert (tmp_path / "old.wav").exists()

    def test_default_pattern_prunes_everything_old(self, tmp_path):
        _make_file(tmp_path / "a.wav", age_days=10)
        _make_file(tmp_path / "b.mp3", age_days=10)
        _make_file(tmp_path / "fresh.wav", age_days=0)

        files, _ = retention.prune_directory(str(tmp_path), 7)

        assert files == 2
        assert (tmp_path / "fresh.wav").exists()

    def test_zero_days_is_noop(self, tmp_path):
        _make_file(tmp_path / "ancient.npy", age_days=400)

        files, bytes_removed = retention.prune_directory(str(tmp_path), 0)

        assert (files, bytes_removed) == (0, 0)
        assert (tmp_path / "ancient.npy").exists()

    def test_missing_directory_is_noop(self, tmp_path):
        files, bytes_removed = retention.prune_directory(
            str(tmp_path / "does-not-exist"), 7
        )
        assert (files, bytes_removed) == (0, 0)

    def test_subdirectories_are_left_alone(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        old = (utc_now() - timedelta(days=30)).timestamp()
        os.utime(sub, (old, old))

        files, _ = retention.prune_directory(str(tmp_path), 7)

        assert files == 0
        assert sub.exists()


# ---------------------------------------------------------------------------
# Settings accessor
# ---------------------------------------------------------------------------

class TestRetentionSettings:
    def test_get_creates_singleton_with_defaults(self, app):
        settings = retention.get_retention_settings()
        assert settings.id == 1
        assert settings.enabled is True
        assert settings.iq_capture_max_age_days == 14
        assert settings.temp_audio_max_age_days == 7
        assert settings.stream_metadata_max_age_days == 90
        assert settings.audio_alert_max_age_days == 90
        assert settings.audio_metrics_max_age_days == 30
        assert settings.received_alert_audio_max_age_days == 30

        # Second call returns the same row
        again = retention.get_retention_settings()
        assert again.id == 1

    def test_update_clamps_and_persists(self, app):
        updated = retention.update_retention_settings(
            {"iq_capture_max_age_days": 3, "enabled": False, "bogus_key": 99}
        )
        assert updated["iq_capture_max_age_days"] == 3
        assert updated["enabled"] is False
        # Untouched fields keep defaults
        assert updated["temp_audio_max_age_days"] == 7

    def test_update_rejects_invalid_values(self, app):
        with pytest.raises(ValueError):
            retention.update_retention_settings({"temp_audio_max_age_days": -1})
        with pytest.raises(ValueError):
            retention.update_retention_settings({"temp_audio_max_age_days": "abc"})
        with pytest.raises(ValueError):
            retention.update_retention_settings({"temp_audio_max_age_days": 99999})


# ---------------------------------------------------------------------------
# DB row pruning and blob stripping
# ---------------------------------------------------------------------------

def _seed_rows(now):
    old = now - timedelta(days=120)
    recent = now - timedelta(days=1)

    db.session.add_all([
        StreamMetadataLog(source_name="stream1", timestamp=old, title="old song"),
        StreamMetadataLog(source_name="stream1", timestamp=recent, title="new song"),
        AudioAlert(
            source_name="src", alert_level="warning", alert_type="silence",
            message="old alert", created_at=old,
        ),
        AudioAlert(
            source_name="src", alert_level="info", alert_type="silence",
            message="new alert", created_at=recent,
        ),
        AudioSourceMetrics(
            source_name="src", source_type="sdr",
            peak_level_db=-6.0, rms_level_db=-20.0,
            peak_level_linear=0.5, rms_level_linear=0.1,
            sample_rate=44100, channels=1, frames_captured=1024,
            timestamp=old,
        ),
        AudioSourceMetrics(
            source_name="src", source_type="sdr",
            peak_level_db=-6.0, rms_level_db=-20.0,
            peak_level_linear=0.5, rms_level_linear=0.1,
            sample_rate=44100, channels=1, frames_captured=2048,
            timestamp=recent,
        ),
        ReceivedEASAlert(
            received_at=old, source_name="src",
            forwarding_decision="ignored", raw_audio_data=b"OLDWAV",
        ),
        ReceivedEASAlert(
            received_at=recent, source_name="src",
            forwarding_decision="forwarded", raw_audio_data=b"NEWWAV",
        ),
    ])
    db.session.commit()


class TestDatabasePruning:
    def test_sweep_prunes_old_rows_and_strips_blobs(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIO_CAPTURE_DIR", str(tmp_path / "captures"))
        monkeypatch.setattr(retention, "TEMP_AUDIO_DIR", str(tmp_path / "eas-audio"))

        now = utc_now()
        _seed_rows(now)
        settings = retention.get_retention_settings().to_dict()

        summary = retention.run_sweep(settings)

        assert summary["errors"] == []
        assert summary["stream_metadata_rows_deleted"] == 1
        assert summary["audio_alert_rows_deleted"] == 1
        assert summary["audio_metrics_rows_deleted"] == 1
        assert summary["received_alert_audio_stripped"] == 1

        assert db.session.query(StreamMetadataLog).count() == 1
        assert db.session.query(AudioAlert).count() == 1
        assert db.session.query(AudioSourceMetrics).count() == 1

        # Received alert ROWS are never deleted — only the blob is stripped.
        alerts = (
            db.session.query(ReceivedEASAlert)
            .order_by(ReceivedEASAlert.received_at)
            .all()
        )
        assert len(alerts) == 2
        assert alerts[0].raw_audio_data is None
        assert alerts[1].raw_audio_data == b"NEWWAV"

    def test_zero_retention_keeps_all_rows(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIO_CAPTURE_DIR", str(tmp_path / "captures"))
        monkeypatch.setattr(retention, "TEMP_AUDIO_DIR", str(tmp_path / "eas-audio"))

        now = utc_now()
        _seed_rows(now)
        settings = retention.update_retention_settings({
            "iq_capture_max_age_days": 0,
            "temp_audio_max_age_days": 0,
            "stream_metadata_max_age_days": 0,
            "audio_alert_max_age_days": 0,
            "audio_metrics_max_age_days": 0,
            "received_alert_audio_max_age_days": 0,
        })

        summary = retention.run_sweep(settings)

        assert summary["errors"] == []
        assert db.session.query(StreamMetadataLog).count() == 2
        assert db.session.query(AudioAlert).count() == 2
        assert db.session.query(AudioSourceMetrics).count() == 2
        stripped = (
            db.session.query(ReceivedEASAlert)
            .filter(ReceivedEASAlert.raw_audio_data.is_(None))
            .count()
        )
        assert stripped == 0

    def test_sweep_prunes_iq_and_temp_files(self, app, tmp_path, monkeypatch):
        capture_dir = tmp_path / "captures"
        temp_dir = tmp_path / "eas-audio"
        capture_dir.mkdir()
        temp_dir.mkdir()
        monkeypatch.setenv("RADIO_CAPTURE_DIR", str(capture_dir))
        monkeypatch.setattr(retention, "TEMP_AUDIO_DIR", str(temp_dir))

        _make_file(capture_dir / "old_iq.npy", age_days=30)
        _make_file(capture_dir / "new_iq.npy", age_days=1)
        # Non-.npy files in the capture dir are not retention's business
        _make_file(capture_dir / "notes.txt", age_days=30)
        _make_file(temp_dir / "old_debug.wav", age_days=30)
        _make_file(temp_dir / "new_debug.wav", age_days=1)

        settings = retention.get_retention_settings().to_dict()
        summary = retention.run_sweep(settings)

        assert summary["errors"] == []
        assert summary["iq_files_removed"] == 1
        assert summary["temp_files_removed"] == 1
        assert summary["bytes_removed"] == 32
        assert not (capture_dir / "old_iq.npy").exists()
        assert (capture_dir / "new_iq.npy").exists()
        assert (capture_dir / "notes.txt").exists()
        assert not (temp_dir / "old_debug.wav").exists()
        assert (temp_dir / "new_debug.wav").exists()

    def test_one_failing_step_does_not_stop_the_rest(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIO_CAPTURE_DIR", str(tmp_path / "captures"))
        monkeypatch.setattr(retention, "TEMP_AUDIO_DIR", str(tmp_path / "eas-audio"))

        now = utc_now()
        _seed_rows(now)

        def _boom(*args, **kwargs):
            raise RuntimeError("disk exploded")

        monkeypatch.setattr(retention, "prune_directory", _boom)

        settings = retention.get_retention_settings().to_dict()
        summary = retention.run_sweep(settings)

        # Both file steps failed but DB steps still ran.
        assert len(summary["errors"]) == 2
        assert summary["stream_metadata_rows_deleted"] == 1
        assert summary["audio_alert_rows_deleted"] == 1
        assert summary["audio_metrics_rows_deleted"] == 1
        assert summary["received_alert_audio_stripped"] == 1


# ---------------------------------------------------------------------------
# Scheduler behaviour
# ---------------------------------------------------------------------------

class TestRetentionScheduler:
    def test_run_sweep_now_respects_disabled_flag(self, app, monkeypatch):
        retention.update_retention_settings({"enabled": False})
        scheduler = retention.RetentionScheduler(app)

        called = []
        monkeypatch.setattr(retention, "run_sweep", lambda s: called.append(s) or {})

        result = scheduler.run_sweep_now()
        assert result == {"skipped": True, "reason": "disabled"}
        assert called == []

    def test_run_sweep_now_runs_when_enabled(self, app, monkeypatch):
        scheduler = retention.RetentionScheduler(app)

        seen = {}
        monkeypatch.setattr(
            retention, "run_sweep", lambda s: seen.update(s) or {"ok": True}
        )

        result = scheduler.run_sweep_now()
        assert result == {"ok": True}
        assert seen["iq_capture_max_age_days"] == 14
        assert seen["enabled"] is True

    def test_start_and_stop(self, app):
        scheduler = retention.RetentionScheduler(
            app, interval_seconds=3600, startup_delay_seconds=3600
        )
        scheduler.start()
        assert scheduler.is_running
        # Idempotent start
        scheduler.start()
        scheduler.stop()
        assert not scheduler.is_running
