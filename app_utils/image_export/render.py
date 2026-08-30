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

"""The public entry point: compose every layer into the finished PNG."""

import io
import json
import logging
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from .logo import _load_logo
from .layout import (
    _LAYOUTS, _LAYOUT_LANDSCAPE,
)
from .palette import (
    WHITE, _BG, _DIVIDER, _SEVERITY, _STRIP,
    _TEXT_MUT, _TEXT_SEC, _darken,
)
from .theme import (
    _apply_urgency_to_theme, _resolve_theme, _resolve_tier, _theme_supports_storm_motion, _urgency_heat,
)
from .fonts import (
    _load_fonts, _th, _title_font_for, _tw,
)
from .text import (
    _format_countdown, _short_local_dt,
)
from .drawing import (
    _apply_card_lift, _draw_pill, _draw_pill_glow, _round_image_corners,
)
from .weather_fx import (
    _draw_themed_header,
)
from .maps import (
    _alert_same_codes, _fetch_same_union_geom, _render_map,
)
from .panels import (
    _draw_areas, _draw_compass_section, _draw_coverage, _draw_threats,
)
from .panels_text import (
    _draw_description, _draw_instruction, _draw_nws_headline,
)

logger = logging.getLogger(__name__)

# ─── Main public function ─────────────────────────────────────────────────────
def generate_alert_image(
    alert: Any,
    coverage_data: Dict[str, Any],
    ipaws_data: Optional[Dict[str, Any]],
    location_settings: Optional[Dict[str, Any]],
    aspect_ratio: str = 'landscape',
    image_format: str = 'png',
    db_session: Any = None,
    scale: float = 1.0,
) -> bytes:
    """Generate a share-card image for *alert* in the requested aspect ratio.

    Args:
        alert:             CAPAlert model instance.
        coverage_data:     Dict returned by calculate_coverage_percentages().
        ipaws_data:        Dict returned by _extract_alert_display_data(), may be None.
        location_settings: Dict from get_location_settings(), may be None.
        aspect_ratio:      One of ``landscape`` (1200×630, default — FB/X/LI
            open-graph), ``square`` (1080×1080 — Instagram, Mastodon),
            ``portrait`` (1080×1350 — Instagram 4:5) or ``story``
            (1080×1920 — IG / TikTok / Snap).  Unknown values fall back
            to landscape so callers can pass any platform hint.
        image_format:      ``png`` (default, universal) or ``webp`` (lossy,
            ~30% smaller at equivalent quality, supported by every major
            social platform).  Unknown values fall back to ``png``.
        db_session:        Optional SQLAlchemy session used to fetch the
            alert polygon and county outlines.  Required when rendering
            outside a Flask application context (the CAP poller and audio
            monitoring services that send notification emails); inside a
            request the Flask-SQLAlchemy session is used by default.
        scale:             Output upscale factor (1.0–3.0, default 1.0).
            Social platforms re-encode every upload to JPEG and display
            it downscaled in the feed; a 2× upload (e.g. 2400×1260 for
            landscape) makes the compression artefacts proportionally
            smaller on screen, which is the difference between a grainy
            and a clean card on Facebook.  The card is composed at the
            native canvas size and Lanczos-upscaled just before encode.

    Returns:
        Raw image bytes in the requested container.
    """
    layout = _LAYOUTS.get(aspect_ratio, _LAYOUT_LANDSCAPE)
    fonts = _load_fonts()

    severity    = (getattr(alert, 'severity', '') or '').lower()
    event_name  = (getattr(alert, 'event', '') or 'Alert').upper()
    county_name = (location_settings or {}).get('county_name', 'County') or 'County'

    # Event-aware theme drives the header gradient, particle style, and
    # accent colour used for section headers + the polygon stroke.  We
    # keep the legacy ``alr_clr`` symbol pointing at the theme accent so
    # downstream draw helpers don't need signature changes.
    theme   = _resolve_theme(event_name, severity)
    alr_clr = tuple(theme['accent'])  # type: ignore[assignment]
    # Watch / warning / advisory ladder — drives the tier badge and the
    # rule under the header so the required response level is colour-coded
    # independently of the hazard-family theme.
    tier = _resolve_tier(event_name)

    # Cool the header gradient for lower-urgency products: a Heat
    # ADVISORY no longer glows as red-hot as an Excessive Heat WARNING.
    # The accent colour (section headers, polygon stroke) keeps its full
    # hazard-family identity; only the gradient + particles calm down.
    theme = _apply_urgency_to_theme(
        theme, _urgency_heat(tier[0] if tier else None, severity))

    # Stable per-alert seed so each alert's bolt/snow/etc pattern is
    # reproducible across re-renders.
    alert_seed = hash((getattr(alert, 'id', 0) or 0, event_name)) & 0xFFFFFFFF

    # ── Base canvas ──────────────────────────────────────────────────────────
    img  = Image.new('RGB', (layout.width, layout.height), _BG)
    draw = ImageDraw.Draw(img)

    # ── Header bar (event-themed gradient + particles) ───────────────────────
    # Diagonal gradient + event-specific particle layer (bolts for storms,
    # snowflakes for winter, raindrops for floods, sun rays for heat, ...).
    _draw_themed_header(img, theme, seed=alert_seed, layout=layout)
    # Soft scrim under the title text for legibility against the particle
    # layer.  Only the left ~half — the right side is reserved for branding
    # and shows the particles clearly.
    scrim = Image.new('RGBA', (layout.width, layout.header_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    sd.rectangle((0, 0, layout.header_scrim_w, layout.header_h),
                 fill=(0, 0, 0, 75))
    base = img.convert('RGBA')
    base.alpha_composite(scrim)
    img.paste(base.convert('RGB'))
    draw = ImageDraw.Draw(img)

    # Rule under the header — tier-coloured when the event carries a
    # watch/warning/advisory word so the escalation level reads even at
    # thumbnail size; falls back to the darkened theme accent otherwise.
    rule_clr = tier[1]['fill'] if tier is not None else _darken(alr_clr, 0.45)
    draw.rectangle((0, layout.header_h - 3, layout.width, layout.header_h),
                   fill=rule_clr)

    # Pre-compute the wordmark width so we know how much room the title
    # has on the left.  The logo's natural aspect ratio + the capped
    # height give us a stable footprint without drawing yet.
    logo_preview = _load_logo()
    logo_target_h = min(layout.header_h - 16, 74) if logo_preview else 0
    if logo_preview and logo_preview.height:
        logo_target_w = max(1, int(round(
            logo_preview.width * (logo_target_h / float(logo_preview.height))
        )))
    else:
        logo_target_w = 0

    # Event name (left).  Title y is tuned to leave room for the sub-line
    # below; sub-line y sits below the title font's natural height.  The
    # title font scales with the layout so larger canvases (Story / IG
    # 4:5) get a headline that still reads at arm's length, with a
    # shrink-to-fit guard so an unusually long event name (e.g. "Special
    # Marine Warning Forecast") never crashes into the wordmark.
    title_max_w = (layout.width - 16) - logo_target_w - 32 - 16
    title_size = layout.title_size

    def _title_font(sz: int) -> ImageFont.FreeTypeFont:
        return fonts['title'] if sz == 30 else _title_font_for(sz)

    title_font = _title_font(title_size)
    while title_size > 22 and _tw(title_font, event_name) > title_max_w:
        title_size -= 2
        title_font = _title_font(title_size)

    title_y = 10
    draw.text((16, title_y), event_name, font=title_font, fill=WHITE)
    title_h = _th(title_font, event_name)

    # Metadata row — severity becomes a coloured pill (the single most
    # glanceable signal for "how worried should I be") with urgency /
    # certainty rendered as quieter secondary text.  Status renders as a
    # neutral pill but only when it isn't the default "Actual" (which
    # holds for ~all production alerts and just adds noise).
    sub_y = title_y + title_h + 8
    pill_x = 18
    # Header badges use the larger bold face — the 11 px label font made
    # the tier/severity colours read as indistinguishable specks once the
    # feed downscaled the card.
    pill_font = fonts['bold']

    # Tier badge first — WARNING / WATCH / ADVISORY in the conventional
    # escalation colour (red / orange / amber).  This is the one signal
    # that tells a reader whether to act or just stay aware, so it leads
    # the metadata row.  The white casing keeps the fill readable when it
    # lands on a same-coloured stretch of the event gradient.
    if tier is not None:
        tier_word, tier_style = tier
        # Glow first (composites onto img directly, invalidating `draw`'s
        # buffer reference like every other img.paste() in this function),
        # then re-bind draw before the crisp pill on top.
        _draw_pill_glow(img, pill_font, tier_word.upper(),
                        tier_style['fill'], pill_x, sub_y)
        draw = ImageDraw.Draw(img)
        pill_x = _draw_pill(draw, pill_font, tier_word.upper(),
                            tier_style['fill'], pill_x, sub_y,
                            text_color=tier_style['text'],
                            outline=WHITE, outline_w=2)
        pill_x += 8

    # Severity pill — solid severity-colour fill (white-cased like the
    # tier badge).  The severity ladder deliberately shares hues with the
    # tier ladder (red / orange / amber / blue), so the common pairings
    # reinforce one urgency colour per card: a Tornado Warning (Extreme)
    # reads all-red, a Heat Advisory (Moderate) reads all-amber.  The
    # words distinguish the two systems; the colour codes the level.
    severity_val = (getattr(alert, 'severity', '') or '').strip()
    if severity_val:
        sev_color = _SEVERITY.get(
            severity_val.lower(),
            _SEVERITY.get('unknown', (108, 117, 125)),
        )
        # Amber needs dark text for contrast; every other fill takes white.
        sev_text = (45, 36, 3) if severity_val.lower() == 'moderate' else WHITE
        _draw_pill_glow(img, pill_font, severity_val.upper(), sev_color, pill_x, sub_y)
        draw = ImageDraw.Draw(img)
        pill_x = _draw_pill(draw, pill_font, severity_val.upper(),
                            sev_color, pill_x, sub_y,
                            text_color=sev_text,
                            outline=WHITE, outline_w=2)
        pill_x += 8

    # Status pill (non-Actual only) — keep neutral so it doesn't compete
    # with the tier/severity pills for attention.
    status_val = (getattr(alert, 'status', '') or '').strip()
    if status_val and status_val.lower() != 'actual':
        pill_x = _draw_pill(draw, pill_font, status_val.upper(),
                            (245, 248, 252), pill_x, sub_y,
                            text_color=(73, 80, 96))
        pill_x += 8

    extras: List[str] = []
    for attr, label in [('urgency', 'Urgency'), ('certainty', 'Certainty')]:
        val = (getattr(alert, attr, '') or '').strip()
        if val:
            extras.append(f'{label}: {val}')
    if extras:
        extra_text = '  ·  '.join(extras)
        # Optically centre the small text against the pill height so the
        # baseline lines up cleanly instead of riding above the pill.
        pill_h = _th(pill_font, 'Mg') + 6  # mirrors _draw_pill padding
        extra_y = sub_y + (pill_h - _th(fonts['small'], extra_text)) // 2 - 1
        draw.text((pill_x, extra_y), extra_text, font=fonts['small'],
                  fill=(*WHITE, 200))  # type: ignore[arg-type]

    # Branding (top-right) — render the canonical EAS Station wordmark image
    # so updating the brand asset is just a matter of swapping the file at
    # static/img/eas-system-wordmark.png (rasterized from the SVG).  Fall
    # back to the legacy text mark only if the file is missing or fails to
    # load.
    logo = _load_logo()
    brand_right = layout.width - 16
    if logo is not None:
        # Cap the wordmark height so it doesn't balloon on tall headers
        # (Story / Portrait) — at unbounded scale the logo crowds the
        # headline and pushes the right side off-canvas.  74 px is the
        # original landscape size, which already reads cleanly.
        logo_h = min(layout.header_h - 16, 74)
        # Preserve aspect ratio
        ratio = logo_h / float(logo.height)
        logo_w = max(1, int(round(logo.width * ratio)))
        logo_resized = logo.resize((logo_w, logo_h), Image.LANCZOS)
        # Dim the wordmark slightly so it reads as a corner mark instead
        # of competing with the headline.  Multiply the alpha channel by
        # 0.78 — opaque enough to stay legible against the gradient,
        # quiet enough to defer to the title.
        r_ch, g_ch, b_ch, a_ch = logo_resized.split()
        a_ch = a_ch.point(lambda v: int(v * 0.78))
        logo_resized = Image.merge('RGBA', (r_ch, g_ch, b_ch, a_ch))
        lx = brand_right - logo_w
        ly = (layout.header_h - logo_h) // 2
        # Paste with the logo's own alpha so the header gradient shows through
        base_rgba = img.convert('RGBA')
        base_rgba.alpha_composite(logo_resized, dest=(lx, ly))
        img.paste(base_rgba.convert('RGB'))
        draw = ImageDraw.Draw(img)
    else:
        brand = 'EAS STATION'
        draw.text((brand_right - _tw(fonts['head'], brand), 10),
                  brand, font=fonts['head'], fill=WHITE)

    # ── Map slot ────────────────────────────────────────────────────────────
    # Map rectangle comes from the layout: side-by-side for landscape (map
    # on the left), stacked for square/portrait (map below the header).
    map_x, map_y, map_w, map_h = layout.map_rect

    # Storm motion is only meaningful for convective / wind / water events.
    # Suppress it on advisories like FROST / HEAT / FOG where the IPAWS
    # blob may still carry a stale motion vector — it adds noise without
    # information for non-convective events.
    storm_motion = (ipaws_data or {}).get('storm_motion')
    if storm_motion and not _theme_supports_storm_motion(theme):
        storm_motion = None
    map_img: Optional[Image.Image] = None
    try:
        from app_core.models import CAPAlert as _CA
        from sqlalchemy import func as _func
        alert_id = getattr(alert, 'id', None)
        if alert_id is not None:
            session = db_session
            if session is None:
                # Web-request path — fall back to the Flask-SQLAlchemy
                # session (requires an active application context).
                from app_core.extensions import db
                session = db.session
            geom_json = (
                session.query(_func.ST_AsGeoJSON(_CA.geom))
                .filter(_CA.id == alert_id)
                .scalar()
            )
            geom_obj: Optional[Dict[str, Any]] = (
                json.loads(geom_json) if geom_json else None
            )
            if geom_obj is None:
                # Stored geometry is NULL — a county-coded product, or the
                # poller's geometry write failed.  Fall back to the union of
                # the affected counties from the alert's SAME geocodes (the
                # shape official NWS county-based graphics show) so the card
                # still carries a coverage map.
                same_codes = _alert_same_codes(alert)
                geom_obj = _fetch_same_union_geom(session, same_codes)
                if geom_obj is not None:
                    logger.info(
                        "Alert %s has no stored geometry; coverage map built "
                        "from %d SAME county code(s)",
                        alert_id, len(same_codes),
                    )
                else:
                    logger.warning(
                        "Alert %s has no stored geometry and no county-union "
                        "fallback (%d SAME code(s)); card will show "
                        "'Map not available'",
                        alert_id, len(same_codes),
                    )
            if geom_obj is not None:
                map_img = _render_map(geom_obj, severity,
                                      storm_motion=storm_motion,
                                      theme=theme,
                                      map_w=map_w, map_h=map_h,
                                      db_session=session,
                                      category=getattr(alert, 'category', None),
                                      sent=getattr(alert, 'sent', None))
    except Exception as exc:
        # The card is still rendered with a "Map not available" slot, but
        # leave a trace — a context/session error here is why an email or
        # share card silently loses its coverage map.
        logger.warning(
            "Alert %s: could not fetch geometry for coverage map: %s",
            getattr(alert, 'id', None), exc,
        )

    if map_img is None:
        map_img = Image.new('RGB', (map_w, map_h), (34, 42, 60))
        md = ImageDraw.Draw(map_img)
        lbl = 'Map not available'
        md.text(((map_w - _tw(fonts['small'], lbl)) // 2, map_h // 2 - 8),
                lbl, font=fonts['small'], fill=_TEXT_MUT)

    # Round the map's corners so it sits visually inside the rounded
    # canvas instead of butting up against sharp 90° edges.  Skip when
    # the layout asked for a full-bleed map (corner_r = 0).
    if layout.map_corner_r > 0:
        map_img = _round_image_corners(map_img, layout.map_corner_r, bg=_BG)
    img.paste(map_img, (map_x, map_y))

    # Thin vertical separator — only meaningful in side-by-side layouts.
    if layout.show_vertical_divider:
        div_x = map_x + map_w
        draw.line([(div_x, map_y),
                   (div_x, layout.height - layout.footer_h)],
                  fill=_darken(alr_clr, 0.20), width=3)

    # ── Info panel ──────────────────────────────────────────────────────────
    ix, iy_top, iw, ih = layout.info_rect
    iy  = iy_top
    bot = iy_top + ih

    # Priority order for a share card: storm threats (when dangerous), the
    # headline, WHO is affected, WHAT is happening, WHAT to do.  Coverage /
    # storm motion come last so they only consume space the copy doesn't
    # need.  VTAC codes and the issuing-office block are intentionally
    # omitted — they're operator data, not share-worthy info, and were the
    # main reason long descriptions were being clipped.
    iy = _draw_threats(draw, fonts, alr_clr, ix, iy, iw, bot, ipaws_data)
    iy = _draw_nws_headline(draw, fonts, alr_clr, ix, iy, iw, bot, alert, ipaws_data)

    # Track whether the areas section actually rendered: when it did, the
    # description's WHERE bullet is that same county list written out as a
    # sentence, and repeating it costs two lines the hazard copy needs.
    iy_before_areas = iy
    iy = _draw_areas(draw, fonts, alr_clr, ix, iy, iw, bot, alert)
    areas_shown = iy > iy_before_areas

    # Likewise the WHEN bullet ("Until 1245 PM EDT") only restates the
    # expiry stamp the footer already carries.
    timing_shown = bool(getattr(alert, 'expires', None))

    iy = _draw_description(draw, fonts, alr_clr, ix, iy, iw, bot, alert,
                           areas_shown=areas_shown, timing_shown=timing_shown)
    iy = _draw_instruction(draw, fonts, alr_clr, ix, iy, iw, bot, alert)
    iy = _draw_coverage(draw, fonts, alr_clr, ix, iy, iw, bot, coverage_data, county_name)
    iy = _draw_compass_section(draw, fonts, alr_clr, ix, iy, iw, bot, ipaws_data)

    # ── Footer ────────────────────────────────────────────────────────────────
    fy = layout.height - layout.footer_h
    draw.rectangle((0, fy, layout.width, layout.height), fill=_STRIP)
    draw.line([(0, fy), (layout.width, fy)], fill=_DIVIDER, width=1)

    timing: List[str] = []
    try:
        sent = getattr(alert, 'sent', None)
        expires = getattr(alert, 'expires', None)
        if sent:
            timing.append(f"Issued {_short_local_dt(sent, ref=None)}")
        if expires:
            # When the expiration falls on a different calendar day than the
            # issue time, include the date so "Expires 10:00 PM" isn't
            # ambiguous; otherwise keep it to the bare time.
            timing.append(f"Expires {_short_local_dt(expires, ref=sent)}")
    except Exception:
        pass

    footer_x = 12
    if timing:
        t_str = '  ·  '.join(timing)
        ty_pos = fy + (layout.footer_h - _th(fonts['small'], t_str)) // 2
        draw.text((footer_x, ty_pos), t_str, font=fonts['small'], fill=_TEXT_SEC)
        footer_x += _tw(fonts['small'], t_str) + 10

    # Countdown badge — the single most share-worthy fact for a social post
    # ("is this still happening") restated as urgency instead of a bare
    # timestamp the reader has to do math on.
    countdown = _format_countdown(getattr(alert, 'expires', None))
    if countdown:
        label, urgency = countdown
        badge_style = {
            'critical': {'fill': _SEVERITY['extreme'], 'text': WHITE},
            'soon':     {'fill': _SEVERITY['severe'],  'text': WHITE},
            'normal':   {'fill': (68, 80, 102),         'text': (222, 228, 240)},
            'expired':  {'fill': (52, 58, 74),          'text': _TEXT_MUT},
        }[urgency]
        pill_w_est = _tw(fonts['tiny'], label) + 14
        credit_w = _tw(fonts['small'], 'EAS Station™  •  Emergency Alert System')
        # Skip the badge rather than crowd the brand credit on a narrow
        # canvas with a long "Issued/Expires" stamp already eating the
        # left side -- the timestamp text itself already conveys this.
        if footer_x + pill_w_est + 16 < layout.width - credit_w - 16:
            pill_h_target = _th(fonts['tiny'], 'Mg') + 6
            pill_y = fy + (layout.footer_h - pill_h_target) // 2
            _draw_pill(draw, fonts['tiny'], label, badge_style['fill'],
                      footer_x, pill_y, text_color=badge_style['text'],
                      pad_x=7, pad_y=3)

    # Footer attribution carries the trademark mark on the brand name —
    # mirrors the wordmark in the header band so a viewer who clipped
    # the screenshot to just the footer still sees the ™.
    credit = 'EAS Station™  •  Emergency Alert System'
    cy_pos = fy + (layout.footer_h - _th(fonts['small'], credit)) // 2
    draw.text((layout.width - _tw(fonts['small'], credit) - 12, cy_pos),
              credit, font=fonts['small'], fill=_TEXT_MUT)

    # ── Optional supersampled output ──────────────────────────────────────────
    # Upscale the composed card before rounding/encoding so the upload
    # carries more pixels than the platform displays — Facebook's JPEG
    # re-encode then lands on an image that gets downscaled on screen,
    # shrinking its artefacts below visibility.  Lanczos keeps text edges
    # smooth without ringing.
    try:
        out_scale = float(scale or 1.0)
    except (TypeError, ValueError):
        out_scale = 1.0
    out_scale = max(1.0, min(out_scale, 3.0))
    corner_r = layout.corner_r
    if out_scale > 1.0:
        img = img.resize(
            (int(round(layout.width * out_scale)),
             int(round(layout.height * out_scale))),
            Image.LANCZOS,
        )
        corner_r = int(round(corner_r * out_scale))

    # A thin inner shadow along the card's own edge so it reads as set into
    # a frame rather than a flat rectangle, without changing the finished
    # PNG's pixel dimensions (see _apply_card_lift's docstring for why a
    # real drop shadow, which needs space *outside* the card, isn't safe
    # here). Scales with corner_r so it stays proportionate at 2x/3x output.
    lift_width = max(4, int(round(6 * out_scale)))
    img = _apply_card_lift(img, corner_r, width=lift_width)

    # ── Round outer corners and serialise ────────────────────────────────────
    # Soft rounded corners across the whole share card — matches modern
    # feed cards and stops the image looking like a screenshot.  PNG keeps
    # the corner pixels fully transparent so renderers that respect alpha
    # show a true rounded shape; renderers that flatten get the matte
    # they composite against (usually white on social feeds).
    img_rounded = _round_image_corners(img, corner_r, bg=None)

    fmt = (image_format or 'png').strip().lower()
    buf = io.BytesIO()

    if fmt == 'webp':
        # ``method=4`` is a good balance between encode time and final
        # size; ``quality=92`` keeps the gradient header artefact-free
        # while still saving ~30% versus the equivalent PNG.  Pillow does
        # not add EXIF or timestamps to WebP by default, so no explicit
        # metadata stripping step is needed.
        img_rounded.save(buf, format='WEBP', quality=92, method=4)
        return buf.getvalue()

    # Default: PNG with minimal metadata.  Passing an explicit
    # ``pnginfo`` suppresses Pillow's default tIME chunk (which would
    # leak a server timestamp) and any inherited EXIF, while keeping a
    # small ``Software`` tag so exports remain auditable.  ``alert_id``
    # is included as a stable identifier so duplicate uploads can be
    # deduped without leaking PII.
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text('Software', 'EAS Station')
    alert_id = getattr(alert, 'id', None)
    if alert_id is not None:
        pnginfo.add_text('Source', f'alert/{alert_id}')

    img_rounded.save(buf, format='PNG', optimize=True, pnginfo=pnginfo)
    return buf.getvalue()
