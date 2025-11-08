"""Tests for parsing rich ICY metadata from stream sources."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.ingest import AudioSourceConfig, AudioSourceType
from app_core.audio.sources import StreamSourceAdapter


def test_icy_metadata_extracts_artist_from_text_attribute_prefix():
    """Ensure artist information is captured when encoded ahead of text=""."""

    config = AudioSourceConfig(
        source_type=AudioSourceType.STREAM,
        name="Test Stream",
        device_params={'stream_url': 'http://example.com/stream'},
    )
    adapter = StreamSourceAdapter(config)

    metadata_text = (
        "StreamTitle='Huntr/X - text=\"Golden\" song_spot=\"M\" "
        "MediaBaseId=\"3136003\" amgArtworkURL=\"https://example.com/art.jpg\" "
        "length=\"00:03:11\"';"
        "StreamUrl='http://example.com/stream'"
    )

    adapter._handle_icy_metadata(metadata_text)

    metadata = adapter.metrics.metadata
    assert metadata is not None
    assert metadata.get('song') == 'Huntr/X - Golden'
    assert metadata.get('song_raw') == (
        'Huntr/X - text="Golden" song_spot="M" MediaBaseId="3136003" '
        'amgArtworkURL="https://example.com/art.jpg" length="00:03:11"'
    )
    assert metadata.get('artist') == 'Huntr/X'
    assert metadata.get('song_artist') == 'Huntr/X'
    assert metadata.get('song_title') == 'Golden'
    assert metadata.get('length') == '00:03:11'

    now_playing = metadata.get('now_playing')
    assert isinstance(now_playing, dict)
    assert now_playing.get('artist') == 'Huntr/X'
    assert now_playing.get('title') == 'Golden'

    icy_fields = metadata.get('icy', {}).get('fields', {})
    assert icy_fields.get('text') == 'Golden'
    assert icy_fields.get('artist') == 'Huntr/X'
    assert icy_fields.get('length') == '00:03:11'
