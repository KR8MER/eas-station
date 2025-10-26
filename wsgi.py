#!/usr/bin/env python3
import os
import sys


def _project_root() -> str:
    """Return the project root based on this file's location."""
    return os.path.dirname(os.path.abspath(__file__))


project_dir = _project_root()
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

os.chdir(project_dir)

from app import app as application  # noqa: E402


__all__ = ["application"]
