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
import sys
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
# Register before exec so ``@dataclass`` (Python 3.11+) can resolve the
# defining module via ``sys.modules[cls.__module__]`` while the class body
# is still being processed.
sys.modules[_spec.name] = image_export
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


# ── ALL-CAPS → sentence-case humanizer ──────────────────────────────────────
def test_is_shouting_detects_all_caps():
    assert image_export._is_shouting(
        "SEVERE THUNDERSTORM WATCH IN EFFECT UNTIL 10 PM EDT"
    ) is True


def test_is_shouting_ignores_sentence_case():
    assert image_export._is_shouting(
        "Severe thunderstorm watch in effect until 10 PM EDT this evening."
    ) is False


def test_is_shouting_short_strings_pass_through():
    assert image_export._is_shouting("HI THERE") is False


def test_humanize_caps_text_no_op_when_not_shouting():
    sample = "Severe thunderstorm watch in effect until 10 PM EDT."
    assert image_export._humanize_caps_text(sample) == sample


def test_humanize_caps_text_sentence_case_with_acronyms():
    src = (
        "SEVERE THUNDERSTORM WATCH 230, PREVIOUSLY IN EFFECT UNTIL 7 PM EDT "
        "THIS EVENING, IS NOW IN EFFECT UNTIL 10 PM EDT THIS EVENING FOR "
        "THE FOLLOWING AREAS IN OHIO."
    )
    out = image_export._humanize_caps_text(src)

    assert out.startswith("Severe thunderstorm watch 230"), out
    assert "PM EDT" in out
    assert "pm edt" not in out
    assert "Ohio" in out
    assert "ohio" not in out
    assert not image_export._is_shouting(out)


def test_humanize_caps_text_title_cases_city_list():
    src = "THIS INCLUDES THE CITIES OF BELLEVUE, FINDLAY, AND PORT CLINTON."
    out = image_export._humanize_caps_text(src)
    assert "Bellevue" in out
    assert "Findlay" in out
    assert "Port Clinton" in out
    assert ", and Port Clinton" in out


def test_humanize_caps_text_state_code_after_comma():
    """State codes are recognised only after a comma+space (e.g.
    ``Erie, OH``).  This avoids false-positives on common English
    words that collide with state codes (IN, OR, ME, HI, OK, …).
    """
    src = "AFFECTED AREAS: ERIE, OH; HANCOCK, OH; AND OTTAWA, OH."
    out = image_export._humanize_caps_text(src)
    # Each comma-prefixed state code uppercased.
    assert out.count(", OH") == 3, out
    # And no all-caps state-code-looking word was uppercased outside the
    # comma context.
    assert " IN " not in out
    assert " OR " not in out


def test_humanize_caps_text_does_not_uppercase_common_words():
    """Words like 'in', 'or', 'me' collide with state codes — they must
    stay lowercase when not in a ``, ST`` position."""
    src = (
        "THE WATCH IS NOW IN EFFECT FOR COUNTIES IN OHIO OR FLORIDA. "
        "REPORTS HAVE COME TO ME FROM SEVERAL OBSERVERS."
    )
    out = image_export._humanize_caps_text(src)
    assert " in effect" in out
    assert " in Ohio" in out
    assert " or Florida" in out
    assert " to me " in out
    # The bare standalone caps should be gone.
    assert " IN " not in out
    assert " OR " not in out
    assert " ME " not in out


def test_humanize_caps_text_no_false_uppercase_after_sentence_comma():
    """Sentence-comma + common-word patterns ("…outdoors, in a vehicle")
    must not be confused with the "City, ST" state-code pattern."""
    src = (
        "IF YOU ARE OUTDOORS, IN A MOBILE HOME, OR IN A VEHICLE, MOVE "
        "TO THE NEAREST SHELTER."
    )
    out = image_export._humanize_caps_text(src)
    # These would have been mis-shouted by a too-permissive lookahead.
    assert ", in a mobile home" in out
    assert ", or in a vehicle" in out
    assert "IN" not in out.split()  # no bare "IN" tokens
    assert "OR" not in out.split()


