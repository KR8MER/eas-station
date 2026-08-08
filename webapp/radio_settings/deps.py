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

"""The injectable seams every radio route shares.

Route modules reach these **through this module** — ``deps.get_redis_client()``
rather than ``from .deps import get_redis_client`` — for one specific reason: a
by-value import binds the object at import time, so a test that replaces the
name here would not be seen by any module that had already imported it. Going
through the module means there is exactly one place to patch, and a route
module added later honours the stub automatically.

That is the same rule the refactor plan records as "never import a mutable
global from a sibling", applied to the handful of names the radio tests inject
fakes for: the Redis client, the RadioManager accessor, the capture directory
and the event log.
"""

import logging
import os
from typing import Any, Dict, Optional

from app_core.extensions import get_radio_manager, get_redis_client

# Pinned to the pre-split module path on purpose: this logger's name is
# what any external log configuration matches on, and it must not shift
# just because the code moved one directory deeper.
_module_logger = logging.getLogger("webapp.routes_settings_radio")


# IQ-capture configuration (mirrors sdr_hardware_service.RADIO_CAPTURE_DIR).
# Captures are produced by the SDR service via the capture_iq command and
# read back here for download. The directory is also the allow-list root
# for path-traversal validation in the download route.
RADIO_CAPTURE_DIR = os.environ.get(
    "RADIO_CAPTURE_DIR", "/var/log/eas-station/captures"
)
# Default capture window in seconds; bounded by the SDR ring buffer size
# (default ~2 s of buffering, but the capture is tapped real-time off the
# publisher thread so total duration is limited only by wall-clock time
# and the sample-count cap on the SDR-service side).
RADIO_CAPTURE_DEFAULT_DURATION_SEC = 1.0
RADIO_CAPTURE_MAX_DURATION_SEC = 60.0
# Extra wall-clock budget added to the requested capture duration when
# waiting for the SDR service to respond. Covers settling, the publisher
# thread cadence, and the disk write.
RADIO_CAPTURE_WAIT_SLACK_SEC = 20.0
# Redis key prefix for capture metadata (path lookup for the download route).
RADIO_CAPTURE_REDIS_PREFIX = "radio:diag:capture:"
RADIO_CAPTURE_REDIS_TTL_SEC = 600


def _is_path_within(child: str, parent: str) -> bool:
    """Return True iff ``child`` resolves to a path under ``parent``.

    Used as a path-traversal guard for the download endpoint: the SDR
    service returns the on-disk path of the capture file, and we only
    serve it if it lives inside RADIO_CAPTURE_DIR.
    """
    try:
        child_abs = os.path.realpath(child)
        parent_abs = os.path.realpath(parent)
        # commonpath raises ValueError on different drives (Windows); on
        # POSIX it's the cheapest containment check available.
        return os.path.commonpath([child_abs, parent_abs]) == parent_abs
    except (ValueError, OSError):
        return False


def _log_radio_event(
    level: str,
    message: str,
    *,
    module_suffix: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist radio UI events to the shared SystemLog table."""

    try:
        manager = get_radio_manager()
    except Exception as exc:  # pragma: no cover - defensive logging
        _module_logger.debug(
            "Unable to acquire RadioManager for log emission: %s", exc, exc_info=True
        )
        return

    module = "radio.ui"
    if module_suffix:
        module = f"{module}.{module_suffix}"

    try:
        manager.log_event(level, message, module=module, details=details)
    except Exception as exc:  # pragma: no cover - defensive logging
        _module_logger.debug(
            "RadioManager.log_event failed for message '%s': %s", message, exc, exc_info=True
        )


__all__ = [
    "RADIO_CAPTURE_DEFAULT_DURATION_SEC",
    "RADIO_CAPTURE_DIR",
    "RADIO_CAPTURE_MAX_DURATION_SEC",
    "RADIO_CAPTURE_REDIS_PREFIX",
    "RADIO_CAPTURE_REDIS_TTL_SEC",
    "RADIO_CAPTURE_WAIT_SLACK_SEC",
    "_is_path_within",
    "_log_radio_event",
    "get_radio_manager",
    "get_redis_client",
]
