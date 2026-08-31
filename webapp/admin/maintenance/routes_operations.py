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

"""Operation status, and the one-click backup and upgrade.

``get_operation_status`` is also imported directly by
``app_core/websocket_push.py`` to feed the admin status push, so it is part of
this package's public surface even though it is a route handler.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import List

from flask import current_app, jsonify, request

from app_core.auth.roles import require_permission
from app_utils.versioning import get_current_version, get_git_metadata
from webapp.routes_logs import get_systemd_logs

from .blueprint import maintenance_bp
from .operations import (
    _sanitize_label,
    _serialize_all_operations,
    _serialize_operation_state,
    _start_background_operation,
)
from .paths import repo_root

# The unit update.sh runs under (see bin/eas-station-run-update): giving it
# its own transient systemd unit, rather than running as a direct child of
# eas-station-web.service, means its "Restarting Services" step doesn't
# kill the very process that launched it -- and its progress keeps landing
# in the journal under this fixed name across that restart, for whichever
# worker process answers the next poll.
_UPGRADE_UNIT = "eas-station-update.service"

_STEP_LINE = re.compile(r"^--- Step (\d+)/(\d+): (.*?) ---$")
_LEVEL_PREFIXES = (
    ("[ OK ]", "success"),
    ("[INFO]", "info"),
    ("[WARN]", "warning"),
    ("[ERROR]", "error"),
)


def _classify_upgrade_log_line(text: str) -> dict:
    """Tag one line of update.sh's output with the structure the UI renders.

    update.sh's echo_step/echo_info/echo_success/echo_warning/echo_error
    helpers (scripts/lib/ui.sh) always write a plain-text line in one of
    these exact forms regardless of whether a TTY is attached -- that
    stability is what makes tailing the journal a faithful stand-in for
    watching the script run interactively.
    """
    stripped = text.strip()
    step_match = _STEP_LINE.match(stripped)
    if step_match:
        return {
            "text": text,
            "level": "step",
            "step": {
                "num": int(step_match.group(1)),
                "total": int(step_match.group(2)),
                "label": step_match.group(3),
            },
        }
    if stripped.startswith("=== UPDATE RESULT: SUCCESS"):
        return {"text": text, "level": "result-success", "step": None}
    if stripped.startswith("=== UPDATE RESULT:"):
        return {"text": text, "level": "result-failed", "step": None}
    for prefix, level in _LEVEL_PREFIXES:
        if stripped.startswith(prefix):
            return {"text": text, "level": level, "step": None}
    # systemd's own lines about the unit's lifecycle (not update.sh's own
    # output) -- the fallback signal for "did it finish and how" once the
    # --collect'd unit itself is gone. These land in the same journal
    # stream under the same unit name, just with a different syslog
    # identity (systemd, not update.sh), which get_systemd_logs doesn't
    # distinguish -- classify by content instead.
    if _UPGRADE_UNIT in stripped and "Failed with result" in stripped:
        return {"text": text, "level": "unit-failed", "step": None}
    if "Main process exited, code=exited, status=" in stripped and not stripped.rstrip().endswith(
        "status=0/SUCCESS"
    ):
        return {"text": text, "level": "unit-failed", "step": None}
    if _UPGRADE_UNIT in stripped and "Deactivated successfully" in stripped:
        return {"text": text, "level": "unit-deactivated-ok", "step": None}
    return {"text": text, "level": "plain", "step": None}


# Route definitions

@maintenance_bp.route("/admin/operations/status", methods=["GET"])
def get_operation_status():
    return jsonify({"operations": _serialize_all_operations()})

@maintenance_bp.route("/admin/operations/backup", methods=["POST"])
@require_permission('system.configure')
def run_one_click_backup():
    payload = request.get_json(silent=True) or {}
    label_value = payload.get("label", "")
    sanitized_label = _sanitize_label(label_value) if isinstance(label_value, str) else ""
    extra_args: List[str] = []
    if sanitized_label:
        extra_args.extend(["--label", sanitized_label])
    output_dir = payload.get("output_dir")
    if isinstance(output_dir, str) and output_dir.strip():
        candidate = output_dir.strip()
        # Reject control-character / argparse-confusing inputs; otherwise pass the
        # operator-supplied path through.  Backups commonly target USB drives,
        # NFS mounts, or arbitrary directories outside BACKUP_DIR, and the route
        # is already gated by admin auth — locking it to BACKUP_DIR breaks the
        # existing UI workflow (relative paths from the form would 400).
        if "\x00" in candidate or "\n" in candidate or "\r" in candidate or candidate.startswith("-"):
            return jsonify({"error": "Invalid output_dir"}), 400
        # If the user supplied a relative path, anchor it under BACKUP_DIR so
        # the form's placeholder ("Default location") behaves intuitively.
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute():
            backup_base = Path(
                current_app.config.get("BACKUP_DIR", "/var/backups/eas-station")
            )
            candidate_path = backup_base / candidate_path
        extra_args.extend(["--output-dir", str(candidate_path)])
    python_executable = sys.executable or "python3"
    command = [python_executable, str(repo_root / "tools" / "create_backup.py"), *extra_args]
    try:
        _start_background_operation(
            "backup",
            command,
            cwd=repo_root,
            logger=current_app.logger,
            description="Backup",
        )
    except RuntimeError as exc:
        return (
            jsonify({"error": str(exc), "operation": _serialize_operation_state("backup")}),
            409,
        )
    message = "Backup started."
    if sanitized_label:
        message = f"Backup started (label: {sanitized_label})."
    return jsonify({"message": message, "operation": _serialize_operation_state("backup")})

@maintenance_bp.route("/admin/operations/upgrade/check", methods=["GET"])
@require_permission('system.configure')
def check_for_upgrade():
    """Compare the running install against a branch's remote HEAD.

    Read-only from the operator's point of view: `git fetch` only updates
    this checkout's remote-tracking refs (origin/<branch>), the same thing
    `git status` implicitly keeps current -- it never touches the working
    tree, so this is safe to call from a page-load handler without asking
    first, unlike the upgrade itself. Answers the question the button gave
    no way to answer before: is there anything to upgrade *to*.
    """
    ref = (request.args.get("ref") or "").strip()
    if not ref:
        ref = get_git_metadata().get("branch") or "main"
        if ref == "unknown":
            ref = "main"

    def _run(args: List[str], timeout: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            args, cwd=repo_root, capture_output=True, text=True, timeout=timeout,
        )

    try:
        fetch = _run(["git", "fetch", "origin", ref, "--quiet"], 20)
        if fetch.returncode != 0:
            return jsonify({"error": (fetch.stderr or "git fetch failed").strip()[:300]}), 502

        remote_version_proc = _run(["git", "show", f"origin/{ref}:VERSION"], 10)
        remote_version = (
            remote_version_proc.stdout.strip()
            if remote_version_proc.returncode == 0 else "unknown"
        )

        local_head = _run(["git", "rev-parse", "HEAD"], 5).stdout.strip()
        remote_head_proc = _run(["git", "rev-parse", f"origin/{ref}"], 5)
        if remote_head_proc.returncode != 0:
            return jsonify({"error": f"No such branch or tag on origin: {ref}"}), 404
        remote_head = remote_head_proc.stdout.strip()

        commits_behind = 0
        update_available = local_head != remote_head
        if update_available:
            count_proc = _run(["git", "rev-list", "--count", f"{local_head}..origin/{ref}"], 10)
            if count_proc.returncode == 0 and count_proc.stdout.strip().isdigit():
                commits_behind = int(count_proc.stdout.strip())

        return jsonify({
            "ref": ref,
            "current_version": get_current_version(),
            "remote_version": remote_version,
            "update_available": update_available,
            "commits_behind": commits_behind,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out reaching the remote repository"}), 504
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.warning("check_for_upgrade failed: %s", exc)
        return jsonify({"error": "Could not check for updates"}), 500


@maintenance_bp.route("/admin/operations/upgrade/tags", methods=["GET"])
@require_permission('system.configure')
def list_upgrade_tags():
    """List released version tags an operator can pin the upgrade to.

    Purely a remote query -- `git ls-remote` talks to the origin over the
    network without touching any local ref, so it's as safe to call from a
    page-load handler as check_for_upgrade()'s `git fetch`. Tags come from
    the release workflow (.github/workflows/release.yml), which creates one
    `vX.Y.Z` tag per published release.

    Returns:
        200 with {branch, tags}. `branch` is this checkout's current branch
        (the "track main" default the picker falls back to). `tags` is up
        to the 15 most recent release tags, newest first.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--sort=-v:refname", "origin", "v*"],
            cwd=repo_root, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return jsonify({"error": (result.stderr or "git ls-remote failed").strip()[:300]}), 502

        tags: List[str] = []
        seen = set()
        for line in result.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2 or not parts[1].startswith("refs/tags/"):
                continue
            tag = parts[1][len("refs/tags/"):]
            tag = tag[:-3] if tag.endswith("^{}") else tag
            if tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
            if len(tags) >= 15:
                break

        branch = get_git_metadata().get("branch") or "main"
        if branch == "unknown":
            branch = "main"

        return jsonify({"branch": branch, "tags": tags})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out reaching the remote repository"}), 504
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.warning("list_upgrade_tags failed: %s", exc)
        return jsonify({"error": "Could not list release tags"}), 500


