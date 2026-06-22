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
Audio Archiver

Records audio from a source's BroadcastQueue to time-segmented files on disk.

Features:
- Configurable segment duration (default: 1 hour)
- WAV or MP3 output (MP3 requires FFmpeg with libmp3lame)
- Age-based retention pruning (default: 7 days)
- Disk-space quota enforcement (stops writing when quota is exceeded)
- Manual purge of all archives for a source
- Statistics for monitoring
"""

import logging
import os
import queue
import subprocess
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AudioArchiverConfig:
    """Configuration for the audio archiver."""

    # Where to write archive files.  Relative paths are relative to the
    # working directory of the process; absolute paths are used as-is.
    output_dir: str = "archives"

    # How long each audio segment file covers (seconds).
    segment_duration_seconds: int = 3600  # 1 hour

    # Delete files older than this many days.  Set to 0 to disable age pruning.
    retention_days: int = 7

    # Maximum total disk space (bytes) used by this source's archives.
    # When the quota is exceeded the oldest date directories are removed until
    # usage falls back below the limit.  Set to 0 to disable quota enforcement.
    max_disk_bytes: int = 0  # 0 = unlimited

    # Output format: "wav" (no extra dependencies) or "mp3" (requires FFmpeg).
    format: str = "wav"

    # MP3 bitrate in kbps (ignored for WAV).
    bitrate: int = 128

    # Silence detection: segments whose RMS amplitude is below this value are
    # skipped (not written to disk).  Useful for dropping dead-air segments
    # when a source is disconnected or not transmitting.
    # Set to 0.0 to disable.  Typical useful range: 0.001 – 0.01.
    silence_threshold: float = 0.0


class AudioArchiver:
    """
    Records audio from a source's BroadcastQueue to segmented files on disk.

    Each instance handles one audio source.  Call ``start()`` after the source
    is running and ``stop()`` before tearing down the source.

    Disk management
    ---------------
    Two independent mechanisms prevent the archive directory from growing
    without bound:

    1. **Age-based pruning** – directories older than ``retention_days`` are
       removed automatically at the start of each new segment.
    2. **Quota enforcement** – if the total size of *this source's* archive
       directory exceeds ``max_disk_bytes``, the oldest date directories are
       removed (oldest-first) until usage falls below the quota.  This runs
       after age pruning so the two mechanisms work together.

    Manual purge
    ------------
    Call :meth:`purge_all` to delete every archive file for this source
    immediately (e.g., triggered from a web UI button).
    """

    def __init__(
        self,
        source_name: str,
        config: AudioArchiverConfig,
        broadcast_queue,
        sample_rate: int = 44100,
        channels: int = 1,
    ):
        """
        Args:
            source_name: Human-readable identifier for this source (used in
                         log messages and as a sub-directory name).
            config: Archiver configuration.
            broadcast_queue: A :class:`BroadcastQueue` instance whose audio
                             chunks this archiver will subscribe to.
            sample_rate: Sample rate of the audio produced by *broadcast_queue*
                         (Hz).
            channels: Number of audio channels (1 = mono, 2 = stereo).
        """
        self.source_name = source_name
        self.config = config
        self._broadcast_queue = broadcast_queue
        self.sample_rate = sample_rate
        self.channels = channels

        self._subscriber_id = f"archiver-{source_name}"
        self._audio_queue: Optional[queue.Queue] = None

        self._stop_event = threading.Event()
        self._stop_event.set()  # Start in stopped state

        self._archive_thread: Optional[threading.Thread] = None
        self._current_segment_start: float = 0.0
        self._current_chunks: List[np.ndarray] = []

        # Statistics (written from archive thread, read from any thread)
        self._lock = threading.Lock()
        self._files_written: int = 0
        self._bytes_written: int = 0
        self._files_skipped_silence: int = 0
        self._last_file_path: Optional[str] = None
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start archiving audio from the broadcast queue.

        Returns:
            True if the archiver was started successfully.
        """
        if not self._stop_event.is_set():
            logger.warning("AudioArchiver for '%s' is already running", self.source_name)
            return False

        source_dir = self._source_dir()
        try:
            source_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.error(
                "AudioArchiver: cannot create output directory %s: %s",
                source_dir,
                exc,
            )
            self._set_error(str(exc))
            return False

        self._audio_queue = self._broadcast_queue.subscribe(self._subscriber_id)
        self._stop_event.clear()

        self._archive_thread = threading.Thread(
            target=self._archive_loop,
            name=f"archiver-{self.source_name}",
            daemon=True,
        )
        self._archive_thread.start()

        logger.info(
            "AudioArchiver started for '%s' -> %s (segment=%ds, retention=%dd, "
            "quota=%s, format=%s, silence_threshold=%s)",
            self.source_name,
            source_dir,
            self.config.segment_duration_seconds,
            self.config.retention_days,
            _format_bytes(self.config.max_disk_bytes) if self.config.max_disk_bytes else "unlimited",
            self.config.format,
            self.config.silence_threshold if self.config.silence_threshold > 0.0 else "disabled",
        )
        return True

    def stop(self) -> None:
        """Stop archiving and flush the current in-progress segment to disk."""
        if self._stop_event.is_set():
            return

        logger.info("AudioArchiver stopping for '%s'", self.source_name)
        self._stop_event.set()

        try:
            self._broadcast_queue.unsubscribe(self._subscriber_id)
        except Exception as exc:
            logger.warning("AudioArchiver: error unsubscribing '%s': %s", self.source_name, exc)

        self._audio_queue = None

        if self._archive_thread:
            self._archive_thread.join(timeout=30.0)
            self._archive_thread = None

        with self._lock:
            logger.info(
                "AudioArchiver stopped for '%s' (files: %d, total: %s)",
                self.source_name,
                self._files_written,
                _format_bytes(self._bytes_written),
            )

    def purge_all(self) -> Dict:
        """Delete all archive files for this source.

        Safe to call while the archiver is running; the archiver will
        continue recording new segments after the purge.

        Returns:
            A dict with keys ``files_deleted``, ``bytes_freed``, and ``error``
            (the last is ``None`` on success).
        """
        source_dir = self._source_dir()
        result: Dict = {"files_deleted": 0, "bytes_freed": 0, "error": None}

        if not source_dir.exists():
            return result

        try:
            for date_dir in sorted(source_dir.iterdir()):
                if not date_dir.is_dir():
                    continue
                for f in date_dir.iterdir():
                    if f.is_file():
                        try:
                            result["bytes_freed"] += f.stat().st_size
                            f.unlink()
                            result["files_deleted"] += 1
                        except Exception as exc:
                            logger.warning("AudioArchiver purge: could not delete %s: %s", f, exc)
                try:
                    date_dir.rmdir()
                except Exception:
                    pass

            logger.info(
                "AudioArchiver: purged %d files (%s) for '%s'",
                result["files_deleted"],
                _format_bytes(result["bytes_freed"]),
                self.source_name,
            )
        except Exception as exc:
            result["error"] = str(exc)
            logger.error("AudioArchiver: purge failed for '%s': %s", self.source_name, exc)

        return result

    def get_stats(self) -> Dict:
        """Return a snapshot of current archiver statistics."""
        with self._lock:
            return {
                "source_name": self.source_name,
                "running": not self._stop_event.is_set(),
                "output_dir": str(self._source_dir()),
                "segment_duration_seconds": self.config.segment_duration_seconds,
                "retention_days": self.config.retention_days,
                "max_disk_bytes": self.config.max_disk_bytes,
                "format": self.config.format,
                "files_written": self._files_written,
                "bytes_written": self._bytes_written,
                "files_skipped_silence": self._files_skipped_silence,
                "disk_usage_bytes": self._measure_disk_usage(),
                "last_file": self._last_file_path,
                "last_error": self._last_error,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _source_dir(self) -> Path:
        return Path(self.config.output_dir) / self.source_name

    def _set_error(self, message: Optional[str]) -> None:
        with self._lock:
            self._last_error = message

    # ------------------------------------------------------------------
    # Archive loop
    # ------------------------------------------------------------------

    def _archive_loop(self) -> None:
        logger.debug("AudioArchiver loop started for '%s'", self.source_name)

        self._current_segment_start = time.time()
        self._current_chunks = []

        # Write a short initial segment (max 5 min) so the UI shows something
        # quickly rather than waiting a full segment duration.
        _INITIAL_FLUSH_SECONDS = 300  # 5 minutes
        first_segment = True

        while not self._stop_event.is_set():
            now = time.time()
            segment_age = now - self._current_segment_start

            flush_after = (
                min(_INITIAL_FLUSH_SECONDS, self.config.segment_duration_seconds)
                if first_segment
                else self.config.segment_duration_seconds
            )

            if segment_age >= flush_after:
                self._flush_segment()
                self._current_segment_start = time.time()
                self._run_pruning()
                first_segment = False

            # Drain up to 200 chunks per iteration to stay responsive
            drained = 0
            audio_queue = self._audio_queue
            if audio_queue is not None:
                while drained < 200:
                    try:
                        chunk = audio_queue.get_nowait()
                        self._current_chunks.append(chunk)
                        drained += 1
                    except queue.Empty:
                        break

            if drained == 0:
                self._stop_event.wait(0.05)

        # Flush whatever is left when we are asked to stop
        if self._current_chunks:
            self._flush_segment()

        logger.debug("AudioArchiver loop stopped for '%s'", self.source_name)

    # ------------------------------------------------------------------
    # Segment writing
    # ------------------------------------------------------------------

    def _flush_segment(self) -> None:
        if not self._current_chunks:
            return

        seg_time = datetime.fromtimestamp(self._current_segment_start)
        date_dir = self._source_dir() / seg_time.strftime("%Y-%m-%d")
        try:
            date_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.error("AudioArchiver: cannot create date directory %s: %s", date_dir, exc)
            self._current_chunks.clear()
            return

        ext = "mp3" if self.config.format == "mp3" else "wav"
        filename = f"{self.source_name}_{seg_time.strftime('%Y-%m-%d_%H-%M-%S')}.{ext}"
        filepath = date_dir / filename

        # Concatenate all buffered chunks
        audio = np.concatenate(self._current_chunks).astype(np.float32)
        self._current_chunks = []

        duration_s = len(audio) / max(self.sample_rate, 1)

        # Silence detection — skip dead-air segments to avoid saving junk files
        if self.config.silence_threshold > 0.0:
            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < self.config.silence_threshold:
                with self._lock:
                    self._files_skipped_silence += 1
                logger.info(
                    "AudioArchiver: skipped silent segment for '%s' "
                    "(rms=%.6f < threshold=%.6f, %.1fs of audio discarded)",
                    self.source_name,
                    rms,
                    self.config.silence_threshold,
                    duration_s,
                )
                return

        try:
            if self.config.format == "mp3":
                self._write_mp3(audio, filepath)
            else:
                self._write_wav(audio, filepath)

            size = filepath.stat().st_size

            with self._lock:
                self._files_written += 1
                self._bytes_written += size
                self._last_file_path = str(filepath)
                self._last_error = None

            logger.info(
                "AudioArchiver: wrote %s (%s, %.1fs audio)",
                filepath.name,
                _format_bytes(size),
                duration_s,
            )
        except Exception as exc:
            self._set_error(str(exc))
            logger.error("AudioArchiver: failed to write segment %s: %s", filepath, exc)
            # Remove partial file if it exists
            try:
                if filepath.exists():
                    filepath.unlink()
            except Exception:
                pass

    def _write_wav(self, audio: np.ndarray, filepath: Path) -> None:
        """Write *audio* (float32, [-1, 1]) to a WAV file."""
        pcm = np.clip(audio, -1.0, 1.0)
        samples_int16 = (pcm * 32767.0).astype(np.int16)
        with wave.open(str(filepath), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit = 2 bytes per sample
            wf.setframerate(self.sample_rate)
            wf.writeframes(samples_int16.tobytes())

    def _write_mp3(self, audio: np.ndarray, filepath: Path) -> None:
        """Encode *audio* to MP3 via FFmpeg (requires libmp3lame)."""
        pcm = np.clip(audio, -1.0, 1.0)
        pcm_bytes = (pcm * 32767.0).astype(np.int16).tobytes()

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "s16le",
            "-ar", str(self.sample_rate),
            "-ac", str(self.channels),
            "-i", "pipe:0",
            "-acodec", "libmp3lame",
            "-b:a", f"{self.config.bitrate}k",
            str(filepath),
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            proc.communicate(input=pcm_bytes, timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError("FFmpeg timed out while encoding MP3")

        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg exited with code {proc.returncode}")

    # ------------------------------------------------------------------
    # Pruning / quota enforcement
    # ------------------------------------------------------------------

    def _run_pruning(self) -> None:
        """Run age-based pruning followed by quota enforcement."""
        self._prune_by_age()
        if self.config.max_disk_bytes > 0:
            self._enforce_quota()

    def _prune_by_age(self) -> None:
        """Remove date directories older than ``retention_days``."""
        if self.config.retention_days <= 0:
            return

        cutoff = datetime.now() - timedelta(days=self.config.retention_days)
        source_dir = self._source_dir()
        if not source_dir.exists():
            return

        deleted_files = 0
        deleted_bytes = 0

        for date_dir in sorted(source_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
            except ValueError:
                continue

            if dir_date >= cutoff:
                continue

            for f in date_dir.iterdir():
                if f.is_file():
                    try:
                        deleted_bytes += f.stat().st_size
                        f.unlink()
                        deleted_files += 1
                    except Exception as exc:
                        logger.warning("AudioArchiver: could not delete %s: %s", f, exc)
            try:
                date_dir.rmdir()
            except Exception:
                pass

        if deleted_files:
            logger.info(
                "AudioArchiver: age pruning removed %d file(s) (%s) for '%s'",
                deleted_files,
                _format_bytes(deleted_bytes),
                self.source_name,
            )

    def _enforce_quota(self) -> None:
        """Remove oldest date directories until total usage <= max_disk_bytes."""
        if self.config.max_disk_bytes <= 0:
            return

        source_dir = self._source_dir()
        if not source_dir.exists():
            return

        # Build sorted list of (date_dir, size_bytes) oldest-first
        date_dirs = []
        for d in source_dir.iterdir():
            if not d.is_dir():
                continue
            try:
                datetime.strptime(d.name, "%Y-%m-%d")
            except ValueError:
                continue
            size = _dir_size(d)
            date_dirs.append((d, size))

        date_dirs.sort(key=lambda x: x[0].name)  # alphabetical = chronological

        total = sum(s for _, s in date_dirs)
        if total <= self.config.max_disk_bytes:
            return

        logger.warning(
            "AudioArchiver: '%s' archive is %s, quota is %s — pruning oldest dirs",
            self.source_name,
            _format_bytes(total),
            _format_bytes(self.config.max_disk_bytes),
        )

        deleted_files = 0
        deleted_bytes = 0

        for date_dir, size in date_dirs:
            if total <= self.config.max_disk_bytes:
                break

            for f in date_dir.iterdir():
                if f.is_file():
                    try:
                        deleted_bytes += f.stat().st_size
                        f.unlink()
                        deleted_files += 1
                    except Exception as exc:
                        logger.warning("AudioArchiver: could not delete %s: %s", f, exc)
            try:
                date_dir.rmdir()
            except Exception:
                pass

            total -= size

        if deleted_files:
            logger.info(
                "AudioArchiver: quota enforcement removed %d file(s) (%s) for '%s' "
                "(usage now ~%s / %s)",
                deleted_files,
                _format_bytes(deleted_bytes),
                self.source_name,
                _format_bytes(total),
                _format_bytes(self.config.max_disk_bytes),
            )

    def _measure_disk_usage(self) -> int:
        """Return total bytes used by this source's archive directory."""
        return _dir_size(self._source_dir())


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------

def _dir_size(path: Path) -> int:
    """Recursively sum file sizes under *path*."""
    total = 0
    if not path.exists():
        return 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except Exception:
                pass
    return total


def _format_bytes(n: int) -> str:
    """Human-readable byte count."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


__all__ = ["AudioArchiver", "AudioArchiverConfig"]
