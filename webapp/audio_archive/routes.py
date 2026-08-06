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
Audio Archive Management Routes

All archive management is performed from the web UI — no CLI required.
Navigate to **Settings → Audio → Audio Archives** (``/admin/audio/archives``).

Endpoints
---------
GET  /admin/audio/archives
     Full management dashboard (HTML).

GET  /api/audio/archives
     Disk stats for every source archive directory (no DB lookup).

GET  /api/audio/archives/sources
     Every configured source with its archive settings and disk usage.

GET|POST /api/audio/archives/<source>/settings
     Read / save archiver settings.  POST does not start or stop the archiver.

POST /api/audio/archives/<source>/start | /stop
     Persist enabled state and send the matching Redis command to audio-service.

POST /api/audio/archives/<source>/purge
     Delete archive files.  Body (optional): ``{"days_older_than": N}``

GET  /api/audio/archives/<source>/files
     Archived files grouped by date.

GET  /api/audio/archives/<source>/files/<date>/<filename>
     Stream or download one archived file (``?download=1`` to download).

GET  /api/audio/archives/<source>/stats
     Per-day breakdown plus top songs / artists.

GET|DELETE /api/audio/archives/<source>/metadata-log
     Read / clear the ICY now-playing history.

POST /api/audio/archives/<source>/metadata-log/clean-junk
     Delete base64-blob junk rows from the history.

POST /api/audio/archives/resolve-stream-url
     Resolve an ad/stream URL (following VAST) to a playable audio URL.
