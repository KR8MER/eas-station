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

"""Actions triggerable from a GPIO input pin.

A distinct concern from the automatic forwarding pipeline
(``app_core/audio/auto_forward.py``) or the manual resend route
(``webapp/eas/messages.py``) -- those act on an alert/message the caller
already identified. A GPIO input only has "which pin fired", so each
function here first has to answer "which alert/message does that mean" on
its own, then reuse the existing, already-reviewed trigger path for it.
"""

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


def forward_most_recent_alert(operator: str = "gpio-input") -> None:
    """Re-broadcast whichever EASMessage was most recently generated.

    Mirrors ``POST /messages/<id>/resend`` (``webapp/eas/messages.py``)
    exactly once the message is identified: same live-broadcast guard, same
    detached-subprocess launch (``scripts/resend_eas_broadcast.py``) so GPIO
    is never keyed from inside this process. Never raises -- this runs
    inside the GPIO input-event dispatch loop, which must stay alive
    regardless of what it finds.
    """
    from flask import current_app

    from app_core.models import EASMessage, db
    from app_utils.eas import get_broadcast_state

    result = (
        db.session.query(EASMessage.id)
        .filter(EASMessage.audio_data.isnot(None))
        .order_by(EASMessage.created_at.desc())
        .first()
    )
    if result is None:
        logger.warning("GPIO-triggered Forward Last Alert skipped: no broadcastable EAS message found")
        return
    message_id = result[0]

    if get_broadcast_state().get("active"):
        logger.warning(
            "GPIO-triggered Forward Last Alert skipped: a broadcast is already in progress"
        )
        return

    script_path = os.path.join(current_app.root_path, "scripts", "resend_eas_broadcast.py")
    command = [sys.executable, script_path, "--message-id", str(message_id), "--operator", operator]

    try:
        # start_new_session detaches the child so it survives this process
        # and is never reaped when the request/dispatch that launched it ends
        # -- same rationale as the manual resend route.
        subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            command,
            cwd=current_app.root_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        logger.error("GPIO-triggered Forward Last Alert failed to launch: %s", exc)
        return

    logger.info("GPIO-triggered Forward Last Alert: re-transmitting EASMessage #%s", message_id)
