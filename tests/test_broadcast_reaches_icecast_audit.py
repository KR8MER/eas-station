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

"""Structural audit: every broadcast-trigger path must reach Icecast.

Twice in the same investigation, a broadcast-trigger function was found
that called ``set_broadcast_active()`` (keys the GPIO relay, drives the
countdown overlay -- i.e. "the program is now controlling the air-chain")
and played audio locally via ``audio_player_cmd``, but never pushed audio
into the live Icecast stream queues at all:

  * ``webapp/eas/workflow.py`` (Manual Send)
  * ``app_core/rwt_scheduler.py`` (automated weekly RWT, the "Run Test
    Now" button, and the GPIO RWT trigger -- all three share one function)

Both were only found because a user noticed silence and asked pointed
questions, not because anything caught it automatically. This test closes
that gap going forward: it walks every function in ``app_core``,
``app_utils``, ``webapp``, and ``scripts`` that calls
``set_broadcast_active()`` and asserts the *same function* also calls one
of the known Icecast-injection entry points. A new broadcast-trigger path
that forgets this call fails this test instead of shipping silent.

This is a structural/AST check, not a runtime one -- it can't verify the
injection call actually reaches a listener (that needs the live
verification in docs/reference/CHANGELOG.md's 2.193.1 entry), only that
every airchain-controlling function *attempts* it.
"""

import ast
from pathlib import Path
from typing import Iterator, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDITED_DIRS = ("app_core", "app_utils", "webapp", "scripts")

#: Every currently-known way a function reaches the live Icecast air-chain:
#:   - inject_eas_audio: Redis command (resend) or the direct in-process
#:     call inside EASBroadcaster.handle_alert() (app_utils/eas.py) via
#:     app_core.audio.eas_stream_injector.inject_eas_audio
#:   - inject_raw_eas_audio: Redis command for callers with WAV bytes in
#:     hand but no EASMessage row to reference by id (Manual Send, RWT)
INJECTION_MARKERS = frozenset({"inject_eas_audio", "inject_raw_eas_audio"})

#: The two functions that manage the marker itself -- never expected to
#: call injection from inside their own bodies.
MARKER_FUNCTIONS = frozenset({"set_broadcast_active", "clear_broadcast_active"})

#: Functions that legitimately call set_broadcast_active() but delegate the
#: actual playout (and therefore injection) to a different function, rather
#: than being a false-positive gap. Adding an entry here must be paired
#: with confirming -- by reading the delegate, not by assumption -- that
#: the delegate itself passes test_every_broadcast_trigger_injects_into_
#: icecast (it will, automatically, since the delegate is scanned too).
#:
#: app_core.rwt_scheduler.trigger_rwt_broadcast: writes the marker
#: synchronously so the countdown overlay appears the instant the request
#: returns (a Pi's blocking GPIO calls can otherwise stall long enough for
#: gunicorn's gevent hub to miss the window), then hands the actual
#: playout -- including injection -- to _dispatch_rwt_airchain() ->
#: _drive_rwt_airchain() on a background thread. See the comment at its
#: set_broadcast_active() call site for the full rationale.
KNOWN_DELEGATING_TRIGGERS = frozenset({
    "app_core/rwt_scheduler.py::trigger_rwt_broadcast",
})


def _iter_python_sources() -> Iterator[Path]:
    for base in AUDITED_DIRS:
        for path in (REPO_ROOT / base).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _called_names(node: ast.AST) -> Set[str]:
    """Every function/method name actually *called* (not just mentioned in
    a comment or docstring) anywhere inside ``node``, including in nested
    closures -- ``ast.Call.func`` is either a bare ``Name`` (``foo()``) or
    an ``Attribute`` (``obj.foo()``); either way the name we care about is
    the same whether or not the call is qualified.
    """
    names: Set[str] = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _broadcast_trigger_functions() -> Iterator[Tuple[Path, str, bool]]:
    """Yield (file, function_name, has_injection_call) for every function
    definition anywhere under AUDITED_DIRS whose body calls
    set_broadcast_active()."""
    for path in _iter_python_sources():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in MARKER_FUNCTIONS:
                continue
            called = _called_names(node)
            if "set_broadcast_active" not in called:
                continue
            yield (
                path.relative_to(REPO_ROOT),
                node.name,
                bool(called & INJECTION_MARKERS),
            )


def test_every_broadcast_trigger_injects_into_icecast() -> None:
    offenders = [
        f"{path}::{func}"
        for path, func, has_injection in _broadcast_trigger_functions()
        if not has_injection and f"{path}::{func}" not in KNOWN_DELEGATING_TRIGGERS
    ]
    assert not offenders, (
        "These functions call set_broadcast_active() (key the GPIO relay / "
        "claim the air-chain) but never call inject_eas_audio() or "
        "inject_raw_eas_audio() in the same function body -- audio may key "
        "the relay and play locally without ever reaching an Icecast "
        "listener (exactly the bug found in Manual Send and RWT, see "
        "docs/reference/CHANGELOG.md's 2.193.1 entry):\n"
        + "\n".join(f"  {name}" for name in offenders)
    )


def test_audit_actually_finds_the_known_broadcast_triggers() -> None:
    """Guards the audit itself: if this drops to zero (e.g. a refactor
    renames set_broadcast_active or moves callers out of AUDITED_DIRS),
    the assertion above would trivially pass with nothing to check --
    silently disabling this whole test's protection. Pin the known count
    so that kind of regression is loud instead of quiet."""
    found = list(_broadcast_trigger_functions())
    # webapp/eas/workflow.py (Manual Send), app_core/rwt_scheduler.py
    # (_drive_rwt_airchain), scripts/resend_eas_broadcast.py (_run), and
    # app_utils/eas.py (EASBroadcaster.handle_alert) -- four distinct
    # broadcast-trigger functions as of the 2.193.x fixes.
    assert len(found) >= 4, (
        f"Expected at least 4 broadcast-trigger functions, found {len(found)}: "
        f"{[f'{p}::{f}' for p, f, _ in found]}. If set_broadcast_active() was "
        "renamed or moved, update INJECTION_MARKERS/this test too -- don't "
        "just lower the count."
    )
