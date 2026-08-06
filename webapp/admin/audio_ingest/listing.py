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

"""Assembling the GET /api/audio/sources response.

The database is the source of truth for *which* sources exist; their live state
comes from one of three places, in priority order:

1. an adapter in the local controller (integrated mode),
2. the audio service's Redis snapshot (separated mode — the deployment shape),
3. nothing, in which case the row is described from its stored config alone.

This module owns that reconciliation. ``webapp/admin/audio_ingest/routes_sources``
holds only the HTTP wrapper around ``build_source_listing``.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import desc

from app_core.models import AudioSourceConfigDB, AudioSourceMetrics

from .controller import _get_audio_controller, _read_audio_metrics_from_redis
from .serialization import _serialize_audio_source
from .source_payload import _serialize_db_only, _serialize_from_redis
from .streaming import _get_auto_streaming_service, _get_icecast_stream_url

logger = logging.getLogger(__name__)


@dataclass
class RedisControllerState:
    """What the audio service is currently publishing about its sources."""

    sources: Dict[str, Any] = field(default_factory=dict)
    #: True only when a usable ``sources`` mapping was found.
    use_redis: bool = False
    #: True when metrics are completely absent — the service is dead or has
    #: never started. Distinct from "running but reporting no sources".
    service_dead: bool = False
    streaming_status: Any = None


def _read_redis_controller_state() -> RedisControllerState:
    """Decode the audio service's Redis snapshot, tolerating every shape of it.

    The ``audio_controller`` entry and its nested ``streaming`` entry may each
    arrive as a dict or as a JSON string, and either may be absent or malformed.
    None of that is worth failing the request over.
    """
    redis_metrics = _read_audio_metrics_from_redis()
    state = RedisControllerState(service_dead=(redis_metrics is None))

    if not redis_metrics or 'audio_controller' not in redis_metrics:
        return state

    try:
        audio_controller_data = redis_metrics.get('audio_controller')
        if isinstance(audio_controller_data, str):
            audio_controller_data = json.loads(audio_controller_data)

        if audio_controller_data and 'sources' in audio_controller_data:
            state.sources = audio_controller_data['sources']
            state.use_redis = True
            logger.info(
                f"Using Redis for audio source status (separated architecture): "
                f"{list(state.sources.keys())}"
            )

        if audio_controller_data and isinstance(audio_controller_data, dict):
            streaming_status = audio_controller_data.get('streaming')
            if isinstance(streaming_status, str):
                try:
                    streaming_status = json.loads(streaming_status)
                except Exception:
                    logger.debug('Failed to decode Redis streaming status string; using raw value')
            state.streaming_status = streaming_status
    except Exception as e:
        logger.warning(f"Failed to parse Redis audio controller data: {e}")

    return state


def _latest_metrics_by_source(source_names: List[str]) -> Dict[str, AudioSourceMetrics]:
    """Most recent persisted metric row per source, in one query."""
    if not source_names:
        return {}

    recent_metrics = (
        AudioSourceMetrics.query
        .filter(AudioSourceMetrics.source_name.in_(source_names))
        .order_by(AudioSourceMetrics.source_name, desc(AudioSourceMetrics.timestamp))
        .all()
    )

    latest: Dict[str, AudioSourceMetrics] = {}
    for metric in recent_metrics:
        if metric.source_name not in latest:
            latest[metric.source_name] = metric
    return latest


def _collect_icecast_status(redis_streaming_status: Any) -> Dict[str, Dict[str, Any]]:
    """Per-source Icecast stats, preferring a locally hosted streaming service.

    Redis is the fallback, not an override: in a separated deployment the UI
    worker has no local service, but in an integrated one the local service is
    authoritative and its numbers are fresher.
    """
    icecast_status_map: Dict[str, Dict[str, Any]] = {}

    auto_streaming = _get_auto_streaming_service()
    if auto_streaming:
        try:
            streaming_status = auto_streaming.get_status()
            active_streams = streaming_status.get('active_streams', {}) if streaming_status else {}
            icecast_status_map = {name: dict(stats) for name, stats in active_streams.items()}
        except Exception as status_exc:
            logger.warning('Failed to get Icecast streaming status: %s', status_exc)

    if not icecast_status_map and redis_streaming_status:
        try:
            active_streams = (
                redis_streaming_status.get('active_streams', {})
                if isinstance(redis_streaming_status, dict) else {}
            )
            icecast_status_map = {name: dict(stats) for name, stats in active_streams.items()}
        except Exception as status_exc:
            logger.warning('Failed to parse Redis streaming status: %s', status_exc)

    return icecast_status_map


def _redis_data_for(state: RedisControllerState, name: str) -> Optional[Dict[str, Any]]:
    """The Redis entry for a source, or ``None`` to fall back to the controller.

    A non-dict entry is treated as absent — but as an empty dict rather than
    ``None``, which is what the pre-refactor code did and what makes the caller
    skip the Redis branch without also consulting the local controller.
    """
    if not (state.use_redis and name in state.sources):
        return None

    redis_source_data = state.sources[name]
    if not isinstance(redis_source_data, dict):
        logger.warning(
            "Redis audio source data for %s is not a dict (type=%s); ignoring",
            name,
            type(redis_source_data),
        )
        return {}

    logger.debug(f"Found Redis data for source '{name}': {redis_source_data}")
    return redis_source_data


def build_source_listing() -> Dict[str, Any]:
    """Build the full GET /api/audio/sources payload."""
    state = _read_redis_controller_state()

    # Get local controller (may be empty in separated architecture)
    controller = _get_audio_controller()
    sources: List[Dict[str, Any]] = []

    # Query DATABASE for all sources (source of truth)
    db_configs = AudioSourceConfigDB.query.all()
    latest_metrics_map = _latest_metrics_by_source([config.name for config in db_configs])
    icecast_status_map = _collect_icecast_status(state.streaming_status)

    for db_config in db_configs:
        latest_metric = latest_metrics_map.get(db_config.name)
        icecast_stats = icecast_status_map.get(db_config.name)
        icecast_url = _get_icecast_stream_url(db_config.name)

        # Try Redis first (separated architecture), then fall back to the
        # local controller (integrated mode or Redis unavailable).
        redis_source_data = _redis_data_for(state, db_config.name)
        adapter = (
            controller._sources.get(db_config.name)
            if redis_source_data is None else None
        )

        if adapter:
            sources.append(
                _serialize_audio_source(db_config.name, adapter, latest_metric, icecast_stats)
            )
        elif redis_source_data:
            sources.append(
                _serialize_from_redis(
                    db_config, redis_source_data, latest_metric, icecast_stats, icecast_url
                )
            )
        else:
            sources.append(
                _serialize_db_only(
                    db_config, latest_metric, icecast_stats, icecast_url, state.service_dead
                )
            )

    return {
        'sources': sources,
        'total': len(sources),
        'active_count': sum(1 for s in sources if s['status'] == 'running'),
        'db_only_count': sum(1 for s in sources if not s.get('in_memory', True)),
    }
