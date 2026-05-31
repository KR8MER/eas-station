"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station

Tests for structural (NRSC-4-B) decode confidence scoring.

These cover the fix for the long-standing "every alert shows ~50% confidence
even on a perfect decode" problem: the raw per-bit FSK tone margin is
structurally floored near 0.5 because the SAME mark/space tones are only one
baud apart, so the headline confidence is instead derived from how many SAME
header fields independently parse to spec-valid values.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_utils.eas import describe_same_header, score_decode_confidence

# A clean, fully NRSC-4-B-compliant header (the everyday "good decode" case).
VALID_HEADER = "ZCZC-WXR-TOR-039137+0030-3662322-WTHI/TV-"


def test_valid_header_reads_high_despite_floored_signal_margin():
    """A perfect decode must NOT report ~50% just because the tone margin does."""
    fields = describe_same_header(VALID_HEADER)
    assert fields.get("nrsc4b_compliant") is True

    # The raw per-bit margin saturates near 0.5 on real EAS audio; the headline
    # confidence should reflect the verified structure instead.
    scored = score_decode_confidence(fields, signal_margin=0.52)
    assert scored >= 0.95
    # Sanity: dramatically higher than the raw margin it replaces.
    assert scored > 0.52 + 0.30


def test_weak_signal_valid_header_still_reads_high():
    """A spec-valid header with weak audio is still a real alert and must not be
    suppressed by the forward gate."""
    fields = describe_same_header(VALID_HEADER)
    scored = score_decode_confidence(fields, signal_margin=0.20)
    assert scored >= 0.95


def test_cleaner_audio_ranks_slightly_higher_among_valid_decodes():
    fields = describe_same_header(VALID_HEADER)
    low = score_decode_confidence(fields, signal_margin=0.30)
    high = score_decode_confidence(fields, signal_margin=0.90)
    assert high > low


def test_garbled_header_is_not_inflated_above_signal_margin():
    """A header whose fields do not validate must never read higher than the raw
    signal margin — the structure cannot vouch for a bad decode."""
    fields = describe_same_header("ZCZC-XXX-ZZZ-999999+9999-9999999-")
    assert fields.get("nrsc4b_compliant") is False
    for margin in (0.20, 0.55, 0.80):
        assert score_decode_confidence(fields, signal_margin=margin) <= margin + 1e-9


def test_empty_fields_fall_back_to_signal_margin():
    """EOM (NNNN) and unparseable headers produce no fields; the raw margin is
    the only evidence available and must pass through unchanged."""
    assert score_decode_confidence({}, signal_margin=0.41) == 0.41
    assert score_decode_confidence(None, signal_margin=0.41) == 0.41


def test_confidence_is_clamped_to_unit_interval():
    fields = describe_same_header(VALID_HEADER)
    assert 0.0 <= score_decode_confidence(fields, signal_margin=5.0) <= 1.0
    assert 0.0 <= score_decode_confidence(fields, signal_margin=-3.0) <= 1.0
    # Non-numeric margin must not raise.
    assert 0.0 <= score_decode_confidence({}, signal_margin="not-a-number") <= 1.0  # type: ignore[arg-type]


def test_partial_structure_below_half_falls_back_to_margin():
    """When fewer than half the fields validate, trust the raw margin only."""
    # Valid originator/event but everything else garbage -> < 3 of 6 valid.
    fields = describe_same_header("ZCZC-WXR-TOR-ZZZZZZ+ZZZZ-ZZZZZZZ-")
    passed = sum(
        1
        for flag in (
            "nrsc4b_valid_originator",
            "nrsc4b_valid_event",
            "nrsc4b_valid_purge",
            "nrsc4b_valid_issue_time",
            "nrsc4b_valid_location_count",
            "nrsc4b_valid_station_id",
        )
        if fields.get(flag)
    )
    assert passed < 3
    assert score_decode_confidence(fields, signal_margin=0.33) == 0.33
