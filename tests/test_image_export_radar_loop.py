"""Tests for lazily-generated, disk-cached radar reflectivity loops.

Three things this depends on, none of which fail loudly if they break:

* **Timestamp stepping.** ``_needed_timestamps`` must produce exactly the
  5-minute-cadence frames the loop needs, capped at
  ``RADAR_LOOP_MAX_FRAMES`` -- get the cap wrong and a multi-day Flood
  Watch either renders hundreds of frames or the loop silently truncates
  somewhere unexpected.
* **Caching.** A frame already on disk must never be re-rendered -- a
  frame for a fixed past timestamp is valid forever, and re-rendering it
  on every poll would make the "poll until pending == 0" API contract
  never actually converge.
* **End-of-window logic.** The loop must stop at whichever of
  ``cancelled_at``/``expires``/now comes first, and never request radar
  for the future.

The renderer package is loaded directly so the tests do not pay for the
full ``app_utils`` import (psutil, sqlalchemy, …) -- same pattern as
test_image_export_map_style.py / test_image_export_radar_overlay.py.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    pytest.skip("Pillow is required for image_export tests", allow_module_level=True)


_PKG_DIR = Path(__file__).resolve().parent.parent / "app_utils" / "image_export"
_spec = importlib.util.spec_from_file_location(
    "image_export_radar_loop_under_test",
    _PKG_DIR / "__init__.py",
    submodule_search_locations=[str(_PKG_DIR)],
)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = image_export
_spec.loader.exec_module(image_export)

radar_loop_mod = image_export.radar_loop

_TEST_GEOM = {
    "type": "Polygon",
    "coordinates": [[[-84.30, 41.10], [-83.85, 40.86], [-83.90, 40.72],
                     [-84.22, 40.61], [-84.30, 41.10]]],
}


def _past(**offset):
    """A cadence-aligned timestamp safely in the past relative to whenever
    the test actually runs -- avoids any dependency on wall-clock timing
    tripping build_radar_loop's "never request the future" clamp, which a
    literal calendar date can't guarantee."""
    return radar_loop_mod._floor_to_cadence(datetime.now(timezone.utc) - timedelta(**offset))


def _alert(**overrides):
    defaults = dict(
        id=1, category="Met", severity="Severe",
        sent=_past(hours=1),
        expires=_past(minutes=0),
        cancelled_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── _needed_timestamps ──────────────────────────────────────────────────────

def test_needed_timestamps_steps_at_5min_cadence_inclusive_of_both_ends():
    start = datetime(2026, 8, 27, 9, 45, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc)
    out = radar_loop_mod._needed_timestamps(
        start, end, leadin_minutes=radar_loop_mod.RADAR_LOOP_LEADIN_MINUTES)
    # Starts RADAR_LOOP_LEADIN_MINUTES before `start` -- the lead-in frames
    # showing the storm on approach before the alert existed.
    assert out == [
        datetime(2026, 8, 27, 9, 30, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 35, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 40, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 45, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 50, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 55, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc),
    ]


def test_needed_timestamps_floors_unaligned_start_and_end():
    start = datetime(2026, 8, 27, 9, 47, 12, tzinfo=timezone.utc)
    end = datetime(2026, 8, 27, 9, 53, 59, tzinfo=timezone.utc)
    out = radar_loop_mod._needed_timestamps(
        start, end, leadin_minutes=radar_loop_mod.RADAR_LOOP_LEADIN_MINUTES)
    assert out == [
        datetime(2026, 8, 27, 9, 30, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 35, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 40, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 45, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 50, 0, tzinfo=timezone.utc),
    ]


def test_needed_timestamps_caps_at_max_frames():
    start = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=5)  # a multi-day Flood Watch
    out = radar_loop_mod._needed_timestamps(
        start, end, leadin_minutes=radar_loop_mod.RADAR_LOOP_LEADIN_MINUTES)
    lead_in_start = start - timedelta(minutes=radar_loop_mod.RADAR_LOOP_LEADIN_MINUTES)
    assert len(out) == radar_loop_mod.RADAR_LOOP_MAX_FRAMES
    assert out[0] == lead_in_start
    # Capped from the (lead-in-extended) start of the window, not evenly
    # resampled across it.
    assert out[-1] == lead_in_start + timedelta(
        minutes=radar_loop_mod.RADAR_LOOP_CADENCE_MINUTES * (radar_loop_mod.RADAR_LOOP_MAX_FRAMES - 1)
    )


def test_needed_timestamps_leadin_window_when_start_equals_end():
    """Even an instantaneous [t, t] window still gets its lead-in frames --
    only the *post-issuance* portion of the loop collapses to one point."""
    t = datetime(2026, 8, 27, 9, 45, 0, tzinfo=timezone.utc)
    out = radar_loop_mod._needed_timestamps(
        t, t, leadin_minutes=radar_loop_mod.RADAR_LOOP_LEADIN_MINUTES)
    assert out == [
        datetime(2026, 8, 27, 9, 30, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 35, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 9, 40, 0, tzinfo=timezone.utc),
        t,
    ]


# ── build_radar_loop: eligibility ───────────────────────────────────────────

def test_build_radar_loop_rejects_non_met_category():
    result = radar_loop_mod.build_radar_loop(_alert(category="Transport"), _TEST_GEOM)
    assert result["frames"] == []
    assert "error" in result


def test_build_radar_loop_rejects_missing_sent_time():
    result = radar_loop_mod.build_radar_loop(_alert(sent=None), _TEST_GEOM)
    assert result["frames"] == []
    assert "error" in result


# ── build_radar_loop: rendering, caching, progress ──────────────────────────

