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

from __future__ import annotations

"""Decorative particle layers painted behind the card title.

Lightning bolts (ported from static/js/core/lightning.js so share images carry
the same visual identity as the web UI), snow, rain, sun rays, embers, wind
streaks and haze, plus the themed header that dispatches between them.
"""

import math
import random
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

from .layout import (
    _LAYOUT_LANDSCAPE, _Layout,
)
from .theme import (
    _Theme,
)
from .drawing import (
    _composite,
)


# ─── Lightning bolt renderer (matches the site's lightning theme) ───────────
# Ported from static/js/core/lightning.js so social-share images carry the
# same stormy-sky visual identity as the web UI.

def _lb_trunk(rng: random.Random, start_x: float, start_y: float,
              end_y: float, segments: int, drift: float) -> List[Tuple[float, float]]:
    """Jagged descending trunk with uneven step length — real bolts aren't even zigzags."""
    pts: List[Tuple[float, float]] = [(start_x, start_y)]
    x, y = start_x, start_y
    avg_step = (end_y - start_y) / max(1, segments)
    for _ in range(1, segments):
        step = avg_step * rng.uniform(0.55, 1.45)
        y = min(end_y, y + step)
        x += rng.uniform(-drift, drift)
        pts.append((x, y))
    pts.append((x + rng.uniform(-drift, drift), end_y))
    return pts


def _lb_branches(rng: random.Random, parent: List[Tuple[float, float]],
                 spawn_chance: float, depth: int, base_width: float,
                 side_hint: int) -> List[Dict[str, Any]]:
    """Branches fork from interior trunk vertices and may recurse."""
    out: List[Dict[str, Any]] = []
    if depth <= 0:
        return out
    for i in range(1, len(parent) - 1):
        if rng.random() >= spawn_chance:
            continue
        ox, oy = parent[i]
        direction = side_hint * (1 if rng.random() < 0.75 else -1)
        length = rng.uniform(40, 140)
        segs = rng.randint(3, 7)
        step = length / segs
        angle = rng.uniform(0.55, 1.25)
        branch: List[Tuple[float, float]] = [(ox, oy)]
        cx, cy = ox, oy
        for _ in range(segs):
            lateral = math.sin(angle + rng.uniform(-0.35, 0.35)) * step * direction
            descent = math.cos(angle) * step * 0.65 + rng.uniform(-step * 0.15, step * 0.35)
            cx += lateral
            cy += descent
            branch.append((cx, cy))
        out.append({'points': branch, 'width': base_width})
        if depth > 1 and rng.random() < spawn_chance * 0.6:
            out.extend(_lb_branches(rng, branch, spawn_chance * 0.5,
                                    depth - 1, base_width * 0.55, direction))
    return out


def _lb_render_polyline(draw: ImageDraw.ImageDraw,
                        points: List[Tuple[float, float]],
                        base_width: float, taper: float,
                        color: Tuple[int, int, int, int]) -> None:
    """Draw a tapered polyline — width shrinks toward the tip for a bolt-like feel."""
    total = len(points) - 1
    if total <= 0:
        return
    for i in range(total):
        t = i / total
        w = max(1, int(round(base_width * ((1 - t) ** taper))))
        p1 = (int(points[i][0]),     int(points[i][1]))
        p2 = (int(points[i + 1][0]), int(points[i + 1][1]))
        draw.line([p1, p2], fill=color, width=w)


