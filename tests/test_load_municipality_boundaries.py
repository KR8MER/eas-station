"""Regression tests for app_core/municipality_boundaries.py's FIPS-code
normalization -- the bug this guards against: SAME codes are 6-digit PSSCCC
(portion digit + state + county, see app_utils/fips_codes.py) while the
Census shapefile's own STATEFP+COUNTYFP is 5-digit SSCCC. Comparing them
without normalizing silently matched nothing (confirmed live: 0 inserted,
36354 "outside scope" against a real Ohio county) before this fix.
"""

from __future__ import annotations

from app_core.municipality_boundaries import county_fips5


class TestCountyFips5:
    def test_six_digit_same_code_with_zero_portion(self):
        # PSSCCC with portion digit 0 (whole county) -- the common case.
        assert county_fips5("039137") == "39137"

    def test_six_digit_same_code_with_nonzero_portion(self):
        # A sub-county portion digit still refers to the same county.
        assert county_fips5("139137") == "39137"

    def test_five_digit_plain_fips_unpadded(self):
        assert county_fips5("39137") == "39137"

    def test_matches_shapefile_county_geoid_format(self):
        # This is the actual bug: the normalized value must equal
        # STATEFP+COUNTYFP as read from the shapefile, e.g. "39" + "137".
        statefp, countyfp = "39", "137"
        county_geoid = f"{statefp}{countyfp}"
        assert county_fips5("039137") == county_geoid

    def test_strips_whitespace_and_non_digits(self):
        assert county_fips5(" 039137 ") == "39137"