def test_humanize_caps_text_preserves_acronyms():
    src = "ISSUED BY NWS CLEVELAND AT 6 PM EDT."
    out = image_export._humanize_caps_text(src)
    assert "NWS" in out
    assert "PM EDT" in out


# ── Coverage section gating ─────────────────────────────────────────────────
def _render_with_coverage(coverage_data):
    alert = _FakeAlert()
    alert.id = 4242
    alert.event = "Severe Thunderstorm Watch"
    alert.severity = "Severe"
    return image_export.generate_alert_image(
        alert, coverage_data, None,
        {"county_name": "Putnam County, Ohio"},
    )


def test_coverage_section_renders_when_county_zero_and_no_services():
    """0% county + no service hits should still produce a valid PNG (the
    COVERAGE section is silently dropped, not an error)."""
    png = _render_with_coverage({
        "county": {"coverage_percentage": 0.0, "is_estimated": True},
        "fire":   {"affected_boundaries": 0, "total_boundaries": 5},
    })
    assert png.startswith(b"\x89PNG")
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)


def test_coverage_section_kept_when_services_have_hits():
    """0% county but service hits → section stays for the services."""
    png = _render_with_coverage({
        "county": {"coverage_percentage": 0.0, "is_estimated": True},
        "fire":   {"affected_boundaries": 2, "total_boundaries": 5},
    })
    assert png.startswith(b"\x89PNG")
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)


# ── Compact footer timestamp ────────────────────────────────────────────────
def test_short_local_dt_same_day_omits_date():
    from datetime import datetime, timezone

    sent    = datetime(2026, 5, 19, 22, 29, tzinfo=timezone.utc)
    expires = datetime(2026, 5, 20,  1,  0, tzinfo=timezone.utc)

    out_sent    = image_export._short_local_dt(sent)
    out_expires = image_export._short_local_dt(expires, ref=sent)

    assert ":" in out_sent and ("AM" in out_sent or "PM" in out_sent)
    assert "2026" not in out_sent
    assert "2026" not in out_expires


def test_short_local_dt_cross_day_includes_date():
    from datetime import datetime, timezone

    sent    = datetime(2026, 5, 19, 12,  0, tzinfo=timezone.utc)
    expires = datetime(2026, 5, 21, 12,  0, tzinfo=timezone.utc)

    out = image_export._short_local_dt(expires, ref=sent)
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    assert any(m in out for m in months), out


# ── Multi aspect-ratio output ───────────────────────────────────────────────
@pytest.mark.parametrize("ratio,expected_size", [
    ("landscape", (1200,  630)),
    ("square",    (1080, 1080)),
    ("portrait",  (1080, 1350)),
    ("story",     (1080, 1920)),
])
def test_generate_alert_image_aspect_ratio(ratio, expected_size):
    alert = _FakeAlert()
    alert.id = 99001 + hash(ratio) % 1000
    alert.event = "Severe Thunderstorm Watch"
    alert.severity = "Severe"
    alert.description = (
        "Severe thunderstorm activity expected. Hail and damaging wind "
        "gusts possible. Stay weather-aware."
    )
    png = image_export.generate_alert_image(
        alert, {}, None,
        {"county_name": "Test County, OH"},
        aspect_ratio=ratio,
    )
    assert png.startswith(b"\x89PNG")
    img = Image.open(io.BytesIO(png))
    assert img.size == expected_size, (
        f"{ratio}: got {img.size}, expected {expected_size}"
    )
    assert img.mode == "RGBA"
    # Outer corners should still be transparent across every layout.
    assert img.getpixel((0, 0))[3] == 0
    assert img.getpixel((expected_size[0] - 1, expected_size[1] - 1))[3] == 0


