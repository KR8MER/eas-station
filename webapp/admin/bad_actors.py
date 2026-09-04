from __future__ import annotations

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

Bad Actor Blocklist management routes.

Backs the Admin -> Application Settings "Bad Actor Blocklist" panel, which
controls the nginx-level known-bad-actor IP blocklist added alongside
scripts/update_bad_actors.sh: a Spamhaus DROP/EDROP feed refreshed daily by
bad-actors-update.timer, merged with config/bad-actors-local.conf (hand-
curated, checked into git) via nginx's `geo $bad_actor` map, gated by a
master on/off switch and a per-IP/CIDR allowlist bypass -- both files here.

nginx enforces the block (see config/nginx-eas-station.conf); this module
only ever edits the three small control files it reads, then asks nginx to
reload -- exactly the same "write via sudo tee, nginx -t, reload" pattern
webapp/admin/fail2ban.py already uses for its own config writes.
"""

import ipaddress
import logging
import subprocess
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger

logger = logging.getLogger(__name__)

bad_actors_bp = Blueprint("bad_actors", __name__, url_prefix="/admin/security/bad-actors")

SWITCH_PATH = "/etc/nginx/bad-actors-switch.conf"
ALLOWLIST_PATH = "/etc/nginx/bad-actors-allowlist.conf"
AUTO_LIST_PATH = "/etc/nginx/bad-actors-auto.conf"
LOCAL_LIST_PATH = "/opt/eas-station/config/bad-actors-local.conf"
UPDATE_SERVICE = "bad-actors-update.service"

ALLOWLIST_HEADER = (
    "# Managed by Admin -> Application Settings -> Bad Actor Blocklist.\n"
    "# IPs/CIDRs here bypass the Spamhaus/local blocklist entirely.\n"
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a privileged command via sudo. Returns (success, output)."""
    try:
        result = subprocess.run(
            ["sudo", "-n"] + cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


def _write_via_sudo(path: str, content: str) -> tuple[bool, str]:
    """Write content to a root-owned path through `sudo tee`."""
    try:
        proc = subprocess.run(
            ["sudo", "-n", "tee", path],
            input=content,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return False, (proc.stderr.strip() or "permission denied")
        return True, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


def _reload_nginx() -> tuple[bool, str]:
    ok, output = _run(["nginx", "-t"])
    if not ok:
        return False, f"nginx config test failed: {output}"
    ok, output = _run(["systemctl", "reload", "nginx"])
    if not ok:
        return False, f"nginx reload failed: {output}"
    return True, ""


def _read_switch_enabled() -> bool:
    try:
        with open(SWITCH_PATH, "r") as f:
            content = f.read()
        # File is exactly: map $host $bad_actor_switch { default 1; }  (or 0)
        return "default 1" in content
    except Exception:
        logger.exception("Could not read %s", SWITCH_PATH)
        return True  # fail open on read errors -- assume protection is on


def _normalize_entry(raw: str) -> str | None:
    """Validate an IP or CIDR and return its canonical string, or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        if "/" in raw:
            return str(ipaddress.ip_network(raw, strict=False))
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def _read_allowlist() -> list[str]:
    entries = []
    try:
        with open(ALLOWLIST_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Lines look like "1.2.3.0/24 1;"
                cidr = line.split()[0]
                entries.append(cidr)
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception("Could not read %s", ALLOWLIST_PATH)
    return entries


def _write_allowlist(entries: list[str]) -> tuple[bool, str]:
    body = ALLOWLIST_HEADER + "".join(f"{e} 1;\n" for e in entries)
    ok, err = _write_via_sudo(ALLOWLIST_PATH, body)
    if not ok:
        return False, f"Could not write allowlist: {err}"
    return _reload_nginx()


def _list_meta(path: str) -> dict:
    """Entry count + mtime for a geo-map data file."""
    import os
    try:
        count = 0
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    count += 1
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        return {"entry_count": count, "last_updated": mtime.isoformat()}
    except Exception:
        return {"entry_count": 0, "last_updated": None}


# ── Routes ───────────────────────────────────────────────────────────────

@bad_actors_bp.route("/status", methods=["GET"])
@require_auth
@require_permission("system.configure")
def status():
    auto_meta = _list_meta(AUTO_LIST_PATH)
    local_meta = _list_meta(LOCAL_LIST_PATH)
    return jsonify({
        "success": True,
        "enabled": _read_switch_enabled(),
        "auto_entry_count": auto_meta["entry_count"],
        "auto_last_updated": auto_meta["last_updated"],
        "local_entry_count": local_meta["entry_count"],
        "allowlist": _read_allowlist(),
    })


@bad_actors_bp.route("/toggle", methods=["POST"])
@require_auth
@require_permission("system.configure")
def toggle():
    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get("enabled"))

    content = f"map $host $bad_actor_switch {{ default {1 if enabled else 0}; }}\n"
    ok, err = _write_via_sudo(SWITCH_PATH, content)
    if not ok:
        return jsonify({"success": False, "error": f"Could not write switch: {err}"}), 500

    ok, err = _reload_nginx()
    if not ok:
        return jsonify({"success": False, "error": err}), 500

    logger.info("Bad actor blocklist %s", "enabled" if enabled else "disabled")
    AuditLogger.log_config_change(
        resource_type="bad_actor_blocklist",
        details={"enabled": enabled},
    )
    return jsonify({"success": True, "enabled": enabled})


@bad_actors_bp.route("/update", methods=["POST"])
@require_auth
@require_permission("system.configure")
def update_now():
    """Trigger an immediate Spamhaus DROP/EDROP refresh.

    `systemctl start` on a oneshot unit blocks until it finishes (or fails),
    so this call's own exit status already tells us whether the refresh --
    including its own internal nginx -t / reload -- actually succeeded.
    """
    ok, output = _run(["systemctl", "start", UPDATE_SERVICE], timeout=45)
    if not ok:
        return jsonify({
            "success": False,
            "error": f"Blocklist refresh failed: {output or 'see journalctl -u ' + UPDATE_SERVICE}",
        }), 500

    auto_meta = _list_meta(AUTO_LIST_PATH)
    logger.info("Bad actor blocklist refreshed on demand: %d entries", auto_meta["entry_count"])
    AuditLogger.log_config_change(
        resource_type="bad_actor_blocklist",
        details={"action": "manual_refresh", "entry_count": auto_meta["entry_count"]},
    )
    return jsonify({
        "success": True,
        "message": f"Blocklist refreshed: {auto_meta['entry_count']} entries.",
        "auto_entry_count": auto_meta["entry_count"],
        "auto_last_updated": auto_meta["last_updated"],
    })


@bad_actors_bp.route("/allowlist", methods=["POST"])
@require_auth
@require_permission("system.configure")
def add_allowlist_entry():
    payload = request.get_json(silent=True) or {}
    entry = _normalize_entry(payload.get("entry"))
    if not entry:
        return jsonify({"success": False, "error": "Enter a valid IP address or CIDR range"}), 400

    entries = _read_allowlist()
    if entry not in entries:
        entries.append(entry)
        ok, err = _write_allowlist(entries)
        if not ok:
            return jsonify({"success": False, "error": err}), 500

        logger.info("Added %s to the bad-actor allowlist", entry)
        AuditLogger.log_config_change(
            resource_type="bad_actor_blocklist",
            details={"action": "allowlist_add", "entry": entry},
        )

    return jsonify({"success": True, "allowlist": entries})


@bad_actors_bp.route("/allowlist", methods=["DELETE"])
@require_auth
@require_permission("system.configure")
def remove_allowlist_entry():
    payload = request.get_json(silent=True) or {}
    entry = _normalize_entry(payload.get("entry"))
    if not entry:
        return jsonify({"success": False, "error": "Enter a valid IP address or CIDR range"}), 400

    entries = [e for e in _read_allowlist() if e != entry]
    ok, err = _write_allowlist(entries)
    if not ok:
        return jsonify({"success": False, "error": err}), 500

    logger.info("Removed %s from the bad-actor allowlist", entry)
    AuditLogger.log_config_change(
        resource_type="bad_actor_blocklist",
        details={"action": "allowlist_remove", "entry": entry},
    )
    return jsonify({"success": True, "allowlist": entries})


def register_bad_actors_routes(app, logger_):
    app.register_blueprint(bad_actors_bp)
    logger_.info("Bad actor blocklist management routes registered")
