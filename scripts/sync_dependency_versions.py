#!/usr/bin/env python3
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

"""Sync documented dependency versions with requirements.txt.

requirements.txt is the source of truth. This rewrites every place that
repeats a pinned version by hand:

* the README dependency tables (``| Library | Version | ... |`` rows)
* the versioned shields in the README header and the footer partial
  (``templates/partials/tech_stack_badges.html``), including their
  alt/title text
* the ``- package version`` list in ``docs/reference/ABOUT.md``

``==`` pins are shown exactly; ``>=`` pins as their floor, keeping the
``+`` suffix a row or shield already uses. ``tests/test_tech_stack_badges.py``
fails CI on any drift and reads ``SHIELDS`` from here, so the mapping has
one home.

``--release TITLE`` additionally cuts a patch release: bumps VERSION and
the README version badge and adds a CHANGELOG heading, as the release
rules in docs/development/AGENTS.md require for every change. The
Dependabot workflow (.github/workflows/dependabot-sync.yml) runs both on
every Dependabot PR.

Usage:
    python scripts/sync_dependency_versions.py            # rewrite files
    python scripts/sync_dependency_versions.py --check    # exit 1 on drift
    python scripts/sync_dependency_versions.py --release "Bump foo to 1.2"
"""

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
README = ROOT / "README.md"
FOOTER = ROOT / "templates" / "partials" / "tech_stack_badges.html"
ABOUT = ROOT / "docs" / "reference" / "ABOUT.md"
VERSION = ROOT / "VERSION"
CHANGELOG = ROOT / "docs" / "reference" / "CHANGELOG.md"

#: requirements.txt dist name -> shield label (as it appears in the shield
#: URL and its alt/title text) for every versioned shield.
SHIELDS: Dict[str, str] = {
    "Flask": "Flask",
    "Werkzeug": "Werkzeug",
    "jinja2": "Jinja2",
    "python-socketio": "Socket.IO",
    "SQLAlchemy": "SQLAlchemy",
    "Alembic": "Alembic",
    "gunicorn": "Gunicorn",
    "numpy": "NumPy",
    "scipy": "SciPy",
    "lxml": "lxml",
    "Pillow": "Pillow",
    "pydub": "pydub",
    "pyotp": "PyOTP",
    # Range/floor pins: shown as the floor, e.g. "Numba-0.68.0%2B".
    "numba": "Numba",
    "gevent": "gevent",
    "cryptography": "cryptography",
}

UNRELEASED_PLACEHOLDER = (
    "- Nothing yet. Document changes here as they land; the next release cut "
    "moves them into a version heading.\n"
)

_PIN = re.compile(
    r"^\s*([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(==|>=)\s*([0-9][^\s,;#]*)"
)


def normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def parse_requirements(path: Path = REQUIREMENTS) -> Dict[str, Tuple[str, str]]:
    """Return ``{normalized_name: (operator, version)}`` for == and >= pins."""
    pins: Dict[str, Tuple[str, str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _PIN.match(raw.split("#", 1)[0])
        if m:
            pins[normalize(m.group(1))] = (m.group(2), m.group(3))
    return pins


def _shown(pin: Tuple[str, str], current: str, plus: str = "+") -> Optional[str]:
    """The version string a doc should show for *pin*, or None if unchanged."""
    op, version = pin
    if op == "==":
        wanted = version
    else:
        base = current[: -len(plus)] if current.endswith(plus) else current
        if version in (base, base + ".0"):  # "0.68+" already shows floor 0.68.0
            return None
        wanted = version + (plus if current.endswith(plus) else "")
    return None if current == wanted else wanted


def sync_readme_table(text: str, pins: Dict[str, Tuple[str, str]]) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("|"):
            cells = line.split("|")
            # cells[0] is "" before the first pipe; [1] name, [2] version.
            if len(cells) > 3:
                name = re.sub(r"\s*\(python\)", "", cells[1], flags=re.I).strip("*` ")
                key = normalize(name).replace(" ", "-")
                current = cells[2].strip()
                if key in pins and re.match(r"^[0-9]", current):
                    wanted = _shown(pins[key], current)
                    if wanted:
                        cells[2] = cells[2].replace(current, wanted, 1)
                        line = "|".join(cells)
        out.append(line)
    return "".join(out)


def sync_shields(text: str, pins: Dict[str, Tuple[str, str]]) -> str:
    for dist, label in SHIELDS.items():
        pin = pins.get(normalize(dist))
        if not pin:
            continue
        lab = re.escape(label)

        def _url(m: "re.Match[str]") -> str:
            wanted = _shown(pin, m.group(2), plus="%2B")
            return m.group(1) + (wanted or m.group(2)) + m.group(3)

        text = re.sub(r"(badge/" + lab + r"-)([0-9][0-9A-Za-z.]*(?:%2B)?)(-)", _url, text)

        def _attr(m: "re.Match[str]") -> str:
            wanted = _shown(pin, m.group(2))
            return m.group(1) + (wanted or m.group(2))

        text = re.sub(r'((?:alt|title)="' + lab + r" )([0-9][0-9A-Za-z.]*\+?)", _attr, text)
    return text


def sync_about(text: str, pins: Dict[str, Tuple[str, str]]) -> str:
    def _line(m: "re.Match[str]") -> str:
        pin = pins.get(normalize(m.group(2)))
        wanted = _shown(pin, m.group(3)) if pin else None
        return m.group(1) + m.group(2) + " " + (wanted or m.group(3))

    return re.sub(r"^(- )([A-Za-z0-9_.\-]+) ([0-9][0-9A-Za-z.]*\+?)", _line, text, flags=re.M)


SYNCERS = (
    (README, (sync_readme_table, sync_shields)),
    (FOOTER, (sync_shields,)),
    (ABOUT, (sync_about,)),
)


def sync(write: bool) -> List[Path]:
    """Sync every documented version; return the files that changed (or would)."""
    pins = parse_requirements()
    changed = []
    for path, funcs in SYNCERS:
        before = path.read_text(encoding="utf-8")
        after = before
        for func in funcs:
            after = func(after, pins)
        if after != before:
            changed.append(path)
            if write:
                path.write_text(after, encoding="utf-8")
    return changed


def release(title: str, notes: List[str], today: Optional[str] = None) -> str:
    """Cut a patch release: VERSION, README version badge, CHANGELOG heading."""
    old = VERSION.read_text(encoding="utf-8").strip()
    major, minor, patch = (int(p) for p in old.split("."))
    new = f"{major}.{minor}.{patch + 1}"
    VERSION.write_text(new + "\n", encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    README.write_text(readme.replace(f"Version-{old}-", f"Version-{new}-"), encoding="utf-8")

    today = today or datetime.date.today().isoformat()
    bullets = "".join(f"- {n}\n" for n in notes) or f"- {title}.\n"
    entry = f"\n## [{new}] - {today} - {title}\n\n### Changed\n{bullets}"
    changelog = CHANGELOG.read_text(encoding="utf-8")
    if UNRELEASED_PLACEHOLDER not in changelog:
        raise SystemExit("CHANGELOG [Unreleased] placeholder not found; add the entry by hand.")
    CHANGELOG.write_text(
        changelog.replace(UNRELEASED_PLACEHOLDER, UNRELEASED_PLACEHOLDER + entry, 1),
        encoding="utf-8",
    )
    return new


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="report drift and exit 1 instead of rewriting files")
    parser.add_argument("--release", metavar="TITLE",
                        help="also cut a patch release with this CHANGELOG title")
    parser.add_argument("--note", action="append", default=[],
                        help="CHANGELOG bullet for --release (repeatable)")
    args = parser.parse_args(argv)

    changed = sync(write=not args.check)
    for path in changed:
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(("drift: " if args.check else "updated: ") + str(shown))
    if args.check:
        return 1 if changed else 0
    if args.release:
        print("released: " + release(args.release, args.note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
