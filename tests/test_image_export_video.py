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

Tests for the animated video share-card export --
app_utils/image_export/video_export.py.

generate_alert_image() itself is stubbed out here (its own DB-backed map
fetch and full font/theme rendering pipeline are covered by
test_image_export_themes.py) so these tests focus on what's specific to
video_export.py: that it drives one call to generate_alert_image() per
build_radar_loop() frame, in order, with the frame's own radar_time and
issued flag threaded through correctly, and that the frames are actually
encoded into a valid MP4 by the real ffmpeg binary (not mocked -- ffmpeg
is already a CI dependency for the audio-source tests, so this exercises
the real subprocess/encode path rather than just the Python glue around
it). The overriding concern, same as the GIF export this replaced, is
that the warning polygon can never appear on a frame timestamped before
the alert's real `sent` time.
"""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    pytest.skip("Pillow is required for image_export tests", allow_module_level=True)

if shutil.which("ffmpeg") is None:  # pragma: no cover
    pytest.skip("ffmpeg is required for video_export tests", allow_module_level=True)


_PKG_DIR = Path(__file__).resolve().parent.parent / "app_utils" / "image_export"
_spec = importlib.util.spec_from_file_location(
    "image_export_video_under_test",
    _PKG_DIR / "__init__.py",
    submodule_search_locations=[str(_PKG_DIR)],
)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = image_export
_spec.loader.exec_module(image_export)

video_mod = image_export.video_export
radar_loop_mod = image_export.radar_loop

_TEST_GEOM = {
    "type": "Polygon",
    "coordinates": [[[-84.30, 41.10], [-83.85, 40.86], [-83.90, 40.72],
                     [-84.22, 40.61], [-84.30, 41.10]]],
}


def _past(**offset):
    return radar_loop_mod._floor_to_cadence(datetime.now(timezone.utc) - timedelta(**offset))


def _alert(**overrides):
    defaults = dict(
        id=1, category="Met", severity="Severe",
        sent=_past(minutes=10),
        expires=_past(minutes=10) + timedelta(minutes=5),
        cancelled_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def isolated_output_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(radar_loop_mod, "_loop_output_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def fake_render_map(monkeypatch):
    """build_radar_loop()'s own frame renderer -- stubbed so the frame
    *list* (timestamps + issued flags) computes fast and without network
    access. Its pixel output is irrelevant here: generate_alert_image()
    (stubbed separately below) never reads these cached frames back."""
    def _fake(geom, severity, *, category, sent, map_w, map_h, show_polygon=True):
        return Image.new("RGB", (4, 4), (0, 128, 0))
    monkeypatch.setattr(radar_loop_mod, "_render_map", _fake)


@pytest.fixture
def fake_generate_alert_image(monkeypatch):
    """Stub the full-card renderer video_export.py drives once per frame.
    Records (radar_time, radar_show_polygon) for every call, and paints a
    frame whose colour varies by timestamp so the encoded video actually
    has distinct frames to check."""
    calls = []

    def _fake(alert, coverage_data, ipaws_data, location_settings, **kwargs):
        radar_time = kwargs["radar_time"]
        show_polygon = kwargs["radar_show_polygon"]
        calls.append((radar_time, show_polygon))
        base = (200, 30, 30) if show_polygon else (30, 30, 200)
        color = (base[0], radar_time.minute % 256, base[2])
        # Even, encoder-friendly size -- keeps the real ffmpeg pass fast.
        img = Image.new("RGB", (64, 48), color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    monkeypatch.setattr(video_mod, "generate_alert_image", _fake)
    return calls


def _ffprobe_json(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, check=True,
    )
    return json.loads(result.stdout)


# ── Eligibility ──────────────────────────────────────────────────────────────

def test_rejects_non_weather_alert(fake_render_map, fake_generate_alert_image, isolated_output_dir):
    alert = _alert(category="Transport")
    with pytest.raises(ValueError):
        video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)


def test_rejects_missing_sent_time(fake_render_map, fake_generate_alert_image, isolated_output_dir):
    alert = _alert(sent=None)
    with pytest.raises(ValueError):
        video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)


def test_raises_when_every_frame_render_fails(monkeypatch, fake_generate_alert_image, isolated_output_dir):
    def _always_fails(*a, **k):
        raise RuntimeError("WMS timeout")
    monkeypatch.setattr(radar_loop_mod, "_render_map", _always_fails)

    alert = _alert()
    with pytest.raises(ValueError):
        video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)


def test_raises_when_ffmpeg_missing(monkeypatch, fake_render_map, fake_generate_alert_image, isolated_output_dir):
    monkeypatch.setattr(video_mod.shutil, "which", lambda name: None)
    alert = _alert()
    with pytest.raises(ValueError, match="ffmpeg"):
        video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)


# ── Frame assembly ───────────────────────────────────────────────────────────

def test_one_generate_alert_image_call_per_radar_loop_frame(
    fake_render_map, fake_generate_alert_image, isolated_output_dir,
):
    alert = _alert()
    loop_result = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=100)

    video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)

    assert len(fake_generate_alert_image) == len(loop_result["frames"])


def test_leadin_frames_render_without_polygon_issuance_frame_with(
    fake_render_map, fake_generate_alert_image, isolated_output_dir,
):
    """The overriding requirement: a frame timestamped before the alert's
    own `sent` time must never be told to draw the polygon, and the first
    frame at/after `sent` must be."""
    alert = _alert()
    video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)

    sent = alert.sent
    for radar_time, show_polygon in fake_generate_alert_image:
        assert show_polygon == (radar_time >= sent)
    assert any(show_polygon is False for _, show_polygon in fake_generate_alert_image)
    assert any(show_polygon is True for _, show_polygon in fake_generate_alert_image)


def test_frames_passed_in_chronological_order(
    fake_render_map, fake_generate_alert_image, isolated_output_dir,
):
    alert = _alert()
    video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)

    times = [radar_time for radar_time, _ in fake_generate_alert_image]
    assert times == sorted(times)


# ── Real ffmpeg encode ───────────────────────────────────────────────────────

def test_output_is_a_valid_mp4(
    fake_render_map, fake_generate_alert_image, isolated_output_dir, tmp_path,
):
    alert = _alert()
    video_bytes = video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)

    assert video_bytes[4:8] == b"ftyp", "not a valid MP4 (missing ftyp box)"

    out_path = tmp_path / "check.mp4"
    out_path.write_bytes(video_bytes)
    probed = _ffprobe_json(out_path)
    video_streams = [s for s in probed["streams"] if s["codec_type"] == "video"]
    assert len(video_streams) == 1
    assert video_streams[0]["codec_name"] == "h264"
    assert video_streams[0]["pix_fmt"] == "yuv420p"
    # Card is 64x48 -- already even, so the even-dimension safety filter
    # must be a no-op here.
    assert video_streams[0]["width"] == 64
    assert video_streams[0]["height"] == 48


def test_last_frame_is_held_by_repeating_it(
    fake_render_map, fake_generate_alert_image, isolated_output_dir, tmp_path,
):
    alert = _alert()
    video_bytes = video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)

    out_path = tmp_path / "check.mp4"
    out_path.write_bytes(video_bytes)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames",
         "-show_entries", "stream=nb_read_frames",
         "-of", "csv=p=0", str(out_path)],
        capture_output=True, check=True,
    )
    n_frames = int(result.stdout.decode().strip())
    n_source_frames = len(fake_generate_alert_image)
    assert n_frames == n_source_frames - 1 + video_mod.VIDEO_LAST_FRAME_HOLD_COUNT


def test_odd_scaled_dimensions_are_forced_even(
    fake_render_map, isolated_output_dir, monkeypatch, tmp_path,
):
    """scale is a user-supplied float and can round a card's even native
    size to an odd pixel count -- yuv420p requires both dimensions even,
    so the encoder must correct this rather than fail."""
    def _fake(alert, coverage_data, ipaws_data, location_settings, **kwargs):
        img = Image.new("RGB", (65, 47), (10, 20, 30))  # deliberately odd
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    monkeypatch.setattr(video_mod, "generate_alert_image", _fake)

    alert = _alert()
    video_bytes = video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)

    out_path = tmp_path / "check.mp4"
    out_path.write_bytes(video_bytes)
    probed = _ffprobe_json(out_path)
    video_stream = next(s for s in probed["streams"] if s["codec_type"] == "video")
    assert video_stream["width"] % 2 == 0
    assert video_stream["height"] % 2 == 0


def test_single_frame_alert_still_produces_a_valid_video(
    monkeypatch, fake_generate_alert_image, isolated_output_dir,
):
    """An alert issued and expiring in the very same 5-minute bucket, with
    the lead-in window fully clamped away by 'never request the future',
    is a degenerate one-frame case -- must not crash the encoder."""
    def _fake(geom, severity, *, category, sent, map_w, map_h, show_polygon=True):
        return Image.new("RGB", (4, 4), (0, 128, 0))
    monkeypatch.setattr(radar_loop_mod, "_render_map", _fake)

    now = _past(minutes=0)
    alert = _alert(sent=now, expires=now)
    monkeypatch.setattr(
        radar_loop_mod, "_needed_timestamps",
        lambda sent, end, **kw: [radar_loop_mod._floor_to_cadence(sent)],
    )

    video_bytes = video_mod.generate_alert_video(alert, {}, None, {}, _TEST_GEOM)
    assert video_bytes[4:8] == b"ftyp"
