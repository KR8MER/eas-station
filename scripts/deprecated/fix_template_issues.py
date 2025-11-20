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

"""Utility helpers for rebuilding Flask template assets.

This module replaces an earlier ad-hoc shell script that attempted to
restore HTML files by moving any corrupted top-level templates out of the
way and re-creating a minimal working set.  The previous version shipped
with invalid Unicode control characters that prevented Python from even
parsing the file.  The helpers below provide the same behaviour with
simple, ASCII-only definitions so the module can be imported safely in
maintenance tooling.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemplateDefinition:
    """Container describing a template that should exist on disk."""

    relative_path: Path
    contents: str


TEMPLATE_DEFINITIONS: Dict[str, TemplateDefinition] = {
    "base": TemplateDefinition(
        Path("templates/base.html"),
        """<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n    <meta charset=\"UTF-8\">\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n    <title>{% block title %}NOAA CAP Alerts System{% endblock %}</title>\n    <link href=\"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css\" rel=\"stylesheet\">\n    <link href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css\" rel=\"stylesheet\">\n</head>\n<body>\n    <nav class=\"navbar navbar-expand-lg navbar-dark bg-dark\">\n        <div class=\"container-fluid\">\n            <a class=\"navbar-brand\" href=\"/\">NOAA CAP Alerts</a>\n            <div class=\"navbar-nav ms-auto\">\n                <a class=\"nav-link\" href=\"/\">Map</a>\n                <a class=\"nav-link\" href=\"/admin\">Admin</a>\n                <a class=\"nav-link\" href=\"/stats\">Stats</a>\n                <a class=\"nav-link\" href=\"/logs\">Logs</a>\n            </div>\n        </div>\n    </nav>\n    <div class=\"container-fluid mt-3\">\n        {% block content %}{% endblock %}\n    </div>\n    <script src=\"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/js/bootstrap.bundle.min.js\"></script>\n    {% block scripts %}{% endblock %}\n</body>\n</html>\n""",
    ),
    "index": TemplateDefinition(
        Path("templates/index.html"),
        """{% extends \"base.html\" %}\n{% block content %}\n<div class=\"row\">\n    <div class=\"col-md-8\">\n        <div class=\"card\">\n            <div class=\"card-header\">Interactive Map</div>\n            <div class=\"card-body\">\n                <div id=\"map\" style=\"height: 500px; background: #f8f9fa;\">\n                    Map will load here\n                </div>\n            </div>\n        </div>\n    </div>\n    <div class=\"col-md-4\">\n        <div class=\"card\">\n            <div class=\"card-header\">System Status</div>\n            <div class=\"card-body\">\n                <div id=\"system-status\">Loading...</div>\n            </div>\n        </div>\n    </div>\n</div>\n{% endblock %}\n""",
    ),
    "admin": TemplateDefinition(
        Path("templates/admin.html"),
        """{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\">\n    <div class=\"card-header\">Admin Panel</div>\n    <div class=\"card-body\">\n        <h5>Upload Boundary Files</h5>\n        <form id=\"uploadForm\" enctype=\"multipart/form-data\">\n            <div class=\"mb-3\">\n                <label class=\"form-label\">Boundary Type</label>\n                <select class=\"form-select\" name=\"boundary_type\" required>\n                    <option value=\"\">Select type...</option>\n                    <option value=\"fire\">Fire District</option>\n                    <option value=\"ems\">EMS District</option>\n                </select>\n            </div>\n            <div class=\"mb-3\">\n                <label class=\"form-label\">GeoJSON File</label>\n                <input type=\"file\" class=\"form-control\" name=\"file\" accept=\".geojson,.json\" required>\n            </div>\n            <button type=\"submit\" class=\"btn btn-primary\">Upload</button>\n        </form>\n    </div>\n</div>\n{% endblock %}\n""",
    ),
}


def move_corrupted_templates(project_root: Path) -> Iterable[Path]:
    """Move any top-level ``*.html`` files out of the way.

    Returns a generator yielding the paths that were moved so a caller can log
    them individually without needing to re-scan the filesystem.
    """

    html_files = sorted(project_root.glob("*.html"))
    for html_file in html_files:
        backup_path = html_file.with_suffix(html_file.suffix + ".corrupted_backup")
        backup_path.write_bytes(html_file.read_bytes())
        html_file.unlink()
        logger.info("Moved %s to %s", html_file, backup_path)
        yield backup_path


def ensure_directory(path: Path) -> None:
    """Ensure that the directory for ``path`` exists."""

    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)


def write_template(project_root: Path, definition: TemplateDefinition) -> Path:
    """Write ``definition`` relative to ``project_root`` and return the path."""

    destination = project_root / definition.relative_path
    ensure_directory(destination)
    destination.write_text(definition.contents, encoding="utf-8")
    logger.info("Wrote template %s", destination)
    return destination


def rebuild_templates(project_root: Path) -> None:
    """Rebuild the template directory inside ``project_root``."""

    logger.info("Rebuilding template directory in %s", project_root)
    moved = list(move_corrupted_templates(project_root))
    if not moved:
        logger.debug("No top-level HTML files to move out of the way")

    for definition in TEMPLATE_DEFINITIONS.values():
        write_template(project_root, definition)


def fix_templates(project_root: Path | None = None) -> None:
    """Public entry point that wraps :func:`rebuild_templates`."""

    project_root = project_root or Path.cwd()
    rebuild_templates(project_root)


__all__ = [
    "TemplateDefinition",
    "TEMPLATE_DEFINITIONS",
    "ensure_directory",
    "fix_templates",
    "move_corrupted_templates",
    "rebuild_templates",
    "write_template",
]


if __name__ == "__main__":  # pragma: no cover - manual utility usage
    logging.basicConfig(level=logging.INFO)
    fix_templates(Path.cwd())
