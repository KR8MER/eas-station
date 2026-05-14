"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Drift guard for the tech-stack shield list.

The project advertises which third-party libraries it uses in three places:

* ``templates/partials/tech_stack_badges.html`` — the live page footer badge
  strip rendered by ``base.html`` on every page (single source of truth).
* ``README.md`` — a curated badge block at the top, plus an exhaustive
  ``## 📚 Attributions & Open-Source Credits`` table near the bottom.
* ``requirements.txt`` — the actual Python dependency pins.

This test enforces that for a curated subset of versioned Python libraries,
the version pinned in ``requirements.txt`` appears verbatim in BOTH the
README badge block and the footer partial. When a contributor bumps one of
these dependencies they must also bump the matching shields, or this test
fails fast in CI.

System packages (chrony, gpsd, FFmpeg, eSpeak NG, Icecast, Nginx, ...) are
not version-pinned here because they are managed by the host OS package
manager rather than by pip; we only verify they're *mentioned*.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQS = ROOT / "requirements.txt"
README = ROOT / "README.md"
BADGES_PARTIAL = ROOT / "templates" / "partials" / "tech_stack_badges.html"
BASE_TEMPLATE = ROOT / "templates" / "base.html"

# Curated subset: dist-name in requirements.txt -> human label used in the
# alt/text of the shield. The version pinned in requirements.txt must appear
# verbatim in both the README badge block and the tech_stack_badges.html
# partial. Keep this list in lock-step with the canonical badge set.
CURATED_VERSIONED = {
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
}

# These libraries / system packages are versionless badges (system-managed
# or floating); we only assert they're attributed in both surfaces.
CURATED_UNVERSIONED = (
    "Nginx",
    "Icecast",
    "SoapySDR",
    "FFmpeg",
    "eSpeak",        # may render as "eSpeak NG" — substring match
    "Raspberry Pi",
    "Docker",
    "Systemd",
    "Redis",         # server is system-managed; Python client version
                     # (requirements.txt redis==7.1.0) is intentionally not
                     # cross-checked here because the badge advertises the
                     # server major.minor, not the client patch.
    "chrony",
    "gpsd",
    "Twilio",
    "Numba",         # version pinned as a range (>=0.61,<0.64) — string "Numba" must appear
    "gevent",        # also a range pin
)


def _parse_requirements_pins() -> dict[str, str]:
    """Return {dist_name: pinned_version_or_range} from requirements.txt.

    The dist_name is lower-cased for case-insensitive lookup. Comment lines,
    blank lines, commented-out optional packages, and lines without an
    explicit version specifier are skipped.
    """
    pins: dict[str, str] = {}
    pattern = re.compile(
        r"^\s*([A-Za-z0-9_.\-]+)\s*"     # 1: dist name
        r"(==|>=|<=|~=|!=|>|<)\s*"        # 2: operator
        r"([A-Za-z0-9_.\-+]+)"            # 3: version
    )
    for raw in REQS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = pattern.match(line)
        if not m:
            continue
        name, _op, version = m.group(1), m.group(2), m.group(3)
        pins[name.lower()] = version
    return pins


def test_footer_partial_is_included_by_base_template() -> None:
    """base.html must {% include %} the canonical badge partial.

    This is the contract that makes the partial the single source of truth.
    If somebody inlines a second copy of the badge list back into base.html,
    we want this test to scream.
    """
    assert BADGES_PARTIAL.exists(), (
        f"Canonical badge partial missing: {BADGES_PARTIAL}"
    )
    base = BASE_TEMPLATE.read_text(encoding="utf-8")
    assert re.search(
        r"{%\s*include\s+['\"]partials/tech_stack_badges\.html['\"]\s*%}",
        base,
    ), (
        "templates/base.html must {% include 'partials/tech_stack_badges.html' %}. "
        "Do not inline the badge list — keep it in the partial so README and "
        "the live footer cannot drift apart."
    )


def test_orphan_footer_partial_is_not_resurrected() -> None:
    """The legacy ``templates/partials/footer.html`` was a stale second copy
    of the badge list that nothing included. It was deleted on purpose.
    If it reappears, fail loudly so the duplicate doesn't silently drift."""
    orphan = ROOT / "templates" / "partials" / "footer.html"
    assert not orphan.exists(), (
        f"{orphan} is dead code that was duplicating the badge list. "
        "Either include it from base.html, or delete it (preferred). "
        "Do not let two copies of the badge list coexist."
    )


