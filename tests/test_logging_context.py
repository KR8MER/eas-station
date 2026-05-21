"""Tests for the alert correlation-ID logging context.

Verifies that ``app_core.logging_context`` correctly threads alert
identifiers through ``logging.LogRecord`` instances so a grep on
``alert=<identifier>`` reconstructs the alert lifecycle.
"""
from __future__ import annotations

import io
import logging

import pytest

from app_core.logging_context import (
    LOG_FORMAT_WITH_ALERT,
    AlertContextFilter,
    bind_alert,
    clear_alert,
    current_alert,
    install_alert_filter,
    pop_alert,
    push_alert,
    set_alert,
)


@pytest.fixture
def configured_logger():
    """Wire a fresh handler into a unique logger so tests don't leak state."""
    buf = io.StringIO()
    logger = logging.getLogger(f"test_logging_context_{id(buf)}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    # Strip any handlers a previous test installed onto this logger.
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter(LOG_FORMAT_WITH_ALERT))
    logger.addHandler(handler)
    install_alert_filter(logger)
    # Reset any context leaked by an earlier test.
    clear_alert()
    yield logger, buf
    clear_alert()


def test_unbound_alert_renders_as_dash(configured_logger):
    log, buf = configured_logger
    log.info("idle")
    assert "[alert=-]" in buf.getvalue()


def test_bind_alert_sets_and_restores(configured_logger):
    log, buf = configured_logger
    with bind_alert("NWS-XYZ-2026-001"):
        log.info("inside")
    log.info("outside")
    lines = buf.getvalue().strip().splitlines()
    assert "[alert=NWS-XYZ-2026-001]" in lines[0]
    assert "[alert=-]" in lines[1]


def test_bind_alert_with_none_is_noop(configured_logger):
    log, buf = configured_logger
    with bind_alert(None):
        log.info("none-bound")
    assert "[alert=-]" in buf.getvalue()


def test_bind_alert_nests_and_restores_outer(configured_logger):
    log, buf = configured_logger
    with bind_alert("outer"):
        log.info("o1")
        with bind_alert("inner"):
            log.info("i")
        log.info("o2")
    lines = buf.getvalue().strip().splitlines()
    assert "[alert=outer]" in lines[0]
    assert "[alert=inner]" in lines[1]
    assert "[alert=outer]" in lines[2]


def test_push_pop_alert_roundtrip(configured_logger):
    log, buf = configured_logger
    token = push_alert("OTA-RWT-deadbeef")
    log.info("pushed")
    pop_alert(token)
    log.info("popped")
    lines = buf.getvalue().strip().splitlines()
    assert "[alert=OTA-RWT-deadbeef]" in lines[0]
    assert "[alert=-]" in lines[1]


def test_push_alert_with_none_returns_none_token(configured_logger):
    log, buf = configured_logger
    token = push_alert(None)
    assert token is None
    pop_alert(token)  # must not raise
    log.info("still-unbound")
    assert "[alert=-]" in buf.getvalue()


def test_set_and_clear_alert(configured_logger):
    log, buf = configured_logger
    set_alert("manual-id")
    assert current_alert() == "manual-id"
    log.info("set")
    clear_alert()
    assert current_alert() is None
    log.info("cleared")
    lines = buf.getvalue().strip().splitlines()
    assert "[alert=manual-id]" in lines[0]
    assert "[alert=-]" in lines[1]


def test_install_alert_filter_is_idempotent():
    """Calling install_alert_filter twice must not stack duplicate filters."""
    test_logger = logging.getLogger("test_idempotent_filter")
    for h in list(test_logger.handlers):
        test_logger.removeHandler(h)
    handler = logging.StreamHandler(io.StringIO())
    test_logger.addHandler(handler)

    install_alert_filter(test_logger)
    install_alert_filter(test_logger)

    handler_filters = [f for f in handler.filters if isinstance(f, AlertContextFilter)]
    logger_filters = [f for f in test_logger.filters if isinstance(f, AlertContextFilter)]
    assert len(handler_filters) == 1
    assert len(logger_filters) == 1


def test_alert_id_field_is_always_present(configured_logger):
    """Records created outside any bind must still have an alert_id attribute."""
    log, buf = configured_logger
    record_holder: dict = {}

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            record_holder["record"] = record

    capture = CaptureHandler()
    log.addHandler(capture)
    install_alert_filter(log)
    log.info("capture")
    assert hasattr(record_holder["record"], "alert_id")
    assert record_holder["record"].alert_id == "-"


class TestAttachAlertIdAutopopulate:
    """The SQLAlchemy ``before_insert`` listener must stamp the bound alert ID
    onto rows that don't carry one, and leave explicit values alone."""

    def _build_session(self):
        """Build a tiny in-process SQLAlchemy setup with a single model that
        mimics the shape of SystemLog (id + alert_identifier).  This keeps
        the test free of Flask/PostGIS/etc. while still exercising the real
        ``event.listen`` machinery used by the production code."""
        from sqlalchemy import Column, Integer, String, create_engine
        from sqlalchemy.orm import declarative_base, sessionmaker

        Base = declarative_base()

        class FakeLog(Base):
            __tablename__ = "fake_log"
            id = Column(Integer, primary_key=True)
            message = Column(String(200))
            alert_identifier = Column(String(255))

        from app_core.logging_context import attach_alert_id_autopopulate
        attach_alert_id_autopopulate(FakeLog)

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)(), FakeLog

    def test_listener_stamps_bound_alert_id(self):
        session, FakeLog = self._build_session()
        try:
            with bind_alert("NWS-XYZ-2026-007"):
                row = FakeLog(message="hello")
                session.add(row)
                session.commit()
            assert row.alert_identifier == "NWS-XYZ-2026-007"
        finally:
            session.close()

    def test_listener_skips_when_no_alert_bound(self):
        session, FakeLog = self._build_session()
        try:
            row = FakeLog(message="idle")
            session.add(row)
            session.commit()
            assert row.alert_identifier is None
        finally:
            session.close()

    def test_listener_respects_explicit_value(self):
        """When the caller set the column explicitly, the listener must not
        clobber it with the context value."""
        session, FakeLog = self._build_session()
        try:
            with bind_alert("ctx-id"):
                row = FakeLog(message="explicit", alert_identifier="caller-id")
                session.add(row)
                session.commit()
            assert row.alert_identifier == "caller-id"
        finally:
            session.close()

    def test_listener_supports_custom_attribute_name(self):
        """``GPIOActivationLog`` uses ``alert_id`` rather than
        ``alert_identifier``; the helper must accept an override."""
        from sqlalchemy import Column, Integer, String, create_engine
        from sqlalchemy.orm import declarative_base, sessionmaker
        from app_core.logging_context import attach_alert_id_autopopulate

        Base = declarative_base()

        class LegacyLog(Base):
            __tablename__ = "legacy_log"
            id = Column(Integer, primary_key=True)
            alert_id = Column(String(255))

        attach_alert_id_autopopulate(LegacyLog, attr="alert_id")

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            with bind_alert("legacy-style"):
                row = LegacyLog()
                session.add(row)
                session.commit()
            assert row.alert_id == "legacy-style"
        finally:
            session.close()
