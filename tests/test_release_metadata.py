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

"""Tests that enforce release governance expectations for contributors."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_utils import versioning
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "docs" / "reference" / "CHANGELOG.md"
ENV_TEMPLATE = ROOT / ".env.example"


def _read_version() -> str:
    version_text = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert version_text, "The VERSION file must not be empty."
    assert (
        re.fullmatch(r"\d+\.\d+\.\d+", version_text)
    ), f"Unexpected version format: {version_text}"
    return version_text


def test_version_file_exists() -> None:
    assert VERSION_FILE.exists(), "Missing VERSION file"
    _read_version()


def test_env_template_omits_build_version() -> None:
    env_contents = ENV_TEMPLATE.read_text(encoding="utf-8")
    assert (
        "APP_BUILD_VERSION" not in env_contents
    ), "Remove APP_BUILD_VERSION from .env.example to avoid stale deployments"


def test_changelog_includes_current_version_entry() -> None:
    version = _read_version()
    changelog = CHANGELOG_FILE.read_text(encoding="utf-8")
    assert re.search(
        rf"^## \[{re.escape(version)}\]",
        changelog,
        flags=re.MULTILINE,
    ), "Add a release heading for the current version to CHANGELOG.md"


def test_version_resolver_matches_manifest(monkeypatch) -> None:
    version = _read_version()
    versioning._resolve_version.cache_clear()
    monkeypatch.setenv("APP_BUILD_VERSION", "999.0.0")
    assert versioning.get_current_version() == version


def test_changelog_unreleased_section_has_entries() -> None:
    changelog = CHANGELOG_FILE.read_text(encoding="utf-8")
    match = re.search(r"## \[Unreleased\](.*?)(?:\n## \[|\Z)", changelog, flags=re.S)
    assert match, "CHANGELOG.md must contain an [Unreleased] section"
    section_body = match.group(1).strip()
    assert "- " in section_body, "Document your changes under the [Unreleased] section"
