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

"""
Test to verify the URL decoding logic works correctly in the normalization pipeline.
This test simulates the metadata flow without requiring full module initialization.
"""

from urllib.parse import unquote
import re


def normalize_metadata_text(value):
    """
    Simulates the _normalize function from icecast_output.py
    to verify the URL decoding logic works correctly.
    """
    if value is None:
        return None
    
    text = str(value).strip()
    if not text:
        return None
    
    # Clean up metadata that contains XML/JSON attributes
    text_match = re.search(r'text="([^"]+)"', text)
    if text_match:
        text = text_match.group(1)
    elif 'title="' in text:
        title_match = re.search(r'title="([^"]+)"', text)
        if title_match:
            text = title_match.group(1)
    elif 'song="' in text:
        song_match = re.search(r'song="([^"]+)"', text)
        if song_match:
            text = song_match.group(1)
    
    # Remove remaining XML-like attributes
    text = re.sub(r'\s+\w+="[^"]*"', '', text)
    text = re.sub(r"\s+\w+='[^']*'", '', text)
    text = re.sub(r'\s+\w+=\S+', '', text)
    
    # Decode URL-encoded characters (this is the new fix)
    try:
        text = unquote(text)
    except Exception:
        pass
    
    # Collapse extraneous whitespace (must happen AFTER URL decoding)
    text = ' '.join(text.split())
    
    return text or None


def test_metadata_normalization_pipeline():
    """Test the full metadata normalization pipeline with URL decoding."""
    
    test_cases = [
        # iHeartMedia examples with URL encoding
        {
            'input': 'Peace%20Orchestra - Who%20Am%20I',
            'expected': 'Peace Orchestra - Who Am I',
            'description': 'URL-encoded artist and title from iHeartMedia'
        },
        {
            'input': 'Unknown%20Artist - VibeLounge%20Station%20ID',
            'expected': 'Unknown Artist - VibeLounge Station ID',
            'description': 'URL-encoded station ID from iHeartMedia'
        },
        {
            'input': 'Unknown%20Artist',
            'expected': 'Unknown Artist',
            'description': 'URL-encoded artist only'
        },
        
        # Normal metadata without encoding
        {
            'input': 'Morgan Wallen - Just In Case',
            'expected': 'Morgan Wallen - Just In Case',
            'description': 'Normal metadata without URL encoding'
        },
        {
            'input': 'Spot Block End',
            'expected': 'Spot Block End',
            'description': 'Simple text without encoding'
        },
        
        # Metadata with XML attributes AND URL encoding (complex case)
        {
            'input': 'Artist%20Name - text="Song%20Title" song_spot="M" MediaBaseId="123"',
            'expected': 'Song Title',  # XML extraction gets the text attribute value
            'description': 'XML attributes with URL-encoded values'
        },
        
        # Edge cases
        {
            'input': 'Song%20With%20Multiple%20%20Spaces',
            'expected': 'Song With Multiple Spaces',
            'description': 'Multiple encoded spaces that should collapse'
        },
        {
            'input': 'Artist%26Band - Song%2FTitle',
            'expected': 'Artist&Band - Song/Title',
            'description': 'URL-encoded special characters'
        },
    ]
    
    print("=" * 80)
    print("Testing Metadata Normalization Pipeline with URL Decoding")
    print("=" * 80)
    print()
    
    all_passed = True
    
    for i, test_case in enumerate(test_cases, 1):
        input_val = test_case['input']
        expected = test_case['expected']
        description = test_case['description']
        
        result = normalize_metadata_text(input_val)
        
        passed = result == expected
        status = '✓' if passed else '✗'
        
        print(f"Test {i}: {description}")
        print(f"  Input:    {input_val!r}")
        print(f"  Expected: {expected!r}")
        print(f"  Result:   {result!r}")
        print(f"  Status:   {status} {'PASS' if passed else 'FAIL'}")
        print()
        
        if not passed:
            all_passed = False
    
    print("=" * 80)
    
    if all_passed:
        print("✅ ALL PIPELINE TESTS PASSED")
        return True
    else:
        print("✗ SOME PIPELINE TESTS FAILED")
        return False


if __name__ == '__main__':
    import sys
    success = test_metadata_normalization_pipeline()
    sys.exit(0 if success else 1)
