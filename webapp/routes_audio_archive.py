"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
Audio Archive Management Routes

All archive management is performed from the web UI — no CLI required.

Endpoints
---------
GET  /admin/audio/archives
     Full management dashboard (HTML).

GET  /api/audio/archives
     JSON: disk stats for every source archive directory.

GET  /api/audio/archives/<source_name>/settings
     JSON: archiver config stored in AudioSourceConfigDB.config_params["archive"].

POST /api/audio/archives/<source_name>/settings
     Save archiver config to DB (does not start/stop the archiver).
     Body: AudioArchiverConfig fields (enabled, output_dir, segment_duration_seconds,
           retention_days, max_disk_bytes, format, bitrate).

POST /api/audio/archives/<source_name>/start
     Save config to DB (enabled=true) and send Redis command to audio-service
     to start the archiver immediately.

POST /api/audio/archives/<source_name>/stop
     Send Redis command to stop the archiver and set enabled=false in DB.

POST /api/audio/archives/<source_name>/purge
     Delete archive files.  Body (optional): {"days_older_than": N}

GET  /api/audio/archives/sources
     JSON: all AudioSourceConfigDB records with their archive config.
"""

import logging
import os
import re
import wave
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_file
from app_core.auth.roles import require_permission

logger = logging.getLogger(__name__)

_DEFAULT_ARCHIVE_DIR = "archives"


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _dir_size(path: Path) -> int:
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


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for f in path.rglob("*") if f.is_file())


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _newest_mtime(source_dir: Path) -> Optional[float]:
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


def _estimate_file_duration(filepath: Path, config_bitrate: int = 128) -> Optional[float]:
    """Return estimated audio duration in seconds, or None on error.

    WAV files: exact duration read from the file header.
    MP3 files: estimated from file size and bitrate.
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
    except Exception:
        pass
    return None


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds as a human-readable string."""
    seconds = int(seconds)
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h}h {m}m"
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s"


_BASE64_BLOB_RE = re.compile(r'^[A-Za-z0-9+/=]{20,}$')


def _is_base64_blob(text: Optional[str]) -> bool:
    """Return True if *text* looks like a raw base64-encoded blob (junk metadata)."""
    if not text:
        return False
    stripped = text.strip()
    return bool(stripped and not re.search(r'\s', stripped) and _BASE64_BLOB_RE.match(stripped))


def _is_junk_metadata(
    title: Optional[str],
    display: Optional[str],
    raw: Optional[str],
    stream_url: Optional[str] = None,
) -> bool:
    """Return True if this metadata log row contains only junk (no useful display text).

    Junk means: the title/display value is a raw base64-encoded URL blob — not a
    real song title, artist, or station ID.  Commercials, promos, and station IDs
    are NOT considered junk and are left alone.

    Entries that have a resolved stream_url (e.g. a VAST ad tag URL) are NOT
    considered junk — they are kept so the user can attempt playback.
    """
    # Entries with a resolved stream URL are meaningful — keep them
    if stream_url and stream_url.startswith(("http://", "https://")):
        return False
    # If the title column is a base64 blob, it's junk
    if _is_base64_blob(title):
        return True
    # If there's no title and the display fallback is a base64 blob, it's junk
    if not (title or "").strip() and _is_base64_blob(display):
        return True
    # If neither title nor display have content but raw is a base64 blob, it's junk
    if not (title or "").strip() and not (display or "").strip() and _is_base64_blob(raw):
        return True
    return False


def _source_disk_summary(source_dir: Path) -> Dict[str, Any]:
    total_bytes = _dir_size(source_dir)
    total_files = _count_files(source_dir)
    newest = _newest_mtime(source_dir)
    return {
        "source_name": source_dir.name,
        "total_bytes": total_bytes,
        "total_bytes_human": _format_bytes(total_bytes),
        "total_files": total_files,
        "newest_file_ts": newest,
        "newest_file_iso": datetime.fromtimestamp(newest).isoformat() if newest else None,
    }


def _purge_source(source_dir: Path, days_older_than: int = 0) -> Dict[str, Any]:
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
    except Exception as exc:
        result["error"] = str(exc)
        logger.error("Archive purge error for %s: %s", source_dir, exc)

    return result


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_DEFAULT_ARCHIVE_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "output_dir": "archives",
    "segment_duration_seconds": 3600,
    "retention_days": 7,
    "max_disk_bytes": 0,
    "format": "wav",
    "bitrate": 128,
    "silence_threshold": 0.0,
}


def _get_archive_config(source_name: str) -> Optional[Dict[str, Any]]:
    """Return the archive config for *source_name* from the DB, or None if not found."""
    try:
        from app_core.models import AudioSourceConfigDB
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if db_config is None:
            return None
        config_params = db_config.config_params or {}
        archive = dict(_DEFAULT_ARCHIVE_CONFIG)
        archive.update(config_params.get("archive", {}))
        return archive
    except Exception as exc:
        logger.error("Error reading archive config for '%s': %s", source_name, exc)
        return None


def _save_archive_config(source_name: str, archive_cfg: Dict[str, Any]) -> bool:
    """Merge *archive_cfg* into AudioSourceConfigDB.config_params["archive"]."""
    try:
        from app_core.extensions import db
        from app_core.models import AudioSourceConfigDB
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if db_config is None:
            return False
        config_params = dict(db_config.config_params or {})
        existing = dict(_DEFAULT_ARCHIVE_CONFIG)
        existing.update(config_params.get("archive", {}))
        existing.update(archive_cfg)
        config_params["archive"] = existing
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


def _all_sources_with_archive_config() -> List[Dict[str, Any]]:
    """Return all AudioSourceConfigDB records with their archive config."""
    try:
        from app_core.models import AudioSourceConfigDB
        rows = AudioSourceConfigDB.query.order_by(AudioSourceConfigDB.name).all()
        result = []
        for row in rows:
            config_params = row.config_params or {}
            archive = dict(_DEFAULT_ARCHIVE_CONFIG)
            archive.update(config_params.get("archive", {}))
            result.append({
                "source_name": row.name,
                "source_type": row.source_type,
                "enabled": row.enabled,
                "archive": archive,
            })
        return result
    except Exception as exc:
        logger.error("Error listing sources: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register(app: Flask, logger_arg, archive_dir: str = _DEFAULT_ARCHIVE_DIR) -> None:
    """Attach audio archive management routes to *app*."""

    route_logger = logger_arg.getChild("routes_audio_archive")
    archive_root = Path(archive_dir)

    # ------------------------------------------------------------------
    # Dashboard page
    # ------------------------------------------------------------------

    @app.route("/admin/audio/archives")
    def audio_archives_dashboard():
        return render_template("admin/audio_archives.html")

    # ------------------------------------------------------------------
    # API: all sources with settings + disk stats
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/sources", methods=["GET"])
    def api_audio_archives_sources():
        sources = _all_sources_with_archive_config()

        # Enrich each source with its current disk usage
        for s in sources:
            source_dir = archive_root / s["source_name"]
            disk = _source_disk_summary(source_dir)
            s["disk_bytes"] = disk["total_bytes"]
            s["disk_bytes_human"] = disk["total_bytes_human"]
            s["disk_files"] = disk["total_files"]
            s["newest_file_iso"] = disk["newest_file_iso"]

        return jsonify({"sources": sources, "archive_dir": str(archive_root)})

    # ------------------------------------------------------------------
    # API: disk-only summary (no DB lookup)
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives", methods=["GET"])
    def api_audio_archives_list():
        sources: List[Dict[str, Any]] = []
        if archive_root.exists():
            for source_dir in sorted(archive_root.iterdir()):
                if source_dir.is_dir():
                    try:
                        sources.append(_source_disk_summary(source_dir))
                    except Exception as exc:
                        route_logger.warning("Error reading archive dir %s: %s", source_dir, exc)

        total_bytes = sum(s["total_bytes"] for s in sources)
        return jsonify({
            "sources": sources,
            "total_bytes": total_bytes,
            "total_bytes_human": _format_bytes(total_bytes),
            "total_files": sum(s["total_files"] for s in sources),
            "archive_dir": str(archive_root),
        })

    # ------------------------------------------------------------------
    # API: get settings for one source
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/settings", methods=["GET"])
    def api_audio_archive_get_settings(source_name: str):
        cfg = _get_archive_config(source_name)
        if cfg is None:
            return jsonify({"error": f"Source '{source_name}' not found"}), 404
        return jsonify({"source_name": source_name, "archive": cfg})

    # ------------------------------------------------------------------
    # API: save settings (does NOT start/stop archiver)
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/settings", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_save_settings(source_name: str):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        if not _save_archive_config(source_name, body):
            return jsonify({"error": f"Failed to save settings for '{source_name}'"}), 500
        cfg = _get_archive_config(source_name)
        return jsonify({"source_name": source_name, "archive": cfg, "saved": True})

    # ------------------------------------------------------------------
    # API: start archiver
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/start", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_start(source_name: str):
        body: Dict[str, Any] = request.get_json(silent=True) or {}

        # Merge any overrides from request body into existing config
        existing = _get_archive_config(source_name)
        if existing is None:
            return jsonify({"error": f"Source '{source_name}' not found"}), 404

        merged = dict(existing)
        merged.update(body)
        merged["enabled"] = True

        if not _save_archive_config(source_name, merged):
            return jsonify({"error": "Failed to save archive config"}), 500

        try:
            from app_core.audio.redis_commands import get_audio_command_publisher
            publisher = get_audio_command_publisher()
            result = publisher.start_archiver(source_name, merged)
            return jsonify({"source_name": source_name, "result": result})
        except Exception as exc:
            route_logger.error("archiver start command failed for '%s': %s", source_name, exc)
            return jsonify({
                "source_name": source_name,
                "result": {"success": False, "message": str(exc)},
            }), 500

    # ------------------------------------------------------------------
    # API: stop archiver
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/stop", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_stop(source_name: str):
        # Persist disabled state to DB
        _save_archive_config(source_name, {"enabled": False})

        try:
            from app_core.audio.redis_commands import get_audio_command_publisher
            publisher = get_audio_command_publisher()
            result = publisher.stop_archiver(source_name)
            return jsonify({"source_name": source_name, "result": result})
        except Exception as exc:
            route_logger.error("archiver stop command failed for '%s': %s", source_name, exc)
            return jsonify({
                "source_name": source_name,
                "result": {"success": False, "message": str(exc)},
            }), 500

    # ------------------------------------------------------------------
    # API: purge archive files
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/purge", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_purge(source_name: str):
        source_dir = archive_root / Path(source_name).name  # prevent path traversal
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        days_older_than = 0
        try:
            days_older_than = int(body.get("days_older_than", 0))
        except (TypeError, ValueError):
            pass

        route_logger.info(
            "Archive purge requested for '%s' (days_older_than=%d)",
            source_name, days_older_than,
        )
        result = _purge_source(source_dir, days_older_than=days_older_than)
        result["bytes_freed_human"] = _format_bytes(result["bytes_freed"])
        status = 200 if result["error"] is None else 500
        return jsonify(result), status

    # ------------------------------------------------------------------
    # API: list archive files for one source, grouped by date
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/files", methods=["GET"])
    def api_audio_archive_files(source_name: str):
        source_dir = archive_root / Path(source_name).name  # prevent path traversal
        if not source_dir.exists():
            return jsonify({"dates": []})

        cfg = _get_archive_config(source_name) or {}
        bitrate = cfg.get("bitrate", 128)

        dates: List[Dict[str, Any]] = []
        for date_dir in sorted(source_dir.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            files: List[Dict[str, Any]] = []
            for f in sorted(date_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in (".wav", ".mp3"):
                    try:
                        stat = f.stat()
                        duration = _estimate_file_duration(f, bitrate)
                        files.append({
                            "filename": f.name,
                            "date": date_dir.name,
                            "size_bytes": stat.st_size,
                            "size_human": _format_bytes(stat.st_size),
                            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "duration_seconds": round(duration, 1) if duration is not None else None,
                            "duration_human": _format_duration(duration) if duration is not None else None,
                        })
                    except OSError:
                        pass
            if files:
                day_duration = sum(f["duration_seconds"] or 0 for f in files)
                dates.append({
                    "date": date_dir.name,
                    "files": files,
                    "total_duration_seconds": round(day_duration, 1),
                    "total_duration_human": _format_duration(day_duration),
                })

        return jsonify({"source_name": source_name, "dates": dates})

    # ------------------------------------------------------------------
    # API: per-source archive statistics
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/stats", methods=["GET"])
    def api_audio_archive_stats(source_name: str):
        """Return rich statistics for one source's archive directory."""
        source_dir = archive_root / Path(source_name).name
        cfg = _get_archive_config(source_name) or {}
        bitrate = cfg.get("bitrate", 128)

        empty = {
            "source_name": source_name,
            "total_files": 0,
            "total_bytes": 0,
            "total_bytes_human": "0 B",
            "total_duration_seconds": 0.0,
            "total_duration_human": "0m 0s",
            "dates": [],
            "oldest_date": None,
            "newest_date": None,
            "top_songs": [],
            "top_artists": [],
        }

        if not source_dir.exists():
            return jsonify(empty)

        # ---- disk / duration breakdown per day ----
        day_rows: List[Dict[str, Any]] = []
        for date_dir in sorted(source_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            day_files = 0
            day_bytes = 0
            day_duration = 0.0
            for f in date_dir.iterdir():
                if f.is_file() and f.suffix.lower() in (".wav", ".mp3"):
                    try:
                        day_bytes += f.stat().st_size
                        day_files += 1
                        dur = _estimate_file_duration(f, bitrate)
                        if dur is not None:
                            day_duration += dur
                    except OSError:
                        pass
            if day_files:
                day_rows.append({
                    "date": date_dir.name,
                    "file_count": day_files,
                    "total_bytes": day_bytes,
                    "total_bytes_human": _format_bytes(day_bytes),
                    "duration_seconds": round(day_duration, 1),
                    "duration_human": _format_duration(day_duration),
                })

        total_files = sum(d["file_count"] for d in day_rows)
        total_bytes = sum(d["total_bytes"] for d in day_rows)
        total_duration = sum(d["duration_seconds"] for d in day_rows)

        # ---- top songs / artists from metadata log ----
        top_songs: List[Dict[str, Any]] = []
        top_artists: List[Dict[str, Any]] = []
        try:
            from app_core.models import StreamMetadataLog
            rows = (
                StreamMetadataLog.query
                .filter_by(source_name=source_name)
                .with_entities(
                    StreamMetadataLog.title,
                    StreamMetadataLog.artist,
                    StreamMetadataLog.album,
                    StreamMetadataLog.artwork_url,
                )
                .all()
            )

            song_counter: Counter = Counter()
            artist_counter: Counter = Counter()
            # Track artwork/album per title for display
            song_meta: Dict[str, Dict] = {}

            for r in rows:
                title = (r.title or "").strip()
                artist = (r.artist or "").strip()
                if title:
                    song_counter[title] += 1
                    if title not in song_meta:
                        song_meta[title] = {
                            "artist": artist,
                            "album": (r.album or "").strip(),
                            "artwork_url": r.artwork_url,
                        }
                if artist:
                    artist_counter[artist] += 1

            top_songs = [
                {
                    "title": title,
                    "count": count,
                    "artist": song_meta[title]["artist"],
                    "album": song_meta[title]["album"],
                    "artwork_url": song_meta[title]["artwork_url"],
                }
                for title, count in song_counter.most_common(10)
            ]
            top_artists = [
                {"artist": artist, "count": count}
                for artist, count in artist_counter.most_common(10)
            ]
        except Exception as exc:
            route_logger.warning("Could not compute top songs/artists for '%s': %s", source_name, exc)

        return jsonify({
            "source_name": source_name,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "total_bytes_human": _format_bytes(total_bytes),
            "total_duration_seconds": round(total_duration, 1),
            "total_duration_human": _format_duration(total_duration),
            "dates": day_rows,
            "oldest_date": day_rows[0]["date"] if day_rows else None,
            "newest_date": day_rows[-1]["date"] if day_rows else None,
            "top_songs": top_songs,
            "top_artists": top_artists,
        })

    # ------------------------------------------------------------------
    # API: serve / download one archive file
    # ------------------------------------------------------------------

    @app.route(
        "/api/audio/archives/<source_name>/files/<date>/<filename>",
        methods=["GET"],
    )
    def api_audio_archive_serve(source_name: str, date: str, filename: str):
        # Prevent path traversal in every segment
        safe_source = Path(source_name).name
        safe_date   = Path(date).name
        safe_file   = Path(filename).name

        file_path = archive_root / safe_source / safe_date / safe_file
        if not file_path.exists() or not file_path.is_file():
            return jsonify({"error": "File not found"}), 404

        suffix = file_path.suffix.lower()
        if suffix not in (".wav", ".mp3"):
            return jsonify({"error": "File type not served"}), 403

        mime = "audio/wav" if suffix == ".wav" else "audio/mpeg"
        as_attachment = request.args.get("download", "0") == "1"
        return send_file(
            file_path,
            mimetype=mime,
            as_attachment=as_attachment,
            download_name=safe_file,
            conditional=True,
        )

    # ------------------------------------------------------------------
    # API: stream metadata log (recent now-playing history)
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/metadata-log", methods=["GET"])
    def api_audio_archive_metadata_log(source_name: str):
        try:
            from sqlalchemy import or_
            from app_core.models import StreamMetadataLog

            limit_param = request.args.get("limit", "100").strip().lower()
            search = request.args.get("search", "").strip()

            if limit_param in ("all", "0", ""):
                limit = None  # No limit — return all matching rows
            else:
                try:
                    limit = max(1, min(int(limit_param), 10000))
                except (ValueError, TypeError):
                    limit = 100

            query = StreamMetadataLog.query.filter_by(source_name=source_name)

            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    or_(
                        StreamMetadataLog.title.ilike(search_term),
                        StreamMetadataLog.artist.ilike(search_term),
                        StreamMetadataLog.album.ilike(search_term),
                        StreamMetadataLog.display.ilike(search_term),
                        StreamMetadataLog.raw.ilike(search_term),
                    )
                )

            query = query.order_by(StreamMetadataLog.timestamp.desc())
            if limit is not None:
                query = query.limit(limit)

            hide_junk = request.args.get("hide_junk", "true").lower() != "false"

            rows = query.all()
            entries = []
            junk_hidden = 0
            for r in rows:
                if hide_junk and _is_junk_metadata(r.title, r.display, r.raw,
                                                   getattr(r, "stream_url", None)):
                    junk_hidden += 1
                    continue
                entries.append({
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "title": r.title,
                    "artist": r.artist,
                    "album": r.album,
                    "artwork_url": r.artwork_url,
                    "length": r.length,
                    "display": r.display,
                    "raw": r.raw,
                    "stream_url": getattr(r, "stream_url", None),
                })
            return jsonify({
                "source_name": source_name,
                "entries": entries,
                "total": len(entries),
                "junk_hidden": junk_hidden,
            })
        except Exception as exc:
            route_logger.error("metadata-log query failed for '%s': %s", source_name, exc)
            return jsonify({"source_name": source_name, "entries": [], "total": 0})

    # ------------------------------------------------------------------
    # API: clear (delete) the metadata log for one source
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/metadata-log", methods=["DELETE"])
    @require_permission('system.configure')
    def api_audio_archive_metadata_log_clear(source_name: str):
        try:
            from app_core.extensions import db
            from app_core.models import StreamMetadataLog
            deleted = (
                StreamMetadataLog.query
                .filter_by(source_name=source_name)
                .delete(synchronize_session=False)
            )
            db.session.commit()
            route_logger.info("Cleared %d metadata-log rows for '%s'", deleted, source_name)
            return jsonify({"source_name": source_name, "deleted": deleted})
        except Exception as exc:
            route_logger.error("metadata-log clear failed for '%s': %s", source_name, exc)
            return jsonify({"error": str(exc)}), 500

    # ------------------------------------------------------------------
    # API: remove junk (base64 blob) metadata entries
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/metadata-log/clean-junk", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_metadata_log_clean_junk(source_name: str):
        """Delete base64-blob junk entries from the metadata log for one source."""
        try:
            from app_core.extensions import db
            from app_core.models import StreamMetadataLog

            rows = (
                StreamMetadataLog.query
                .filter_by(source_name=source_name)
                .with_entities(StreamMetadataLog.id, StreamMetadataLog.title,
                               StreamMetadataLog.display, StreamMetadataLog.raw,
                               StreamMetadataLog.stream_url)
                .all()
            )
            junk_ids = [
                r.id for r in rows
                if _is_junk_metadata(r.title, r.display, r.raw,
                                     getattr(r, "stream_url", None))
            ]
            if junk_ids:
                StreamMetadataLog.query.filter(
                    StreamMetadataLog.id.in_(junk_ids)
                ).delete(synchronize_session=False)
                db.session.commit()

            route_logger.info(
                "Cleaned %d junk metadata-log rows for '%s'", len(junk_ids), source_name
            )
            return jsonify({"source_name": source_name, "deleted": len(junk_ids)})
        except Exception as exc:
            route_logger.error("metadata-log clean-junk failed for '%s': %s", source_name, exc)
            return jsonify({"error": str(exc)}), 500

    # ------------------------------------------------------------------
    # API: resolve a stream/ad URL to a playable audio URL
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/resolve-stream-url", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_resolve_stream_url():
        """Fetch a stream URL and resolve it to a direct playable audio URL.

        Handles three cases:
        1. Direct audio (audio/* content-type) — returns the URL as-is.
        2. VAST XML — parses the XML and returns the first audio MediaFile URL.
        3. Anything else — returns an error explaining it could not be resolved.
        """
        import ipaddress
        import socket as _socket
        import urllib.request
        import xml.etree.ElementTree as ET

        body = request.get_json(silent=True) or {}
        url = (body.get("url") or "").strip()

        if not url or not url.startswith(("http://", "https://")):
            return jsonify({"error": "Invalid or missing URL"}), 400

        # Block SSRF: reject URLs that resolve to private/loopback/link-local addresses
        try:
            from urllib.parse import urlparse as _urlparse
            _host = _urlparse(url).hostname or ""
            if not _host:
                return jsonify({"error": "Invalid or missing URL"}), 400
            _ip = ipaddress.ip_address(_socket.gethostbyname(_host))
            if _ip.is_private or _ip.is_loopback or _ip.is_link_local or _ip.is_reserved or _ip.is_multicast or _ip.is_unspecified:
                return jsonify({"error": "Invalid or missing URL"}), 400
        except (_socket.gaierror, ValueError):
            return jsonify({"error": "Invalid or missing URL"}), 400

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (EAS-Station)"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                content_type = (resp.headers.get("Content-Type") or "").lower()
                data = resp.read(2 * 1024 * 1024)  # cap at 2 MB

            # 1. Already a direct audio stream
            if any(ct in content_type for ct in ("audio/", "video/mp2t", "application/ogg")):
                return jsonify({"audio_url": url, "type": "direct"})

            # 2. Try VAST / XML parsing
            if "xml" in content_type or data.lstrip()[:5] in (b"<?xml", b"<VAST"):
                try:
                    root = ET.fromstring(data)
                    _audio_mimes = {
                        "audio/mpeg", "audio/mp3", "audio/mp4", "audio/aac",
                        "audio/ogg", "audio/wav", "audio/x-wav", "audio/webm",
                    }
                    for media_file in root.iter("MediaFile"):
                        mime = (media_file.get("type") or "").lower().strip()
                        audio_url = (media_file.text or "").strip()
                        if audio_url.startswith(("http://", "https://")) and (
                            mime in _audio_mimes or mime.startswith("audio/")
                        ):
                            return jsonify({
                                "audio_url": audio_url,
                                "type": "vast",
                                "mime": mime,
                                "original_url": url,
                            })
                    # VAST parsed but no audio MediaFile found
                    return jsonify({
                        "error": "VAST parsed but no audio MediaFile found",
                        "type": "vast_no_audio",
                        "original_url": url,
                    })
                except ET.ParseError as exc:
                    return jsonify({
                        "error": f"XML parse error: {exc}",
                        "type": "xml_error",
                        "original_url": url,
                    })

            # 3. Unknown format
            return jsonify({
                "error": f"Unrecognised content type: {content_type or '(none)'}",
                "type": "unknown",
                "original_url": url,
            })

        except Exception as exc:
            route_logger.warning("resolve-stream-url failed for %s: %s", url, exc)
            return jsonify({"error": str(exc)}), 500

    route_logger.info("Audio archive routes registered (archive_dir=%s)", archive_root)


__all__ = ["register"]
