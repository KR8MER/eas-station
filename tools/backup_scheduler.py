#!/usr/bin/env python3
"""Automated backup scheduler for EAS Station.

This script orchestrates regular backups, applies retention policies, and logs results.
It can be run manually, via cron, or systemd timer.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(log_file: Optional[Path] = None, verbose: bool = False) -> logging.Logger:
    """Configure logging for the backup scheduler.

    Args:
        log_file: Optional path to log file
        verbose: Enable verbose logging

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("backup_scheduler")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def run_backup(
    output_dir: Path,
    label: Optional[str] = None,
    include_media: bool = True,
    include_volumes: bool = True,
    logger: Optional[logging.Logger] = None,
) -> tuple[bool, Optional[Path]]:
    """Execute a backup using create_backup.py.

    Args:
        output_dir: Directory to store backups
        label: Optional label for the backup
        include_media: Include media files in backup
        include_volumes: Include Docker volumes in backup
        logger: Logger instance

    Returns:
        Tuple of (success, backup_directory_path)
    """
    if logger:
        logger.info("Starting backup creation...")

    script_dir = Path(__file__).parent
    backup_script = script_dir / "create_backup.py"

    if not backup_script.exists():
        if logger:
            logger.error(f"Backup script not found: {backup_script}")
        return False, None

    cmd = [sys.executable, str(backup_script), "--output-dir", str(output_dir)]

    if label:
        cmd.extend(["--label", label])

    if not include_media:
        cmd.append("--no-media")

    if not include_volumes:
        cmd.append("--no-volumes")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
        )

        if result.returncode != 0:
            if logger:
                logger.error(f"Backup failed: {result.stderr}")
            return False, None

        # Parse output to find backup directory
        backup_dir = None
        for line in result.stdout.splitlines():
            if "Backup completed successfully!" in line or "Location:" in line:
                # Extract path from next line or current line
                continue
            if "backups/" in line or "/backup-" in line:
                # Try to extract the path
                parts = line.split()
                for part in parts:
                    if "backup-" in part:
                        backup_dir = Path(part.strip())
                        break

        if logger:
            logger.info("Backup created successfully")
            if backup_dir:
                logger.info(f"Backup location: {backup_dir}")

        return True, backup_dir

    except subprocess.TimeoutExpired:
        if logger:
            logger.error("Backup timed out after 1 hour")
        return False, None
    except Exception as exc:
        if logger:
            logger.error(f"Backup failed with exception: {exc}")
        return False, None


