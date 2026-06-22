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

"""Tests for stream URL whitespace handling in StreamSourceAdapter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.ingest import AudioSourceConfig, AudioSourceType
from app_core.audio.sources import StreamSourceAdapter


def test_stream_url_with_leading_whitespace():
    """Ensure URLs with leading whitespace are properly trimmed."""
    
    # Test with leading whitespace
    config = AudioSourceConfig(
        source_type=AudioSourceType.STREAM,
        name="Test Stream",
        device_params={'stream_url': ' https://example.com/stream'},
    )
    adapter = StreamSourceAdapter(config)
    
    resolved = adapter._resolve_stream_url(' https://example.com/stream')
    assert resolved == 'https://example.com/stream'
    assert not resolved.startswith(' ')


def test_stream_url_with_trailing_whitespace():
    """Ensure URLs with trailing whitespace are properly trimmed."""
    
    config = AudioSourceConfig(
        source_type=AudioSourceType.STREAM,
        name="Test Stream",
        device_params={'stream_url': 'https://example.com/stream '},
    )
    adapter = StreamSourceAdapter(config)
    
    resolved = adapter._resolve_stream_url('https://example.com/stream ')
    assert resolved == 'https://example.com/stream'
    assert not resolved.endswith(' ')


def test_stream_url_with_leading_and_trailing_whitespace():
    """Ensure URLs with both leading and trailing whitespace are properly trimmed."""
    
    config = AudioSourceConfig(
        source_type=AudioSourceType.STREAM,
        name="Test Stream",
        device_params={'stream_url': '  https://example.com/stream  '},
    )
    adapter = StreamSourceAdapter(config)
    
    resolved = adapter._resolve_stream_url('  https://example.com/stream  ')
    assert resolved == 'https://example.com/stream'
    assert not resolved.startswith(' ')
    assert not resolved.endswith(' ')


def test_stream_url_without_whitespace():
    """Ensure URLs without whitespace are not affected."""
    
    config = AudioSourceConfig(
        source_type=AudioSourceType.STREAM,
        name="Test Stream",
        device_params={'stream_url': 'https://example.com/stream'},
    )
    adapter = StreamSourceAdapter(config)
    
    resolved = adapter._resolve_stream_url('https://example.com/stream')
    assert resolved == 'https://example.com/stream'
