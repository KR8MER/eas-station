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

"""Utility to perform an in-place upgrade of the EAS Station stack.

This script keeps the existing containers and volumes intact while pulling the
latest code, rebuilding the Docker image, and running database migrations. It
is intended to support the "upgrade in place" workflow described in the
project documentation so operators do not need to tear down and recreate the
stack on every release.
"""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Iterable, List


def run(cmd: Iterable[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a shell command and stream the output to the console."""
    command_list: List[str] = list(cmd)
    print(f"\n▶ {' '.join(command_list)}")
    return subprocess.run(command_list, check=check, text=True)


def ensure_clean_worktree(allow_dirty: bool) -> None:
    """Abort if the git worktree has uncommitted changes."""
    if allow_dirty:
        return

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True,
        text=True,
        capture_output=True,
    )
    if status.stdout.strip():
        print(
            "ERROR: Uncommitted changes detected. Commit, stash, or rerun with "
            "--allow-dirty if you intentionally want to proceed."
        )
        sys.exit(2)


def detect_compose_command() -> List[str]:
    """Return the preferred docker compose invocation as a list."""
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

    print("ERROR: Neither 'docker compose' nor 'docker-compose' is available in PATH.")
    sys.exit(3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Perform an in-place upgrade of EAS Station")
    parser.add_argument(
        "--checkout",
        metavar="REF",
        help="Git ref (branch or tag) to check out before pulling updates.",
    )
    parser.add_argument(
        "--compose-file",
        default="docker-compose.yml",
        help="Compose file to use (defaults to docker-compose.yml).",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Proceed even if the git worktree has uncommitted changes.",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Skip running Alembic database migrations after the upgrade.",
    )
    args = parser.parse_args()

    ensure_clean_worktree(args.allow_dirty)

    # Fetch the latest refs and optionally check out a specific release tag/branch.
    run(["git", "fetch", "--tags", "--prune"])
    if args.checkout:
        run(["git", "checkout", args.checkout])

    # Fast-forward the currently checked-out branch.
    run(["git", "pull", "--ff-only"])

    compose_cmd = detect_compose_command()

    # Pull/build updated container images while keeping volumes intact.
    run([*compose_cmd, "-f", args.compose_file, "pull"])
    run([*compose_cmd, "-f", args.compose_file, "up", "-d", "--build"])

    if not args.skip_migrations:
        run([*compose_cmd, "-f", args.compose_file, "exec", "app", "python", "-m", "alembic", "upgrade", "head"])

    # Restart poller containers to pick up new code without recreating the stack.
    run([*compose_cmd, "-f", args.compose_file, "restart", "poller", "ipaws-poller"])

    print("\nUpgrade complete at", datetime.utcnow().isoformat() + "Z")


if __name__ == "__main__":
    main()
