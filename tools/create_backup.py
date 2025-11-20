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

"""Create a comprehensive snapshot of configuration, database, media, and Docker volumes."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

try:
    from app_utils.versioning import get_current_version
except ImportError:
    # Fallback if app_utils not in path
    def get_current_version():
        """Fallback version getter."""
        version_file = Path(__file__).parent.parent / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
        return "unknown"


def read_env(path: Path) -> Dict[str, str]:
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


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def detect_git_command() -> Optional[str]:
    """Detect the git command path.

    Returns:
        Full path to git executable, or None if not found
    """
    git_path = shutil.which("git")
    if git_path is not None:
        return git_path

    # Try common locations as fallback
    common_paths = ["/usr/bin/git", "/usr/local/bin/git", "/bin/git"]
    for path in common_paths:
        if Path(path).exists():
            return path

    return None


def detect_compose_command() -> List[str]:
    docker_path = shutil.which("docker")
    legacy_path = shutil.which("docker-compose")

    if docker_path is not None:
        probe = subprocess.run(
            [docker_path, "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return [docker_path, "compose"]

    if legacy_path is not None:
        return [legacy_path]

    return []


def compose_service_running(compose_cmd: List[str], service: str) -> bool:
    if not compose_cmd:
        return False
    result = subprocess.run(
        [*compose_cmd, "ps", "-q", service],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() != ""


def run_pg_dump(env: Dict[str, str], output_path: Path) -> str:
    host = env.get("POSTGRES_HOST", "localhost")
    port = env.get("POSTGRES_PORT", "5432")
    user = env.get("POSTGRES_USER", "postgres")
    db_name = env.get("POSTGRES_DB", "alerts")
    password = env.get("POSTGRES_PASSWORD", "")

    compose_cmd = detect_compose_command()
    use_compose = host in {"alerts-db", "postgres", "postgresql"} and compose_service_running(compose_cmd, "alerts-db")

    if use_compose:
        dump_cmd: List[str] = [*compose_cmd, "exec", "-T", "alerts-db", "pg_dump", "-U", user, "-d", db_name]
    else:
        dump_cmd = [
            "pg_dump",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            db_name,
        ]

    env_vars = os.environ.copy()
    if password:
        env_vars["PGPASSWORD"] = password

    with output_path.open("wb") as handle:
        process = subprocess.run(dump_cmd, stdout=handle, stderr=subprocess.PIPE, env=env_vars)
    if process.returncode != 0:
        output_path.unlink(missing_ok=True)
        sys.stderr.write(process.stderr.decode())
        raise RuntimeError("pg_dump failed; see stderr above for details.")

    sanitized_parts = []
    skip_next = False
    for part in dump_cmd:
        if skip_next:
            skip_next = False
            continue
        if part in {"-U", "--username"}:
            skip_next = True
            continue
        sanitized_parts.append(part)
    return " ".join(sanitized_parts)


def write_metadata(target: Path, env: Dict[str, str], dump_cmd: str) -> None:
    """Write backup metadata to a JSON file."""
    git_cmd = detect_git_command()
    git_commit = "unknown"
    git_status = "unknown"

    if git_cmd:
        try:
            git_commit = subprocess.run(
                [git_cmd, "rev-parse", "HEAD"], capture_output=True, text=True, check=False
            ).stdout.strip() or "unknown"
        except Exception:
            pass

        try:
            git_status = subprocess.run(
                [git_cmd, "status", "-sb"], capture_output=True, text=True, check=False
            ).stdout.strip() or "unknown"
        except Exception:
            pass

    metadata = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "git_commit": git_commit,
        "git_status": git_status,
        "app_version": get_current_version(),
        "database": {
            "host": env.get("POSTGRES_HOST", "unknown"),
            "port": env.get("POSTGRES_PORT", "5432"),
            "name": env.get("POSTGRES_DB", "alerts"),
            "user": env.get("POSTGRES_USER", "postgres"),
            "command": dump_cmd,
        },
    }

    target.write_text(json.dumps(metadata, indent=2))


def copy_files(files: Iterable[Path], destination: Path) -> None:
    for file_path in files:
        if not file_path.exists():
            continue
        target_path = destination / file_path.name
        shutil.copy2(file_path, target_path)


def backup_directory(source: Path, destination: Path, name: str) -> Optional[int]:
    """Backup a directory by creating a tarball.

    Args:
        source: Source directory to backup
        destination: Destination directory for the tarball
        name: Name for the tarball (without .tar.gz extension)

    Returns:
        Size in bytes of the created tarball, or None if source doesn't exist
    """
    if not source.exists() or not source.is_dir():
        return None

    tarball_path = destination / f"{name}.tar.gz"
    with tarfile.open(tarball_path, "w:gz") as tar:
        tar.add(source, arcname=source.name)

    return tarball_path.stat().st_size


def backup_docker_volume(compose_cmd: List[str], volume_name: str, destination: Path) -> Optional[int]:
    """Backup a Docker volume to a tarball.

    Args:
        compose_cmd: Docker compose command (e.g., ['docker', 'compose'])
        volume_name: Name of the volume to backup
        destination: Destination directory for the tarball

    Returns:
        Size in bytes of the created tarball, or None if backup failed
    """
    if not compose_cmd:
        return None

    # Get the full volume name (includes project prefix)
    result = subprocess.run(
        [*compose_cmd, "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    full_volume_name = None
    for line in result.stdout.splitlines():
        if volume_name in line:
            full_volume_name = line.strip()
            break

    if not full_volume_name:
        return None

    tarball_path = destination / f"volume-{volume_name}.tar.gz"

    # Use docker run to backup the volume
    backup_cmd = [
        "docker", "run", "--rm",
        "-v", f"{full_volume_name}:/data:ro",
        "-v", f"{destination.absolute()}:/backup",
        "busybox",
        "tar", "czf", f"/backup/{tarball_path.name}", "-C", "/data", "."
    ]

    result = subprocess.run(backup_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None

    if tarball_path.exists():
        return tarball_path.stat().st_size
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a comprehensive backup of EAS Station",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full backup (recommended)
  python create_backup.py

  # Backup with custom label
  python create_backup.py --label pre-upgrade

  # Database and config only (fast)
  python create_backup.py --no-media --no-volumes

  # Custom output directory
  python create_backup.py --output-dir /var/backups/eas-station
        """,
    )
    parser.add_argument(
        "--output-dir",
        default="backups",
        help="Directory where the backup snapshot should be stored (default: backups)",
    )
    parser.add_argument(
        "--label",
        help="Optional label appended to the backup folder name (e.g., pre-upgrade)",
    )
    parser.add_argument(
        "--no-media",
        action="store_true",
        help="Skip backing up media files (EAS messages, uploads)",
    )
    parser.add_argument(
        "--no-volumes",
        action="store_true",
        help="Skip backing up Docker volumes",
    )
    args = parser.parse_args()

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    folder_name = f"backup-{timestamp}" + (f"-{args.label}" if args.label else "")
    output_dir = Path(args.output_dir).resolve() / folder_name
    ensure_directory(output_dir)

    print(f"Creating backup: {output_dir}")
    print()

    backup_summary = {
        "config": False,
        "database": False,
        "media": [],
        "volumes": [],
        "total_size_mb": 0.0,
    }

    # 1. Copy configuration artifacts
    print("Backing up configuration files...")
    env_path = Path(".env")
    env_values = read_env(env_path)
    copy_files(
        [env_path, Path("docker-compose.yml"), Path("docker-compose.embedded-db.yml"), Path("stack.env")],
        output_dir
    )
    backup_summary["config"] = True
    print("  ✓ Configuration files backed up")
    print()

    # 2. Dump the database
    print("Backing up PostgreSQL database...")
    dump_path = output_dir / "alerts_database.sql"
    try:
        dump_command = run_pg_dump(env_values, dump_path)
        db_size_mb = dump_path.stat().st_size / (1024 * 1024)
        backup_summary["database"] = True
        backup_summary["total_size_mb"] += db_size_mb
        print(f"  ✓ Database backed up ({db_size_mb:.1f} MB)")
    except Exception as exc:
        print(f"  ✗ Database backup failed: {exc}")
        dump_command = "FAILED"
    print()

    # 3. Backup media directories
    if not args.no_media:
        print("Backing up media directories...")
        media_dirs = [
            ("static/eas_messages", "eas-messages"),
            ("static/uploads", "uploads"),
            ("uploads", "app-uploads"),
        ]

        for source_path, archive_name in media_dirs:
            source = Path(source_path)
            if source.exists():
                try:
                    size = backup_directory(source, output_dir, archive_name)
                    if size:
                        size_mb = size / (1024 * 1024)
                        backup_summary["media"].append(archive_name)
                        backup_summary["total_size_mb"] += size_mb
                        print(f"  ✓ {source_path} backed up ({size_mb:.1f} MB)")
                except Exception as exc:
                    print(f"  ✗ Failed to backup {source_path}: {exc}")
        print()

    # 4. Backup Docker volumes
    if not args.no_volumes:
        print("Backing up Docker volumes...")
        compose_cmd = detect_compose_command()

        if compose_cmd:
            volumes = [
                "app-config",
                "certbot-conf",
                "alerts-db-data",
            ]

            for volume in volumes:
                try:
                    size = backup_docker_volume(compose_cmd, volume, output_dir)
                    if size:
                        size_mb = size / (1024 * 1024)
                        backup_summary["volumes"].append(volume)
                        backup_summary["total_size_mb"] += size_mb
                        print(f"  ✓ Volume '{volume}' backed up ({size_mb:.1f} MB)")
                    else:
                        print(f"  - Volume '{volume}' not found or empty")
                except Exception as exc:
                    print(f"  ✗ Failed to backup volume '{volume}': {exc}")
        else:
            print("  - Docker not available, skipping volume backups")
        print()

    # 5. Persist metadata
    git_cmd = detect_git_command()
    git_commit = "unknown"
    git_branch = "unknown"

    if git_cmd:
        try:
            git_commit = subprocess.run(
                [git_cmd, "rev-parse", "HEAD"], capture_output=True, text=True, check=False
            ).stdout.strip() or "unknown"
        except Exception:
            pass

        try:
            git_branch = subprocess.run(
                [git_cmd, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=False
            ).stdout.strip() or "unknown"
        except Exception:
            pass

    metadata = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "label": args.label,
        "git_commit": git_commit,
        "git_branch": git_branch,
        "app_version": get_current_version(),
        "database": {
            "host": env_values.get("POSTGRES_HOST", "unknown"),
            "port": env_values.get("POSTGRES_PORT", "5432"),
            "name": env_values.get("POSTGRES_DB", "alerts"),
            "user": env_values.get("POSTGRES_USER", "postgres"),
            "command": dump_command,
        },
        "summary": backup_summary,
    }

    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (output_dir / "README.txt").write_text(
        f"""EAS Station Backup
==================

Created: {metadata['timestamp']}
Version: {metadata['app_version']}
Git Commit: {metadata['git_commit']}
Git Branch: {metadata['git_branch']}
Label: {metadata.get('label') or 'N/A'}

Contents:
---------
- Configuration files (.env, docker-compose.yml)
- PostgreSQL database dump (alerts_database.sql)
"""
        + (f"- Media archives ({len(backup_summary['media'])} directories)\n" if backup_summary['media'] else "")
        + (f"- Docker volumes ({len(backup_summary['volumes'])} volumes)\n" if backup_summary['volumes'] else "")
        + f"\nTotal Size: {backup_summary['total_size_mb']:.1f} MB\n\n"
        + """Restoration:
-----------
To restore this backup, use the restore_backup.py tool:
    python tools/restore_backup.py --backup-dir <path-to-this-directory>

For manual restoration, see docs/runbooks/backup_strategy.md
"""
    )

    print("=" * 60)
    print(f"Backup completed successfully!")
    print(f"Location: {output_dir}")
    print(f"Total size: {backup_summary['total_size_mb']:.1f} MB")
    print(f"Database: {'✓' if backup_summary['database'] else '✗'}")
    print(f"Media directories: {len(backup_summary['media'])}")
    print(f"Docker volumes: {len(backup_summary['volumes'])}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface meaningful errors to operators
        sys.stderr.write(f"ERROR: {exc}\n")
        sys.exit(1)