"""

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request, send_file

from app_core.auth.roles import require_permission

from .config import (
    all_sources_with_archive_config,
    get_archive_config,
    save_archive_config,
)
from .fsutil import (
    AUDIO_SUFFIXES,
    estimate_file_duration,
    format_bytes,
    format_duration,
    purge_source,
    source_disk_summary,
)
from .metadata import is_junk_metadata, resolve_stream_url

logger = logging.getLogger(__name__)

DEFAULT_ARCHIVE_DIR = "archives"


def register(app: Flask, logger_arg, archive_dir: str = DEFAULT_ARCHIVE_DIR) -> None:
    """Attach audio archive management routes to *app*."""

    route_logger = logger_arg.getChild("routes_audio_archive")
    archive_root = Path(archive_dir)

    def _source_dir(source_name: str) -> Path:
        """Return the archive directory for *source_name*, blocking traversal."""
        return archive_root / Path(source_name).name

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
        sources = all_sources_with_archive_config()

        for s in sources:
            disk = source_disk_summary(_source_dir(s["source_name"]))
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
                        sources.append(source_disk_summary(source_dir))
                    except OSError as exc:
                        route_logger.warning("Error reading archive dir %s: %s", source_dir, exc)

        total_bytes = sum(s["total_bytes"] for s in sources)
        return jsonify({
            "sources": sources,
            "total_bytes": total_bytes,
            "total_bytes_human": format_bytes(total_bytes),
            "total_files": sum(s["total_files"] for s in sources),
            "archive_dir": str(archive_root),
        })

    # ------------------------------------------------------------------
    # API: get / save settings
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/settings", methods=["GET"])
    def api_audio_archive_get_settings(source_name: str):
        cfg = get_archive_config(source_name)
        if cfg is None:
            return jsonify({"error": f"Source '{source_name}' not found"}), 404
        return jsonify({"source_name": source_name, "archive": cfg})

    @app.route("/api/audio/archives/<source_name>/settings", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_save_settings(source_name: str):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        if not save_archive_config(source_name, body):
            return jsonify({"error": f"Failed to save settings for '{source_name}'"}), 500
        cfg = get_archive_config(source_name)
        route_logger.info("Saved archive settings for '%s'", source_name)
        return jsonify({"source_name": source_name, "archive": cfg, "saved": True})

    # ------------------------------------------------------------------
    # API: start / stop archiver
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/start", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_start(source_name: str):
        body: Dict[str, Any] = request.get_json(silent=True) or {}

        existing = get_archive_config(source_name)
        if existing is None:
            return jsonify({"error": f"Source '{source_name}' not found"}), 404

        merged = dict(existing)
        merged.update(body)
        merged["enabled"] = True

        if not save_archive_config(source_name, merged):
            return jsonify({"error": "Failed to save archive config"}), 500

        # Re-read so the archiver is handed the normalised values that were
        # actually persisted, not the raw request body.
        merged = get_archive_config(source_name) or merged

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

    @app.route("/api/audio/archives/<source_name>/stop", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_stop(source_name: str):
        save_archive_config(source_name, {"enabled": False})

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
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        try:
            days_older_than = max(0, int(body.get("days_older_than", 0)))
        except (TypeError, ValueError):
            days_older_than = 0

        route_logger.info(
            "Archive purge requested for '%s' (days_older_than=%d)",
            source_name, days_older_than,
        )
        result = purge_source(_source_dir(source_name), days_older_than=days_older_than)
        result["bytes_freed_human"] = format_bytes(result["bytes_freed"])
        status = 200 if result["error"] is None else 500
        return jsonify(result), status

    # ------------------------------------------------------------------
    # API: list archive files for one source, grouped by date
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/files", methods=["GET"])
    def api_audio_archive_files(source_name: str):
        source_dir = _source_dir(source_name)
        if not source_dir.exists():
            return jsonify({"source_name": source_name, "dates": []})

        cfg = get_archive_config(source_name) or {}
        bitrate = cfg.get("bitrate", 128)

        dates: List[Dict[str, Any]] = []
        for date_dir in sorted(source_dir.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            files: List[Dict[str, Any]] = []
            for f in sorted(date_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES:
                    try:
                        stat = f.stat()
                    except OSError:
                        continue
                    duration = estimate_file_duration(f, bitrate)
                    files.append({
                        "filename": f.name,
                        "date": date_dir.name,
                        "size_bytes": stat.st_size,
                        "size_human": format_bytes(stat.st_size),
                        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "duration_seconds": round(duration, 1) if duration is not None else None,
                        "duration_human": format_duration(duration) if duration is not None else None,
                    })
            if files:
                day_duration = sum(f["duration_seconds"] or 0 for f in files)
                dates.append({
                    "date": date_dir.name,
                    "files": files,
                    "total_duration_seconds": round(day_duration, 1),
                    "total_duration_human": format_duration(day_duration),
                })

        return jsonify({"source_name": source_name, "dates": dates})

    # ------------------------------------------------------------------
    # API: per-source archive statistics
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/stats", methods=["GET"])
    def api_audio_archive_stats(source_name: str):
        """Return per-day disk/duration totals plus top songs and artists."""
        source_dir = _source_dir(source_name)
        cfg = get_archive_config(source_name) or {}
        bitrate = cfg.get("bitrate", 128)

        day_rows: List[Dict[str, Any]] = []
        if source_dir.exists():
            for date_dir in sorted(source_dir.iterdir()):
                if not date_dir.is_dir():
                    continue
                day_files = 0
                day_bytes = 0
                day_duration = 0.0
                for f in date_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES:
                        try:
                            day_bytes += f.stat().st_size
                        except OSError:
                            continue
                        day_files += 1
                        dur = estimate_file_duration(f, bitrate)
                        if dur is not None:
                            day_duration += dur
                if day_files:
                    day_rows.append({
                        "date": date_dir.name,
                        "file_count": day_files,
                        "total_bytes": day_bytes,
                        "total_bytes_human": format_bytes(day_bytes),
                        "duration_seconds": round(day_duration, 1),
                        "duration_human": format_duration(day_duration),
                    })

        total_files = sum(d["file_count"] for d in day_rows)
        total_bytes = sum(d["total_bytes"] for d in day_rows)
        total_duration = sum(d["duration_seconds"] for d in day_rows)
        top_songs, top_artists = _top_songs_and_artists(source_name, route_logger)

        return jsonify({
            "source_name": source_name,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "total_bytes_human": format_bytes(total_bytes),
            "total_duration_seconds": round(total_duration, 1),
            "total_duration_human": format_duration(total_duration),
            "dates": day_rows,
            "oldest_date": day_rows[0]["date"] if day_rows else None,
            "newest_date": day_rows[-1]["date"] if day_rows else None,
            "top_songs": top_songs,
            "top_artists": top_artists,
        })

    # ------------------------------------------------------------------
    # API: serve / download one archive file
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/<source_name>/files/<date>/<filename>", methods=["GET"])
    def api_audio_archive_serve(source_name: str, date: str, filename: str):
        # Prevent path traversal in every segment
        file_path = _source_dir(source_name) / Path(date).name / Path(filename).name
        if not file_path.exists() or not file_path.is_file():
            return jsonify({"error": "File not found"}), 404

        suffix = file_path.suffix.lower()
        if suffix not in AUDIO_SUFFIXES:
            return jsonify({"error": "File type not served"}), 403

        return send_file(
            file_path,
            mimetype="audio/wav" if suffix == ".wav" else "audio/mpeg",
            as_attachment=request.args.get("download", "0") == "1",
            download_name=file_path.name,
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
                limit = None
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

            entries = []
            junk_hidden = 0
            for r in query.all():
                stream_url = getattr(r, "stream_url", None)
                if hide_junk and is_junk_metadata(r.title, r.display, r.raw, stream_url):
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
                    "stream_url": stream_url,
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
            _rollback()
            route_logger.error("metadata-log clear failed for '%s': %s", source_name, exc)
            return jsonify({"error": str(exc)}), 500

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
                if is_junk_metadata(r.title, r.display, r.raw, getattr(r, "stream_url", None))
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
            _rollback()
            route_logger.error("metadata-log clean-junk failed for '%s': %s", source_name, exc)
            return jsonify({"error": str(exc)}), 500

    # ------------------------------------------------------------------
    # API: resolve a stream/ad URL to a playable audio URL
    # ------------------------------------------------------------------

    @app.route("/api/audio/archives/resolve-stream-url", methods=["POST"])
    @require_permission('system.configure')
    def api_audio_archive_resolve_stream_url():
        body = request.get_json(silent=True) or {}
        url = (body.get("url") or "").strip()
        if not url:
            return jsonify({"error": "Invalid or missing URL"}), 400

        result = resolve_stream_url(url)
        if result.get("type") == "rejected":
            return jsonify(result), 400
        if result.get("type") == "fetch_error":
            return jsonify(result), 500
        return jsonify(result)

    route_logger.info("Audio archive routes registered (archive_dir=%s)", archive_root)


def _rollback() -> None:
    """Roll back the current session, ignoring failures during error handling."""
    try:
        from app_core.extensions import db
        db.session.rollback()
    except Exception:
        pass


def _top_songs_and_artists(source_name: str, route_logger) -> tuple:
    """Return ``(top_songs, top_artists)`` for *source_name* from the metadata log."""
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
    except Exception as exc:
        route_logger.warning("Could not compute top songs/artists for '%s': %s", source_name, exc)
        return [], []

    song_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    song_meta: Dict[str, Dict[str, Any]] = {}

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
        {"title": title, "count": count, **song_meta[title]}
        for title, count in song_counter.most_common(10)
    ]
    top_artists = [
        {"artist": artist, "count": count}
        for artist, count in artist_counter.most_common(10)
    ]
    return top_songs, top_artists


__all__ = ["register"]