def test_curated_versioned_badges_match_requirements_txt() -> None:
    """Every curated, versioned shield must show the version pinned in
    requirements.txt — in BOTH README.md and the footer partial."""
    pins = _parse_requirements_pins()
    readme = README.read_text(encoding="utf-8")
    partial = BADGES_PARTIAL.read_text(encoding="utf-8")

    failures: list[str] = []
    for dist, label in CURATED_VERSIONED.items():
        key = dist.lower()
        assert key in pins, (
            f"requirements.txt is missing a version pin for {dist!r} "
            f"(needed by the {label!r} badge). Pin it with == or "
            f"remove the badge."
        )
        version = pins[key]
        # We assert the literal "Label-Version" appears at least once.
        # Shields URLs use "Label-Version-Color..." so the dash-version
        # substring is unambiguous and order-independent.
        needle = f"{label}-{version}"
        if needle not in readme:
            failures.append(
                f"README.md is missing badge for {label} {version} "
                f"(expected substring {needle!r}). Bump the README badge "
                f"to match requirements.txt."
            )
        if needle not in partial:
            failures.append(
                f"templates/partials/tech_stack_badges.html is missing "
                f"badge for {label} {version} (expected substring "
                f"{needle!r}). Bump the footer badge to match "
                f"requirements.txt."
            )

    assert not failures, (
        "Tech-stack shield drift detected:\n  - " + "\n  - ".join(failures)
    )


def test_curated_unversioned_badges_are_attributed_everywhere() -> None:
    """System / floating dependencies must at least be *mentioned* in both
    surfaces (no version cross-check, since they're not pip-pinned)."""
    readme = README.read_text(encoding="utf-8")
    partial = BADGES_PARTIAL.read_text(encoding="utf-8")
    failures: list[str] = []
    for label in CURATED_UNVERSIONED:
        if label not in readme:
            failures.append(f"README.md does not attribute {label!r}")
        if label not in partial:
            failures.append(
                f"templates/partials/tech_stack_badges.html does not "
                f"attribute {label!r}"
            )
    assert not failures, (
        "Missing attributions:\n  - " + "\n  - ".join(failures)
    )


def test_footer_badges_have_descriptive_tooltips() -> None:
    """Every <a class="tech-badge"> in the live footer partial must carry a
    title="..." tooltip that explains the library's role in EAS Station.

    The README's Attributions section carries the long-form explanation;
    the footer carries the short-form one as a hover tooltip so users see
    "what this library does" on every page without clicking through.
    """
    partial = BADGES_PARTIAL.read_text(encoding="utf-8")

    # Find every tech-badge anchor opening tag.
    anchors = re.findall(
        r'<a\b[^>]*class="tech-badge"[^>]*>',
        partial,
    )
    assert anchors, (
        "No <a class=\"tech-badge\"> anchors found in the badge partial; "
        "did the partial change shape?"
    )

    missing: list[str] = []
    for anchor in anchors:
        m = re.search(r'\btitle="([^"]+)"', anchor)
        if not m:
            missing.append(anchor[:120])
            continue
        title = m.group(1).strip()
        # Must be more than a placeholder — at least 25 chars and contain
        # at least one space so it reads like a sentence, not a bare label.
        if len(title) < 25 or " " not in title:
            missing.append(f"{anchor[:80]} -> title={title!r}")

    assert not missing, (
        "Every tech-stack badge in the footer must have a descriptive "
        "title=\"...\" tooltip (>=25 chars, explaining its role). "
        "Anchors missing or with insufficient tooltips:\n  - "
        + "\n  - ".join(missing)
    )


def test_attributions_section_present_in_readme() -> None:
    """README must contain the exhaustive attributions section. This is
    where the long-tail libraries that aren't worth a footer shield (e.g.
    Werkzeug, lxml, pyserial, Twilio, zigpy) get formally credited."""
    readme = README.read_text(encoding="utf-8")
    assert "Attributions & Open" in readme or "Attributions and Open" in readme, (
        "README.md must contain a '## 📚 Attributions & Open-Source Credits' "
        "section listing every dependency, its license, and its project URL. "
        "This is the canonical attribution surface for the long tail of "
        "libraries that don't warrant a top-level shield."
    )
