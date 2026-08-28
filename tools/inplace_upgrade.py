#!/usr/bin/env python3
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

"""Perform a bare-metal in-place upgrade of the EAS Station stack.

This is the script the one-click "System Upgrade" button
(``webapp/admin/maintenance/routes_operations.py``) runs as a background
subprocess, using the same Python interpreter (and therefore the same venv)
as the web app itself. It mirrors the manual bare-metal upgrade steps
documented in ``docs/development/AGENTS.md`` and performed interactively by
``update.sh``: pull the latest code, update this venv's Python dependencies,
apply pending Alembic migrations, and restart services via systemd. There is
no Docker/Compose deployment path to support -- EAS Station ships as a
bare-metal systemd install (see ``install.sh``).
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

import argparse


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Perform a bare-metal in-place upgrade of EAS Station"
    )
    parser.add_argument(
        "--checkout",
        metavar="REF",
        help="Git ref (branch or tag) to check out before pulling updates.",
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

    # Update Python dependencies in this same venv (sys.executable is the venv
    # interpreter the web app itself is running under -- see install.sh).
    repo_root = Path(__file__).resolve().parent.parent
    requirements = repo_root / "requirements.txt"
    if requirements.exists():
        run([sys.executable, "-m", "pip", "install", "--upgrade", "-r", str(requirements)])

    if not args.skip_migrations:
        run([sys.executable, "-m", "alembic", "upgrade", "head"])

    # Restart every EAS Station service. eas-station.target includes
    # eas-station-web.service, so this call -- like the equivalent "Restart
    # All" button in Settings -> Environment -- kills the very process
    # running it; systemd has already accepted the restart job by then.
    run(["sudo", "systemctl", "restart", "eas-station.target"], check=False)

    print("\nUpgrade complete at", datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    main()
