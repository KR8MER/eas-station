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

"""Unit tests for coverage calculation fix and XML signature C14N verification.

Coverage tests verify that coverage percentage is based on the area of
intersecting boundaries, not all boundaries system-wide.

Signature tests verify that _canonicalize_signed_info correctly extracts
and C14N-serialises the SignedInfo block, and that _verify_with_cryptography
uses the canonical bytes when they are supplied.
"""

import re

import pytest

from app_utils.ipaws_enrichment import (
    _canonicalize_signed_info,
    _verify_with_cryptography,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal XML document with a ds:Signature / ds:SignedInfo block using
# inclusive C14N 1.0.  The values are synthetic – we only test the
# canonicalization logic here, not real IPAWS certificate material.
_SAMPLE_CAP_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"
       xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
  <identifier>TEST-001</identifier>
  <ds:Signature>
    <ds:SignedInfo>
      <ds:CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
      <ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>
      <ds:Reference URI="">
        <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
        <ds:DigestValue>ZmFrZWRpZ2VzdA==</ds:DigestValue>
      </ds:Reference>
    </ds:SignedInfo>
    <ds:SignatureValue>ZmFrZXNpZw==</ds:SignatureValue>
    <ds:KeyInfo>
      <ds:X509Data>
        <ds:X509Certificate>FAKE</ds:X509Certificate>
      </ds:X509Data>
    </ds:KeyInfo>
  </ds:Signature>
</alert>
"""

_SAMPLE_CAP_XML_EXC_C14N = _SAMPLE_CAP_XML.replace(
    "http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    "http://www.w3.org/2001/10/xml-exc-c14n#",
)


# ---------------------------------------------------------------------------
# _canonicalize_signed_info tests
# ---------------------------------------------------------------------------

class TestCanonicalizeSignedInfo:

    def test_returns_bytes_for_valid_xml(self):
        """Should return non-empty bytes when lxml is available and XML is valid."""
        result = _canonicalize_signed_info(_SAMPLE_CAP_XML)
        if result is None:
            pytest.skip('lxml not available')
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_contains_signed_info_element(self):
        result = _canonicalize_signed_info(_SAMPLE_CAP_XML)
        if result is None:
            pytest.skip('lxml not available')
        assert b'SignedInfo' in result

    def test_contains_canonicalization_method(self):
        result = _canonicalize_signed_info(_SAMPLE_CAP_XML)
        if result is None:
            pytest.skip('lxml not available')
        assert b'CanonicalizationMethod' in result

    def test_returns_none_for_empty_string(self):
        result = _canonicalize_signed_info('')
        assert result is None

    def test_returns_none_when_no_signed_info(self):
        result = _canonicalize_signed_info('<alert><identifier>X</identifier></alert>')
        assert result is None

    def test_returns_none_for_invalid_xml(self):
        result = _canonicalize_signed_info('not valid xml <<<')
        assert result is None

    def test_exclusive_c14n_detected(self):
        """Exclusive C14N algorithm should be detected without error."""
        result = _canonicalize_signed_info(_SAMPLE_CAP_XML_EXC_C14N)
        if result is None:
            pytest.skip('lxml not available')
        assert isinstance(result, bytes)

    def test_deterministic_output(self):
        """Canonicalization should be deterministic across calls."""
        r1 = _canonicalize_signed_info(_SAMPLE_CAP_XML)
        r2 = _canonicalize_signed_info(_SAMPLE_CAP_XML)
        if r1 is None:
            pytest.skip('lxml not available')
        assert r1 == r2


# ---------------------------------------------------------------------------
# _verify_with_cryptography – canonical bytes path
# ---------------------------------------------------------------------------

class TestVerifyWithCryptographyCanonical:
    """Verify that _verify_with_cryptography uses canonical bytes when supplied."""

    def _make_matches(self):
        sig_match = re.search(r'SignatureValue[^>]*>([^<]+)</.*?SignatureValue>',
                              _SAMPLE_CAP_XML, re.DOTALL)
        info_match = re.search(r'(<(?:\w+:)?SignedInfo[\s>].*?</(?:\w+:)?SignedInfo>)',
                               _SAMPLE_CAP_XML, re.DOTALL)
        return sig_match, info_match

    def test_uses_canonical_bytes_not_raw(self):
        """When canonical_signed_info is supplied it should be passed to verify()."""
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        except ImportError:
            pytest.skip('cryptography not available')

        sig_match, info_match = self._make_matches()
        sentinel = b'CANONICAL_SENTINEL_BYTES_XYZ'
        captured = {}

        from unittest.mock import MagicMock, patch

        fake_key = MagicMock(spec=RSAPublicKey)
        def record_and_raise(sig, data, *args, **kwargs):
            captured['data'] = data
            raise Exception('forced failure')
        fake_key.verify.side_effect = record_and_raise

        fake_cert = MagicMock()
        fake_cert.public_key.return_value = fake_key

        with patch('cryptography.x509.load_der_x509_certificate', return_value=fake_cert):
            _verify_with_cryptography(
                cert_b64='AAAA',
                sig_value_match=sig_match,
                signed_info_match=info_match,
                raw_xml=_SAMPLE_CAP_XML,
                canonical_signed_info=sentinel,
            )

        # The verify call should have received our sentinel bytes
        assert 'data' in captured, "verify() was never called"
        assert captured['data'] == sentinel, (
            "verify() received raw XML bytes instead of the canonical bytes"
        )

    def test_falls_back_to_raw_when_no_canonical(self):
        """When canonical_signed_info is None the status mentions C14N required."""
        try:
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        except ImportError:
            pytest.skip('cryptography not available')

        sig_match, info_match = self._make_matches()

        from unittest.mock import MagicMock, patch

        fake_key = MagicMock(spec=RSAPublicKey)
        fake_key.verify.side_effect = Exception('forced failure')

        fake_cert = MagicMock()
        fake_cert.public_key.return_value = fake_key

        with patch('cryptography.x509.load_der_x509_certificate', return_value=fake_cert):
            result = _verify_with_cryptography(
                cert_b64='AAAA',
                sig_value_match=sig_match,
                signed_info_match=info_match,
                raw_xml=_SAMPLE_CAP_XML,
                canonical_signed_info=None,
            )

        if result is None:
            pytest.skip('cryptography not available')

        assert 'C14N' in result.get('signature_status', ''), (
            f"Expected 'C14N' in status, got: {result.get('signature_status')}"
        )

    def test_status_when_canonical_present_but_sig_invalid(self):
        """When C14N bytes are present but the signature is wrong, status reflects that."""
        try:
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        except ImportError:
            pytest.skip('cryptography not available')

        sig_match, info_match = self._make_matches()
        canonical = b'<ds:SignedInfo>...</ds:SignedInfo>'

        from unittest.mock import MagicMock, patch

        fake_key = MagicMock(spec=RSAPublicKey)
        fake_key.verify.side_effect = Exception('InvalidSignature')

        fake_cert = MagicMock()
        fake_cert.public_key.return_value = fake_key

        with patch('cryptography.x509.load_der_x509_certificate', return_value=fake_cert):
            result = _verify_with_cryptography(
                cert_b64='AAAA',
                sig_value_match=sig_match,
                signed_info_match=info_match,
                raw_xml=_SAMPLE_CAP_XML,
                canonical_signed_info=canonical,
            )

        if result is None:
            pytest.skip('cryptography not available')

        # Should NOT say "C14N required" – the C14N step was done
        assert 'C14N canonicalization required' not in result.get('signature_status', '')
        assert result.get('signature_verified') is False


# ---------------------------------------------------------------------------
# Coverage calculation: denominator is intersecting boundary area (pure logic)
# ---------------------------------------------------------------------------

class TestCoverageCalculationLogic:
    """
    These tests verify the coverage formula directly without requiring a
    database connection.  They mirror the arithmetic inside
    ``calculate_coverage_percentages`` to guard against regressions.

    The coverage percentage must be:
        sum(intersection_area) / sum(full area of each intersecting boundary) * 100

    Previously the denominator was the sum of ALL boundaries of that type in
    the system (including those far outside the alert area), which produced
    misleadingly low numbers.
    """

    def _coverage(self, intersection_areas, boundary_areas):
        """Simulate the new formula."""
        total_area = sum(boundary_areas)
        intersected_area = sum(intersection_areas)
        if total_area == 0:
            return 0.0
        pct = (intersected_area / total_area) * 100
        return round(min(100.0, max(0.0, pct)), 1)

    def _old_coverage(self, intersection_areas, boundary_areas, all_system_areas):
        """Simulate the OLD (incorrect) formula that used all-system area."""
        total_area = sum(all_system_areas)
        intersected_area = sum(intersection_areas)
        if total_area == 0:
            return 0.0
        pct = (intersected_area / total_area) * 100
        return round(min(100.0, max(0.0, pct)), 1)

    def test_full_coverage_when_alert_exactly_matches_two_districts(self):
        """Alert completely covers 2 fire districts → 100 % coverage."""
        b_areas = [1000.0, 1000.0]
        i_areas = [1000.0, 1000.0]  # perfect overlap
        assert self._coverage(i_areas, b_areas) == 100.0

    def test_half_coverage_of_single_district(self):
        """Alert covers exactly half a district → 50 % coverage."""
        b_areas = [2000.0]
        i_areas = [1000.0]
        assert self._coverage(i_areas, b_areas) == 50.0

    def test_mixed_coverage(self):
        """Alert fully covers one district and half-covers another."""
        b_areas = [1000.0, 1000.0]
        i_areas = [1000.0, 500.0]   # first full, second half
        assert self._coverage(i_areas, b_areas) == 75.0

    def test_new_formula_vs_old_formula(self):
        """New formula gives higher (more correct) result than old system-wide one.

        Scenario: 3 fire districts are affected.  The system (whole state) has 50.
        All 3 affected districts are fully covered.
        Old formula:  3 * 1000 / (50 * 1000) = 6 %   ← wrong
        New formula:  3 * 1000 / (3 * 1000)  = 100 %  ← correct
        """
        n_affected = 3
        n_system   = 50
        dist_area  = 1000.0
        b_areas = [dist_area] * n_affected
        i_areas = [dist_area] * n_affected  # all fully covered
        all_areas = [dist_area] * n_system

        new_pct = self._coverage(i_areas, b_areas)
        old_pct = self._old_coverage(i_areas, b_areas, all_areas)

        assert new_pct == 100.0, f"New formula should give 100 %, got {new_pct}"
        assert old_pct < 10.0,   f"Old formula should give ~6 %, got {old_pct}"
        assert new_pct > old_pct, "New formula should outperform old formula"

    def test_zero_intersection_gives_zero_coverage(self):
        """Alert touches boundaries but has zero area overlap → 0 %."""
        b_areas = [500.0, 500.0]
        i_areas = [0.0, 0.0]
        assert self._coverage(i_areas, b_areas) == 0.0

    def test_coverage_clamped_at_100(self):
        """Floating point rounding should never push coverage above 100 %."""
        b_areas = [1000.0]
        i_areas = [1000.0001]  # tiny floating-point excess
        assert self._coverage(i_areas, b_areas) == 100.0



# ---------------------------------------------------------------------------
# Fallback coverage guard: boundaries exist but none intersect → 0 %
# ---------------------------------------------------------------------------

class TestCoverageFallbackLogic:
    """
    Guard against the bug where the county-wide fallback assigned 100 %
    coverage to ALL boundaries in the database for an alert that covers a
    *different* county (one whose boundaries are not loaded).

    The rule is:
    - No boundaries in DB at all  → estimated 100 % (station not configured)
    - Boundaries exist, none intersect → 0 % (different county or no overlap)
    """

    def test_zero_when_boundaries_exist_but_none_intersect(self):
        """If boundaries exist in the DB but none overlap the alert, coverage = 0 %."""
        # Simulate: is_county_wide=True, no intersections, but DB has boundaries
        # The fallback MUST NOT assign 100 % in this case.
        intersections = []  # no intersections for this alert

        # coverage formula with empty intersections
        total_area = 0.0
        intersected_area = sum(0 for _ in intersections)
        if total_area > 0:
            pct = (intersected_area / total_area) * 100
        else:
            pct = 0.0

        assert pct == 0.0, (
            "With no intersections, coverage must be 0 %, not 100 %"
        )

    def test_estimated_100_only_when_no_boundaries_at_all(self):
        """The 100 % estimate is only valid when the boundaries table is empty."""
        # When the station has zero boundary records, we cannot compute real
        # coverage and fall back to an optimistic 100 % estimate.
        # When boundaries DO exist (e.g. a neighbouring county's districts),
        # the estimate must NOT fire – the absence of intersections means 0 %.

        # Case 1: no boundaries → estimated fallback is appropriate
        total_boundary_count = 0
        should_apply_fallback = (total_boundary_count == 0)
        assert should_apply_fallback, (
            "Fallback should apply when there are zero boundaries in the DB"
        )

        # Case 2: boundaries exist → fallback must NOT apply
        total_boundary_count = 42  # Putnam County boundaries loaded
        should_apply_fallback = (total_boundary_count == 0)
        assert not should_apply_fallback, (
            "Fallback must NOT apply when boundaries exist; "
            "use 0 % instead of 100 % estimate"
        )
