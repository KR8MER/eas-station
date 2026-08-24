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

"""Web-triggered broadcast abort -- the same action a physical GPIO
Dump/Abort Broadcast input pin performs, reachable from the full-screen
countdown overlay for stations without one wired up.

Kept as its own module rather than growing ``webapp/eas/workflow.py`` (already
well past the ~400-line modularity guideline) or ``routes_monitoring.py``
(same) -- follows the same plain ``register(app, logger)`` convention as its
GPIO siblings (``webapp/routes/system_controls.py``,
``webapp/routes/gpio_interlocks.py``).
"""

from flask import Flask, jsonify, session

from app_core.auth.roles import require_permission


def register(app: Flask, logger) -> None:

    def _get_current_user() -> str:
        return session.get("username", "anonymous")

    @app.route("/api/broadcast/abort", methods=["POST"])
    @require_permission('eas.cancel')
    def broadcast_abort():
        """Forcibly stop the broadcast currently on air.

        Calls the exact same ``abort_current_broadcast()`` the GPIO input
        dispatch loop uses for a physically-held Dump/Abort button: cuts the
        in-progress message but always attempts to play the required EOM
        burst (47 CFR 11.61(a)) before releasing the relay, and writes an
        entry to the tamper-evident audit ledger. The client-side press-
        and-hold gesture on the countdown overlay is this route's safety
        equivalent of the physical button's 3-second hold -- a plain click
        must never reach this endpoint.
        """
        from app_utils.eas import get_broadcast_pid, get_broadcast_state

        state = get_broadcast_state()
        if not state.get('active'):
            return jsonify({
                'success': False,
                'error': 'No broadcast is currently active.',
            }), 409

        pid_before = get_broadcast_pid()
        operator = _get_current_user()

        try:
            from app_core.audio.gpio_input_actions import abort_current_broadcast
            abort_current_broadcast(
                reason="Web UI Dump/Abort button", operator=operator,
            )
        except Exception as exc:
            logger.error("Web-triggered broadcast abort failed: %s", exc)
            return jsonify({
                'success': False,
                'error': 'Failed to abort the broadcast; see server logs.',
            }), 500

        # A local playback subprocess is only one of two surfaces
        # abort_current_broadcast() stops -- it also purges audio already
        # queued into the live Icecast air-chain (a station with no local
        # player configured, e.g. Icecast-only, never has a trackable PID at
        # all). The state marker being active above is enough to know there
        # was something to abort; pid_before is only logged for context.
        logger.warning(
            "Web-triggered Dump/Abort Broadcast by %s (pid %s)", operator, pid_before,
        )
        return jsonify({'success': True})
