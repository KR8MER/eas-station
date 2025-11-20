#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Restore an EAS Station backup with validation and safety checks."""

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def load_metadata(backup_dir: Path) -> Dict:
    """Load and validate backup metadata.

    Args:
        backup_dir: Directory containing the backup

    Returns:
        Dictionary containing backup metadata

    Raises:
        FileNotFoundError: If metadata.json doesn't exist
        ValueError: If metadata is invalid
    """
    metadata_path = backup_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Backup metadata not found: {metadata_path}")

    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid metadata.json: {exc}") from exc

    required_fields = ["timestamp", "app_version", "database"]
    for field in required_fields:
        if field not in metadata:
            raise ValueError(f"Missing required field in metadata: {field}")

    return metadata


def validate_backup(backup_dir: Path) -> tuple[bool, List[str]]:
    """Validate backup integrity.

    Args:
        backup_dir: Directory containing the backup

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    # Check metadata
    try:
        metadata = load_metadata(backup_dir)
    except Exception as exc:
        issues.append(f"Metadata validation failed: {exc}")
        return False, issues

    # Check database dump
    db_dump = backup_dir / "alerts_database.sql"
    if not db_dump.exists():
        issues.append("Database dump file not found")
    elif db_dump.stat().st_size == 0:
        issues.append("Database dump file is empty")

    # Check configuration files
    env_file = backup_dir / ".env"
    if not env_file.exists():
        issues.append("Configuration file .env not found")

    # Report summary
    summary = metadata.get("summary", {})
    media_count = len(summary.get("media", []))
    volume_count = len(summary.get("volumes", []))

    print(f"Backup validation for: {backup_dir.name}")
    print(f"  Created: {metadata.get('timestamp')}")
    print(f"  Version: {metadata.get('app_version')}")
    print(f"  Database: {'✓' if db_dump.exists() else '✗'}")
    print(f"  Config: {'✓' if env_file.exists() else '✗'}")
    print(f"  Media archives: {media_count}")
    print(f"  Docker volumes: {volume_count}")

    return len(issues) == 0, issues


def confirm_action(prompt: str, default: bool = False) -> bool:
    """Prompt user for confirmation.

    Args:
        prompt: Question to ask
        default: Default response if user just presses Enter

    Returns:
        True if user confirms, False otherwise
    """
    choices = " [Y/n]" if default else " [y/N]"
    response = input(prompt + choices + ": ").strip().lower()

    if not response:
        return default

    return response in {"y", "yes"}


def detect_compose_command() -> List[str]:
    """Detect available Docker Compose command."""
    docker_path = shutil.which("docker")
    legacy_path = shutil.which("docker-compose")

    if docker_path:
        probe = subprocess.run(
            [docker_path, "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return [docker_path, "compose"]

    if legacy_path:
        return [legacy_path]

    return []


def read_env(path: Path) -> Dict[str, str]:
    """Read environment variables from .env file."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def restore_database(backup_dir: Path, env_values: Dict[str, str], force: bool = False) -> bool:
    """Restore PostgreSQL database from backup.

    Args:
        backup_dir: Directory containing the backup
        env_values: Environment variables from .env
        force: Skip confirmation prompts

    Returns:
        True if restoration succeeded, False otherwise
    """
    db_dump = backup_dir / "alerts_database.sql"
    if not db_dump.exists():
        print("  ✗ Database dump not found")
        return False

    if not force:
        print("\n  WARNING: This will OVERWRITE the current database!")
        print("  All existing data will be replaced with the backup.")
        if not confirm_action("  Continue with database restoration?", default=False):
            print("  - Database restoration skipped")
            return False

    host = env_values.get("POSTGRES_HOST", "localhost")
    port = env_values.get("POSTGRES_PORT", "5432")
    user = env_values.get("POSTGRES_USER", "postgres")
    db_name = env_values.get("POSTGRES_DB", "alerts")
    password = env_values.get("POSTGRES_PASSWORD", "")

    compose_cmd = detect_compose_command()
    use_compose = host in {"alerts-db", "postgres", "postgresql"}

    # Drop and recreate database
    print("  Recreating database...")
    if use_compose:
        drop_cmd = [
            *compose_cmd, "exec", "-T", "alerts-db",
            "psql", "-U", user, "-c", f"DROP DATABASE IF EXISTS {db_name}"
        ]
        create_cmd = [
            *compose_cmd, "exec", "-T", "alerts-db",
            "psql", "-U", user, "-c", f"CREATE DATABASE {db_name}"
        ]
        restore_cmd = [
            *compose_cmd, "exec", "-T", "alerts-db",
            "psql", "-U", user, "-d", db_name
        ]
    else:
        drop_cmd = [
            "psql", "-h", host, "-p", port, "-U", user,
            "-c", f"DROP DATABASE IF EXISTS {db_name}"
        ]
        create_cmd = [
            "psql", "-h", host, "-p", port, "-U", user,
            "-c", f"CREATE DATABASE {db_name}"
        ]
        restore_cmd = [
            "psql", "-h", host, "-p", port, "-U", user, "-d", db_name
        ]

    env_vars = dict(os.environ) if 'os' in dir() else {}
    import os
    env_vars = os.environ.copy()
    if password:
        env_vars["PGPASSWORD"] = password

    # Execute restoration
    try:
        subprocess.run(drop_cmd, env=env_vars, check=True, capture_output=True)
        subprocess.run(create_cmd, env=env_vars, check=True, capture_output=True)

        with db_dump.open("rb") as dump_file:
            result = subprocess.run(
                restore_cmd,
                stdin=dump_file,
                env=env_vars,
                capture_output=True
            )

        if result.returncode != 0:
            print(f"  ✗ Database restoration failed: {result.stderr.decode()}")
            return False

        print("  ✓ Database restored successfully")
        return True

    except subprocess.CalledProcessError as exc:
        print(f"  ✗ Database restoration failed: {exc}")
        return False


