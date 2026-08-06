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

"""
Alert share-image renderer.

Generates a social-ready PNG for a given CAP alert containing the event
header, a map inset of the affected area, and information panels for
threats, coverage, affected areas, headline, description and safety
instructions.

Operator-only fields (VTAC strings, issuing-office block) are
intentionally omitted - they're technical noise for social sharing and
previously crowded out the readable copy.

The map tile layer is fetched live from OpenStreetMap.  If tiles are
unavailable (network timeout, offline environment, ...) the map area is
replaced with a plain dark background; all data cards are unaffected.

Usage::

    from app_utils.image_export import generate_alert_image
    png_bytes = generate_alert_image(alert, coverage_data, ipaws_data, location_settings)

This package was split out of the former single-file
``app_utils/image_export.py``. The layering is one-directional:

    logo        (leaf - no package deps)
    layout      (leaf - no package deps)
    palette     (leaf - no package deps)
    fonts       (leaf - no package deps)
    text        (leaf - no package deps)
    icons       (leaf - no package deps)
    theme       palette
    drawing     fonts, palette
    weather_fx  drawing, layout, theme
    tiles       layout
    maps        fonts, layout, palette, theme, tiles
    panels      drawing, fonts, icons, palette, text
    render      drawing, fonts, layout, logo, maps, palette, panels, text, theme, weather_fx

Every name the single-file module exposed is re-exported here, so
``from app_utils.image_export import <anything>`` keeps working. Import
from the submodules directly in new code.
"""


import logging

# The single-file module exposed a module-level ``logger``; keep the name so
# anything that reached for or patched it still resolves. Each submodule that
# actually logs has its own logger under its own name.
logger = logging.getLogger(__name__)

from .logo import (  # noqa: E402,F401
    _LOGO_CACHE, _LOGO_PATH, _load_logo,
)

from .layout import (  # noqa: F401
    BODY_H, CARD_CORNER_R, CORNER_R, FB_HEIGHT, FB_WIDTH, FOOTER_H,
    HEADER_H, INFO_W, INFO_X, MAP_CORNER_R, MAP_H, MAP_W, TILE_SIZE,
    _LAYOUTS, _LAYOUT_LANDSCAPE, _LAYOUT_PORTRAIT, _LAYOUT_SQUARE,
    _LAYOUT_STORY, _Layout,
)

from .palette import (  # noqa: F401
    WHITE, _BG, _CARD, _DIVIDER, _PANEL, _SECTION_BG, _SEVERITY, _STRIP,
    _TEXT, _TEXT_MUT, _TEXT_SEC, _THREAT_CLR, _darken, _pct_bar_color,
)

from .theme import (  # noqa: F401
    _SEVERITY_HEAT, _THEMES, _THEME_DEFAULT, _TIER_HEAT, _TIER_STYLES,
    _Theme, _apply_urgency_to_theme, _resolve_theme, _resolve_tier,
    _soften, _theme_supports_storm_motion, _urgency_heat,
)

from .fonts import (  # noqa: F401
    _FONT_BOLD_PATHS, _FONT_CACHE, _FONT_REG_PATHS, _TITLE_FONT_CACHE,
    _load_font, _load_fonts, _th, _title_font_for, _truncate, _tw,
)

from .text import (  # noqa: F401
    _LIST_STOPWORDS, _LIST_TRIGGER_RE, _PRESERVE_ACRONYMS, _US_STATES,
    _US_STATE_CODES, _humanize_caps_text, _is_shouting, _resolve_local_tz,
    _short_local_dt,
)

from .drawing import (  # noqa: F401
    _card_row, _composite, _draw_pill, _round_image_corners,
    _section_header,
)

from .weather_fx import (  # noqa: F401
    _PARTICLE_FNS, _draw_embers, _draw_haze, _draw_lightning_bolts,
    _draw_rain, _draw_snow, _draw_sun_rays, _draw_themed_header,
    _draw_wind_streaks, _lb_branches, _lb_render_polyline, _lb_trunk,
)

from .tiles import (  # noqa: F401
    _TILE_CACHE, _TILE_CACHE_LOCK, _TILE_CACHE_MAX,
    _TILE_DISK_CACHE_DIR_DEFAULT, _best_zoom, _fetch_tile, _geojson_bbox,
    _geojson_centroid, _lat_to_ty, _lon_to_tx, _tile_cache_clear,
    _tile_cache_get, _tile_cache_put, _tile_disk_cache_dir,
    _tile_disk_get, _tile_disk_path, _tile_disk_put,
)

from .maps import (  # noqa: F401
    _SCALE_BAR_MILES, _alert_same_codes, _draw_scale_bar,
    _draw_storm_track, _fetch_county_outlines, _fetch_same_union_geom,
    _nice_scale_miles, _render_map,
)

from .icons import (  # noqa: F401
    _ICON_FN, _icon_hail, _icon_tornado, _icon_wind,
)

from .panels import (  # noqa: F401
    _INSTR_ACCENT, _draw_areas, _draw_compass_section, _draw_coverage,
    _draw_description, _draw_instruction, _draw_nws_headline,
    _draw_threats, _wrap_text,
)

from .render import (  # noqa: F401
    generate_alert_image,
)


__all__ = ['generate_alert_image']
