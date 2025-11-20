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

"""Tests for URL-encoded metadata decoding in Icecast output."""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.icecast_output import IcecastConfig, IcecastStreamer


class _DummyAudioSource:
    """Dummy audio source for testing."""
    
    def get_audio_chunk(self, timeout=0.1):  # pragma: no cover - stub
        return None
    
    metrics = mock.MagicMock()


def test_url_encoded_metadata_is_decoded():
    """Test that URL-encoded metadata (e.g., %20) is properly decoded."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing URL decoding',
        admin_user='admin',
        admin_password='admin',
    )
    
    audio_source = _DummyAudioSource()
    streamer = IcecastStreamer(config, audio_source)
    
    # Test metadata with URL-encoded spaces (like from iHeartMedia streams)
    metadata = {
        'song_title': 'Peace%20Orchestra - Who%20Am%20I',
        'artist': 'Unknown%20Artist',
    }
    
    result = streamer._extract_metadata_fields(metadata)
    
    assert result is not None
    # Should decode %20 to spaces
    assert result['title'] == 'Peace Orchestra - Who Am I'
    assert result['artist'] == 'Unknown Artist'


def test_url_encoded_metadata_with_special_chars():
    """Test URL decoding with various encoded characters."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing URL decoding',
        admin_user='admin',
        admin_password='admin',
    )
    
    audio_source = _DummyAudioSource()
    streamer = IcecastStreamer(config, audio_source)
    
    # Test with multiple types of URL encoding
    metadata = {
        'song_title': 'Artist%20Name%20-%20Song%20Title',
        'artist': 'The%20Artist%26Band',  # %26 is &
    }
    
    result = streamer._extract_metadata_fields(metadata)
    
    assert result is not None
    assert result['title'] == 'Artist Name - Song Title'
    assert result['artist'] == 'The Artist&Band'


def test_metadata_without_url_encoding_unchanged():
    """Test that normal metadata without URL encoding works correctly."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing normal metadata',
        admin_user='admin',
        admin_password='admin',
    )
    
    audio_source = _DummyAudioSource()
    streamer = IcecastStreamer(config, audio_source)
    
    # Test normal metadata without URL encoding
    metadata = {
        'song_title': 'Morgan Wallen - Just In Case',
        'artist': 'Morgan Wallen',
    }
    
    result = streamer._extract_metadata_fields(metadata)
    
    assert result is not None
    # Should remain unchanged
    assert result['title'] == 'Morgan Wallen - Just In Case'
    assert result['artist'] == 'Morgan Wallen'


def test_nested_now_playing_url_encoded():
    """Test URL decoding works with nested now_playing structure."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing nested URL decoding',
        admin_user='admin',
        admin_password='admin',
    )
    
    audio_source = _DummyAudioSource()
    streamer = IcecastStreamer(config, audio_source)
    
    # Test with nested now_playing dict (common structure)
    metadata = {
        'now_playing': {
            'title': 'VibeLounge%20Station%20ID',
            'artist': 'Unknown%20Artist',
        }
    }
    
    result = streamer._extract_metadata_fields(metadata)
    
    assert result is not None
    assert result['title'] == 'VibeLounge Station ID'
    assert result['artist'] == 'Unknown Artist'


def test_sanitize_metadata_with_url_encoding():
    """Test that _sanitize_metadata_value doesn't double-decode."""
    # _sanitize_metadata_value shouldn't need to decode since
    # _extract_metadata_fields already handles it
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing sanitize',
        admin_user='admin',
        admin_password='admin',
    )
    
    audio_source = _DummyAudioSource()
    streamer = IcecastStreamer(config, audio_source)
    
    # After extraction, metadata should already be decoded
    # _sanitize should just clean whitespace
    sanitized = streamer._sanitize_metadata_value('Peace Orchestra - Who Am I', '')
    assert sanitized == 'Peace Orchestra - Who Am I'


def test_send_metadata_update_with_decoded_values():
    """Test that metadata updates work with previously URL-encoded values."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing metadata update',
        admin_user='admin',
        admin_password='admin',
    )
    
    audio_source = _DummyAudioSource()
    streamer = IcecastStreamer(config, audio_source)
    
    # Mock successful response
    mock_response = mock.MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"
    
    with mock.patch('requests.get', return_value=mock_response) as mock_get:
        # These values are already decoded (as they would be after extraction)
        result = streamer._send_metadata_update("Peace Orchestra - Who Am I", "Peace Orchestra")
        
        assert result is not None
        assert "Peace Orchestra" in result
        assert "Who Am I" in result
        
        # Verify the URL was properly constructed with the decoded values
        # The song parameter should be URL-encoded by the send function
        assert mock_get.call_count == 1
        called_url = mock_get.call_args[0][0]
        # The URL should contain properly encoded metadata
        assert 'Peace' in called_url or 'Peace%20' in called_url


if __name__ == '__main__':
    # Run tests
    print("Testing Icecast metadata URL decoding...")
    
    try:
        import pytest
        pytest.main([__file__, '-v'])
    except ImportError:
        print("Running tests without pytest...")
        
        test_url_encoded_metadata_is_decoded()
        print("✓ test_url_encoded_metadata_is_decoded")
        
        test_url_encoded_metadata_with_special_chars()
        print("✓ test_url_encoded_metadata_with_special_chars")
        
        test_metadata_without_url_encoding_unchanged()
        print("✓ test_metadata_without_url_encoding_unchanged")
        
        test_nested_now_playing_url_encoded()
        print("✓ test_nested_now_playing_url_encoded")
        
        test_sanitize_metadata_with_url_encoding()
        print("✓ test_sanitize_metadata_with_url_encoding")
        
        test_send_metadata_update_with_decoded_values()
        print("✓ test_send_metadata_update_with_decoded_values")
        
        print("\n✅ All URL decoding tests passed!")
