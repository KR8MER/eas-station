"""Database helpers for radio receiver persistence."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import RadioReceiver, RadioReceiverStatus


_TABLE_NAMES: Iterable[str] = ("radio_receivers", "radio_receiver_status")


def ensure_radio_tables(logger) -> bool:
    """Ensure radio receiver tables exist before accessing them."""

    try:
        RadioReceiver.__table__.create(bind=db.engine, checkfirst=True)
        RadioReceiverStatus.__table__.create(bind=db.engine, checkfirst=True)

        inspector = inspect(db.engine)
        missing = [name for name in _TABLE_NAMES if name not in inspector.get_table_names()]
        if missing:
            logger.error(
                "Radio receiver tables missing after creation attempt: %s",
                ", ".join(sorted(missing)),
            )
            return False

        return True
    except SQLAlchemyError as exc:
        logger.error("Failed to ensure radio receiver tables: %s", exc)
        return False


__all__ = ["ensure_radio_tables"]
