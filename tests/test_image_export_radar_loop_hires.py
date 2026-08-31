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

"""Tests for the separate, explicitly "High-Resolution" (Level II) radar
loop -- app_utils/image_export/radar_loop_hires.py.

Deliberately mirrors tests/test_image_export_radar_loop.py's structure
(same caching/eligibility/window-clamping guarantees apply, reusing
radar_loop.py's _needed_timestamps under the hood) plus what's actually
new here:

* **The upfront coverage-gap short-circuit.** Unlike the standard loop
  (which silently renders a radar-less frame on a WMS fetch failure --
  acceptable there since Level III is a national mosaic and gaps are
  vanishingly rare), Level II only reaches ~230km from a single site, so
  "no coverage" is a routine, expected outcome that must be reported
  distinctly from "not a weather alert", not silently cached as a
  blank frame indistinguishable from a legitimate no-echo scan.
* **Field-scoped caching.** reflectivity and velocity are different
  images for the same timestamp and must not collide on disk or be
  served to the wrong selector.
"""

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
    "image_export_radar_loop_hires_under_test",
    _PKG_DIR / "__init__.py",
    submodule_search_locations=[str(_PKG_DIR)],
)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = image_export
_spec.loader.exec_module(image_export)

hires_mod = image_export.radar_loop_hires
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
        sent=_past(hours=1),
        expires=_past(minutes=0),
        cancelled_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture(autouse=True)
def _site_in_range(monkeypatch):
    """Most tests are about the loop mechanics, not coverage lookup --
    default to "a site is in range" so build_hires_radar_loop() proceeds
    past the upfront check. The coverage-gap tests override this."""
    monkeypatch.setattr(hires_mod._radar_level2, "nearest_site", lambda lat, lon: "KCLE")


@pytest.fixture
def fake_render(monkeypatch):
    """Stub _render_map to return a tiny image instantly and record the
    (sent, radar_source, radar_field) each call was made with."""
    calls = []

    def _fake(geom, severity, *, category, sent, map_w, map_h, radar_source=None, radar_field=None):
        calls.append((sent, radar_source, radar_field))
        return Image.new("RGB", (4, 4), (0, 128, 0))

    monkeypatch.setattr(hires_mod, "_render_map", _fake)
    return calls


@pytest.fixture
def isolated_output_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(hires_mod, "_loop_output_dir", lambda: tmp_path)
    return tmp_path


# ── Eligibility ──────────────────────────────────────────────────────────────

def test_rejects_non_met_category():
    result = hires_mod.build_hires_radar_loop(_alert(category="Transport"), _TEST_GEOM)
    assert result["frames"] == []
    assert "error" in result


def test_rejects_missing_sent_time():
    result = hires_mod.build_hires_radar_loop(_alert(sent=None), _TEST_GEOM)
    assert result["frames"] == []
    assert "error" in result


def test_rejects_unknown_field():
    result = hires_mod.build_hires_radar_loop(_alert(), _TEST_GEOM, field="pressure")
    assert result["frames"] == []
    assert "error" in result


# ── Coverage-gap short-circuit ──────────────────────────────────────────────

def test_no_site_in_range_reports_coverage_gap_not_a_generic_error(monkeypatch, isolated_output_dir):
    monkeypatch.setattr(hires_mod._radar_level2, "nearest_site", lambda lat, lon: None)
    result = hires_mod.build_hires_radar_loop(_alert(), _TEST_GEOM)
    assert result["frames"] == []
    assert result["total"] == 0
    assert result["pending"] == 0
    assert "coverage" in result["error"].lower()


def test_no_site_in_range_never_calls_render(monkeypatch, isolated_output_dir):
    monkeypatch.setattr(hires_mod._radar_level2, "nearest_site", lambda lat, lon: None)
    render_calls = []
    monkeypatch.setattr(hires_mod, "_render_map", lambda *a, **k: render_calls.append(1))
    hires_mod.build_hires_radar_loop(_alert(), _TEST_GEOM)
    assert render_calls == []


# ── Rendering, caching, field scoping ───────────────────────────────────────

def test_renders_up_to_max_new_frames_per_call(fake_render, isolated_output_dir):
    now = datetime.now(timezone.utc)
    sent = radar_loop_mod._floor_to_cadence(now - timedelta(minutes=15))
    expires = sent + timedelta(minutes=10)
    alert = _alert(sent=sent, expires=expires)

    result = hires_mod.build_hires_radar_loop(alert, _TEST_GEOM, max_new_frames=2)

    assert result["total"] == 3  # sent, +5, +10
    assert len(result["frames"]) == 2
    assert result["pending"] == 1
    assert len(fake_render) == 2


def test_never_rerenders_a_cached_frame(fake_render, isolated_output_dir):
    sent = _past(minutes=5)
    alert = _alert(sent=sent, expires=sent + timedelta(minutes=5))
    result1 = hires_mod.build_hires_radar_loop(alert, _TEST_GEOM, max_new_frames=10)
    assert result1["pending"] == 0
    assert len(fake_render) == 2

    fake_render.clear()
    result2 = hires_mod.build_hires_radar_loop(alert, _TEST_GEOM, max_new_frames=10)
    assert len(result2["frames"]) == 2
    assert fake_render == []


def test_calls_render_map_with_level2_source_and_requested_field(fake_render, isolated_output_dir):
    t = _past(minutes=0)
    alert = _alert(sent=t, expires=t)
    hires_mod.build_hires_radar_loop(alert, _TEST_GEOM, field="velocity")
    assert len(fake_render) == 1
    _sent, radar_source, radar_field = fake_render[0]
    assert radar_source == "level2"
    assert radar_field == "velocity"


def test_reflectivity_and_velocity_caches_do_not_collide(fake_render, isolated_output_dir):
    t = _past(minutes=0)
    alert = _alert(sent=t, expires=t)

    hires_mod.build_hires_radar_loop(alert, _TEST_GEOM, field="reflectivity")
    hires_mod.build_hires_radar_loop(alert, _TEST_GEOM, field="velocity")

    # Both fields rendered independently -- a shared cache path would have
    # let the second call serve the first field's cached (wrong) frame.
    assert len(fake_render) == 2
    assert {c[2] for c in fake_render} == {"reflectivity", "velocity"}


def test_frame_urls_are_scoped_under_alert_id_and_field(fake_render, isolated_output_dir):
    t = _past(minutes=0)
    alert = _alert(id=42, sent=t, expires=t)
    result = hires_mod.build_hires_radar_loop(alert, _TEST_GEOM, field="velocity")
    assert result["frames"][0]["url"].startswith("/static/radar_loops_hires/42/velocity/")


def test_skips_a_frame_whose_render_raised(monkeypatch, isolated_output_dir):
    sent = _past(minutes=5)
    failing_frame_time = sent + timedelta(minutes=5)

    def _flaky(geom, severity, *, category, sent, map_w, map_h, radar_source=None, radar_field=None):
        if sent == failing_frame_time:
            raise RuntimeError("volume download timed out")
        return Image.new("RGB", (4, 4), (0, 128, 0))

    monkeypatch.setattr(hires_mod, "_render_map", _flaky)

    alert = _alert(sent=sent, expires=sent + timedelta(minutes=5))
    result = hires_mod.build_hires_radar_loop(alert, _TEST_GEOM, max_new_frames=10)

    times = [f["time"] for f in result["frames"]]
    assert failing_frame_time.isoformat() not in times
    assert len(result["frames"]) == 1  # sent still rendered
