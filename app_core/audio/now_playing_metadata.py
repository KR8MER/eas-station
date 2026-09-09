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

from __future__ import annotations

"""Pure now-playing metadata extraction, shared across processes.

Split out of ``icecast_output.py`` (which pulls in numpy/requests/subprocess
for FFmpeg process management) so the webapp process -- which only wants the
parsing logic for a lightweight public "now playing" API -- doesn't have to
import that whole module just to reach this one function. ``IcecastStreamer``
keeps a thin instance-method wrapper around ``extract_now_playing_fields``
for backward compatibility with existing callers/tests.

Takes the same raw source metadata dict AudioSourceManager attaches to a
source's ``metrics.metadata`` (ICY tags, RBDS fields, relay-station JSON,
however the upstream source shape it) and normalizes it into the handful of
fields a "now playing" display actually needs: title, artist, album,
artwork_url, length.
"""

import re
from typing import Any, Dict, Optional
from urllib.parse import unquote


def _normalize(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ('title', 'song', 'text', 'value', 'name'):
            if key in value:
                return _normalize(value.get(key))
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            normalized = _normalize(item)
            if normalized:
                return normalized
        return None

    text = str(value).strip()
    if not text:
        return None

    # Clean up metadata that contains XML/JSON attributes
    # Example: text="Everybody Talks" song_spot="M" MediaBaseId="1842682" ...
    # Extract just the text="" value
    text_match = re.search(r'text="([^"]+)"', text)
    if text_match:
        text = text_match.group(1)

    # Also try title="" attribute
    elif 'title="' in text:
        title_match = re.search(r'title="([^"]+)"', text)
        if title_match:
            text = title_match.group(1)

    # Also try song="" attribute
    elif 'song="' in text:
        song_match = re.search(r'song="([^"]+)"', text)
        if song_match:
            text = song_match.group(1)

    # Remove any remaining XML-like attributes
    # Remove key="value" patterns
    text = re.sub(r'\s+\w+="[^"]*"', '', text)
    # Remove key='value' patterns
    text = re.sub(r"\s+\w+='[^']*'", '', text)
    # Remove standalone key=value patterns (no quotes)
    text = re.sub(r'\s+\w+=\S+', '', text)

    # Decode URL-encoded characters (e.g., %20 -> space)
    # This handles metadata from sources like iHeartMedia that include URL encoding
    try:
        text = unquote(text)
    except Exception:
        # If unquote fails for any reason, keep the original text
        pass

    # Collapse extraneous whitespace (including newlines)
    # This must happen AFTER URL decoding to handle decoded spaces properly
    text = ' '.join(text.split())

    return text or None


def extract_now_playing_fields(
    metadata: Dict[str, Any]
) -> Optional[Dict[str, Optional[str]]]:
    """Derive title/artist and extended metadata from raw source metadata.

    Returns a dict with keys: title, artist, artwork_url, length, album.
    Returns None if no useful metadata found (title and artist both empty --
    a station identifier alone, e.g. RBDS PS name with no song data, isn't
    "now playing" info).
    """
    now_playing = metadata.get('now_playing')
    nested_title = None
    nested_artist = None
    if isinstance(now_playing, dict):
        nested_title = _normalize(now_playing.get('title') or now_playing.get('song'))
        nested_artist = _normalize(now_playing.get('artist'))
    elif now_playing is not None:
        nested_title = _normalize(now_playing)

    title_candidates = [
        nested_title,
        _normalize(metadata.get('song_title')),
        _normalize(metadata.get('song')),
        _normalize(metadata.get('title')),
        _normalize(metadata.get('program_title')),
        _normalize(metadata.get('rbds_radio_text')),
    ]

    artist_candidates = [
        nested_artist,
        _normalize(metadata.get('artist')),
        _normalize(metadata.get('song_artist')),
        _normalize(metadata.get('performer')),
        _normalize(metadata.get('rbds_ps_name')),
        _normalize(metadata.get('station_name')),
        _normalize(metadata.get('station_callsign')),
    ]

    title = next((candidate for candidate in title_candidates if candidate), None)
    artist = next((candidate for candidate in artist_candidates if candidate), None)

    if not title and not artist:
        return None

    result: Dict[str, Optional[str]] = {
        'title': title,
        'artist': artist,
        'artwork_url': None,
        'length': None,
        'album': None,
    }

    # Try to extract album art URL (various field names)
    try:
        artwork_candidates = [
            _normalize(metadata.get('amgArtworkURL')),
            _normalize(metadata.get('artwork_url')),
            _normalize(metadata.get('artworkURL')),
            _normalize(metadata.get('album_art')),
            _normalize(metadata.get('cover_art')),
        ]
        if isinstance(now_playing, dict):
            artwork_candidates.extend([
                _normalize(now_playing.get('artwork_url')),
                _normalize(now_playing.get('album_art')),
            ])

        # Find first valid URL (should contain http/https)
        for candidate in artwork_candidates:
            if candidate and ('http://' in candidate or 'https://' in candidate):
                result['artwork_url'] = candidate
                break
    except Exception:
        pass

    # Try to extract song length/duration
    try:
        length_candidates = [
            _normalize(metadata.get('length')),
            _normalize(metadata.get('duration')),
            _normalize(metadata.get('song_length')),
        ]
        if isinstance(now_playing, dict):
            length_candidates.extend([
                _normalize(now_playing.get('length')),
                _normalize(now_playing.get('duration')),
            ])

        result['length'] = next((candidate for candidate in length_candidates if candidate), None)
    except Exception:
        pass

    # Try to extract album name
    try:
        album_candidates = [
            _normalize(metadata.get('album')),
            _normalize(metadata.get('album_name')),
        ]
        if isinstance(now_playing, dict):
            album_candidates.append(_normalize(now_playing.get('album')))

        result['album'] = next((candidate for candidate in album_candidates if candidate), None)
    except Exception:
        pass

    return result
