"""System health snapshot helpers shared across route modules."""

from __future__ import annotations

from typing import Any, Dict

from flask import current_app

from app_core.extensions import db
from app_utils import build_system_health_snapshot


def get_system_health(logger=None) -> Dict[str, Any]:
    """Return a structured health snapshot for the running application."""

    effective_logger = logger or _resolve_logger()
    return build_system_health_snapshot(db, effective_logger)


def _resolve_logger():
    """Fallback to Flask's application logger when none is provided."""

    try:
        return current_app.logger  # type: ignore[return-value]
    except RuntimeError:
        # Outside an application context we have no logger; defer to a noop.
        from logging import getLogger

        return getLogger(__name__)


__all__ = ["get_system_health"]
