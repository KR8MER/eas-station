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

"""Automatic scheduled backup service for EAS Station.

Runs as a background daemon thread and triggers create_backup.py at the
configured interval.  Configuration is persisted in a JSON file inside the
backup directory so it survives application restarts.
"""

import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG: dict = {
    "enabled": False,
    "interval_hours": 24,
    "hour": 2,
    "include_media": True,
    "include_volumes": False,
    "keep_count": 7,
    "last_run": None,
    "last_run_success": None,
    "next_run": None,
}

_scheduler_instance: Optional["BackupScheduler"] = None
_scheduler_lock = threading.Lock()


class BackupScheduler:
    """Background scheduler that creates automatic backups on a fixed interval."""

    def __init__(self, backup_dir: Path) -> None:
        self.backup_dir = backup_dir
        self.config_file = backup_dir / "auto_backup.json"
        self._config: dict = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._load_config()

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Load config from disk, filling in defaults for missing keys."""
        config = dict(_DEFAULT_CONFIG)
        if self.config_file.exists():
            try:
                on_disk = json.loads(self.config_file.read_text())
                config.update({k: v for k, v in on_disk.items() if k in _DEFAULT_CONFIG})
            except Exception as exc:
                logger.warning("Could not read auto-backup config: %s", exc)
        with self._lock:
            self._config = config

    def _save_config(self) -> None:
        """Persist current config to disk."""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            self.config_file.write_text(json.dumps(self._config, indent=2))
        except Exception as exc:
            logger.error("Could not save auto-backup config: %s", exc)

    def get_config(self) -> dict:
        with self._lock:
            return dict(self._config)

    def update_config(self, updates: dict) -> dict:
        """Merge *updates* into the config and save.  Returns the new config."""
        allowed = set(_DEFAULT_CONFIG.keys()) - {"last_run", "last_run_success", "next_run"}
        with self._lock:
            for key, value in updates.items():
                if key in allowed:
                    self._config[key] = value
            if self._config.get("enabled"):
                self._config["next_run"] = self._compute_next_run().isoformat()
            else:
                self._config["next_run"] = None
            self._save_config()
            return dict(self._config)

    # ------------------------------------------------------------------
    # Scheduling logic
    # ------------------------------------------------------------------

    def _compute_next_run(self) -> datetime:
        """Return the UTC datetime of the next scheduled backup."""
        now = datetime.now(timezone.utc)
        interval = timedelta(hours=max(1, self._config.get("interval_hours", 24)))
        last_raw = self._config.get("last_run")
        if last_raw:
            try:
                last = datetime.fromisoformat(last_raw)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                candidate = last + interval
                if candidate > now:
                    return candidate
            except Exception:
                pass
        # No previous run or it's overdue – schedule from the configured hour
        target_hour = int(self._config.get("hour", 2))
        candidate = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        # But don't wait longer than the full interval from now
        return min(candidate, now + interval)

    def _should_run_now(self) -> bool:
        if not self._config.get("enabled"):
            return False
        next_raw = self._config.get("next_run")
        if not next_raw:
            return False
        try:
            next_run = datetime.fromisoformat(next_raw)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) >= next_run
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Backup execution
    # ------------------------------------------------------------------

    def _run_backup(self, label: str = "auto") -> bool:
        """Run create_backup.py and return True on success."""
        script = Path(__file__).parent.parent / "tools" / "create_backup.py"
        if not script.exists():
            logger.error("Backup script not found: %s", script)
            return False

        args = [sys.executable, str(script),
                "--output-dir", str(self.backup_dir),
                "--label", label]
        if not self._config.get("include_media", True):
            args.append("--no-media")
        if not self._config.get("include_volumes", False):
            args.append("--no-volumes")

        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=3600)
            if result.returncode == 0:
                logger.info("Auto-backup completed successfully")
                self._prune_old_backups()
                return True
            else:
                logger.error("Auto-backup failed (rc=%d): %s", result.returncode, result.stderr)
                return False
        except subprocess.TimeoutExpired:
            logger.error("Auto-backup timed out after 1 hour")
            return False
        except Exception as exc:
            logger.error("Auto-backup error: %s", exc)
            return False

    def _prune_old_backups(self) -> None:
        """Delete oldest auto-backups beyond keep_count."""
        keep = int(self._config.get("keep_count", 7))
        if keep <= 0:
            return
        try:
            auto_dirs = sorted(
                [d for d in self.backup_dir.iterdir()
                 if d.is_dir() and d.name.startswith("backup-") and d.name.endswith("-auto")],
                key=lambda d: d.name,
            )
            for old in auto_dirs[:-keep]:
                import shutil
                shutil.rmtree(old, ignore_errors=True)
                logger.info("Pruned old auto-backup: %s", old.name)
        except Exception as exc:
            logger.warning("Failed to prune old backups: %s", exc)

    def trigger_now(self) -> bool:
        """Run a backup immediately (called from API, not from the scheduler loop)."""
        logger.info("Auto-backup triggered manually")
        success = self._run_backup(label="auto-manual")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._config["last_run"] = now
            self._config["last_run_success"] = success
            self._config["next_run"] = self._compute_next_run().isoformat()
            self._save_config()
        return success

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="backup-scheduler")
        self._thread.start()
        logger.info("Backup scheduler started")

    def stop(self) -> None:
        self._running = False
        logger.info("Backup scheduler stopped")

    def _loop(self) -> None:
        while self._running:
            try:
                self._load_config()
                if self._should_run_now():
                    logger.info("Running scheduled auto-backup")
                    success = self._run_backup(label="auto")
                    now = datetime.now(timezone.utc).isoformat()
                    with self._lock:
                        self._config["last_run"] = now
                        self._config["last_run_success"] = success
                        self._config["next_run"] = self._compute_next_run().isoformat()
                        self._save_config()
            except Exception as exc:
                logger.error("Error in backup scheduler loop: %s", exc, exc_info=True)
            time.sleep(60)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def get_scheduler(backup_dir: Optional[Path] = None) -> BackupScheduler:
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is None:
            if backup_dir is None:
                backup_dir = Path("/var/backups/eas-station")
            _scheduler_instance = BackupScheduler(backup_dir)
    return _scheduler_instance


def start_scheduler(app) -> None:
    """Start the global backup scheduler using the Flask app's BACKUP_DIR config."""
    backup_dir = Path(app.config.get("BACKUP_DIR", "/var/backups/eas-station"))
    scheduler = get_scheduler(backup_dir)
    scheduler.start()


def stop_scheduler() -> None:
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None:
            _scheduler_instance.stop()
            _scheduler_instance = None


__all__ = ["BackupScheduler", "get_scheduler", "start_scheduler", "stop_scheduler"]
