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

"""
Changelog Parser Utility
Parses CHANGELOG.md files and extracts version history for display.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


class ChangelogEntry:
    """Represents a single changelog entry for a version."""

    def __init__(
        self,
        version: str,
        date: Optional[str] = None,
        is_current: bool = False
    ):
        self.version = version
        self.date = date
        self.is_current = is_current
        self.added: List[str] = []
        self.fixed: List[str] = []
        self.changed: List[str] = []
        self.removed: List[str] = []
        self.deprecated: List[str] = []
        self.security: List[str] = []
        self.raw_content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert entry to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "date": self.date,
            "is_current": self.is_current,
            "added": self.added,
            "fixed": self.fixed,
            "changed": self.changed,
            "removed": self.removed,
            "deprecated": self.deprecated,
            "security": self.security,
            "raw_content": self.raw_content,
        }

    def has_content(self) -> bool:
        """Check if entry has any content."""
        return bool(
            self.added or self.fixed or self.changed or
            self.removed or self.deprecated or self.security or
            self.raw_content
        )


def parse_changelog(changelog_path: Path, current_version: str = None) -> List[ChangelogEntry]:
    """
    Parse a CHANGELOG.md file and extract version entries.

    Args:
        changelog_path: Path to the CHANGELOG.md file
        current_version: Current system version to mark as current

    Returns:
        List of ChangelogEntry objects
    """
    if not changelog_path.exists():
        return []

    content = changelog_path.read_text(encoding="utf-8")
    entries: List[ChangelogEntry] = []
    current_entry: Optional[ChangelogEntry] = None
    current_section: Optional[str] = None

    # Regex patterns
    version_pattern = re.compile(
        r"^##\s+\[?(\d+\.\d+\.\d+[^\]]*)\]?\s*(?:-\s*(\d{4}-\d{2}-\d{2}))?",
        re.MULTILINE
    )
    section_pattern = re.compile(r"^###\s+(Added|Fixed|Changed|Removed|Deprecated|Security)\s*$", re.MULTILINE)

    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check for version header
        version_match = version_pattern.match(line)
        if version_match:
            # Save previous entry
            if current_entry and current_entry.has_content():
                entries.append(current_entry)

            # Start new entry
            version = version_match.group(1)
            date = version_match.group(2)
            is_current = (current_version and version == current_version)

            current_entry = ChangelogEntry(version, date, is_current)
            current_section = None
            i += 1
            continue

        # Check for section header
        section_match = section_pattern.match(line)
        if section_match and current_entry:
            current_section = section_match.group(1).lower()
            i += 1
            continue

        # Parse bullet points
        if line.strip().startswith("-") and current_entry and current_section:
            bullet_text = line.strip()[1:].strip()

            # Add to appropriate section
            if current_section == "added":
                current_entry.added.append(bullet_text)
            elif current_section == "fixed":
                current_entry.fixed.append(bullet_text)
            elif current_section == "changed":
                current_entry.changed.append(bullet_text)
            elif current_section == "removed":
                current_entry.removed.append(bullet_text)
            elif current_section == "deprecated":
                current_entry.deprecated.append(bullet_text)
            elif current_section == "security":
                current_entry.security.append(bullet_text)

        # Collect raw content for current entry
        if current_entry and line.strip() and not version_pattern.match(line):
            if current_entry.raw_content:
                current_entry.raw_content += "\n" + line
            else:
                current_entry.raw_content = line

        i += 1

    # Save last entry
    if current_entry and current_entry.has_content():
        entries.append(current_entry)

    return entries


def get_version_summary(entry: ChangelogEntry, max_items: int = 3) -> str:
    """
    Get a summary of changes for a version entry.

    Args:
        entry: ChangelogEntry to summarize
        max_items: Maximum number of items to include

    Returns:
        Summary string
    """
    summary_parts = []

    if entry.added:
        count = len(entry.added)
        summary_parts.append(f"{count} feature{'s' if count != 1 else ''} added")

    if entry.fixed:
        count = len(entry.fixed)
        summary_parts.append(f"{count} bug{'s' if count != 1 else ''} fixed")

    if entry.changed:
        count = len(entry.changed)
        summary_parts.append(f"{count} change{'s' if count != 1 else ''}")

    if entry.security:
        count = len(entry.security)
        summary_parts.append(f"{count} security update{'s' if count != 1 else ''}")

    if not summary_parts:
        return "Minor updates"

    return ", ".join(summary_parts)


def parse_all_changelogs(repo_root: Path, current_version: str = None) -> Dict[str, List[ChangelogEntry]]:
    """
    Parse all CHANGELOG*.md files in the repository.

    Args:
        repo_root: Root directory of the repository
        current_version: Current system version

    Returns:
        Dictionary mapping changelog file names to parsed entries
    """
    changelogs = {}

    # Parse main CHANGELOG.md
    main_changelog = repo_root / "docs" / "reference" / "CHANGELOG.md"
    if main_changelog.exists():
        changelogs["main"] = parse_changelog(main_changelog, current_version)

    # Parse dated changelogs in docs/
    docs_dir = repo_root / "docs"
    if docs_dir.exists():
        for changelog_file in docs_dir.glob("CHANGELOG_*.md"):
            name = changelog_file.stem  # e.g., "CHANGELOG_2025-11-07"
            changelogs[name] = parse_changelog(changelog_file, current_version)

    return changelogs