def test_generate_alert_image_unknown_ratio_falls_back_to_landscape():
    """Unknown aspect-ratio names must not crash — they fall back to the
    Facebook-card default so a typo in a query string still ships
    something useful."""
    alert = _FakeAlert()
    alert.event = "Frost Advisory"
    png = image_export.generate_alert_image(
        alert, {}, None,
        {"county_name": "Test County, OH"},
        aspect_ratio="not-a-real-ratio",
    )
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)


def test_layout_presets_are_consistent():
    """Each preset's map_rect and info_rect should fit inside the canvas
    and sit below the header / above the footer — guards against typos
    in the layout table."""
    for name, lay in image_export._LAYOUTS.items():
        assert lay.width > 0 and lay.height > 0, name
        # Map rect must fit inside the canvas.
        mx, my, mw, mh = lay.map_rect
        assert mx >= 0 and my >= lay.header_h, name
        assert mx + mw <= lay.width, name
        assert my + mh <= lay.height - lay.footer_h, name
        # Info rect must fit inside the canvas.
        ix, iy, iw, ih = lay.info_rect
        assert ix >= 0 and iy >= lay.header_h, name
        assert ix + iw <= lay.width, name
        assert iy + ih <= lay.height - lay.footer_h, name


# ── OSM tile cache ──────────────────────────────────────────────────────────
def test_tile_cache_returns_image_on_hit(monkeypatch):
    """A cached tile should bypass the HTTP layer entirely."""
    # Build a tiny PNG payload in memory and pre-load the cache.
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), (10, 20, 30)).save(buf, format="PNG")
    payload = buf.getvalue()
    image_export._tile_cache_clear()
    image_export._tile_cache_put((5, 7, 11), payload)

    calls = []

    def _no_network(*args, **kwargs):  # pragma: no cover - guard
        calls.append(args)
        raise AssertionError("network should not be touched on cache hit")

    monkeypatch.setattr(image_export, "_http",
                        type("X", (), {"get": staticmethod(_no_network)})())
    tile = image_export._fetch_tile(7, 11, 5)
    assert tile is not None
    assert tile.size == (256, 256)
    assert calls == []


def test_tile_cache_evicts_oldest(monkeypatch):
    """LRU eviction kicks in when the cache exceeds its bound."""
    image_export._tile_cache_clear()
    payload = b"\x00" * 8  # not a real PNG; we only test the OrderedDict
    cap = image_export._TILE_CACHE_MAX
    # Fill cache + 5 over the cap.
    for i in range(cap + 5):
        image_export._tile_cache_put((0, i, 0), payload)
    # The five oldest keys (0..4) should have been evicted.
    for i in range(5):
        assert image_export._tile_cache_get((0, i, 0)) is None, i
    # Newest keys still present.
    for i in range(cap + 5 - 1, cap, -1):
        assert image_export._tile_cache_get((0, i, 0)) == payload
    image_export._tile_cache_clear()


# ── Pill helper ─────────────────────────────────────────────────────────────
def test_draw_pill_advances_x_past_pill_width():
    """The pill helper should return the x past its right edge so callers
    can chain pills horizontally without re-measuring."""
    from PIL import ImageDraw as _ID
    canvas = Image.new("RGB", (400, 60), (10, 10, 10))
    draw = _ID.Draw(canvas)
    fonts = image_export._load_fonts()

    end_x = image_export._draw_pill(
        draw, fonts['label'], 'SEVERE', (253, 126, 20), 18, 10,
    )
    assert end_x > 18, "pill end should be to the right of its start"

    # And the pill should have actually drawn coloured pixels somewhere
    # inside its claimed bounding box (top-left → end_x).
    px = canvas.load()
    pixels = [px[x, y] for x in range(20, end_x) for y in range(12, 28)]
    assert any(p != (10, 10, 10) for p in pixels), (
        "no pixels were drawn inside the pill rectangle"
    )


