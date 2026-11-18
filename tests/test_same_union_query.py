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

"""Tests for app_core.county_boundaries.build_same_union_query.

Regression for the 2026-11-17 National Periodic Test: its only SAME code,
000000 ("entire United States"), ends in "000" and was read as statewide
code for the nonexistent state FIPS "00", so the alert got no geometry and
never appeared on the map.
"""

from app_core.county_boundaries import NATIONWIDE_SAME_CODE, build_same_union_query


def test_nationwide_code_selects_every_county():
    sql, params = build_same_union_query([NATIONWIDE_SAME_CODE])
    assert params == {}
    assert "WHERE geom IS NOT NULL" in sql
    assert "statefp" not in sql and "geoid" not in sql
    assert "ST_SimplifyPreserveTopology" in sql


def test_nationwide_wins_over_other_codes():
    sql, params = build_same_union_query(["039069", "000000", "039000"])
    assert params == {}
    assert "statefp" not in sql


def test_statewide_code_maps_to_state_fips():
    sql, params = build_same_union_query(["039000"])
    assert params == {"state_fps": ["39"]}
    assert "statefp = ANY(:state_fps)" in sql
    assert "ST_SimplifyPreserveTopology" not in sql


def test_county_code_drops_only_one_leading_zero():
    _, params = build_same_union_query(["001001", "039069"])
    assert params == {"geoids": ["01001", "39069"]}


def test_mixed_county_and_statewide():
    sql, params = build_same_union_query(["039069", "018000"])
    assert params == {"geoids": ["39069"], "state_fps": ["18"]}
    assert " OR " in sql


def test_unusable_codes_return_none():
    assert build_same_union_query([]) is None
    assert build_same_union_query(None) is None
    assert build_same_union_query(["39069", "ABCDEF", 39069, "0390690"]) is None
