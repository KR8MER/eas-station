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

"""Simple test to verify URL decoding logic without full module imports."""

from urllib.parse import unquote


def test_url_decode_metadata():
    """Test that URL-encoded metadata strings are properly decoded."""
    
    # Test cases from the problem statement
    test_cases = [
        # iHeartMedia stream examples
        ('Peace%20Orchestra - Who%20Am%20I', 'Peace Orchestra - Who Am I'),
        ('Unknown%20Artist - VibeLounge%20Station%20ID', 'Unknown Artist - VibeLounge Station ID'),
        ('Unknown%20Artist', 'Unknown Artist'),
        ('VibeLounge%20Station%20ID', 'VibeLounge Station ID'),
        
        # Normal metadata (should pass through unchanged)
        ('Morgan Wallen - Just In Case', 'Morgan Wallen - Just In Case'),
        ('Spot Block End', 'Spot Block End'),
        
        # Other URL-encoded characters
        ('Artist%20%26%20Band', 'Artist & Band'),  # %26 is &
        ('Song%2FTitle', 'Song/Title'),  # %2F is /
        ('100%25%20Perfect', '100% Perfect'),  # %25 is %
    ]
    
    print('Testing URL decoding for Icecast metadata...')
    all_passed = True
    
    for encoded, expected in test_cases:
        decoded = unquote(encoded)
        status = '✓' if decoded == expected else '✗'
        print(f'{status} {encoded!r:60} -> {decoded!r}')
        
        if decoded != expected:
            print(f'   ERROR: Expected {expected!r}')
            all_passed = False
    
    assert all_passed, "Some URL decoding tests failed"
    print('\n✅ All URL decoding tests passed!')


if __name__ == '__main__':
    test_url_decode_metadata()
