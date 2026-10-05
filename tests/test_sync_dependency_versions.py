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

"""Unit tests for scripts/sync_dependency_versions.py.

The Dependabot workflow runs this script on every Dependabot PR, so it
must rewrite stale docs correctly, leave current ones alone, and cut a
release the release-metadata rules accept.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "sync_dependency_versions", ROOT / "scripts" / "sync_dependency_versions.py"
)
sdv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sdv)

PINS = {
    "redis": ("==", "7.4.1"),
    "numba": (">=", "0.68.0"),
    "gevent": (">=", "26.9.0"),
    "sqlalchemy": ("==", "2.1.2"),
    "pytz": ("==", "2026.4"),
}


def test_parse_requirements_handles_extras_ranges_and_comments(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# comment\nredis==7.4.1  # held\nnumba>=0.68.0,<0.69.0\n"
        "psycopg[binary]==3.2.1\nunpinned\n", encoding="utf-8")
    pins = sdv.parse_requirements(req)
    assert pins["redis"] == ("==", "7.4.1")
    assert pins["numba"] == (">=", "0.68.0")
    assert pins["psycopg"] == ("==", "3.2.1")
    assert "unpinned" not in pins


def test_readme_table_rows_are_rewritten_and_suffixes_kept():
    text = (
        "| redis (Python) | 8.1.0 | MIT | client | url |\n"
        "| gevent | 26.8.0+ | MIT | worker | url |\n"
        "| SomethingElse | 1.0 | MIT | untouched | url |\n"
    )
    out = sdv.sync_readme_table(text, PINS)
    assert "| redis (Python) | 7.4.1 |" in out
    assert "| gevent | 26.9.0+ |" in out
    assert "| SomethingElse | 1.0 |" in out


def test_shield_urls_and_alt_title_text_are_rewritten():
    text = (
        '<a title="Numba 0.67+ - JIT"><img src="https://img.shields.io/badge/'
        'Numba-0.67%2B-00A3E0" alt="Numba 0.67+"></a>\n'
        '<img src="https://img.shields.io/badge/SQLAlchemy-2.0.52-CA2C39" alt="SQLAlchemy 2.0.52">'
    )
    out = sdv.sync_shields(text, PINS)
    assert "badge/Numba-0.68.0%2B-00A3E0" in out
    assert 'alt="Numba 0.68.0+"' in out and 'title="Numba 0.68.0+ - JIT"' in out
    assert "badge/SQLAlchemy-2.1.2-CA2C39" in out and 'alt="SQLAlchemy 2.1.2"' in out


def test_equivalent_floor_is_left_alone():
    assert sdv.sync_shields('alt="Numba 0.68+"', PINS) == 'alt="Numba 0.68+"'


def test_about_list_lines_are_rewritten():
    assert sdv.sync_about("- pytz 2026.3.post1 timezone utilities\n", PINS) == (
        "- pytz 2026.4 timezone utilities\n"
    )


def test_release_bumps_patch_badge_and_changelog(tmp_path, monkeypatch):
    version = tmp_path / "VERSION"
    readme = tmp_path / "README.md"
    changelog = tmp_path / "CHANGELOG.md"
    version.write_text("3.24.2\n", encoding="utf-8")
    readme.write_text("[![Version](https://img.shields.io/badge/Version-3.24.2-blueviolet)]\n",
                      encoding="utf-8")
    changelog.write_text("## [Unreleased]\n\n" + sdv.UNRELEASED_PLACEHOLDER
                         + "\n## [3.24.2] - 2026-10-05 - Old\n", encoding="utf-8")
    monkeypatch.setattr(sdv, "VERSION", version)
    monkeypatch.setattr(sdv, "README", readme)
    monkeypatch.setattr(sdv, "CHANGELOG", changelog)

    assert sdv.release("Bump numba", ["numba 0.68.0 -> 0.69.0."], today="2026-10-06") == "3.24.3"
    assert version.read_text(encoding="utf-8").strip() == "3.24.3"
    assert "Version-3.24.3-" in readme.read_text(encoding="utf-8")
    text = changelog.read_text(encoding="utf-8")
    assert "## [3.24.3] - 2026-10-06 - Bump numba\n\n### Changed\n- numba 0.68.0 -> 0.69.0.\n" in text
    assert text.index("[3.24.3]") < text.index("[3.24.2]")
    assert sdv.UNRELEASED_PLACEHOLDER in text


def test_check_mode_reports_drift_without_writing(tmp_path, monkeypatch, capsys):
    about = tmp_path / "ABOUT.md"
    about.write_text("- pytz 2026.3.post1 timezone utilities\n", encoding="utf-8")
    monkeypatch.setattr(sdv, "SYNCERS", ((about, (sdv.sync_about,)),))
    monkeypatch.setattr(sdv, "parse_requirements", lambda path=None: PINS)

    assert sdv.main(["--check"]) == 1
    assert "2026.3.post1" in about.read_text(encoding="utf-8")
    assert sdv.main([]) == 0
    assert "- pytz 2026.4 " in about.read_text(encoding="utf-8")
    assert sdv.main(["--check"]) == 0


@pytest.mark.parametrize("path", ["README.md", "templates/partials/tech_stack_badges.html",
                                  "docs/reference/ABOUT.md"])
def test_repository_docs_are_in_sync(path):
    assert not [p for p in sdv.sync(write=False) if p.relative_to(ROOT).as_posix() == path]
