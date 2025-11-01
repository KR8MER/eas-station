"""Tests that enforce release governance expectations for contributors."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def test_env_template_matches_version() -> None:
    version = _read_version()
    env_contents = ENV_TEMPLATE.read_text(encoding="utf-8")
    assert (
        f"APP_BUILD_VERSION={version}" in env_contents
    ), "Update .env.example to advertise the current version"


def test_changelog_includes_current_version_entry() -> None:
    version = _read_version()
    changelog = CHANGELOG_FILE.read_text(encoding="utf-8")
    assert re.search(
        rf"^## \[{re.escape(version)}\]",
        changelog,
        flags=re.MULTILINE,
    ), "Add a release heading for the current version to CHANGELOG.md"


def test_changelog_unreleased_section_has_entries() -> None:
    changelog = CHANGELOG_FILE.read_text(encoding="utf-8")
    match = re.search(r"## \[Unreleased\](.*?)(?:\n## \[|\Z)", changelog, flags=re.S)
    assert match, "CHANGELOG.md must contain an [Unreleased] section"
    section_body = match.group(1).strip()
    assert "- " in section_body, "Document your changes under the [Unreleased] section"