@maintenance_bp.route("/admin/operations/upgrade", methods=["POST"])
@require_permission('system.configure')
def run_one_click_upgrade():
    """Launch update.sh -- the same script `sudo bash update.sh` runs on the
    box -- as its own systemd unit, non-interactively.

    This call itself only has to start that unit; systemd-run returns as
    soon as the unit is queued; see bin/eas-station-run-update for why a
    dedicated unit exists. Poll /admin/operations/upgrade/progress for the
    step-by-step feed the CLI wizard would otherwise print to a terminal.
    """
    payload = request.get_json(silent=True) or {}
    command = ["sudo", str(repo_root / "bin" / "eas-station-run-update"), "--non-interactive"]
    summary_bits = []
    checkout_value = payload.get("checkout")
    if isinstance(checkout_value, str) and checkout_value.strip():
        checkout_clean = checkout_value.strip()
        command.extend(["--checkout", checkout_clean])
        summary_bits.append(f"checkout {checkout_clean}")
    if payload.get("skip_backup"):
        command.append("--skip-backup")
        summary_bits.append("skip backup")
    try:
        _start_background_operation(
            "upgrade",
            command,
            cwd=repo_root,
            logger=current_app.logger,
            description="Upgrade",
        )
    except RuntimeError as exc:
        return (
            jsonify({"error": str(exc), "operation": _serialize_operation_state("upgrade")}),
            409,
        )
    message = "Upgrade started."
    if summary_bits:
        message = f"Upgrade started ({', '.join(summary_bits)})."
    return jsonify({"message": message, "operation": _serialize_operation_state("upgrade")})


