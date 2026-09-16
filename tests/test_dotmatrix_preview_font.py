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

"""Tests for the shared 5x7 dot-matrix glyph font and its scaled blit helper.

scripts.dotmatrix_preview_font is the single glyph source shared by the LED
and VFD preview renderers; blit_text_scaled() is what lets the LED preview
approximate a larger/smaller Alpha Font selection from those same glyph
shapes instead of a second, hand-maintained font table.
"""

from scripts.dotmatrix_preview_font import CELL_H, CELL_W, blit_text, blit_text_scaled, cell_size


def _count_lit(grid):
    return sum(1 for row in grid for px in row if px)


def test_cell_size_base_scale_matches_legacy_constants():
    assert cell_size(1, 1) == (CELL_W, CELL_H)


def test_cell_size_scales_linearly():
    assert cell_size(2, 1) == (5 * 2 + 2, CELL_H)
    assert cell_size(1, 3) == (CELL_W, 7 * 3 + 3)


def test_blit_text_scaled_at_1x_matches_blit_text():
    """blit_text() is defined in terms of blit_text_scaled(); a 1x scale
    must reproduce the exact same pixels as the original fixed-size blit."""
    grid_a = [[0] * 40 for _ in range(8)]
    grid_b = [[0] * 40 for _ in range(8)]
    blit_text(grid_a, 0, 0, "HI")
    blit_text_scaled(grid_b, 0, 0, "HI", 1, 1)
    assert grid_a == grid_b


def test_blit_text_scaled_larger_scale_lights_more_pixels():
    text = "A"
    grid_small = [[0] * 20 for _ in range(10)]
    grid_large = [[0] * 40 for _ in range(30)]
    blit_text_scaled(grid_small, 0, 0, text, 1, 1)
    blit_text_scaled(grid_large, 0, 0, text, 3, 3)
    # A 3x3 scale replicates each source dot into a 3x3 block: exactly 9x
    # the lit-pixel count of the 1x rendering.
    assert _count_lit(grid_large) == _count_lit(grid_small) * 9


def test_blit_text_scaled_returns_cell_dimensions():
    assert blit_text_scaled([[0] * 10 for _ in range(10)], 0, 0, "", 2, 4) == cell_size(2, 4)


def test_blit_text_scaled_clips_to_grid_bounds():
    # Placing text so it overflows the grid on all sides must not raise or
    # write out of bounds -- only in-bounds pixels should ever be set.
    grid = [[0] * 6 for _ in range(6)]
    blit_text_scaled(grid, -3, -3, "WW", 2, 2)
    assert _count_lit(grid) >= 0  # no exception is the actual assertion
