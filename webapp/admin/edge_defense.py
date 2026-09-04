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

Edge Defense tab (Security Center): stats for requests nginx rejected
before they ever reached the app. Read-only -- configuring these
protections (the blocklist toggle/allowlist) lives on the "Bad Actor
Blocklist" panel in Application Settings (webapp/admin/bad_actors.py),
whose entry-count/last-updated helpers this reuses so the tab can show
blocklist size without a second round trip.
"""

from flask import Blueprint, jsonify

from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.analytics.security_blocks import summary_counts, top_ips, top_paths, recent_events
from webapp.admin.bad_actors import _list_meta, _read_switch_enabled, AUTO_LIST_PATH, LOCAL_LIST_PATH

edge_defense_bp = Blueprint("edge_defense", __name__, url_prefix="/admin/security/edge-defense")


@edge_defense_bp.route("/summary", methods=["GET"])
@require_auth
@require_permission("logs.view")
def summary():
    auto_meta = _list_meta(AUTO_LIST_PATH)
    local_meta = _list_meta(LOCAL_LIST_PATH)
    return jsonify({
        "success": True,
        "counts_24h": summary_counts(hours=24),
        "counts_7d": summary_counts(hours=24 * 7),
        "top_ips_24h": top_ips(hours=24, limit=10),
        "top_paths_24h": top_paths(hours=24, limit=10),
        "recent_events": recent_events(limit=30),
        "blocklist_enabled": _read_switch_enabled(),
        "blocklist_entry_count": auto_meta["entry_count"] + local_meta["entry_count"],
    })


def register_edge_defense_routes(app, logger_):
    app.register_blueprint(edge_defense_bp)
    logger_.info("Edge Defense analytics routes registered")