def _draw_lightning_bolts(target: Image.Image, region: Tuple[int, int, int, int],
                          *, count: int = 2, seed: int = 0,
                          intensity: float = 1.0) -> None:
    """Composite glowing lightning bolts onto *target* within *region* (x, y, w, h).

    Bolts are rendered once as geometry, then drawn three times with
    shrinking widths and increasing opacity: a wide blurred halo, a
    medium-width glow, and a crisp white core.  This stack mimics the
    CSS drop-shadow layers used by the web UI's lightning.js so the
    share image carries the same visual identity.
    """
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return

    rng = random.Random(seed)

    # ── Geometry pass: build trunks + branches once, reuse for each layer ──
    bolts: List[Dict[str, Any]] = []
    # Extend virtual height so the trunk develops a natural zigzag rhythm
    # even when the physical region is short (e.g. the 90-px header).  We
    # draw into the full virtual range, then clip by the region when
    # compositing.
    vh = max(rh, 260)
    for _ in range(count):
        start_x  = rng.uniform(rw * 0.08, rw * 0.92)
        start_y  = rng.uniform(-vh * 0.20, -vh * 0.05)
        end_y    = vh + rng.uniform(-vh * 0.10, vh * 0.05)
        segments = rng.randint(12, 18)
        # Drift is per-step, proportional to segment length — this keeps
        # the bolt predominantly vertical instead of ping-ponging sideways.
        step_h   = (end_y - start_y) / segments
        drift    = step_h * rng.uniform(0.35, 0.75)
        side     = 1 if start_x < rw / 2 else -1

        trunk    = _lb_trunk(rng, start_x, start_y, end_y, segments, drift)
        branches = _lb_branches(rng, trunk, 0.38, 2, 1.6, side)
        bolts.append({'trunk': trunk, 'branches': branches})

    # Render geometry to three layers at different widths/opacities.
    def _stamp(width_trunk: float, width_branch: float,
               taper_t: float, taper_b: float, alpha: int) -> Image.Image:
        layer = Image.new('RGBA', (rw, vh), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        color = (255, 255, 255, min(255, max(0, int(alpha * intensity))))
        for bolt in bolts:
            _lb_render_polyline(ld, bolt['trunk'], width_trunk, taper_t, color)
            for b in bolt['branches']:
                _lb_render_polyline(ld, b['points'],
                                    max(1.0, b['width'] * width_branch),
                                    taper_b, color)
        return layer

    halo = _stamp(width_trunk=14, width_branch=7, taper_t=1.0, taper_b=1.3, alpha=110)
    glow = _stamp(width_trunk=7,  width_branch=4, taper_t=1.1, taper_b=1.4, alpha=170)
    core = _stamp(width_trunk=3,  width_branch=1, taper_t=1.3, taper_b=1.6, alpha=245)

    halo = halo.filter(ImageFilter.GaussianBlur(radius=10))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=3))

    # Composite onto target, clipping to the physical region height.
    def _paste(layer: Image.Image) -> None:
        cropped = layer.crop((0, 0, rw, rh))
        if target.mode != 'RGBA':
            base = target.convert('RGBA')
            base.alpha_composite(cropped, dest=(x0, y0))
            target.paste(base.convert('RGB'))
        else:
            target.alpha_composite(cropped, dest=(x0, y0))

    _paste(halo)
    _paste(glow)
    _paste(core)

# ─── Other particle styles (event-specific) ─────────────────────────────────

def _draw_snow(target: Image.Image, region: Tuple[int, int, int, int],
               *, seed: int = 0, intensity: float = 1.0) -> None:
    """Snowflake particles — drifting white dots and 6-armed stars."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0xA5A5)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    flake_count = int(45 * intensity)
    for _ in range(flake_count):
        fx = rng.uniform(0, rw)
        fy = rng.uniform(0, rh)
        r = rng.uniform(1.4, 3.6)
        alpha = int(rng.uniform(110, 220) * intensity)
        ld.ellipse((fx - r, fy - r, fx + r, fy + r),
                   fill=(255, 255, 255, min(255, alpha)))
    # A few larger stylised flakes with arms
    for _ in range(int(7 * intensity)):
        fx = rng.uniform(rw * 0.05, rw * 0.95)
        fy = rng.uniform(rh * 0.10, rh * 0.85)
        r = rng.uniform(4.0, 6.5)
        alpha = int(rng.uniform(180, 240) * intensity)
        col = (255, 255, 255, min(255, alpha))
        for k in range(6):
            ang = math.radians(k * 60)
            ex = fx + math.cos(ang) * r
            ey = fy + math.sin(ang) * r
            ld.line([(fx, fy), (ex, ey)], fill=col, width=1)
        ld.ellipse((fx - 1, fy - 1, fx + 1, fy + 1), fill=col)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.6))
    _composite(target, region, layer)


def _draw_rain(target: Image.Image, region: Tuple[int, int, int, int],
               *, seed: int = 0, intensity: float = 1.0) -> None:
    """Diagonal rain streaks."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0x3C3C)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    streak_count = int(55 * intensity)
    slant = 4   # x-offset per streak length
    for _ in range(streak_count):
        sx = rng.uniform(-rw * 0.1, rw)
        sy = rng.uniform(-rh * 0.3, rh)
        length = rng.uniform(rh * 0.20, rh * 0.55)
        alpha = int(rng.uniform(100, 200) * intensity)
        col = (200, 225, 255, min(255, alpha))
        ld.line([(sx, sy),
                 (sx + slant, sy + length)],
                fill=col, width=1)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.5))
    _composite(target, region, layer)


