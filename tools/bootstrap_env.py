#!/usr/bin/env python3
"""Utility helpers for synchronizing the runtime .env file.

Running containers locally requires a populated ``.env`` that mirrors the
configuration documented in ``.env.example``.  The file is intentionally kept
out of version control so secrets are never committed, but that also means a
fresh checkout (or wiping an old container) can leave the stack without the
expected configuration file.  This script copies the example file when the
runtime configuration is missing and appends any newly introduced variables so
redeployments stay effortless.

Example usage::

    # Create .env if it doesn't exist yet
    python tools/bootstrap_env.py

    # Preview which keys would be added without touching the file
    python tools/bootstrap_env.py --dry-run

    # Overwrite the current .env with the latest example defaults
    python tools/bootstrap_env.py --overwrite

The script preserves comments and ordering in the existing runtime file.  Only
new variables from the example are appended to the end of the file so operators
can fill them in before restarting the containers.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ENV = REPO_ROOT / ".env.example"
RUNTIME_ENV = REPO_ROOT / ".env"


def load_key_values(path: Path) -> Dict[str, str]:
    """Return key/value pairs defined in the provided dotenv-style file."""

    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.rstrip()
    return values


def append_missing_keys(target: Path, missing_items: Iterable[Tuple[str, str]]) -> None:
    """Append any missing key/value pairs to ``target`` with helpful context."""

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "",
        f"# Added missing keys from .env.example on {timestamp}",
    ]
    for key, value in missing_items:
        lines.append(f"{key}={value}")

    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def ensure_runtime_env(*, dry_run: bool, overwrite: bool) -> int:
    """Ensure the runtime .env mirrors ``.env.example`` as closely as possible."""

    if not EXAMPLE_ENV.exists():
        print("ERROR: .env.example is missing from the repository.", file=sys.stderr)
        return 1

    if overwrite and RUNTIME_ENV.exists() and not dry_run:
        shutil.copy2(EXAMPLE_ENV, RUNTIME_ENV)
        print("Overwrote existing .env with .env.example contents.")
        return 0

    if not RUNTIME_ENV.exists():
        if dry_run:
            print("Dry run: would create .env from .env.example")
            return 0
        shutil.copy2(EXAMPLE_ENV, RUNTIME_ENV)
        print("Created .env from .env.example. Update secrets before restarting Docker.")
        return 0

    example_values = load_key_values(EXAMPLE_ENV)
    runtime_values = load_key_values(RUNTIME_ENV)

    missing = [(key, value) for key, value in example_values.items() if key not in runtime_values]

    if not missing:
        print(".env already includes all keys from .env.example.")
        return 0

    if dry_run:
        print("Dry run: the following keys would be appended to .env:")
        for key, _ in missing:
            print(f"  - {key}")
        return 0

    append_missing_keys(RUNTIME_ENV, missing)
    print(
        "Appended missing keys to .env. Review the new entries at the end of the file "
        "and provide appropriate values before redeploying."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize .env with .env.example")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the operations that would be performed without modifying files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the current .env with .env.example (ignores missing-key sync).",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return ensure_runtime_env(dry_run=args.dry_run, overwrite=args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
