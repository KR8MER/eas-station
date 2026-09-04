"""Tests for the share-card map's framing and styling.

Three things the map depends on, none of which fail loudly if they break:

* **Framing.** ``_crop_window`` frames the alert's bounding box instead of
  cropping a fixed window at whatever integer zoom happened to fit, which
  used to leave the hazard as a small patch in a sea of unrelated
  geography.
* **Tile budget.** ``_detail_zoom`` must count tiles exactly the way the
  renderer does; an under-count sends ``_render_map`` down its "Map not
  available" path, which looks like a network failure rather than a
  arithmetic bug.
* **Styling.** ``tone_basemap`` / ``apply_vignette`` knock the basemap back
  so the polygon reads, and ``place_labels`` puts county names on without
  the collisions that got labels removed from the card once before.

The renderer package is loaded directly so the tests do not pay for the
full ``app_utils`` import (psutil, sqlalchemy, …).
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

try:
    from PIL import Image, ImageStat
except ImportError:  # pragma: no cover
    pytest.skip("Pillow is required for image_export tests", allow_module_level=True)


_PKG_DIR = Path(__file__).resolve().parent.parent / "app_utils" / "image_export"
_spec = importlib.util.spec_from_file_location(
    "image_export_map_style_under_test",
    _PKG_DIR / "__init__.py",
    submodule_search_locations=[str(_PKG_DIR)],
)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = image_export
_spec.loader.exec_module(image_export)

maps_mod = image_export.maps
tiles_mod = image_export.tiles


# ── Tile budget ─────────────────────────────────────────────────────────────
# ``_render_map`` bails to the "Map not available" placeholder above 30
# tiles, counting them as ceil(edge)+1 − (floor(edge)−1) + 1 per axis.  An
# approximation in ``_detail_zoom`` under-counted and pushed real alerts onto
# the placeholder path.

def _renderer_tile_count(min_lon, min_lat, max_lon, max_lat, z):
    """Count tiles the way ``_render_map`` does, without the world clamp."""
    tx_min = int(math.floor(tiles_mod._lon_to_tx(min_lon, z))) - 1
    tx_max = int(math.ceil(tiles_mod._lon_to_tx(max_lon, z))) + 1
    ty_min = int(math.floor(tiles_mod._lat_to_ty(max_lat, z))) - 1
    ty_max = int(math.ceil(tiles_mod._lat_to_ty(min_lat, z))) + 1
    return (tx_max - tx_min + 1) * (ty_max - ty_min + 1)


@pytest.mark.parametrize("bbox", [
    (-84.35, 40.55, -83.80, 41.15),    # a county-scale flood advisory
    (-84.60, 39.00, -82.10, 41.40),    # a multi-county flood watch
    (-90.00, 32.00, -80.00, 42.00),    # a multi-state watch
    (-84.05, 40.70, -83.95, 40.78),    # a single tornado-warning polygon
])
def test_detail_zoom_stays_within_the_renderer_tile_budget(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    z = tiles_mod._detail_zoom(min_lon, min_lat, max_lon, max_lat, 582, 490)
    assert _renderer_tile_count(min_lon, min_lat, max_lon, max_lat, z) <= 30, (
        f"z{z} exceeds the renderer's 30-tile limit — _render_map would fall "
        f"back to 'Map not available'"
    )


# ── Framing ─────────────────────────────────────────────────────────────────
def _crop_fill_fractions(bbox, z, map_w=582, map_h=490):
    """Return how much of the crop window the bbox spans, per axis."""
    min_lon, min_lat, max_lon, max_lat = bbox
    tx_min = int(math.floor(tiles_mod._lon_to_tx(min_lon, z))) - 1
    ty_min = int(math.floor(tiles_mod._lat_to_ty(max_lat, z))) - 1
    tx_max = int(math.ceil(tiles_mod._lon_to_tx(max_lon, z))) + 1
    ty_max = int(math.ceil(tiles_mod._lat_to_ty(min_lat, z))) + 1
    canvas_w = (tx_max - tx_min + 1) * tiles_mod.TILE_SIZE
    canvas_h = (ty_max - ty_min + 1) * tiles_mod.TILE_SIZE

    (x1, y1, x2, y2), scale = maps_mod._crop_window(
        min_lon, min_lat, max_lon, max_lat, z, tx_min, ty_min,
        canvas_w, canvas_h, map_w, map_h,
    )
    bw = (tiles_mod._lon_to_tx(max_lon, z)
          - tiles_mod._lon_to_tx(min_lon, z)) * tiles_mod.TILE_SIZE
    bh = (tiles_mod._lat_to_ty(min_lat, z)
          - tiles_mod._lat_to_ty(max_lat, z)) * tiles_mod.TILE_SIZE
    return bw / (x2 - x1), bh / (y2 - y1), scale


@pytest.mark.parametrize("bbox", [
    (-84.35, 40.55, -83.80, 41.15),
    (-84.60, 39.00, -82.10, 41.40),
    (-84.05, 40.70, -83.95, 40.78),
])
def test_crop_window_lets_the_alert_fill_the_frame(bbox):
    """The bbox must fill the crop on its constrained axis.

    Aspect correction grows exactly one axis, so the other should still be
    filled edge to edge — that is the whole point of framing the bbox
    rather than cropping a fixed window.
    """
    fx, fy, _ = _crop_fill_fractions(bbox, tiles_mod._detail_zoom(*bbox, 582, 490))
    assert max(fx, fy) > 0.97, f"neither axis fills the frame ({fx:.2f}, {fy:.2f})"
    # And the unconstrained axis must not be starved either.
    assert min(fx, fy) > 0.45, f"frame is mostly empty on one axis ({fx:.2f}, {fy:.2f})"


def test_crop_window_never_leaves_the_canvas():
    bbox = (-84.35, 40.55, -83.80, 41.15)
    z = tiles_mod._detail_zoom(*bbox, 582, 490)
    min_lon, min_lat, max_lon, max_lat = bbox
    tx_min = int(math.floor(tiles_mod._lon_to_tx(min_lon, z))) - 1
    ty_min = int(math.floor(tiles_mod._lat_to_ty(max_lat, z))) - 1
    tx_max = int(math.ceil(tiles_mod._lon_to_tx(max_lon, z))) + 1
    ty_max = int(math.ceil(tiles_mod._lat_to_ty(min_lat, z))) + 1
    canvas_w = (tx_max - tx_min + 1) * tiles_mod.TILE_SIZE
    canvas_h = (ty_max - ty_min + 1) * tiles_mod.TILE_SIZE

    (x1, y1, x2, y2), scale = maps_mod._crop_window(
        min_lon, min_lat, max_lon, max_lat, z, tx_min, ty_min,
        canvas_w, canvas_h, 582, 490,
    )
    assert 0 <= x1 < x2 <= canvas_w
    assert 0 <= y1 < y2 <= canvas_h
    assert scale == pytest.approx(582 / (x2 - x1))


# ── Basemap toning ──────────────────────────────────────────────────────────
def _pastel_tile(size=(120, 120)):
    """Stand-in for an OSM tile: pale landcover with a saturated road."""
    img = Image.new('RGB', size, (242, 239, 233))
    for x in range(size[0]):
        for y in range(size[1] // 2 - 2, size[1] // 2 + 2):
            img.putpixel((x, y), (232, 146, 60))     # motorway orange
    return img


def test_tone_basemap_darkens_and_desaturates():
    src = _pastel_tile()
    out = image_export.tone_basemap(src)

    src_mean = sum(ImageStat.Stat(src).mean) / 3
    out_mean = sum(ImageStat.Stat(out).mean) / 3
    assert out_mean < src_mean * 0.6, (
        f"basemap not knocked back enough ({src_mean:.0f} → {out_mean:.0f})"
    )

    def _chroma(img):
        r, g, b = ImageStat.Stat(img).mean
        return max(r, g, b) - min(r, g, b)

    assert _chroma(out) < _chroma(src), "basemap was not desaturated"


def test_tone_basemap_darkening_survives_the_contrast_step():
    """Regression: contrast ran last and pushed the pale majority back to white.

    ``ImageEnhance.Contrast`` blends away from the image mean, so on a tile
    that is overwhelmingly pale landcover it *brightens* almost everything.
    Applied after the darkening step it silently undid it.
    """
    src = _pastel_tile()
    mean = sum(ImageStat.Stat(image_export.tone_basemap(
        src, brightness=0.40, contrast=1.25)).mean) / 3
    darker = sum(ImageStat.Stat(image_export.tone_basemap(
        src, brightness=0.25, contrast=1.25)).mean) / 3
    assert darker < mean, "brightness has no effect at this contrast setting"


def _dark_native_tile(size=(120, 120)):
    """Stand-in for a CARTO Dark Matter tile: already dark and desaturated,
    unlike _pastel_tile()'s stand-in for a raw OSM tile."""
    return Image.new('RGB', size, (35, 38, 44))


