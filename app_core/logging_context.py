"""Correlation-ID logging context for the EAS Station alert pipeline.

A single alert (CAP identifier or OTA-derived ID) is bound to a
``contextvars.ContextVar`` while it flows through ingestion, forwarding,
SAME encoding, broadcast, and archiving.  Every ``logging.LogRecord``
produced inside that scope picks up the bound ID through
``AlertContextFilter``, so a coherent trail can be reconstructed with::

    grep 'alert=NWS-IPAWS-...' /var/log/eas-station/*.log

When no alert is bound the field renders as ``-`` so format strings stay
fixed-width and don't blow up on idle log lines (audio streaming,
hardware health, etc.).

Usage at an entry point::

    from app_core.logging_context import bind_alert

    with bind_alert(cap_alert.identifier):
        run_pipeline(cap_alert)

Usage from a Redis subscriber where there is no natural ``with`` block::

    from app_core.logging_context import set_alert, clear_alert

    set_alert(payload.get('identifier'))
    try:
        handle(payload)
    finally:
        clear_alert()
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Iterator, Optional

# Sentinel rendered when no alert is bound.  Kept short so log lines stay
# aligned and greppable.
_UNBOUND = '-'

_alert_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'eas_alert_id', default=None,
)

# Format string services should adopt so the alert ID appears in every line.
LOG_FORMAT_WITH_ALERT = (
    '%(asctime)s [%(levelname)s] [alert=%(alert_id)s] [%(name)s] %(message)s'
)


class AlertContextFilter(logging.Filter):
    """Inject the current alert ID into every ``LogRecord``.

    Adding this filter to a handler (or the root logger) guarantees that
    ``%(alert_id)s`` is always populated, even for records produced
    outside an active ``bind_alert`` scope.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        if not hasattr(record, 'alert_id') or not record.alert_id:
            record.alert_id = _alert_id_var.get() or _UNBOUND
        return True


def install_alert_filter(logger: Optional[logging.Logger] = None) -> AlertContextFilter:
    """Attach :class:`AlertContextFilter` to *logger* and all of its handlers.

    Defaults to the root logger so every downstream logger inherits the
    filter.  Safe to call multiple times — the filter is idempotent and
    we de-dupe by type so repeated calls during reload don't stack copies.
    """
    target = logger if logger is not None else logging.getLogger()
    flt: Optional[AlertContextFilter] = None
    for existing in target.filters:
        if isinstance(existing, AlertContextFilter):
            flt = existing
            break
    if flt is None:
        flt = AlertContextFilter()
        target.addFilter(flt)
    for handler in target.handlers:
        if not any(isinstance(f, AlertContextFilter) for f in handler.filters):
            handler.addFilter(flt)
    return flt


@contextmanager
def bind_alert(identifier: Optional[str]) -> Iterator[Optional[str]]:
    """Bind *identifier* as the current correlation ID for the calling task.

    No-op (yields ``None``) when *identifier* is falsy so callers don't
    have to guard the ``with`` site themselves.
    """
    if not identifier:
        yield None
        return
    token = _alert_id_var.set(str(identifier))
    try:
        yield str(identifier)
    finally:
        _alert_id_var.reset(token)


def set_alert(identifier: Optional[str]) -> None:
    """Set the current alert ID without scoping.

    Use when a context manager is awkward — e.g. inside a long-lived
    Redis subscriber loop where ``bind_alert`` would have to wrap each
    iteration manually.  Pair every ``set_alert`` with ``clear_alert``
    in a ``finally`` block.
    """
    _alert_id_var.set(str(identifier) if identifier else None)


def clear_alert() -> None:
    """Drop the current binding.  Counterpart to :func:`set_alert`."""
    _alert_id_var.set(None)


def push_alert(identifier: Optional[str]) -> Optional[contextvars.Token]:
    """Bind *identifier* and return a token that can be passed to :func:`pop_alert`.

    Useful for ``try/finally`` patterns inside long functions where
    re-indenting the whole body to fit under a ``with bind_alert(...):``
    block would be churn.  Returns ``None`` when *identifier* is falsy
    (in which case :func:`pop_alert` is also a no-op).
    """
    if not identifier:
        return None
    return _alert_id_var.set(str(identifier))


def pop_alert(token: Optional[contextvars.Token]) -> None:
    """Restore the binding that was in effect before :func:`push_alert`.

    Tolerates a ``None`` token so callers don't have to special-case
    "nothing was bound" at the call site.
    """
    if token is not None:
        _alert_id_var.reset(token)


def current_alert() -> Optional[str]:
    """Return the alert ID currently bound to this task, or ``None``."""
    return _alert_id_var.get()


def attach_alert_id_autopopulate(*models, attr: str = 'alert_identifier') -> None:
    """Register listeners on each model that stamp the current correlation
    ID onto *attr* when the column is unset.

    Two listeners are registered:

    * ``init`` — fires when an instance is constructed (e.g.
      ``SystemLog(message=...)``).  This is the primary capture point
      because callers almost always commit *after* the
      ``bind_alert``/``push_alert`` scope has exited.  Capturing at
      construction time freezes the ContextVar value onto the instance
      before the bind unwinds.
    * ``before_insert`` — fallback for callers that construct outside a
      bind and only enter one before flushing, or that mutate
      ``alert_identifier`` to ``None`` after construction.  No-op when
      the column already has a value.

    Args:
        *models: SQLAlchemy declarative classes to attach the listener to.
        attr: Column name on each model to populate.  Defaults to
            ``alert_identifier``; pass ``alert_id`` for legacy tables
            (e.g. ``GPIOActivationLog``) that already shipped with a
            differently-named column.
    """
    from sqlalchemy import event  # Imported lazily so logging_context stays
    # importable in environments without SQLAlchemy (tests, CLI tools).

    def _init(target, args, kwargs):  # noqa: ARG001
        # ``kwargs`` lets us see whether the caller passed the column
        # explicitly.  We don't want to overwrite caller intent.
        if kwargs.get(attr):
            return
        if getattr(target, attr, None):
            return
        try:
            cid = _alert_id_var.get()
        except Exception:
            cid = None
        if cid:
            try:
                setattr(target, attr, cid)
            except Exception:
                pass

    def _before_insert(mapper, connection, target):  # noqa: ARG001
        try:
            if getattr(target, attr, None):
                return  # Already set (by caller or by the init listener).
            cid = _alert_id_var.get()
            if cid:
                setattr(target, attr, cid)
        except Exception:
            # Listeners must never break a write.  Silently skip on any
            # unexpected error (e.g. detached instance, missing attr).
            pass

    for model in models:
        # propagate=True so subclasses (if any) inherit the behaviour.
        event.listen(model, 'init', _init, propagate=True)
        event.listen(model, 'before_insert', _before_insert, propagate=True)
