"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station

Tests for the /api/radio/diagnostics/capture endpoints.

The endpoints orchestrate three moving parts:
  1. A Redis-backed command queue to the standalone SDR hardware service
  2. An on-disk .npy capture file written by that service
  3. A second Redis key (RADIO_CAPTURE_REDIS_PREFIX + capture_id) that
     maps the operator-facing capture id to the on-disk path

Each test patches a minimal fake Redis and pretends the SDR service has
already produced a result so the web layer can be exercised in isolation.
The on-disk capture file is created in a tmp_path so the path-traversal
guard sees a realistic in-tree path.
"""

from __future__ import annotations

import json
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
from app_core.models import RadioReceiver
import webapp.routes_settings_radio as radio_routes


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover
    return "TEXT"


class FakeRedis:
    """Tiny in-memory Redis stand-in for the capture endpoints.

    Covers exactly the operations the routes use: ``rpush`` (writing the
    capture command), ``get`` (polling for the SDR-service result and
    looking up capture metadata), ``setex`` (storing the capture pointer
    for the download route), and ``delete`` (cleanup after download).

    A canned ``capture_iq_result`` can be pre-loaded; when the route's
    polling loop calls ``get("sdr:command_result:<id>")`` for any command
    id, the canned result is returned. This lets each test pretend the
    SDR service responded with a specific payload without spinning one up.
    """

    def __init__(self, capture_iq_result=None):
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.capture_iq_result = capture_iq_result

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def get(self, key):
        if key.startswith("sdr:command_result:") and self.capture_iq_result is not None:
            return json.dumps(self.capture_iq_result)
        return self.kv.get(key)

    def setex(self, key, ttl, value):
        self.kv[key] = value
        return True

    def delete(self, key):
        return self.kv.pop(key, None) is not None


@pytest.fixture
def capture_app(tmp_path, monkeypatch):
    """Build a minimal Flask app with just the radio routes registered."""
    database_path = tmp_path / "diag.db"
    app = Flask("radio-diag-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    # Point the capture dir at tmp_path so path-traversal validation
    # exercises a real filesystem location without needing /var/log.
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    monkeypatch.setattr(radio_routes, "RADIO_CAPTURE_DIR", str(capture_dir))

    # Silence the event-log shim — its real implementation talks to the
    # RadioManager which is not present in this isolated test app.
    monkeypatch.setattr(
        radio_routes, "_log_radio_event", lambda *args, **kwargs: None
    )

    with app.app_context():
        engine = db.engine
        RadioReceiver.__table__.create(bind=engine)
        radio_routes.register(app, logging.getLogger("radio-diag-test"))
        yield app, capture_dir
        db.session.remove()
        RadioReceiver.__table__.drop(bind=engine, checkfirst=True)


def _add_receiver():
    receiver = RadioReceiver(
        identifier="WXTEST",
        display_name="Capture Test",
        driver="rtlsdr",
        frequency_hz=98_500_000,
        sample_rate=2_400_000,
        modulation_type="WFM",
        audio_output=True,
        stereo_enabled=False,
        deemphasis_us=75.0,
        enable_rbds=True,
        enabled=True,
        auto_start=False,
        squelch_enabled=False,
        squelch_threshold_db=-60.0,
        squelch_open_ms=100,
        squelch_close_ms=400,
        squelch_alarm=False,
    )
    db.session.add(receiver)
    db.session.commit()
    return receiver


def test_capture_iq_happy_path(capture_app, monkeypatch):
    """POST creates a capture; GET streams it and cleans up."""
    app, capture_dir = capture_app

    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        # Simulate the .npy the SDR service would have written.
        capture_path = capture_dir / "iq_WXTEST_250000Hz_1700000000_abcd1234.npy"
        capture_path.write_bytes(b"NUMPY-FAKE-PAYLOAD")

        fake_redis = FakeRedis(capture_iq_result={
            "success": True,
            "path": str(capture_path),
            "filename": capture_path.name,
            "num_samples": 250_000,
            "sample_rate": 250_000,
            "frequency_hz": 98_500_000,
            "size_bytes": capture_path.stat().st_size,
            "dtype": "complex64",
        })
        monkeypatch.setattr(radio_routes, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.post(
            f"/api/radio/diagnostics/capture/{receiver_id}",
            json={"duration_sec": 1.0},
        )
        assert resp.status_code == 200, resp.get_json()
        payload = resp.get_json()
        assert payload["filename"] == capture_path.name
        assert payload["num_samples"] == 250_000
        assert payload["download_url"].endswith(
            f"/{payload['capture_id']}/download"
        )
        capture_id = payload["capture_id"]
        # capture id is hex-only and ≤ 64 chars (download endpoint enforces this).
        assert all(c in "0123456789abcdef" for c in capture_id)

        # Download succeeds and returns the file bytes.
        dl = client.get(
            f"/api/radio/diagnostics/capture/{capture_id}/download"
        )
        assert dl.status_code == 200
        assert dl.data == b"NUMPY-FAKE-PAYLOAD"
        # send_file sets the attachment headers
        assert "attachment" in dl.headers.get("Content-Disposition", "")
        assert capture_path.name in dl.headers.get("Content-Disposition", "")

        # The route deletes the file and the Redis pointer synchronously
        # before streaming, so the capture is single-use even if the
        # client never finishes reading the response.
        assert not capture_path.exists()
        assert f"radio:diag:capture:{capture_id}" not in fake_redis.kv

        # A second download attempt with the same id must now 404.
        dl2 = client.get(
            f"/api/radio/diagnostics/capture/{capture_id}/download"
        )
        assert dl2.status_code == 404


def test_capture_iq_rejects_out_of_tree_path(capture_app, monkeypatch, tmp_path):
    """The POST handler refuses to register a path outside RADIO_CAPTURE_DIR.

    Defends against a compromised SDR-service worker (or a developer
    accidentally pointing the service at /tmp on a shared host) handing
    the web layer a path it would later happily stream to the browser.
    """
    app, _ = capture_app

    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        # An on-disk file outside the allow-list directory.
        attacker_path = tmp_path / "etc-passwd-lookalike.npy"
        attacker_path.write_bytes(b"sensitive")

        fake_redis = FakeRedis(capture_iq_result={
            "success": True,
            "path": str(attacker_path),
            "filename": "evil.npy",
            "num_samples": 1,
            "sample_rate": 1,
            "frequency_hz": 1,
            "size_bytes": attacker_path.stat().st_size,
        })
        monkeypatch.setattr(radio_routes, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.post(
            f"/api/radio/diagnostics/capture/{receiver_id}",
            json={"duration_sec": 1.0},
        )
        assert resp.status_code == 500
        # The bogus path must never have made it into Redis under any key.
        assert not any(
            k.startswith("radio:diag:capture:") for k in fake_redis.kv
        )
        # And the file itself is untouched (the route doesn't read or delete it).
        assert attacker_path.exists()


def test_download_rejects_non_hex_capture_id(capture_app, monkeypatch):
    """Path traversal via the URL segment is blocked before Redis lookup."""
    app, _ = capture_app

    fake_redis = FakeRedis()
    monkeypatch.setattr(radio_routes, "get_redis_client", lambda: fake_redis)

    with app.app_context():
        client = app.test_client()
        # Slashes are url-encoded by Werkzeug routing, so we test the
        # validation directly with a non-hex string that survives routing.
        resp = client.get(
            "/api/radio/diagnostics/capture/not-a-hex-uuid/download"
        )
        assert resp.status_code == 400


def test_download_404_when_capture_expired(capture_app, monkeypatch):
    """A capture id with no Redis entry returns 404 (TTL expired)."""
    app, _ = capture_app
    fake_redis = FakeRedis()
    monkeypatch.setattr(radio_routes, "get_redis_client", lambda: fake_redis)

    with app.app_context():
        client = app.test_client()
        resp = client.get(
            "/api/radio/diagnostics/capture/" + ("a" * 32) + "/download"
        )
        assert resp.status_code == 404


def test_download_blocks_tampered_redis_path(capture_app, monkeypatch, tmp_path):
    """Defence-in-depth: download endpoint re-validates the on-disk path.

    Even if a capture pointer in Redis has been tampered with to point
    outside RADIO_CAPTURE_DIR (e.g. by a compromised internal process),
    the download route must refuse to serve it.
    """
    app, _ = capture_app
    fake_redis = FakeRedis()
    monkeypatch.setattr(radio_routes, "get_redis_client", lambda: fake_redis)

    bad_path = tmp_path / "tampered.npy"
    bad_path.write_bytes(b"should-not-be-served")
    capture_id = "b" * 32
    fake_redis.kv[f"radio:diag:capture:{capture_id}"] = json.dumps({
        "path": str(bad_path),
        "filename": "tampered.npy",
    })

    with app.app_context():
        client = app.test_client()
        resp = client.get(
            f"/api/radio/diagnostics/capture/{capture_id}/download"
        )
        assert resp.status_code == 400
        # The on-disk file must not have been read or removed.
        assert bad_path.exists()


def test_capture_iq_timeout_returns_504(capture_app, monkeypatch):
    """If the SDR service never responds, the operator gets a 504 with a hint."""
    app, _ = capture_app

    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        # No capture_iq_result configured → the polling loop will time out.
        fake_redis = FakeRedis(capture_iq_result=None)
        monkeypatch.setattr(radio_routes, "get_redis_client", lambda: fake_redis)
        # Short-circuit time so the test doesn't actually sleep 15 seconds.
        time_counter = {"t": 0.0}

        def fake_monotonic():
            time_counter["t"] += 1.0
            return time_counter["t"]

        monkeypatch.setattr(radio_routes.time, "time", fake_monotonic)
        monkeypatch.setattr(radio_routes.time, "sleep", lambda _s: None)

        client = app.test_client()
        resp = client.post(
            f"/api/radio/diagnostics/capture/{receiver_id}",
            json={"duration_sec": 1.0},
        )
        assert resp.status_code == 504
        body = resp.get_json()
        assert "Timeout" in body.get("error", "")