def _dark_native_tile_with_thin_road(size=(512, 512), background=(8, 9, 11), road=(62, 62, 66)):
    """A synthetic stand-in for a *real* CARTO Dark Matter tile's low
    headroom: a near-black background with a single 1px-wide road line
    only ~50-60 (out of 255) brighter than it -- the actual contrast a
    live CARTO tile has (measured from a real fetched tile), unlike the
    flat swatch _dark_native_tile() uses for the simpler brightness test
    above."""
    from PIL import ImageDraw

    img = Image.new('RGB', size, background)
    draw = ImageDraw.Draw(img)
    draw.line([(0, size[1] // 2), (size[0], size[1] // 2)], fill=road, width=1)
    return img


def test_tone_preset_dark_native_lifts_a_low_contrast_dark_tile():
    """tone_basemap()'s *default* params are tuned for a light OSM source
    (see test_tone_basemap_darkens_and_desaturates above) -- applying them
    to a tile that's already dark darkens it further, which is backwards.

    The dark-native preset needs to move the other way: CARTO's own
    roads/labels sit only ~50-65 (out of 255) above its near-black
    background, and that low-contrast signal doesn't survive the card's
    tile resize + radar-overlay compositing -- it washes out to solid
    black (a real regression caught from a live render). The preset's
    brightness/contrast lift exists to pull that signal into a range
    that does survive, so it should land clearly *brighter* than the
    source, not merely "not darker"."""
    src = _dark_native_tile()
    src_mean = sum(ImageStat.Stat(src).mean) / 3

    default_out = image_export.tone_basemap(src)
    preset_out = image_export.tone_basemap(src, **image_export.TONE_PRESET_DARK_NATIVE)

    default_mean = sum(ImageStat.Stat(default_out).mean) / 3
    preset_mean = sum(ImageStat.Stat(preset_out).mean) / 3

    assert default_mean < src_mean, "OSM-tuned defaults should darken a dark-native tile further"
    assert preset_mean > src_mean, (
        f"dark-native preset ({preset_mean:.0f}) should brighten a low-contrast "
        f"dark-native tile ({src_mean:.0f}) so its linework survives downstream "
        f"resizing/compositing"
    )


def test_tone_preset_dark_native_road_survives_the_map_inset_downscale():
    """Regression test for a real bug: a CARTO Dark Matter share-card map
    rendered as solid black with no visible roads/labels, because the
    tile's thin, low-contrast linework (see _dark_native_tile_with_thin_road)
    was washed out by the same Lanczos downscale maps.py uses to fit
    stitched tiles to the card's exact map_rect pixel size -- OSM's much
    higher-contrast tiles survive that resize; CARTO's did not until the
    dark-native preset's brightness/contrast lift was added.

    Downscaling first mimics maps.py's actual order of operations
    (tone_basemap() runs on the already-stitched, already-resized canvas).
    """
    src = _dark_native_tile_with_thin_road()
    downscaled = src.resize((128, 128), Image.LANCZOS)

    background_mean = sum(ImageStat.Stat(Image.new('RGB', (8, 8), (8, 9, 11))).mean) / 3

    default_out = image_export.tone_basemap(downscaled)
    preset_out = image_export.tone_basemap(downscaled, **image_export.TONE_PRESET_DARK_NATIVE)

    default_peak = max(ImageStat.Stat(default_out).extrema[c][1] for c in range(3))
    preset_peak = max(ImageStat.Stat(preset_out).extrema[c][1] for c in range(3))

    # The OSM-tuned defaults reproduce the bug: darkening an already-dark,
    # already-thin line pushes its brightest surviving pixel close enough
    # to the background that it reads as solid black.
    assert default_peak - background_mean < 30, (
        "sanity check: the OSM-tuned defaults should reproduce the washed-out bug "
        "on this synthetic low-contrast tile"
    )
    # The dark-native preset must keep the road visibly above the background
    # after the same downscale, or the map reads as featureless black again.
    assert preset_peak - background_mean > 40, (
        f"dark-native preset's brightest surviving road pixel ({preset_peak}) isn't "
        f"far enough above the background ({background_mean:.0f}) to read as visible "
        f"after the card's tile downscale"
    )


def test_vignette_darkens_edges_but_not_the_centre():
    flat = Image.new('RGB', (200, 200), (160, 160, 160))
    out = image_export.apply_vignette(flat)

    centre = ImageStat.Stat(out.crop((85, 85, 115, 115))).mean[0]
    corner = ImageStat.Stat(out.crop((0, 0, 30, 30))).mean[0]
    assert centre == pytest.approx(160, abs=3), "vignette dimmed the centre"
    assert corner < 140, f"vignette did not darken the corner ({corner:.0f})"


# ── Label placement ─────────────────────────────────────────────────────────
def _blank(w=400, h=300):
    return Image.new('RGB', (w, h), (40, 48, 66))


def test_place_labels_skips_overlapping_labels():
    img = _blank()
    fonts = image_export._load_fonts()
    # Three anchors at the same point — only the first can be placed.
    drawn = image_export.place_labels(
        img, fonts, [("Allen", (200, 150)), ("Putnam", (200, 150)),
                     ("Henry", (203, 152))])
    assert drawn == 1


def test_place_labels_places_well_separated_labels():
    img = _blank()
    fonts = image_export._load_fonts()
    drawn = image_export.place_labels(
        img, fonts, [("Allen", (80, 80)), ("Putnam", (280, 80)),
                     ("Henry", (80, 220)), ("Defiance", (280, 220))])
    assert drawn == 4


def test_place_labels_honours_max_labels():
    img = _blank(900, 700)
    fonts = image_export._load_fonts()
    anchors = [(f"County{i}", (60 + (i % 6) * 130, 60 + (i // 6) * 90))
               for i in range(24)]
    assert image_export.place_labels(img, fonts, anchors, max_labels=5) == 5


def test_place_labels_skips_labels_outside_the_frame():
    img = _blank()
    fonts = image_export._load_fonts()
    assert image_export.place_labels(
        img, fonts, [("Offscreen", (-40, 150)), ("AlsoOff", (200, 320))]) == 0


def test_place_labels_respects_keep_out_boxes():
    """The scale bar and OSM attribution must never be covered by a label."""
    img = _blank()
    fonts = image_export._load_fonts()
    keep_out = [(0, 250, 190, 300)]
    assert image_export.place_labels(
        img, fonts, [("Allen", (60, 275))], avoid=keep_out) == 0
    # The same label away from the keep-out box does get placed.
    assert image_export.place_labels(
        img, fonts, [("Allen", (200, 120))], avoid=keep_out) == 1


def test_place_labels_of_empty_list_is_a_noop():
    assert image_export.place_labels(_blank(), image_export._load_fonts(), []) == 0


# ── End to end ──────────────────────────────────────────────────────────────
def test_render_map_frames_the_polygon_across_the_slot(monkeypatch):
    """The alert outline must span most of the finished map.

    Before the framing change the polygon could occupy barely a tenth of
    the frame; this pins the fix in pixels rather than in the geometry
    helper alone.  Tiles are stubbed to the offline path, so the only
    near-white pixels are the polygon's casing stroke.
    """
    monkeypatch.setattr(maps_mod, "_fetch_tile", lambda tx, ty, z, **kw: None)
    monkeypatch.setattr(maps_mod, "_fetch_county_outlines",
                        lambda *a, **k: [])

    geom = {
        "type": "Polygon",
        "coordinates": [[[-84.30, 41.10], [-83.85, 40.86], [-83.90, 40.72],
                         [-84.22, 40.61], [-84.30, 41.10]]],
    }
    map_w, map_h = 582, 490
    img = maps_mod._render_map(geom, "severe", map_w=map_w, map_h=map_h)
    assert img.size == (map_w, map_h)

    # Skip the map's own chrome — the scale bar and the attribution strip
    # also paint near-white pixels.
    chrome = [(0, map_h - 44, 190, map_h),
              (map_w - 210, map_h - 26, map_w, map_h)]

    def _is_chrome(x, y):
        return any(bx0 <= x < bx1 and by0 <= y < by1
                   for bx0, by0, bx1, by1 in chrome)

    px = img.convert('RGB').load()
    xs, ys = [], []
    for y in range(map_h):
        for x in range(map_w):
            r, g, b = px[x, y]
            if r > 235 and g > 235 and b > 235 and not _is_chrome(x, y):
                xs.append(x)
                ys.append(y)

    assert xs, "polygon casing stroke was not drawn"
    span_x = (max(xs) - min(xs)) / map_w
    span_y = (max(ys) - min(ys)) / map_h
    # This polygon is taller than it is wide, so height is the constrained
    # axis.  The bbox is padded 16% per side, so the polygon should span
    # 1 / 1.32 ≈ 76% of the frame; anything far below that means the crop
    # has stopped tracking the bounding box.
    assert max(span_x, span_y) > 0.70, (
        f"polygon fills only {span_x:.0%}x{span_y:.0%} of the map"
    )
