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

"""The repository root, used to locate the tools scripts and ``.env``.

``repo_root`` is resolved from ``__file__``. Three things depend on it being
the *repository* root and not some directory inside it: the one-click backup
and upgrade both run ``tools/*.py`` from here and set it as their ``cwd``, and
the environment editor reads and writes ``<repo_root>/.env``. None of those
fail loudly if it points somewhere else — the backup would run the wrong
script path and the env editor would silently edit a file nobody reads.
"""

from pathlib import Path


# Repository root path for finding tools scripts
# Four levels up is the repository root:
#   paths.py -> maintenance/ -> admin/ -> webapp/ -> <repo root>
# The single-file module needed three. Dropping one here would point the
# backup/upgrade tooling and the .env editor at webapp/ instead — pinned
# by tests/test_maintenance_package.py.
repo_root = Path(__file__).resolve().parent.parent.parent.parent
