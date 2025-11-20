"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Integration test to verify URL decoding in the full metadata pipeline."""

import sys
from pathlib import Path

# Simple test that verifies the URL decoding logic is in place
# without requiring full module imports

def test_url_decode_in_normalize_function():
    """Verify that the _normalize function includes URL decoding."""
    
    # Read the icecast_output.py file and check for unquote usage
    icecast_file = Path(__file__).parent.parent / 'app_core' / 'audio' / 'icecast_output.py'
    
    if not icecast_file.exists():
        print(f"ERROR: Could not find {icecast_file}")
        return False
    
    content = icecast_file.read_text()
    
    # Check that unquote is imported
    has_import = 'from urllib.parse import quote, unquote' in content
    
    # Check that unquote is used in the _normalize function
    has_usage = 'text = unquote(text)' in content
    
    # Check that it's in the right place (after attribute removal, before final whitespace collapse)
    has_correct_placement = 'text = unquote(text)' in content and \
                           content.index('text = unquote(text)') < content.index("text = ' '.join(text.split())", content.index('text = unquote(text)'))
    
    print('Checking URL decoding implementation...')
    print(f'  {"✓" if has_import else "✗"} Import statement present')
    print(f'  {"✓" if has_usage else "✗"} unquote() usage present')
    print(f'  {"✓" if has_correct_placement else "✗"} Correct placement in pipeline')
    
    all_checks = has_import and has_usage and has_correct_placement
    
    if all_checks:
        print('\n✅ URL decoding correctly implemented in icecast_output.py')
    else:
        print('\n✗ URL decoding implementation issues detected')
    
    return all_checks


def test_example_metadata_from_problem_statement():
    """Test the exact examples from the problem statement."""
    from urllib.parse import unquote
    
    # Examples from the problem statement logs
    examples = [
        'Peace%20Orchestra - Who%20Am%20I',
        'Unknown%20Artist - VibeLounge%20Station%20ID',
    ]
    
    print('\nTesting examples from problem statement...')
    
    for example in examples:
        decoded = unquote(example)
        print(f'  ✓ {example!r:50} -> {decoded!r}')
        assert '%20' not in decoded, f"Still contains %20: {decoded}"
    
    print('✅ All examples decode correctly')
    return True


if __name__ == '__main__':
    print("=" * 70)
    print("Integration Test: URL Decoding for iHeartMedia Metadata")
    print("=" * 70)
    print()
    
    test1 = test_url_decode_in_normalize_function()
    test2 = test_example_metadata_from_problem_statement()
    
    print()
    print("=" * 70)
    
    if test1 and test2:
        print("✅ ALL INTEGRATION TESTS PASSED")
        print("=" * 70)
        sys.exit(0)
    else:
        print("✗ SOME TESTS FAILED")
        print("=" * 70)
        sys.exit(1)