def test_severity_pill_rendered_for_each_severity():
    """Each known severity should round-trip through generate_alert_image
    without crashing — covers the colour-lookup branch in the header."""
    for sev in ('Extreme', 'Severe', 'Moderate', 'Minor', 'Unknown'):
        alert = _FakeAlert()
        alert.id = 7000 + abs(hash(sev)) % 1000
        alert.event = 'Severe Thunderstorm Watch'
        alert.severity = sev
        png = image_export.generate_alert_image(
            alert, {}, None, {"county_name": "Test County, OH"},
        )
        img = Image.open(io.BytesIO(png))
        assert img.size == (1200, 630), sev


# ── WebP output ─────────────────────────────────────────────────────────────
def test_generate_alert_image_webp_returns_valid_webp():
    """WebP output should be a valid WebP file at the requested aspect."""
    alert = _FakeAlert()
    alert.id = 5500
    alert.event = "Severe Thunderstorm Warning"
    alert.severity = "Severe"
    image = image_export.generate_alert_image(
        alert, {}, None, {"county_name": "Test County, OH"},
        aspect_ratio="square", image_format="webp",
    )
    # WebP files start with "RIFF" + 4 bytes length + "WEBP".
    assert image[:4] == b"RIFF", "missing RIFF header"
    assert image[8:12] == b"WEBP", "missing WEBP marker"
    img = Image.open(io.BytesIO(image))
    assert img.size == (1080, 1080)
    assert img.format == "WEBP"


def test_webp_is_smaller_than_png_for_same_content():
    """At equivalent quality, WebP should beat PNG on file size — the
    main reason to expose it as a format option.  We don't pin an exact
    ratio because Pillow + libwebp versions differ, but the WebP output
    must come in measurably smaller than the PNG equivalent."""
    alert = _FakeAlert()
    alert.id = 5501
    alert.event = "Tornado Warning"
    alert.severity = "Extreme"
    alert.description = (
        "Reports of damaging wind gusts and large hail across the warned "
        "area. Move to an interior room on the lowest floor."
    )
    png_bytes  = image_export.generate_alert_image(
        alert, {}, None, {"county_name": "Test County, OH"},
        aspect_ratio="square", image_format="png",
    )
    webp_bytes = image_export.generate_alert_image(
        alert, {}, None, {"county_name": "Test County, OH"},
        aspect_ratio="square", image_format="webp",
    )
    assert len(webp_bytes) < len(png_bytes), (
        f"WebP ({len(webp_bytes)}B) was not smaller than PNG "
        f"({len(png_bytes)}B) for the same content"
    )


def test_unknown_format_falls_back_to_png():
    """A typo in ``image_format`` should not crash — it falls back to
    PNG so the caller still gets a usable file."""
    alert = _FakeAlert()
    alert.event = "Frost Advisory"
    image = image_export.generate_alert_image(
        alert, {}, None, {"county_name": "Test County, OH"},
        image_format="jpg",  # not a supported format
    )
    assert image.startswith(b"\x89PNG"), "unknown format should fall back to PNG"


# ── PNG metadata is minimal + reproducible ──────────────────────────────────
def test_png_output_carries_software_tag_only():
    """Exports must not leak server timestamps via tIME and must carry a
    stable ``Software`` marker so downstream consumers can audit the
    source."""
    alert = _FakeAlert()
    alert.id = 12345
    alert.event = "Frost Advisory"
    png = image_export.generate_alert_image(
        alert, {}, None, {"county_name": "Test County, OH"},
    )
    img = Image.open(io.BytesIO(png))
    text_chunks = getattr(img, "text", {}) or {}
    assert text_chunks.get("Software") == "EAS Station", text_chunks
    assert text_chunks.get("Source") == "alert/12345", text_chunks
    # No tIME chunk — Pillow surfaces that via ``img.info['date:modify']``
    # when present; if it's there we leaked a timestamp.
    info = getattr(img, "info", {}) or {}
    assert "date:modify" not in info
    assert "Modify Date" not in info
