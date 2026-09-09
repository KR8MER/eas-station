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

"""Public "now playing" API for the station's Icecast stream(s).

Icecast/Shoutcast's in-stream metadata (ICY ``StreamTitle``) is text-only --
there is no field for an image, so album art can never travel *inside* the
audio stream to an external player (VLC, a phone app, a car radio, an
embedded widget on another site). The standard way every real internet radio
station solves this is a small public "now playing" JSON endpoint the player
or widget polls alongside the audio; this module is that endpoint.

It is intentionally a thin, redacted view: only the fields a now-playing
display needs (title/artist/album/artwork_url/length) plus the public
listener URL. It reuses the same Redis-published metadata the internal
``/api/audio/sources`` (LOCAL_API_GET_PATHS, see app.py) already surfaces for
the audio-monitoring page, and the same field-extraction logic
``IcecastStreamer`` uses to push ``StreamTitle`` updates to Icecast itself --
see ``app_core.audio.now_playing_metadata.extract_now_playing_fields`` --
but never returns the machine-describing data (mount/server/port, bitrate,
device params, priority, ...) that endpoint carries, none of which belongs
on the public internet (see the ``PUBLIC_API_GET_PATHS`` comment in app.py).
"""

import logging
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from app_core.models import AudioSourceConfigDB, AudioSourceMetrics
from app_core.audio.now_playing_metadata import extract_now_playing_fields

logger = logging.getLogger(__name__)


def _latest_source_metadata(source_name: str) -> Optional[Dict[str, Any]]:
    """Merge live Redis metadata with the last-known DB row for *source_name*.

    Live values win; the persisted metric row fills in when the audio
    service hasn't published a fresh Redis snapshot recently (e.g. right
    after a restart) so the endpoint doesn't flash empty between polls.
    """
    from webapp.admin.audio_ingest.serialization import _read_redis_source_data
    from webapp.admin.audio_ingest.sanitize import _merge_metadata

    redis_source_data = _read_redis_source_data(source_name)
    redis_metadata = (
        redis_source_data.get('metadata') if isinstance(redis_source_data, dict) else None
    )

    latest_metric = (
        AudioSourceMetrics.query
        .filter_by(source_name=source_name)
        .order_by(AudioSourceMetrics.timestamp.desc())
        .first()
    )
    db_metadata = latest_metric.source_metadata if latest_metric else None

    return _merge_metadata(redis_metadata, db_metadata)


def _public_stream_url(source_name: str) -> Optional[str]:
    from webapp.admin.audio_ingest.streaming import _get_icecast_stream_url
    return _get_icecast_stream_url(source_name)


def _now_playing_payload(db_config: AudioSourceConfigDB, icecast_url: str) -> Dict[str, Any]:
    metadata = _latest_source_metadata(db_config.name) or {}
    fields = extract_now_playing_fields(metadata) or {}

    return {
        'source': db_config.name,
        'stream_name': db_config.description or db_config.name,
        'icecast_url': icecast_url,
        'title': fields.get('title'),
        'artist': fields.get('artist'),
        'album': fields.get('album'),
        'artwork_url': fields.get('artwork_url'),
        'length': fields.get('length'),
    }


def _default_public_candidate() -> Optional[tuple]:
    """Pick the source and payload for a request with no ``?source=``.

    ``priority`` orders which *audio input* the EAS/SAME decoder should
    prefer on failover -- it has nothing to do with which source is worth
    showing the public as "now playing". A hardware line-in kept at high
    priority for reliable EAS monitoring can carry no song metadata at
    all, while a lower-priority network relay is an actual music station
    with real title/artist/artwork -- confirmed live on a multi-source
    deployment where the highest-priority source (an auto-configured USB
    device with no metadata) shadowed a real relay every request.

    Walks candidates in priority order and returns the first one that
    actually *has* title or artist metadata right now; only falls back to
    bare priority order when nothing has metadata yet (e.g. right after
    startup, before any source has published a StreamTitle), so the
    common single-station case is unaffected.
    """
    candidates = [
        config
        for config in AudioSourceConfigDB.query.filter_by(enabled=True).order_by(
            AudioSourceConfigDB.priority.desc(), AudioSourceConfigDB.name.asc()
        )
        if _public_stream_url(config.name)
    ]
    if not candidates:
        return None

    fallback = None
    for config in candidates:
        icecast_url = _public_stream_url(config.name)
        payload = _now_playing_payload(config, icecast_url)
        if fallback is None:
            fallback = (config, icecast_url, payload)
        if payload.get('title') or payload.get('artist'):
            return (config, icecast_url, payload)

    return fallback


def register(app: Flask, logger_instance) -> None:
    """Register the public now-playing routes."""
    global logger
    if logger_instance:
        logger = logger_instance

    @app.route('/api/audio/now-playing', methods=['GET'])
    def api_now_playing_default():
        """Now-playing metadata (title/artist/album/artwork) for the
        station's default public Icecast stream.

        A player or "now playing" widget polls this alongside the raw
        Icecast audio to show album art and track info -- Icecast's own
        in-stream metadata is text-only and can't carry an image.

        Query:
            source (str, optional): Which configured audio source to report
                on, for a multi-stream deployment. Omit to auto-pick: the
                first enabled, Icecast-published source that currently has
                real title/artist metadata (not just the highest EAS
                failover *priority*, which is a different axis -- see
                _default_public_candidate), falling back to priority order
                if nothing has metadata yet.

        Returns:
            200 with {source, stream_name, icecast_url, title, artist,
            album, artwork_url, length}. Unknown fields are null rather
            than omitted, so a client can bind to a stable shape.
            404 if no public Icecast stream is configured (or the named
            source doesn't exist / isn't published to Icecast).
        """
        try:
            source_name = (request.args.get('source') or '').strip()
            if source_name:
                db_config = AudioSourceConfigDB.query.filter_by(
                    name=source_name, enabled=True
                ).first()
                if db_config is None:
                    return jsonify({'error': f'Stream "{source_name}" not found'}), 404
                icecast_url = _public_stream_url(db_config.name)
                if not icecast_url:
                    return jsonify({'error': 'No public Icecast stream configured'}), 404
                payload = _now_playing_payload(db_config, icecast_url)
            else:
                candidate = _default_public_candidate()
                if candidate is None:
                    return jsonify({'error': 'No public Icecast stream configured'}), 404
                _db_config, _icecast_url, payload = candidate

            response = jsonify(payload)
            # Encourage polite polling without needing server-side caching --
            # now-playing changes on the order of minutes, not seconds.
            response.headers['Cache-Control'] = 'public, max-age=5'
            return response
        except Exception as exc:
            logger.error('Error building now-playing payload: %s', exc)
            return jsonify({'error': 'Internal server error'}), 500

    logger.info('Now-playing routes registered')
