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

"""Runtime dependency version probing."""

import platform
import subprocess
from typing import Dict, List


def _collect_dependency_versions(logger) -> List[Dict[str, str]]:
    """Collect version information for key software dependencies."""

    versions: List[Dict[str, str]] = []

    # Python runtime
    versions.append({
        "name": "Python",
        "version": platform.python_version(),
        "category": "runtime",
    })

    # Key Python packages
    _pkg_list = [
        ("Flask", "flask", "framework"),
        ("SQLAlchemy", "sqlalchemy", "database"),
        ("Alembic", "alembic", "database"),
        ("Redis", "redis", "database"),
        ("psutil", "psutil", "system"),
        ("Gunicorn", "gunicorn", "server"),
        ("Jinja2", "jinja2", "framework"),
        ("Werkzeug", "werkzeug", "framework"),
        ("NumPy", "numpy", "processing"),
        ("SciPy", "scipy", "processing"),
        ("lxml", "lxml", "processing"),
        ("Requests", "requests", "network"),
        ("httpx", "httpx", "network"),
        ("Pillow", "PIL", "processing"),
        ("PyYAML", "yaml", "processing"),
        ("pytest", "pytest", "testing"),
    ]

    from importlib.metadata import version as pkg_version, PackageNotFoundError

    for display_name, import_name, category in _pkg_list:
        try:
            ver = pkg_version(import_name if import_name != "PIL" else "Pillow")
            versions.append({"name": display_name, "version": ver, "category": category})
        except PackageNotFoundError:
            pass
        except Exception:
            pass

    # System-level tools
    for cmd, name, category in [
        (["redis-server", "--version"], "Redis Server", "database"),
        (["ffmpeg", "-version"], "FFmpeg", "processing"),
        (["smartctl", "--version"], "smartmontools", "system"),
    ]:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=5,
            )
            output = (result.stdout or "").strip()
            if output:
                # Extract version from first line
                first_line = output.split("\n")[0]
                # Common patterns: "redis-server v=7.0.0", "ffmpeg version 6.1"
                ver_str = first_line
                for prefix in ("redis-server ", "Redis server ", "ffmpeg version ", "smartctl "):
                    if prefix.lower() in ver_str.lower():
                        idx = ver_str.lower().index(prefix.lower()) + len(prefix)
                        ver_str = ver_str[idx:].split()[0].strip("v=,")
                        break
                versions.append({"name": name, "version": ver_str, "category": category})
        except Exception:
            pass

    return versions
