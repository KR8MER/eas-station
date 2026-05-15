"""Smoke tests for the event-themed social-share image renderer.

These exercise the public ``generate_alert_image`` plus the helpers that
drive event-aware theming, particle styles, and the rounded-corner
output mask.  The intent is to lock down:

* Each common CAP event family resolves to the correct particle style.
* Convective / wind / water events keep the storm-motion overlay;
  advisories (frost, heat, fire, fog) suppress it.
* Every particle renderer actually paints pixels into its region.
* ``generate_alert_image`` returns a 1200×630 RGBA PNG with transparent
  corners (rounded-corner output).

The full image generation path is exercised with a minimal in-memory
fake alert so the test does not need a database, network access, or
the rest of the app context.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

try:  # pragma: no cover - Pillow is a hard requirement of the renderer
    from PIL import Image
except ImportError:  # pragma: no cover
    pytest.skip("Pillow is required for image_export tests", allow_module_level=True)


# Load app_utils/image_export.py directly so the test does not pay the
# cost of importing the full ``app_utils`` package (which pulls in
# psutil, sqlalchemy, etc).  This keeps the test fast and isolated.
_MODULE_PATH = Path(__file__).resolve().parent.parent / "app_utils" / "image_export.py"
_spec = importlib.util.spec_from_file_location("image_export_under_test", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(image_export)


# ── Theme resolution ────────────────────────────────────────────────────────
@pytest.mark.parametrize("event,severity,expected_particles", [
    ("FROST ADVISORY",                "minor",    "snow"),
    ("FREEZE WARNING",                "moderate", "snow"),
    ("WIND CHILL ADVISORY",           "minor",    "snow"),
    ("WINTER STORM WARNING",          "severe",   "snow"),
    ("BLIZZARD WARNING",              "extreme",  "snow"),
    ("TORNADO WARNING",               "extreme",  "bolts"),
    ("SEVERE THUNDERSTORM WARNING",   "severe",   "bolts"),
    ("FLASH FLOOD WARNING",           "severe",   "rain"),
    ("FLOOD WATCH",                   "moderate", "rain"),
    ("COASTAL FLOOD ADVISORY",        "minor",    "rain"),
    ("EXCESSIVE HEAT WARNING",        "extreme",  "sun"),
    ("HEAT ADVISORY",                 "moderate", "sun"),
    ("RED FLAG WARNING",              "severe",   "embers"),
    ("FIRE WEATHER WATCH",            "moderate", "embers"),
    ("DENSE FOG ADVISORY",            "minor",    "haze"),
    ("DUST STORM WARNING",            "severe",   "haze"),
    ("HIGH WIND WARNING",             "severe",   "wind"),
    ("HURRICANE WARNING",             "extreme",  "wind"),
    ("AMBER ALERT",                   "severe",   "none"),
])
def test_theme_resolves_expected_particles(event, severity, expected_particles):
    theme = image_export._resolve_theme(event, severity)
    assert theme["particles"] == expected_particles, (
        f"{event} resolved to particles={theme['particles']!r}, "
        f"expected {expected_particles!r}"
    )
    # Each theme should also expose a sane gradient + accent.
    assert "top" in theme and "bottom" in theme and "accent" in theme
    for key in ("top", "bottom", "accent"):
        rgb = theme[key]
        assert len(rgb) == 3 and all(0 <= c <= 255 for c in rgb)


def test_unknown_event_falls_back_to_severity():
    theme = image_export._resolve_theme("UNKNOWN GIBBERISH ALERT", "extreme")
    # Falls back to a derived theme — accent is the severity colour.
    assert theme["accent"] == image_export._SEVERITY["extreme"]


# ── Storm-motion suppression ───────────────────────────────────────────────
@pytest.mark.parametrize("event,supports", [
    ("TORNADO WARNING",            True),
    ("SEVERE THUNDERSTORM WARNING", True),
    ("FLASH FLOOD WARNING",         True),
    ("HIGH WIND WARNING",           True),
    ("FROST ADVISORY",              False),
    ("FREEZE WARNING",              False),
    ("HEAT ADVISORY",               False),
    ("EXCESSIVE HEAT WARNING",      False),
    ("FIRE WEATHER WATCH",          False),
    ("DENSE FOG ADVISORY",          False),
    ("AMBER ALERT",                 False),
])
def test_storm_motion_suppressed_for_non_convective(event, supports):
    theme = image_export._resolve_theme(event, "moderate")
    assert image_export._theme_supports_storm_motion(theme) is supports


# ── Particle renderers actually draw something ──────────────────────────────
@pytest.mark.parametrize("particle", ["bolts", "snow", "rain",
                                       "sun", "embers", "wind", "haze"])
def test_particle_renderer_draws_pixels(particle):
    bg = (10, 20, 40)
    img = Image.new("RGB", (1200, 90), bg)
    fn = image_export._PARTICLE_FNS[particle]
    fn(img, (0, 0, 1200, 90), seed=12345, intensity=1.0)

    # Sample a grid — at least one cell should differ from the bg colour.
    px = img.load()
    differing = sum(
        1 for x in range(0, 1200, 40) for y in range(0, 90, 10)
        if px[x, y] != bg
    )
    assert differing > 0, f"{particle} renderer drew no visible pixels"


def test_particle_none_is_noop():
    assert image_export._PARTICLE_FNS["none"] is None


# ── Rounded-corner helper ───────────────────────────────────────────────────
def test_round_image_corners_transparent_mode():
    img = Image.new("RGB", (400, 200), (255, 0, 0))
    out = image_export._round_image_corners(img, 30, bg=None)
    assert out.mode == "RGBA"
    assert out.size == (400, 200)
    # Corners should be transparent; interior should be opaque red.
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((399, 199))[3] == 0
    centre = out.getpixel((200, 100))
    assert centre[3] == 255
    assert centre[:3] == (255, 0, 0)


def test_round_image_corners_with_matte():
    img = Image.new("RGB", (400, 200), (255, 0, 0))
    out = image_export._round_image_corners(img, 30, bg=(0, 255, 0))
    assert out.mode == "RGB"
    # Corners flatten to matte colour.
    assert out.getpixel((0, 0)) == (0, 255, 0)
    # Interior keeps original colour.
    assert out.getpixel((200, 100)) == (255, 0, 0)


def test_round_image_corners_zero_radius_returns_input():
    img = Image.new("RGB", (50, 50), (1, 2, 3))
    assert image_export._round_image_corners(img, 0) is img


# ── Font cache memoization ──────────────────────────────────────────────────
def test_load_fonts_is_memoized():
    # First call warms the cache; second call must return the same dict.
    f1 = image_export._load_fonts()
    f2 = image_export._load_fonts()
    assert f1 is f2


# ── End-to-end PNG generation ───────────────────────────────────────────────
class _FakeAlert:
    """Minimal stand-in for CAPAlert with just the attributes the renderer touches."""
    id = 0
    event = "Alert"
    severity = "Minor"
    urgency = "Expected"
    certainty = "Likely"
    status = "Actual"
    sent = None
    expires = None
    headline = "TEST HEADLINE"
    description = "Test description."
    instruction = "Test instruction."
    area_desc = "Test Area"


def _generate(event: str, severity: str = "Minor", *, storm_motion=None) -> bytes:
    alert = _FakeAlert()
    alert.id = abs(hash(event)) % (10**6)
    alert.event = event
    alert.severity = severity
    ipaws = {"storm_motion": storm_motion} if storm_motion else None
    return image_export.generate_alert_image(
        alert, {}, ipaws, {"county_name": "Test County, OH"}
    )


def test_generate_alert_image_returns_rounded_rgba_png():
    png = _generate("Frost Advisory", "Minor")
    assert png.startswith(b"\x89PNG"), "Output is not a PNG"

    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)
    # PNG must be RGBA so the rounded corners are actually transparent.
    assert img.mode == "RGBA"
    # Top-left and bottom-right pixels are inside the corner-radius
    # cutout → fully transparent.
    assert img.getpixel((0, 0))[3] == 0
    assert img.getpixel((1199, 629))[3] == 0
    # A pixel well inside the header area must be fully opaque.
    assert img.getpixel((600, 45))[3] == 255


@pytest.mark.parametrize("event,severity", [
    ("Frost Advisory",              "Minor"),
    ("Tornado Warning",             "Extreme"),
    ("Flash Flood Warning",         "Severe"),
    ("Excessive Heat Warning",      "Severe"),
    ("Red Flag Warning",            "Severe"),
    ("Dense Fog Advisory",          "Minor"),
    ("High Wind Warning",           "Severe"),
    ("Winter Storm Warning",        "Severe"),
])
def test_generate_alert_image_each_event_family(event, severity):
    """Each themed event family produces a valid non-empty PNG."""
    png = _generate(event, severity)
    assert png.startswith(b"\x89PNG")
    # Sanity: empty/error PNGs are typically tiny; a real card is many KB.
    assert len(png) > 2000, f"{event}: PNG suspiciously small ({len(png)} bytes)"
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)
    assert img.mode == "RGBA"


def test_generate_alert_image_with_storm_motion():
    """Tornado warning + storm-motion payload should render without error."""
    storm = {
        "track":       [[40.5, -82.5], [40.7, -82.4], [40.85, -82.3]],
        "toward_deg":  60,
        "speed_mph":   35,
        "compass_toward": "NE",
        "compass_from":   "SW",
    }
    png = _generate("Tornado Warning", "Extreme", storm_motion=storm)
    assert png.startswith(b"\x89PNG")
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)
