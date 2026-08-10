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

"""Regression tests: an audio command must never claim success undelivered.

``AudioCommandPublisher`` talks to the audio service over Redis Pub/Sub. When
that service is down there is nobody subscribed to the command channel, so the
message is discarded by Redis — ``PUBLISH`` succeeds and delivers to zero
receivers.

The fire-and-forget commands (``eas_monitor_start``, ``streaming_start``, …)
used to report ``success: True`` in exactly that case. Pressing "Start Monitor"
against a dead audio service therefore produced no error, no state change and
no explanation — the panel simply stayed "Unavailable". The wait-for-response
commands were less wrong but still burned their full timeout before saying
anything.

``PUBLISH``'s return value is the receiver count, which distinguishes the two
cases immediately.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.audio import redis_commands


@pytest.fixture
def publisher(monkeypatch):
    """A publisher wired to a fake Redis whose receiver count is settable."""
    fake_redis = MagicMock()
    fake_redis.publish.return_value = 1  # one subscriber by default
    monkeypatch.setattr(
        redis_commands, 'get_redis_client', lambda *a, **kw: fake_redis
    )
    pub = redis_commands.AudioCommandPublisher()
    pub.redis_client = fake_redis
    return pub


@pytest.mark.unit
def test_fire_and_forget_command_fails_when_nobody_is_listening(publisher):
    """The bug: 'Start Monitor' silently succeeded against a dead service."""
    publisher.redis_client.publish.return_value = 0

    result = publisher.start_eas_monitor()

    assert result['success'] is False
    assert result['no_subscribers'] is True
    assert 'audio service is not running' in result['message'].lower()


@pytest.mark.unit
def test_wait_for_response_command_fails_fast_when_nobody_is_listening(publisher):
    """No subscribers is knowable immediately — don't burn the timeout."""
    publisher.redis_client.publish.return_value = 0

    result = publisher.start_source('wnci')

    assert result['success'] is False
    assert result['no_subscribers'] is True
    # A timeout would have polled for a response key; nothing was listening,
    # so the publisher must not have waited at all.
    publisher.redis_client.get.assert_not_called()


@pytest.mark.unit
def test_stop_commands_are_covered_too(publisher):
    publisher.redis_client.publish.return_value = 0

    assert publisher.stop_eas_monitor()['success'] is False
    assert publisher.stop_source('wnci')['success'] is False


@pytest.mark.unit
def test_command_succeeds_when_the_audio_service_is_subscribed(publisher):
    """The happy path must be untouched by the receiver-count guard."""
    publisher.redis_client.publish.return_value = 1

    result = publisher.start_eas_monitor()

    assert result['success'] is True
    assert 'no_subscribers' not in result
    assert result['command_id'].startswith('eas_monitor_start_')


@pytest.mark.unit
def test_subscribed_wait_for_response_command_still_waits(publisher):
    """With a live subscriber the response poll runs as before."""
    import json

    publisher.redis_client.publish.return_value = 1
    publisher.redis_client.get.return_value = json.dumps(
        {'success': True, 'message': 'Source started'}
    )

    result = publisher.start_source('wnci')

    assert result['success'] is True
    assert result['message'] == 'Source started'
    publisher.redis_client.get.assert_called()