@pytest.fixture
def fake_render(monkeypatch):
    """Stub _render_map to return a tiny image instantly and record calls."""
    calls = []

    def _fake(geom, severity, *, category, sent, map_w, map_h, show_polygon=True):
        calls.append((sent, show_polygon))
        return Image.new("RGB", (4, 4), (0, 128, 0))

    monkeypatch.setattr(radar_loop_mod, "_render_map", _fake)
    return calls


@pytest.fixture
def isolated_output_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(radar_loop_mod, "_loop_output_dir", lambda: tmp_path)
    return tmp_path


def test_build_radar_loop_renders_up_to_max_new_frames_per_call(fake_render, isolated_output_dir):
    # Both sent and expires safely in the past (relative to whenever this
    # test actually runs), so the "never request the future" clamp in
    # build_radar_loop doesn't truncate the window -- avoids mocking
    # datetime.now() for what a fixed-in-the-past window doesn't need.
    now = datetime.now(timezone.utc)
    sent = radar_loop_mod._floor_to_cadence(now - timedelta(hours=2))
    expires = sent + timedelta(hours=1)
    alert = _alert(sent=sent, expires=expires)

    result = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=3)

    assert result["total"] == 16  # 60 min / 5 min + 1, plus 3 lead-in frames
    assert len(result["frames"]) == 3
    assert result["pending"] == 13
    assert len(fake_render) == 3


def test_build_radar_loop_never_rerenders_a_cached_frame(fake_render, isolated_output_dir):
    sent = _past(minutes=10)
    alert = _alert(sent=sent, expires=sent + timedelta(minutes=10))
    result1 = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=10)
    assert result1["pending"] == 0
    assert len(fake_render) == 6  # sent-15,-10,-5 (lead-in), sent, sent+5, sent+10

    fake_render.clear()
    result2 = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=10)
    assert len(result2["frames"]) == 6
    assert fake_render == []  # nothing re-rendered -- all served from disk


def test_build_radar_loop_skips_a_frame_whose_render_raised(monkeypatch, isolated_output_dir):
    sent = _past(minutes=10)
    failing_frame_time = sent + timedelta(minutes=5)

    def _flaky(geom, severity, *, category, sent, map_w, map_h, show_polygon=True):
        if sent == failing_frame_time:
            raise RuntimeError("WMS timeout")
        return Image.new("RGB", (4, 4), (0, 128, 0))

    monkeypatch.setattr(radar_loop_mod, "_render_map", _flaky)

    alert = _alert(sent=sent, expires=sent + timedelta(minutes=10))
    result = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=10)

    times = [f["time"] for f in result["frames"]]
    assert failing_frame_time.isoformat() not in times
    # sent-15,-10,-5 (lead-in), sent, sent+10 rendered; sent+5 failed.
    assert len(result["frames"]) == 5


def test_build_radar_loop_stops_at_cancelled_at_not_expires(fake_render, isolated_output_dir):
    """A Cancel arriving early must shorten the loop, not the full expires window."""
    sent = _past(hours=3)
    alert = _alert(
        sent=sent,
        expires=sent + timedelta(hours=3),
        cancelled_at=sent + timedelta(minutes=10),
    )
    result = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=100)
    # sent-15,-10,-5 (lead-in), sent, sent+5, sent+10 -- not all the way to +3h
    assert result["total"] == 6


def test_frame_urls_are_scoped_under_the_alert_id(fake_render, isolated_output_dir):
    t = _past(minutes=0)
    alert = _alert(id=42, sent=t, expires=t)
    result = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM)
    assert result["frames"][0]["url"].startswith("/static/radar_loops/42/")


# ── lead-in / polygon-reveal (issued flag) ──────────────────────────────────

def test_leadin_frames_marked_not_issued_and_render_without_polygon(fake_render, isolated_output_dir):
    """Frames before the alert's own `sent` time must both report
    issued=False AND be rendered with show_polygon=False -- the two must
    never disagree, or a "pre-alert" frame could still show the polygon.
    """
    sent = _past(minutes=0)
    alert = _alert(sent=sent, expires=sent)
    result = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=100)

    lead_in = [f for f in result["frames"] if f["time"] < sent.isoformat()]
    assert len(lead_in) == 3  # sent-15, sent-10, sent-5
    assert all(f["issued"] is False for f in lead_in)


def test_issuance_frame_and_later_marked_issued(fake_render, isolated_output_dir):
    # sent safely in the past (not right at "now"'s cadence boundary) so
    # sent+5 doesn't get clipped by the "never request the future" clamp.
    sent = _past(minutes=10)
    alert = _alert(sent=sent, expires=sent + timedelta(minutes=5))
    result = radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=100)

    at_or_after = [f for f in result["frames"] if f["time"] >= sent.isoformat()]
    assert len(at_or_after) == 2  # sent, sent+5
    assert all(f["issued"] is True for f in at_or_after)


def test_show_polygon_kwarg_matches_issued_flag_for_every_rendered_frame(fake_render, isolated_output_dir):
    """The show_polygon kwarg _render_map is actually called with must never
    disagree with the issued flag the caller sees -- checked against the
    real per-call arguments, not just the returned frame list."""
    sent = _past(minutes=10)
    alert = _alert(sent=sent, expires=sent + timedelta(minutes=5))
    radar_loop_mod.build_radar_loop(alert, _TEST_GEOM, max_new_frames=100)

    assert len(fake_render) == 5  # sent-15, -10, -5 (lead-in), sent, sent+5
    for call_sent, show_polygon in fake_render:
        assert show_polygon == (call_sent >= sent)
