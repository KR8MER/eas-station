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

"""Regression tests for CAPPoller.retry_failed_icecast_injections().

EASBroadcaster.handle_alert() (app_utils/eas.py) persists the EASMessage
row before attempting Icecast injection, and records the outcome in
metadata_payload['icecast_injected'] rather than raising -- a broadcast
record must survive an injection failure. Before this sweep existed,
nothing ever retried that failure: a transient outage (eas-station-audio
down, Redis unreachable) at exactly the wrong moment meant the alert was
permanently logged "forwarded" while no listener ever heard it. This
sweep re-sends via the same resend command the EASMessage detail page's
manual "Resend" button uses (AudioCommandPublisher.inject_eas_audio).
"""

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

cp = pytest.importorskip(
    "poller.cap_poller",
    reason="poller.cap_poller dependencies not installed",
)
from poller.cap_poller import CAPPoller  # noqa: E402


class _FakeQuery:
    def __init__(self, items):
        self._items = items

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._items)


class _FakeSession:
    def __init__(self, items):
        self._items = items
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):
        return _FakeQuery(self._items)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _aware(offset_minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)


def _make_message(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        alert_identifier="TEST-FFW-1",
        same_header="ZCZC-WXR-FFW-039161+0600-2601144-KR8MER-",
        created_at=_aware(-2),
        metadata_payload={"icecast_injected": False},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_poller(items) -> CAPPoller:
    poller = object.__new__(CAPPoller)
    poller.logger = logging.getLogger("test_icecast_injection_retry_sweep")
    poller.db_session = _FakeSession(items)
    system_events = []
    poller.log_system_event = lambda level, message, details=None: system_events.append(
        (level, message, details)
    )
    poller._system_events = system_events
    return poller


def test_retry_reinjects_failed_message(monkeypatch):
    msg = _make_message()
    poller = _make_poller([msg])

    fake_publisher = SimpleNamespace(inject_eas_audio=lambda message_id, **kw: {"success": True})
    monkeypatch.setattr(
        "app_core.audio.redis_commands.get_audio_command_publisher",
        lambda: fake_publisher,
    )

    reinjected = poller.retry_failed_icecast_injections()

    assert reinjected == 1
    assert msg.metadata_payload["icecast_injected"] is True
    assert msg.metadata_payload["icecast_injection_retries"] == 1
    assert poller.db_session.commits == 1
    assert poller._system_events == []


def test_retry_skips_already_injected_messages(monkeypatch):
    msg = _make_message(metadata_payload={"icecast_injected": True})
    poller = _make_poller([msg])

    calls = []
    fake_publisher = SimpleNamespace(
        inject_eas_audio=lambda message_id, **kw: calls.append(message_id) or {"success": True}
    )
    monkeypatch.setattr(
        "app_core.audio.redis_commands.get_audio_command_publisher",
        lambda: fake_publisher,
    )

    assert poller.retry_failed_icecast_injections() == 0
    assert calls == []


def test_retry_stops_after_max_attempts(monkeypatch):
    msg = _make_message(
        metadata_payload={
            "icecast_injected": False,
            "icecast_injection_retries": CAPPoller.ICECAST_INJECTION_MAX_RETRIES,
        }
    )
    poller = _make_poller([msg])

    calls = []
    fake_publisher = SimpleNamespace(
        inject_eas_audio=lambda message_id, **kw: calls.append(message_id) or {"success": True}
    )
    monkeypatch.setattr(
        "app_core.audio.redis_commands.get_audio_command_publisher",
        lambda: fake_publisher,
    )

    assert poller.retry_failed_icecast_injections() == 0
    assert calls == []


def test_retry_logs_system_event_on_final_failure(monkeypatch):
    msg = _make_message(
        metadata_payload={
            "icecast_injected": False,
            "icecast_injection_retries": CAPPoller.ICECAST_INJECTION_MAX_RETRIES - 1,
        }
    )
    poller = _make_poller([msg])

    fake_publisher = SimpleNamespace(
        inject_eas_audio=lambda message_id, **kw: {"success": False, "message": "audio service down"}
    )
    monkeypatch.setattr(
        "app_core.audio.redis_commands.get_audio_command_publisher",
        lambda: fake_publisher,
    )

    reinjected = poller.retry_failed_icecast_injections()

    assert reinjected == 0
    assert msg.metadata_payload["icecast_injected"] is False
    assert msg.metadata_payload["icecast_injection_retries"] == CAPPoller.ICECAST_INJECTION_MAX_RETRIES
    assert len(poller._system_events) == 1
    level, message, details = poller._system_events[0]
    assert level == "ERROR"
    assert "never reached Icecast" in message
    assert details["message_id"] == msg.id