def _draw_sun_rays(target: Image.Image, region: Tuple[int, int, int, int],
                   *, seed: int = 0, intensity: float = 1.0) -> None:
    """Radial rays + warm glow ball — heat-advisory visual."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0x5E11)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    # Place sun centre off the right edge so rays sweep across the header
    cx = rw - rng.randint(40, 110)
    cy = rng.randint(-int(rh * 0.4), int(rh * 0.2))
    # Bright halo
    for r in range(120, 25, -8):
        a = int(8 * intensity * (1 - (r - 25) / 100))
        if a <= 0:
            continue
        ld.ellipse((cx - r, cy - r, cx + r, cy + r),
                   fill=(255, 230, 130, max(0, min(255, a))))
    # Rays
    n_rays = 14
    for k in range(n_rays):
        ang = 2 * math.pi * k / n_rays + rng.uniform(-0.05, 0.05)
        length = rng.uniform(rw * 0.45, rw * 0.85)
        ex = cx + math.cos(ang) * length
        ey = cy + math.sin(ang) * length
        alpha = int(rng.uniform(60, 160) * intensity)
        ld.line([(cx, cy), (ex, ey)],
                fill=(255, 220, 110, min(255, alpha)), width=2)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=2.0))
    # Bright core on top of the blur
    ld2 = ImageDraw.Draw(layer)
    ld2.ellipse((cx - 22, cy - 22, cx + 22, cy + 22),
                fill=(255, 240, 170, int(220 * intensity)))
    _composite(target, region, layer)


def _draw_embers(target: Image.Image, region: Tuple[int, int, int, int],
                 *, seed: int = 0, intensity: float = 1.0) -> None:
    """Rising hot embers — orange dots with glow, sparser at the top."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0xE3B5)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    count = int(55 * intensity)
    for _ in range(count):
        # Embers concentrate near the bottom — bias toward higher y
        fy = rh - (rng.random() ** 1.8) * rh
        fx = rng.uniform(0, rw)
        r = rng.uniform(1.0, 3.0)
        # Colour ramp: deep red at bottom → bright yellow toward top
        t = fy / max(1, rh)   # 0 top → 1 bottom
        red   = int(255)
        green = int(80 + (1 - t) * 150)
        blue  = int(20 + (1 - t) * 40)
        alpha = int(rng.uniform(120, 230) * intensity)
        ld.ellipse((fx - r, fy - r, fx + r, fy + r),
                   fill=(red, green, blue, min(255, alpha)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=1.2))
    # A few crisp sparks on top
    ld2 = ImageDraw.Draw(layer)
    for _ in range(int(10 * intensity)):
        fx = rng.uniform(0, rw)
        fy = rh - (rng.random() ** 1.6) * rh
        ld2.ellipse((fx - 1, fy - 1, fx + 1, fy + 1),
                    fill=(255, 245, 180, int(230 * intensity)))
    _composite(target, region, layer)


