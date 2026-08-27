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


def test_icy_metadata_resolves_ihheart_ad_context_to_vast_url():
    """iHeartRadio ad breaks send StreamTitle=adContext="<base64 VAST url>".

    Before this fix, none of the text=/title=/song=/artist= patterns
    matched (it's a single unrecognised attribute), and it wasn't treated
    as a decodable base64 blob either because it's wrapped in
    `adContext="..."` rather than being a bare blob -- so the raw,
    undecoded attribute (quotes and all) was stored as the song title and
    shown verbatim in the Song History UI. It should instead resolve to a
    stream_url so the UI's existing "Ad URL" badge/resolve button appears,
    and 'song'/'display' should stay unset rather than showing raw junk.
    """

    config = AudioSourceConfig(
        source_type=AudioSourceType.STREAM,
        name="Test Stream",
        device_params={'stream_url': 'http://example.com/stream'},
    )
    adapter = StreamSourceAdapter(config)

    vast_url = "https://n05b-e2.revma.ihrhls.com/cache/vast/e1884975-f69f-38a5-a857-2e59e7630348"
    import base64
    encoded = base64.b64encode(vast_url.encode()).decode()

    metadata_text = f'StreamTitle=\'adContext="{encoded}"\';'

    adapter._handle_icy_metadata(metadata_text)

    metadata = adapter.metrics.metadata
    assert metadata is not None
    assert metadata.get('stream_url') == vast_url
    assert metadata.get('song') is None
    assert 'adContext=' not in (metadata.get('song') or '')
