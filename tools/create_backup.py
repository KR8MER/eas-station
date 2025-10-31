#!/usr/bin/env python3
"""Create a snapshot of configuration files and the Postgres database."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List


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
    metadata = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "git_status": subprocess.run(
            ["git", "status", "-sb"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "app_version": env.get("APP_BUILD_VERSION", "unknown"),
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a configuration and database backup")
    parser.add_argument(
        "--output-dir",
        default="backups",
        help="Directory where the backup snapshot should be stored.",
    )
    parser.add_argument(
        "--label",
        help="Optional label appended to the backup folder name (e.g., pre-upgrade).",
    )
    args = parser.parse_args()

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    folder_name = f"backup-{timestamp}" + (f"-{args.label}" if args.label else "")
    output_dir = Path(args.output_dir).resolve() / folder_name
    ensure_directory(output_dir)

    env_path = Path(".env")
    env_values = read_env(env_path)

    # Copy configuration artifacts for safekeeping.
    copy_files([env_path, Path("docker-compose.yml"), Path("docker-compose.embedded-db.yml")], output_dir)

    # Dump the database to disk.
    dump_path = output_dir / "alerts_database.sql"
    dump_command = run_pg_dump(env_values, dump_path)

    # Persist metadata for auditing.
    write_metadata(output_dir / "metadata.json", env_values, dump_command)

    print(f"Backup completed: {output_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface meaningful errors to operators
        sys.stderr.write(f"ERROR: {exc}\n")
        sys.exit(1)