def restore_media(backup_dir: Path, force: bool = False) -> int:
    """Restore media directories from backup.

    Args:
        backup_dir: Directory containing the backup
        force: Skip confirmation prompts

    Returns:
        Number of media archives restored
    """
    media_archives = {
        "eas-messages.tar.gz": "static/eas_messages",
        "uploads.tar.gz": "static/uploads",
        "app-uploads.tar.gz": "uploads",
    }

    restored = 0

    for archive_name, target_dir in media_archives.items():
        archive_path = backup_dir / archive_name
        if not archive_path.exists():
            continue

        target = Path(target_dir)

        if not force and target.exists():
            print(f"\n  Target directory exists: {target_dir}")
            if not confirm_action(f"  Overwrite {target_dir}?", default=False):
                print(f"  - Skipped {archive_name}")
                continue

        # Extract archive
        try:
            if target.exists():
                shutil.rmtree(target)

            target.parent.mkdir(parents=True, exist_ok=True)

            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(target.parent)

            size_mb = archive_path.stat().st_size / (1024 * 1024)
            print(f"  ✓ Restored {target_dir} ({size_mb:.1f} MB)")
            restored += 1

        except Exception as exc:
            print(f"  ✗ Failed to restore {archive_name}: {exc}")

    return restored


def restore_docker_volume(compose_cmd: List[str], volume_name: str, backup_dir: Path, force: bool = False) -> bool:
    """Restore a Docker volume from backup.

    Args:
        compose_cmd: Docker compose command
        volume_name: Name of the volume to restore
        backup_dir: Directory containing the backup
        force: Skip confirmation prompts

    Returns:
        True if restoration succeeded, False otherwise
    """
    archive_path = backup_dir / f"volume-{volume_name}.tar.gz"
    if not archive_path.exists():
        return False

    if not force:
        print(f"\n  WARNING: This will OVERWRITE volume '{volume_name}'!")
        if not confirm_action(f"  Continue with volume restoration?", default=False):
            print(f"  - Skipped volume '{volume_name}'")
            return False

    # Get full volume name
    result = subprocess.run(
        [*compose_cmd, "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
    )

    full_volume_name = None
    for line in result.stdout.splitlines():
        if volume_name in line:
            full_volume_name = line.strip()
            break

    if not full_volume_name:
        print(f"  ✗ Volume '{volume_name}' not found")
        return False

    # Restore volume
    try:
        restore_cmd = [
            "docker", "run", "--rm",
            "-v", f"{full_volume_name}:/data",
            "-v", f"{backup_dir.absolute()}:/backup",
            "busybox",
            "sh", "-c",
            f"cd /data && rm -rf * && tar xzf /backup/{archive_path.name}"
        ]

        result = subprocess.run(restore_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ✗ Failed to restore volume '{volume_name}': {result.stderr}")
            return False

        size_mb = archive_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ Restored volume '{volume_name}' ({size_mb:.1f} MB)")
        return True

    except Exception as exc:
        print(f"  ✗ Failed to restore volume '{volume_name}': {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore an EAS Station backup with validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Safety Features:
  - Validates backup integrity before restoration
  - Prompts for confirmation before overwriting data
  - Can restore individual components selectively
  - Creates automatic pre-restoration backup

Examples:
  # Validate backup without restoring
  python restore_backup.py --backup-dir backups/backup-20250111-120000 --dry-run

  # Full restoration with confirmation prompts
  python restore_backup.py --backup-dir backups/backup-20250111-120000

  # Restore database only
  python restore_backup.py --backup-dir backups/backup-20250111-120000 --database-only

  # Force restoration without prompts (dangerous!)
  python restore_backup.py --backup-dir backups/backup-20250111-120000 --force

CAUTION: This tool will OVERWRITE existing data. Always create a backup before restoring!
        """,
    )
    parser.add_argument(
        "--backup-dir",
        required=True,
        help="Directory containing the backup to restore",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate backup without actually restoring",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip all confirmation prompts (DANGEROUS)",
    )
    parser.add_argument(
        "--database-only",
        action="store_true",
        help="Restore only the database",
    )
    parser.add_argument(
        "--skip-database",
        action="store_true",
        help="Skip database restoration",
    )
    parser.add_argument(
        "--skip-media",
        action="store_true",
        help="Skip media restoration",
    )
    parser.add_argument(
        "--skip-volumes",
        action="store_true",
        help="Skip Docker volume restoration",
    )
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir).resolve()
    if not backup_dir.exists():
        print(f"ERROR: Backup directory not found: {backup_dir}")
        sys.exit(1)

    print("=" * 60)
    print("EAS Station Backup Restoration")
    print("=" * 60)
    print()

    # Validate backup
    print("Validating backup...")
    is_valid, issues = validate_backup(backup_dir)
    print()

    if not is_valid:
        print("Backup validation FAILED:")
        for issue in issues:
            print(f"  ✗ {issue}")
        sys.exit(1)

    print("✓ Backup validation passed")
    print()

    if args.dry_run:
        print("Dry run mode - no changes will be made")
        return

    # Load metadata and current env
    metadata = load_metadata(backup_dir)
    env_path = Path(".env")
    current_env = read_env(env_path)

    # Confirmation
    if not args.force:
        print("=" * 60)
        print("WARNING: This operation will OVERWRITE existing data!")
        print("=" * 60)
        print(f"Backup created: {metadata.get('timestamp')}")
        print(f"Backup version: {metadata.get('app_version')}")
        print()
        print("It is HIGHLY RECOMMENDED to create a backup of the current")
        print("system before proceeding. Run:")
        print("    python tools/create_backup.py --label pre-restore")
        print()
        if not confirm_action("Have you created a backup and want to proceed?", default=False):
            print("\nRestoration cancelled")
            sys.exit(0)
        print()

    # Track results
    results = {
        "config": False,
        "database": False,
        "media": 0,
        "volumes": 0,
    }

    # Restore configuration
    if not args.database_only:
        print("Restoring configuration files...")
        try:
            # Backup current .env
            if env_path.exists():
                backup_env = env_path.with_suffix(".env.backup")
                shutil.copy2(env_path, backup_env)
                print(f"  Current .env backed up to {backup_env}")

            # Restore configuration files
            for config_file in [".env", "docker-compose.yml", "stack.env"]:
                source = backup_dir / config_file
                if source.exists():
                    shutil.copy2(source, Path(config_file))
                    print(f"  ✓ Restored {config_file}")

            results["config"] = True
            print()
        except Exception as exc:
            print(f"  ✗ Configuration restoration failed: {exc}")
            print()

    # Restore database
    if not args.skip_database and not args.database_only:
        print("Restoring database...")
        # Re-read env after config restoration
        env_values = read_env(Path(".env"))
        results["database"] = restore_database(backup_dir, env_values, args.force)
        print()
    elif args.database_only:
        print("Restoring database...")
        results["database"] = restore_database(backup_dir, current_env, args.force)
        print()

    # Restore media
    if not args.skip_media and not args.database_only:
        print("Restoring media directories...")
        results["media"] = restore_media(backup_dir, args.force)
        print()

    # Restore Docker volumes
    if not args.skip_volumes and not args.database_only:
        print("Restoring Docker volumes...")
        compose_cmd = detect_compose_command()

        if compose_cmd:
            volumes = ["app-config", "certbot-conf"]
            for volume in volumes:
                if restore_docker_volume(compose_cmd, volume, backup_dir, args.force):
                    results["volumes"] += 1
        else:
            print("  - Docker not available, skipping volume restoration")
        print()

    # Summary
    print("=" * 60)
    print("Restoration Summary")
    print("=" * 60)
    print(f"Configuration: {'✓' if results['config'] else '-'}")
    print(f"Database: {'✓' if results['database'] else '-'}")
    print(f"Media directories: {results['media']}")
    print(f"Docker volumes: {results['volumes']}")
    print("=" * 60)

    if results["database"] or results["config"]:
        print("\nNOTE: You may need to restart services for changes to take effect:")
        print("    docker compose restart")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nRestoration cancelled by user")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 - surface meaningful errors to operators
        sys.stderr.write(f"\nERROR: {exc}\n")
        sys.exit(1)