def run_rotation(
    backup_dir: Path,
    keep_daily: int = 7,
    keep_weekly: int = 4,
    keep_monthly: int = 6,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """Execute backup rotation using rotate_backups.py.

    Args:
        backup_dir: Directory containing backups
        keep_daily: Number of daily backups to keep
        keep_weekly: Number of weekly backups to keep
        keep_monthly: Number of monthly backups to keep
        logger: Logger instance

    Returns:
        True if rotation succeeded, False otherwise
    """
    if logger:
        logger.info("Running backup rotation...")

    script_dir = Path(__file__).parent
    rotation_script = script_dir / "rotate_backups.py"

    if not rotation_script.exists():
        if logger:
            logger.warning(f"Rotation script not found: {rotation_script}")
        return False

    cmd = [
        sys.executable,
        str(rotation_script),
        "--backup-dir", str(backup_dir),
        "--keep-daily", str(keep_daily),
        "--keep-weekly", str(keep_weekly),
        "--keep-monthly", str(keep_monthly),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )

        if result.returncode != 0:
            if logger:
                logger.error(f"Rotation failed: {result.stderr}")
            return False

        if logger:
            # Log rotation summary
            for line in result.stdout.splitlines():
                if "Summary:" in line or "kept" in line.lower() or "deleted" in line.lower():
                    logger.info(line.strip())

        return True

    except subprocess.TimeoutExpired:
        if logger:
            logger.error("Rotation timed out after 10 minutes")
        return False
    except Exception as exc:
        if logger:
            logger.error(f"Rotation failed with exception: {exc}")
        return False


def send_notification(
    success: bool,
    backup_dir: Optional[Path],
    error_message: Optional[str] = None,
    email: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Send notification about backup status.

    Args:
        success: Whether backup succeeded
        backup_dir: Path to backup directory
        error_message: Error message if backup failed
        email: Email address to send notification to
        logger: Logger instance
    """
    if not email:
        return

    subject = "EAS Station Backup " + ("Successful" if success else "FAILED")

    if success:
        body = f"""
EAS Station automated backup completed successfully.

Backup Location: {backup_dir}
Timestamp: {datetime.now().isoformat()}

This is an automated message from the EAS Station backup scheduler.
"""
    else:
        body = f"""
EAS Station automated backup FAILED!

Error: {error_message or "Unknown error"}
Timestamp: {datetime.now().isoformat()}

Please investigate immediately.

This is an automated message from the EAS Station backup scheduler.
"""

    try:
        # Try to send email using mail command
        mail_cmd = ["mail", "-s", subject, email]
        result = subprocess.run(
            mail_cmd,
            input=body,
            text=True,
            capture_output=True,
            timeout=30,
        )

        if result.returncode == 0 and logger:
            logger.info(f"Notification sent to {email}")

    except FileNotFoundError:
        if logger:
            logger.warning("mail command not found, skipping email notification")
    except Exception as exc:
        if logger:
            logger.warning(f"Failed to send notification: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated backup scheduler for EAS Station",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Modes:

  1. Manual execution:
     python backup_scheduler.py

  2. Cron job (daily at 2 AM):
     0 2 * * * /usr/bin/python3 /path/to/backup_scheduler.py --label scheduled

  3. Systemd timer:
     See examples/systemd/eas-backup.timer and eas-backup.service

Configuration:
  The scheduler uses the following retention policy by default:
  - Keep 7 daily backups
  - Keep 4 weekly backups (Sundays)
  - Keep 6 monthly backups (1st of month)

Examples:
  # Run backup with default settings
  python backup_scheduler.py

  # Custom retention policy
  python backup_scheduler.py --keep-daily 14 --keep-weekly 8 --keep-monthly 12

  # Database and config only (fast)
  python backup_scheduler.py --no-media --no-volumes

  # With email notification
  python backup_scheduler.py --notify admin@example.com

  # Verbose logging
  python backup_scheduler.py --verbose --log-file /var/log/eas-backup.log
        """,
    )
    parser.add_argument(
        "--output-dir",
        default="backups",
        help="Directory to store backups (default: backups)",
    )
    parser.add_argument(
        "--label",
        default="scheduled",
        help="Label for backup (default: scheduled)",
    )
    parser.add_argument(
        "--no-media",
        action="store_true",
        help="Skip backing up media files",
    )
    parser.add_argument(
        "--no-volumes",
        action="store_true",
        help="Skip backing up Docker volumes",
    )
    parser.add_argument(
        "--keep-daily",
        type=int,
        default=7,
        help="Number of daily backups to keep (default: 7)",
    )
    parser.add_argument(
        "--keep-weekly",
        type=int,
        default=4,
        help="Number of weekly backups to keep (default: 4)",
    )
    parser.add_argument(
        "--keep-monthly",
        type=int,
        default=6,
        help="Number of monthly backups to keep (default: 6)",
    )
    parser.add_argument(
        "--skip-rotation",
        action="store_true",
        help="Skip backup rotation after creation",
    )
    parser.add_argument(
        "--notify",
        metavar="EMAIL",
        help="Send email notification to this address",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Log file path (default: no file logging)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.log_file, args.verbose)

    logger.info("=" * 60)
    logger.info("EAS Station Automated Backup")
    logger.info("=" * 60)
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info(f"Output directory: {args.output_dir}")
    logger.info(f"Label: {args.label}")
    logger.info(f"Retention: {args.keep_daily}d / {args.keep_weekly}w / {args.keep_monthly}m")
    logger.info("")

    output_dir = Path(args.output_dir).resolve()

    # Run backup
    success, backup_dir = run_backup(
        output_dir=output_dir,
        label=args.label,
        include_media=not args.no_media,
        include_volumes=not args.no_volumes,
        logger=logger,
    )

    error_message = None

    if not success:
        error_message = "Backup creation failed"
        logger.error(error_message)
        send_notification(False, None, error_message, args.notify, logger)
        sys.exit(1)

    # Run rotation
    if not args.skip_rotation:
        rotation_success = run_rotation(
            backup_dir=output_dir,
            keep_daily=args.keep_daily,
            keep_weekly=args.keep_weekly,
            keep_monthly=args.keep_monthly,
            logger=logger,
        )

        if not rotation_success:
            logger.warning("Rotation failed, but backup was created successfully")

    logger.info("")
    logger.info("=" * 60)
    logger.info("Backup completed successfully")
    logger.info(f"Finished at: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # Send success notification
    send_notification(True, backup_dir, None, args.notify, logger)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nBackup cancelled by user")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 - surface meaningful errors to operators
        logging.error(f"Backup scheduler failed: {exc}", exc_info=True)
        sys.exit(1)