def _draw_wind_streaks(target: Image.Image, region: Tuple[int, int, int, int],
                       *, seed: int = 0, intensity: float = 1.0) -> None:
    """Horizontal motion streaks — wind/hurricane visual."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0x7777)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    streak_count = int(28 * intensity)
    for _ in range(streak_count):
        sy = rng.uniform(0, rh)
        sx = rng.uniform(-rw * 0.1, rw * 0.4)
        length = rng.uniform(rw * 0.20, rw * 0.55)
        width = rng.choice([1, 1, 2])
        alpha = int(rng.uniform(80, 180) * intensity)
        col = (235, 240, 255, min(255, alpha))
        # Slight upward curve to feel "blown"
        mx = sx + length * 0.5
        my = sy - rng.uniform(0, 4)
        ex = sx + length
        ey = sy
        # Quadratic-ish — approximate with two line segments
        ld.line([(sx, sy), (mx, my)], fill=col, width=width)
        ld.line([(mx, my), (ex, ey)], fill=col, width=width)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.7))
    _composite(target, region, layer)


def _draw_haze(target: Image.Image, region: Tuple[int, int, int, int],
               *, seed: int = 0, intensity: float = 1.0) -> None:
    """Soft horizontal fog/haze bands."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0x4ADE)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    bands = 5
    for _ in range(bands):
        cy_ = rng.uniform(rh * 0.15, rh * 0.85)
        band_h = rng.uniform(rh * 0.15, rh * 0.35)
        alpha = int(rng.uniform(35, 70) * intensity)
        # Ellipse much wider than tall = horizontal smear
        ld.ellipse((-rw * 0.1, cy_ - band_h / 2,
                    rw * 1.1, cy_ + band_h / 2),
                   fill=(230, 235, 245, min(255, alpha)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=8.0))
    _composite(target, region, layer)


_PARTICLE_FNS = {
    'bolts':  lambda t, r, **kw: _draw_lightning_bolts(t, r, count=3, **kw),
    'snow':   _draw_snow,
    'rain':   _draw_rain,
    'sun':    _draw_sun_rays,
    'embers': _draw_embers,
    'wind':   _draw_wind_streaks,
    'haze':   _draw_haze,
    'none':   None,
}


def _draw_themed_header(img: Image.Image, theme: _Theme,
                        seed: int = 0,
                        layout: Optional[_Layout] = None) -> None:
    """Paint a themed header: diagonal gradient + event-appropriate particles.

    Replaces the older single-colour vertical gradient + always-bolts
    combo.  The gradient runs diagonally (top-left → bottom-right) for
    a more dynamic feel, and the particle layer is event-specific:
    snowflakes for winter advisories, raindrops for floods, sun rays for
    heat, etc.  See ``_THEMES`` for the full mapping.
    """
    lay = layout or _LAYOUT_LANDSCAPE
    canvas_w = lay.width
    header_h = lay.header_h
    top = theme['top']
    bot = theme['bottom']
    # Diagonal gradient — compute t from a normal vector pointing from
    # the top-left corner to the bottom-right of the header.  Drawing per
    # row is fast enough and lets us shade left→right per row by sampling
    # the diagonal coordinate at line midpoint.
    diag = header_h + canvas_w * 0.35   # how far along the diagonal we go
    for y in range(header_h):
        # Two-stop interpolation with per-row x sweep so the right side
        # of the image runs ahead of the left — diagonal feel.
        row = Image.new('RGB', (canvas_w, 1), bot)
        rd = ImageDraw.Draw(row)
        for x in range(0, canvas_w, 8):   # step by 8 px — visually smooth, fast
            t = (y + x * 0.35) / diag
            t = max(0.0, min(1.0, t))
            r = int(top[0] * (1 - t) + bot[0] * t)
            g = int(top[1] * (1 - t) + bot[1] * t)
            b = int(top[2] * (1 - t) + bot[2] * t)
            rd.line([(x, 0), (min(canvas_w, x + 8), 0)], fill=(r, g, b))
        img.paste(row, (0, y))
    # Slight darkening at the very top edge so the title reads clearly
    # against the brighter parts of the gradient.
    shade = Image.new('RGBA', (canvas_w, header_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(28):
        a = int(60 * (1 - y / 28))
        sd.line([(0, y), (canvas_w, y)], fill=(0, 0, 0, a))
    base = img.convert('RGBA')
    base.alpha_composite(shade)
    img.paste(base.convert('RGB'))
    # Particle layer
    particle = theme.get('particles', 'bolts')
    intensity = float(theme.get('particle_intensity', 1.0))
    fn = _PARTICLE_FNS.get(particle)
    if fn is not None and intensity > 0.01:
        fn(img, (0, 0, canvas_w, header_h), seed=seed, intensity=intensity)
