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
"""

from __future__ import annotations

"""Tests for the Git Commit badge URL encoding in the footer.

This test verifies that the Git Commit badge displays correctly for both:
1. Actual git commit hashes (e.g., "07EF1E")
2. Dev build placeholder ("DEV BUILD")
"""

import re
from pathlib import Path


def _read_badge_sources() -> str:
    """Return the concatenated text of every template that participates in
    rendering the Git Commit badge.

    The badge logic was extracted into ``templates/partials/tech_stack_badges.html``
    so it could be shared as a single source of truth, but ``base.html`` still
    {% include %}s it. We search both files together so the legacy assertions
    keep passing regardless of which file currently owns the markup.
    """
    project_root = Path(__file__).resolve().parents[1]
    base_template = project_root / 'templates' / 'base.html'
    badges_partial = project_root / 'templates' / 'partials' / 'tech_stack_badges.html'

    assert base_template.exists(), f"base.html not found at {base_template}"
    assert badges_partial.exists(), (
        f"tech_stack_badges.html partial not found at {badges_partial}. "
        f"base.html includes this partial; it must exist."
    )

    return base_template.read_text() + "\n" + badges_partial.read_text()


def test_git_commit_badge_uses_url_encoding():
    """Verify the Git Commit badge uses proper URL encoding."""

    content = _read_badge_sources()

    # Check that the badge encoding uses both shields_escape AND urlencode
    pattern = r'{%\s*set\s+commit_badge_encoded\s*=\s*commit_badge_text\s*\|\s*shields_escape\s*\|\s*urlencode\s*%}'
    match = re.search(pattern, content)
    
    assert match, (
        "Git Commit badge must use both 'shields_escape' and 'urlencode' filters. "
        "Expected: {% set commit_badge_encoded = commit_badge_text | shields_escape | urlencode %}"
    )
    
    print("✓ Git Commit badge uses proper URL encoding")


def test_git_commit_badge_url_format():
    """Verify the Git Commit badge URL uses the encoded variable."""

    content = _read_badge_sources()

    # Check that the badge URL uses commit_badge_encoded
    pattern = r'https://img\.shields\.io/badge/Git%20Commit-{{\s*commit_badge_encoded\s*}}-181717'
    match = re.search(pattern, content)
    
    assert match, (
        "Git Commit badge URL must use {{ commit_badge_encoded }} variable. "
        "Expected format: https://img.shields.io/badge/Git%20Commit-{{ commit_badge_encoded }}-181717"
    )
    
    print("✓ Git Commit badge URL format is correct")


def test_git_commit_badge_logic():
    """Verify the Git Commit badge displays commit hash or 'DEV BUILD' fallback."""

    content = _read_badge_sources()

    # Check that the template has logic to fall back to 'dev build'
    has_dev_build_fallback = re.search(
        r"{%\s*if\s+not\s+commit_label\s+or\s+commit_label\|lower\s*==\s*'unknown'\s*%}"
        r".*?"
        r"{%\s*set\s+commit_label\s*=\s*'dev build'\s*%}",
        content,
        re.DOTALL
    )
    
    assert has_dev_build_fallback, (
        "Template must have fallback logic to show 'dev build' when commit is unknown"
    )
    
    # Check that the label is converted to uppercase
    has_uppercase = re.search(
        r'{%\s*set\s+commit_badge_text\s*=\s*commit_label\s*\|\s*upper\s*%}',
        content
    )
    
    assert has_uppercase, (
        "Template must convert commit_label to uppercase for consistency"
    )
    
    print("✓ Git Commit badge logic handles both commit hash and fallback correctly")


def test_shields_escape_and_urlencode_behavior():
    """Document and verify the expected encoding behavior."""
    
    # Test the shields_escape logic
    def shields_escape(text):
        if not text:
            return text
        # Replace underscores first to avoid double-escaping
        escaped = str(text).replace('_', '__')
        # Replace dashes with double dashes
        escaped = escaped.replace('-', '--')
        return escaped
    
    # Test urlencode (using urllib.parse.quote behavior)
    import urllib.parse
    
    # Test case 1: DEV BUILD (with space)
    text1 = "DEV BUILD"
    escaped1 = shields_escape(text1)
    encoded1 = urllib.parse.quote(escaped1, safe='')
    
    assert escaped1 == "DEV BUILD", "shields_escape should not modify spaces"
    assert encoded1 == "DEV%20BUILD", "urlencode should convert spaces to %20"
    
    # Test case 2: Commit hash (no special chars)
    text2 = "07EF1E"
    escaped2 = shields_escape(text2)
    encoded2 = urllib.parse.quote(escaped2, safe='')
    
    assert escaped2 == "07EF1E", "shields_escape should not modify alphanumeric"
    assert encoded2 == "07EF1E", "urlencode should not modify alphanumeric"
    
    # Test case 3: Hypothetical commit with dash
    text3 = "A7B-123"
    escaped3 = shields_escape(text3)
    encoded3 = urllib.parse.quote(escaped3, safe='')
    
    assert escaped3 == "A7B--123", "shields_escape should double dashes"
    assert encoded3 == "A7B--123", "urlencode should preserve double dashes"
    
    print("✓ Encoding behavior verified for all cases")


if __name__ == "__main__":
    print("Running Git Commit badge tests...\n")
    
    try:
        test_git_commit_badge_uses_url_encoding()
        test_git_commit_badge_url_format()
        test_git_commit_badge_logic()
        test_shields_escape_and_urlencode_behavior()
        
        print("\n✅ All Git Commit badge tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
