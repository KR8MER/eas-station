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
Filesystem and formatting helpers for the Audio Archives admin page.

Pure functions over the archive directory tree — no Flask, no database.
"""

import logging
import wave
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

AUDIO_SUFFIXES = (".wav", ".mp3")


def dir_size(path: Path) -> int:
    """Return the total size in bytes of every file under *path*."""
    total = 0
    if not path.exists():
        return 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def count_files(path: Path) -> int:
    """Return the number of files under *path* (recursively)."""
    if not path.exists():
        return 0
    return sum(1 for f in path.rglob("*") if f.is_file())


def format_bytes(n: float) -> str:
    """Format a byte count as a human-readable string (e.g. ``1.5 GB``)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as ``1h 5m`` or ``5m 30s``."""
    seconds = int(seconds)
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h}h {m}m"
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s"


def newest_mtime(source_dir: Path) -> Optional[float]:
    """Return the newest file mtime under *source_dir*, or None if empty."""
    best: Optional[float] = None
    if source_dir.exists():
        for f in source_dir.rglob("*"):
            if f.is_file():
                try:
                    mt = f.stat().st_mtime
                    if best is None or mt > best:
                        best = mt
                except OSError:
                    pass
    return best


def estimate_file_duration(filepath: Path, config_bitrate: int = 128) -> Optional[float]:
    """Return estimated audio duration in seconds, or None on error.

    WAV files: exact duration read from the file header.
    MP3 files: estimated from file size and bitrate.

    Args:
        filepath: Path to the audio file.
        config_bitrate: MP3 bitrate in kbps, used only for ``.mp3`` estimation.

    Returns:
        float | None: Duration in seconds, or None if it could not be determined.
    """
    try:
        suffix = filepath.suffix.lower()
        if suffix == ".wav":
            with wave.open(str(filepath), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0 and frames > 0:
                    return frames / rate
        elif suffix == ".mp3":
            size = filepath.stat().st_size
            bytes_per_sec = config_bitrate * 125  # kbps * 1000 / 8
            if bytes_per_sec > 0:
                return size / bytes_per_sec
    except (OSError, wave.Error, EOFError) as exc:
        logger.debug("Could not determine duration of %s: %s", filepath, exc)
    return None


def source_disk_summary(source_dir: Path) -> Dict[str, Any]:
    """Return total bytes / file count / newest-file timestamp for one source."""
    total_bytes = dir_size(source_dir)
    total_files = count_files(source_dir)
    newest = newest_mtime(source_dir)
    return {
        "source_name": source_dir.name,
        "total_bytes": total_bytes,
        "total_bytes_human": format_bytes(total_bytes),
        "total_files": total_files,
        "newest_file_ts": newest,
        "newest_file_iso": datetime.fromtimestamp(newest).isoformat() if newest else None,
    }


def purge_source(source_dir: Path, days_older_than: int = 0) -> Dict[str, Any]:
    """Delete archived audio for one source.

    Args:
        source_dir: The source's archive directory (``<archive_root>/<source>``).
        days_older_than: Only delete date directories older than this many days.
            0 deletes everything.

    Returns:
        dict: ``{"files_deleted": int, "bytes_freed": int, "error": str | None}``
    """
    result: Dict[str, Any] = {"files_deleted": 0, "bytes_freed": 0, "error": None}
    if not source_dir.exists():
        return result

    cutoff = (
        datetime.now() - timedelta(days=days_older_than)
        if days_older_than > 0
        else None
    )

    try:
        for date_dir in sorted(source_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            if cutoff is not None:
                try:
                    dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                except ValueError:
                    continue
                if dir_date >= cutoff:
                    continue
            for f in date_dir.iterdir():
                if f.is_file():
                    try:
                        result["bytes_freed"] += f.stat().st_size
                        f.unlink()
                        result["files_deleted"] += 1
                    except OSError as exc:
                        logger.warning("Archive purge: cannot delete %s: %s", f, exc)
            try:
                date_dir.rmdir()
            except OSError:
                pass
    except OSError as exc:
        result["error"] = str(exc)
        logger.error("Archive purge error for %s: %s", source_dir, exc)

    return result


__all__ = [
    "AUDIO_SUFFIXES",
    "count_files",
    "dir_size",
    "estimate_file_duration",
    "format_bytes",
    "format_duration",
    "newest_mtime",
    "purge_source",
    "source_disk_summary",
]
