#!/usr/bin/env python3
"""Simple maintenance helpers used by ad-hoc recovery tooling."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterable

from fix_template_issues import fix_templates

logger = logging.getLogger(__name__)


class MaintenanceError(RuntimeError):
    """Raised when a maintenance routine reports a recoverable failure."""


def validate_project_root(path: Path) -> Path:
    """Ensure ``path`` exists and contains a ``templates`` directory."""

    if not path.exists():
        raise MaintenanceError(f"Project root {path} does not exist")
    if not (path / "templates").exists():
        logger.warning("templates directory missing under %s; it will be created", path)
    return path


def run_fix_templates(path: Path) -> None:
    """Invoke :func:`fix_template_issues.fix_templates` with logging."""

    logger.info("Rebuilding templates in %s", path)
    fix_templates(path)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run basic maintenance routines")
    parser.add_argument(
        "project_root",
        nargs="?",
        default=Path.cwd(),
        type=Path,
        help="Path to the NOAA alerts project root (defaults to CWD)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    project_root = validate_project_root(args.project_root)
    run_fix_templates(project_root)
    logger.info("Maintenance completed successfully")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual utility usage
    raise SystemExit(main())