@maintenance_bp.route("/admin/operations/upgrade/progress", methods=["GET"])
@require_permission('system.configure')
def get_upgrade_progress():
    """Step-by-step upgrade feedback, read from eas-station-update.service.

    Deliberately not backed by ``_OPERATION_STATE`` (an in-memory dict that
    resets when this very worker restarts partway through the upgrade it is
    reporting on). Everything here comes from systemd/the journal instead,
    which survive that restart -- so whichever worker answers the next poll,
    before or after it, sees the same picture.
    """
    # `systemctl show` is only trustworthy as a "still running right now"
    # signal: --collect (bin/eas-station-run-update) unloads the transient
    # unit within seconds of exit, success or failure, so by the time
    # anyone polls it has usually already gone back to looking exactly like
    # a unit that never ran. Actual result detection below comes entirely
    # from the journal, which does not get cleaned up.
    unit_state = {"active_state": None, "sub_state": None}
    try:
        show = subprocess.run(
            ["sudo", "systemctl", "show", _UPGRADE_UNIT, "--property=ActiveState,SubState"],
            capture_output=True, text=True, timeout=10,
        )
        props = dict(
            line.split("=", 1) for line in (show.stdout or "").splitlines() if "=" in line
        )
        unit_state = {
            "active_state": props.get("ActiveState") or None,
            "sub_state": props.get("SubState") or None,
        }
    except Exception as exc:
        current_app.logger.debug("Could not read %s unit state: %s", _UPGRADE_UNIT, exc)

    log_result = get_systemd_logs(_UPGRADE_UNIT, lines=500)
    lines = [_classify_upgrade_log_line(entry["message"]) for entry in log_result.get("logs", [])]

    result = "running"
    for entry in lines:
        # update.sh's own marker is authoritative whenever present; systemd's
        # unit-lifecycle lines are the fallback for a crash that happened
        # before update.sh ever reached its own summary block (e.g. `set -e`
        # on an early command failure).
        if entry["level"] == "result-success":
            result = "success"
        elif entry["level"] == "result-failed":
            result = "failed"
        elif entry["level"] == "unit-failed" and result == "running":
            result = "failed"
        elif entry["level"] == "unit-deactivated-ok" and result == "running":
            result = "unknown"
    if not lines and unit_state["active_state"] not in ("active", "activating", "reloading"):
        result = "idle"

    return jsonify({"unit": unit_state, "result": result, "lines": lines})
