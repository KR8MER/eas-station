"""Tests for Icecast metadata update retry logic."""

import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.icecast_output import (
    IcecastConfig, 
    IcecastStreamer, 
    METADATA_UPDATE_MAX_RETRIES,
    METADATA_UPDATE_RETRY_DELAY,
)


class _DummyAudioSource:
    """Dummy audio source for testing."""
    
    def get_audio_chunk(self, timeout=0.1):  # pragma: no cover - stub
        return None
    
    metrics = mock.MagicMock(metadata={})


def test_metadata_retry_constants_defined():
    """Verify metadata retry constants are defined."""
    assert METADATA_UPDATE_MAX_RETRIES is not None
    assert isinstance(METADATA_UPDATE_MAX_RETRIES, int)
    assert METADATA_UPDATE_MAX_RETRIES > 0
    
    assert METADATA_UPDATE_RETRY_DELAY is not None
    assert isinstance(METADATA_UPDATE_RETRY_DELAY, (int, float))
    assert METADATA_UPDATE_RETRY_DELAY > 0


def test_metadata_update_succeeds_on_first_attempt(monkeypatch):
    """Test successful metadata update on first attempt (no retries needed)."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing metadata updates',
        admin_user='admin',
        admin_password='admin',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())
    
    # Mock successful response
    mock_response = mock.MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"
    
    with mock.patch('requests.get', return_value=mock_response) as mock_get:
        result = streamer._send_metadata_update("Test Song", "Test Artist")
        
        # Should succeed on first attempt
        assert result is not None
        assert "Test" in result
        assert mock_get.call_count == 1


def test_metadata_update_retries_on_400_error(monkeypatch):
    """Test that 400 errors trigger retry logic."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing 400 retry',
        admin_user='admin',
        admin_password='admin',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())
    
    # Mock responses: first two attempts get 400, third succeeds
    responses = [
        mock.MagicMock(status_code=400, text="Source does not exist"),
        mock.MagicMock(status_code=400, text="Source does not exist"),
        mock.MagicMock(status_code=200, text="OK"),
    ]
    
    # Track sleep calls to verify exponential backoff
    sleep_calls = []
    
    def mock_sleep(seconds):
        sleep_calls.append(seconds)
    
    monkeypatch.setattr(time, "sleep", mock_sleep)
    
    with mock.patch('requests.get', side_effect=responses) as mock_get:
        result = streamer._send_metadata_update("Test Song", "Test Artist")
        
        # Should succeed after retries
        assert result is not None
        assert "Test" in result
        
        # Should have made 3 attempts
        assert mock_get.call_count == 3
        
        # Should have slept twice (after first two 400 errors)
        assert len(sleep_calls) == 2
        
        # Verify exponential backoff: first sleep = delay, second = delay * 2
        expected_first_sleep = METADATA_UPDATE_RETRY_DELAY
        expected_second_sleep = METADATA_UPDATE_RETRY_DELAY * 2
        
        assert sleep_calls[0] == expected_first_sleep
        assert sleep_calls[1] == expected_second_sleep


def test_metadata_update_fails_after_max_retries(monkeypatch):
    """Test that metadata update fails after max retries are exhausted."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing max retries',
        admin_user='admin',
        admin_password='admin',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())
    
    # Mock response: always return 400
    mock_response = mock.MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Source does not exist"
    
    sleep_calls = []
    
    def mock_sleep(seconds):
        sleep_calls.append(seconds)
    
    monkeypatch.setattr(time, "sleep", mock_sleep)
    
    with mock.patch('requests.get', return_value=mock_response) as mock_get:
        result = streamer._send_metadata_update("Test Song", "Test Artist")
        
        # Should fail after all retries
        assert result is None
        
        # Should have made max_retries + 1 attempts (initial + retries)
        assert mock_get.call_count == METADATA_UPDATE_MAX_RETRIES + 1
        
        # Should have slept max_retries times (not after the last attempt)
        assert len(sleep_calls) == METADATA_UPDATE_MAX_RETRIES


def test_metadata_update_no_retry_on_other_errors(monkeypatch):
    """Test that non-400 errors don't trigger retries."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing non-400 errors',
        admin_user='admin',
        admin_password='admin',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())
    
    # Mock 403 Forbidden response (no retries expected)
    mock_response = mock.MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"
    
    sleep_calls = []
    
    def mock_sleep(seconds):
        sleep_calls.append(seconds)
    
    monkeypatch.setattr(time, "sleep", mock_sleep)
    
    with mock.patch('requests.get', return_value=mock_response) as mock_get:
        result = streamer._send_metadata_update("Test Song", "Test Artist")
        
        # Should fail immediately without retries
        assert result is None
        assert mock_get.call_count == 1
        assert len(sleep_calls) == 0


def test_metadata_update_no_retry_on_connection_error(monkeypatch):
    """Test that connection errors don't trigger retries."""
    import requests
    
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing connection errors',
        admin_user='admin',
        admin_password='admin',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())
    
    sleep_calls = []
    
    def mock_sleep(seconds):
        sleep_calls.append(seconds)
    
    monkeypatch.setattr(time, "sleep", mock_sleep)
    
    # Mock connection error
    with mock.patch('requests.get', side_effect=requests.exceptions.ConnectionError("Connection refused")) as mock_get:
        result = streamer._send_metadata_update("Test Song", "Test Artist")
        
        # Should fail immediately without retries
        assert result is None
        assert mock_get.call_count == 1
        assert len(sleep_calls) == 0


if __name__ == '__main__':
    # Run tests
    print("Testing Icecast metadata retry logic...")
    
    # If pytest is not available, use simple assertions
    try:
        import pytest
        pytest.main([__file__, '-v'])
    except ImportError:
        print("Running tests without pytest...")
        
        class FakeMonkeypatch:
            def setattr(self, obj, name, value):
                if isinstance(obj, type):
                    # Setting on module/class
                    original = getattr(obj, name)
                    setattr(obj, name, value)
                else:
                    # Setting on instance
                    setattr(obj, name, value)
        
        monkeypatch = FakeMonkeypatch()
        
        test_metadata_retry_constants_defined()
        print("✓ test_metadata_retry_constants_defined")
        
        monkeypatch = FakeMonkeypatch()
        test_metadata_update_succeeds_on_first_attempt(monkeypatch)
        print("✓ test_metadata_update_succeeds_on_first_attempt")
        
        monkeypatch = FakeMonkeypatch()
        test_metadata_update_retries_on_400_error(monkeypatch)
        print("✓ test_metadata_update_retries_on_400_error")
        
        monkeypatch = FakeMonkeypatch()
        test_metadata_update_fails_after_max_retries(monkeypatch)
        print("✓ test_metadata_update_fails_after_max_retries")
        
        monkeypatch = FakeMonkeypatch()
        test_metadata_update_no_retry_on_other_errors(monkeypatch)
        print("✓ test_metadata_update_no_retry_on_other_errors")
        
        monkeypatch = FakeMonkeypatch()
        test_metadata_update_no_retry_on_connection_error(monkeypatch)
        print("✓ test_metadata_update_no_retry_on_connection_error")
        
        print("\n✅ All metadata retry tests passed!")
