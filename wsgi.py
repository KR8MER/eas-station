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
