"""Helpers for recording radio system events to the application log."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import SystemLog

LOGGER = logging.getLogger(__name__)


def build_radio_event_logger(flask_app) -> Callable[..., None]:
    """Return a callable that persists radio events to ``SystemLog``."""

    def _log_event(
        level: str,
        message: str,
        *,
        module: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        module_name = module or "radio"
        payload = details or {}

        try:
            with flask_app.app_context():
                entry = SystemLog(
                    level=level,
                    message=message,
                    module=module_name,
                    details=payload or None,
                )
                db.session.add(entry)
                db.session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover - defensive logging
            db.session.rollback()
            LOGGER.warning("Failed to persist radio event '%s': %s", message, exc, exc_info=True)
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.warning("Unexpected error recording radio event '%s': %s", message, exc, exc_info=True)
        finally:
            try:
                db.session.remove()
            except Exception:  # pragma: no cover - defensive cleanup
                pass

    return _log_event


__all__ = ["build_radio_event_logger"]
