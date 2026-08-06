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

"""
Persistence for per-source audio archiving settings.

Settings live in ``AudioSourceConfigDB.config_params["archive"]`` — the database,
not the ``.env`` file — so they survive ``git pull`` upgrades and reboots.  The
runtime consumers of this block are
:func:`eas_monitoring_service.initialize_archivers` (at service start) and the
``archiver_start`` Redis command handler in
:mod:`app_core.audio.redis_commands` (live start from the web UI).

Every value written here is normalised first: the runtime reads these back with
``int()`` / ``float()`` at service start, and a single unparseable value stored
from a hand-rolled API call would make archiving fail to come up with only a log
line to show for it.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_ARCHIVE_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "output_dir": "archives",
    "segment_duration_seconds": 3600,
    "retention_days": 7,
    "max_disk_bytes": 0,
    "format": "wav",
    "bitrate": 128,
    "silence_threshold": 0.0,
}

SUPPORTED_FORMATS = ("wav", "mp3")

# Bounds mirror the input constraints on the Audio Archives page so the API and
# the UI cannot disagree about what is valid.
MIN_SEGMENT_SECONDS = 60          # 1 minute
MAX_SEGMENT_SECONDS = 86400       # 24 hours
MIN_BITRATE_KBPS = 64
MAX_BITRATE_KBPS = 320


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
    return default


def _coerce_int(value: Any, default: int, minimum: int, maximum: Optional[int] = None) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        return default
    result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _coerce_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, result))


def normalize_archive_config(
    raw: Optional[Dict[str, Any]],
    base: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a fully-populated, type-correct archive config.

    Unknown keys in *raw* are dropped; out-of-range values are clamped rather
    than rejected so a partially valid save still persists the rest.

    Args:
        raw:  Values to apply (an API request body, or a stored config block).
        base: Values to fall back on per key.  Defaults to
              :data:`DEFAULT_ARCHIVE_CONFIG`.

    Returns:
        dict: Every key of :data:`DEFAULT_ARCHIVE_CONFIG`, correctly typed.

    Example:
        >>> normalize_archive_config({"retention_days": "14", "format": "MP3"})["retention_days"]
        14
    """
    merged = dict(DEFAULT_ARCHIVE_CONFIG)
    if base:
        merged.update({k: v for k, v in base.items() if k in DEFAULT_ARCHIVE_CONFIG})
    if raw:
        merged.update({k: v for k, v in raw.items() if k in DEFAULT_ARCHIVE_CONFIG})

    output_dir = str(merged.get("output_dir") or "").strip()
    fmt = str(merged.get("format") or "").strip().lower()

    return {
        "enabled": _coerce_bool(merged.get("enabled"), DEFAULT_ARCHIVE_CONFIG["enabled"]),
        "output_dir": output_dir or DEFAULT_ARCHIVE_CONFIG["output_dir"],
        "segment_duration_seconds": _coerce_int(
            merged.get("segment_duration_seconds"),
            DEFAULT_ARCHIVE_CONFIG["segment_duration_seconds"],
            MIN_SEGMENT_SECONDS,
            MAX_SEGMENT_SECONDS,
        ),
        "retention_days": _coerce_int(
            merged.get("retention_days"), DEFAULT_ARCHIVE_CONFIG["retention_days"], 0
        ),
        "max_disk_bytes": _coerce_int(
            merged.get("max_disk_bytes"), DEFAULT_ARCHIVE_CONFIG["max_disk_bytes"], 0
        ),
        "format": fmt if fmt in SUPPORTED_FORMATS else DEFAULT_ARCHIVE_CONFIG["format"],
        "bitrate": _coerce_int(
            merged.get("bitrate"),
            DEFAULT_ARCHIVE_CONFIG["bitrate"],
            MIN_BITRATE_KBPS,
            MAX_BITRATE_KBPS,
        ),
        "silence_threshold": _coerce_float(
            merged.get("silence_threshold"),
            DEFAULT_ARCHIVE_CONFIG["silence_threshold"],
            0.0,
            1.0,
        ),
    }


def get_archive_config(source_name: str) -> Optional[Dict[str, Any]]:
    """Return the archive config for *source_name*, or None if no such source."""
    try:
        from app_core.models import AudioSourceConfigDB
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if db_config is None:
            return None
        config_params = db_config.config_params or {}
        return normalize_archive_config(config_params.get("archive"))
    except Exception as exc:
        logger.error("Error reading archive config for '%s': %s", source_name, exc)
        return None


def save_archive_config(source_name: str, archive_cfg: Dict[str, Any]) -> bool:
    """Merge *archive_cfg* into ``config_params["archive"]`` for *source_name*.

    Only the ``archive`` key is touched — the receiver-managed keys alongside it
    (see :mod:`app_core.audio.source_config`) are left exactly as they were.

    Returns:
        bool: True on success, False if the source does not exist or the commit
        failed.
    """
    try:
        from app_core.extensions import db
        from app_core.models import AudioSourceConfigDB
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if db_config is None:
            return False
        config_params = dict(db_config.config_params or {})
        config_params["archive"] = normalize_archive_config(
            archive_cfg, base=config_params.get("archive")
        )
        # Reassign the whole dict so SQLAlchemy flags the JSON column dirty;
        # mutating it in place would not be detected.
        db_config.config_params = config_params
        db.session.commit()
        return True
    except Exception as exc:
        logger.error("Error saving archive config for '%s': %s", source_name, exc)
        try:
            from app_core.extensions import db
            db.session.rollback()
        except Exception:
            pass
        return False


def all_sources_with_archive_config() -> List[Dict[str, Any]]:
    """Return every configured audio source with its normalised archive config."""
    try:
        from app_core.models import AudioSourceConfigDB
        rows = AudioSourceConfigDB.query.order_by(AudioSourceConfigDB.name).all()
        return [
            {
                "source_name": row.name,
                "source_type": row.source_type,
                "enabled": row.enabled,
                "archive": normalize_archive_config((row.config_params or {}).get("archive")),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.error("Error listing sources: %s", exc)
        return []


__all__ = [
    "DEFAULT_ARCHIVE_CONFIG",
    "MAX_BITRATE_KBPS",
    "MAX_SEGMENT_SECONDS",
    "MIN_BITRATE_KBPS",
    "MIN_SEGMENT_SECONDS",
    "SUPPORTED_FORMATS",
    "all_sources_with_archive_config",
    "get_archive_config",
    "normalize_archive_config",
    "save_archive_config",
]
