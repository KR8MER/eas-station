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

Tests for the animated GIF share-card export --
app_utils/image_export/gif_export.py.

generate_alert_image() itself is stubbed out here (its own DB-backed map
fetch and full font/theme rendering pipeline are covered by
test_image_export_themes.py) so these tests focus on what's specific to
gif_export.py: that it drives one call to generate_alert_image() per
build_radar_loop() frame, in order, with the frame's own radar_time and
issued flag threaded through correctly, and assembles the results into a
valid multi-frame looping GIF -- the overriding concern being that the
warning polygon can never appear on a frame timestamped before the
alert's real `sent` time (see radar_loop.py's RADAR_LOOP_LEADIN_MINUTES).
"""
from __future__ import annotations

import importlib.util
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from PIL import Image, ImageSequence
except ImportError:  # pragma: no cover
    pytest.skip("Pillow is required for image_export tests", allow_module_level=True)


_PKG_DIR = Path(__file__).resolve().parent.parent / "app_utils" / "image_export"
_spec = importlib.util.spec_from_file_location(
    "image_export_gif_under_test",
    _PKG_DIR / "__init__.py",
    submodule_search_locations=[str(_PKG_DIR)],
)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = image_export
_spec.loader.exec_module(image_export)

gif_mod = image_export.gif_export
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
    """Stub the full-card renderer gif_export.py drives once per frame.
    Records (radar_time, radar_show_polygon) for every call, and paints a
    visibly different colour depending on radar_show_polygon so a real
    GIF decode can confirm the frames actually differ."""
    calls = []

    def _fake(alert, coverage_data, ipaws_data, location_settings, **kwargs):
        radar_time = kwargs["radar_time"]
        show_polygon = kwargs["radar_show_polygon"]
        calls.append((radar_time, show_polygon))
        # Vary pixel content per timestamp (not just per issued/not-issued)
        # so no two frames are byte-identical -- Pillow's GIF writer
        # coalesces genuinely-identical consecutive frames (accumulating
        # their durations into one), which a real card render would never
        # trigger since the radar tile changes every 5 minutes.
        base = (200, 30, 30) if show_polygon else (30, 30, 200)
        color = (base[0], radar_time.minute % 256, base[2])
        img = Image.new("RGB", (40, 30), color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    monkeypatch.setattr(gif_mod, "generate_alert_image", _fake)
    return calls


def _gif_durations(gif_bytes: bytes):
    img = Image.open(io.BytesIO(gif_bytes))
    return [frame.info.get("duration") for frame in ImageSequence.Iterator(img)]


# ── Eligibility ──────────────────────────────────────────────────────────────

def test_rejects_non_weather_alert(fake_render_map, fake_generate_alert_image, isolated_output_dir):
    alert = _alert(category="Transport")
    with pytest.raises(ValueError):
        gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)


def test_rejects_missing_sent_time(fake_render_map, fake_generate_alert_image, isolated_output_dir):
    alert = _alert(sent=None)
    with pytest.raises(ValueError):
        gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)


def test_raises_when_every_frame_render_fails(monkeypatch, fake_generate_alert_image, isolated_output_dir):
    def _always_fails(*a, **k):
        raise RuntimeError("WMS timeout")
    monkeypatch.setattr(radar_loop_mod, "_render_map", _always_fails)

    alert = _alert()
    with pytest.raises(ValueError):
        gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)


# ── Frame assembly ───────────────────────────────────────────────────────────

def test_one_generate_alert_image_call_per_radar_loop_frame(
    fake_render_map, fake_generate_alert_image, isolated_output_dir,
):
    alert = _alert()
    loop_result = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=100)

    gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)

    assert len(fake_generate_alert_image) == len(loop_result["frames"])


def test_leadin_frames_render_without_polygon_issuance_frame_with(
    fake_render_map, fake_generate_alert_image, isolated_output_dir,
):
    """The overriding requirement: a frame timestamped before the alert's
    own `sent` time must never be told to draw the polygon, and the first
    frame at/after `sent` must be."""
    alert = _alert()
    gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)

    sent = alert.sent
    for radar_time, show_polygon in fake_generate_alert_image:
        assert show_polygon == (radar_time >= sent)
    # At least one lead-in (pre-issuance) and one issued frame actually
    # got exercised -- otherwise the assertion above is vacuously true.
    assert any(show_polygon is False for _, show_polygon in fake_generate_alert_image)
    assert any(show_polygon is True for _, show_polygon in fake_generate_alert_image)


def test_frames_passed_in_chronological_order(
    fake_render_map, fake_generate_alert_image, isolated_output_dir,
):
    alert = _alert()
    gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)

    times = [radar_time for radar_time, _ in fake_generate_alert_image]
    assert times == sorted(times)


def test_output_is_a_valid_looping_multiframe_gif(
    fake_render_map, fake_generate_alert_image, isolated_output_dir,
):
    alert = _alert()
    gif_bytes = gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)

    img = Image.open(io.BytesIO(gif_bytes))
    assert img.format == "GIF"
    assert img.n_frames == len(fake_generate_alert_image)
    assert img.n_frames > 1
    assert img.info.get("loop") == 0  # loops forever


def test_last_frame_holds_longer_than_the_others(
    fake_render_map, fake_generate_alert_image, isolated_output_dir,
):
    alert = _alert()
    gif_bytes = gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)

    durations = _gif_durations(gif_bytes)
    assert durations[:-1] == [gif_mod.GIF_FRAME_DURATION_MS] * (len(durations) - 1)
    assert durations[-1] == gif_mod.GIF_LAST_FRAME_DURATION_MS


def test_single_frame_alert_still_produces_a_valid_gif(
    monkeypatch, fake_generate_alert_image, isolated_output_dir,
):
    """An alert issued and expiring in the very same 5-minute bucket, with
    the lead-in window fully clamped away by 'never request the future',
    is a degenerate one-frame case -- must not crash the GIF encoder."""
    def _fake(geom, severity, *, category, sent, map_w, map_h, show_polygon=True):
        return Image.new("RGB", (4, 4), (0, 128, 0))
    monkeypatch.setattr(radar_loop_mod, "_render_map", _fake)

    now = _past(minutes=0)
    alert = _alert(sent=now, expires=now)
    monkeypatch.setattr(
        radar_loop_mod, "_needed_timestamps",
        lambda sent, end, **kw: [radar_loop_mod._floor_to_cadence(sent)],
    )

    gif_bytes = gif_mod.generate_alert_gif(alert, {}, None, {}, _TEST_GEOM)
    img = Image.open(io.BytesIO(gif_bytes))
    assert img.format == "GIF"
