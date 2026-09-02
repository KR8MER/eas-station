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

"""Live progress feed for the one-click upgrade (run_one_click_upgrade in
routes_operations.py), split out of that module to stay under the
package's 400-line guidance (tests/test_maintenance_package.py).
"""

import re
import subprocess
from pathlib import Path
from typing import List

from flask import current_app, jsonify

from app_core.auth.roles import require_permission
from webapp.routes_logs import get_systemd_logs

from .blueprint import maintenance_bp

# The unit update.sh runs under (see bin/eas-station-run-update): giving it
# its own transient systemd unit, rather than running as a direct child of
# eas-station-web.service, means its "Restarting Services" step doesn't
# kill the very process that launched it -- and its unit-lifecycle events
# (start/fail/deactivate) keep landing in the journal under this fixed name
# across that restart, for whichever worker process answers the next poll.
_UPGRADE_UNIT = "eas-station-update.service"

# update.sh's own log file (see update.sh: `exec 1>>"$LOG_FILE" 2>&1`, right
# after its root check). That redirect means every echo_step/echo_info/...
# line -- including the "=== UPDATE RESULT ===" marker _classify_upgrade_log_
# line looks for -- only ever reaches this file, never the journal: the
# redirect happens inside the script itself, replacing the fd 1 the
# eas-station-update.service unit handed it, so journalctl for that unit
# only ever sees systemd's own unit-lifecycle lines (and sudo/PAM session
# noise from the commands update.sh runs) -- never update.sh's actual
# progress output. This file is the primary source below; the journal is
# only consulted for the unit-lifecycle fallback (see get_upgrade_progress).
_UPDATE_LOG_FILE = Path("/var/log/eas-update.log")

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
    stability is what makes _UPDATE_LOG_FILE a faithful stand-in for
    watching the script run interactively. Also used on the small number of
    journal lines get_upgrade_progress reads for the unit-lifecycle
    fallback, which land in the same "level" vocabulary via the two
    `_UPGRADE_UNIT in stripped` branches below.
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


def _tail_update_log(max_lines: int = 1000) -> List[str]:
    """Read update.sh's own progress, from the log file it actually writes to.

    See _UPDATE_LOG_FILE above for why the journal alone can't be used.
    Tolerates the file not existing yet (no update has ever run on this
    host) or being unreadable -- either way, get_upgrade_progress's journal
    fallback still covers unit-lifecycle detection.
    """
    try:
        text = _UPDATE_LOG_FILE.read_text(errors="replace")
    except OSError:
        return []
    return text.splitlines()[-max_lines:]


@maintenance_bp.route("/admin/operations/upgrade/progress", methods=["GET"])
@require_permission('system.configure')
def get_upgrade_progress():
    """Step-by-step upgrade feedback, read from update.sh's own log file.

    Deliberately not backed by ``_OPERATION_STATE`` (an in-memory dict that
    resets when this very worker restarts partway through the upgrade it is
    reporting on). Everything here comes from the filesystem/systemd
    instead, which survive that restart -- so whichever worker answers the
    next poll, before or after it, sees the same picture.
    """
    # `systemctl show` is only trustworthy as a "still running right now"
    # signal: --collect (bin/eas-station-run-update) unloads the transient
    # unit within seconds of exit, success or failure, so by the time
    # anyone polls it has usually already gone back to looking exactly like
    # a unit that never ran. Actual result detection below comes from
    # _UPDATE_LOG_FILE (which does not get cleaned up) and, as a fallback,
    # the journal's own unit-lifecycle lines (which also survive it).
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

    lines = [_classify_upgrade_log_line(text) for text in _tail_update_log()]

    # The journal never gets update.sh's own output (see _UPDATE_LOG_FILE),
    # only systemd's own lines about the unit itself -- kept as a fallback
    # for a crash so early update.sh never got to write anything to its log
    # (e.g. failing to source scripts/lib/ui.sh at all). Only the most
    # recent one is used, so a stale lifecycle line from a previous run
    # sitting earlier in the journal's last-500-lines window can't override
    # this run's own (fresher, more specific) log-file content.
    log_result = get_systemd_logs(_UPGRADE_UNIT, lines=500)
    unit_lifecycle_lines = [
        entry
        for entry in (
            _classify_upgrade_log_line(item["message"]) for item in log_result.get("logs", [])
        )
        if entry["level"] in ("unit-failed", "unit-deactivated-ok")
    ]
    lines.extend(unit_lifecycle_lines[-1:])

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
