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

"""Guard against the redis-py 8.x pub/sub leak coming back.

Every redis-py 8.x release tested (8.0.0, 8.0.1, 8.1.0) leaks one ``list``
per pub/sub message read through the hiredis parser; 7.4.1 does not, and
neither does the pure-Python parser. ``eas-station-demod`` and
``eas-station-audio`` each read ~31 messages/s (IQ chunks and demodulated
audio), so on 8.1.0 demod reached 8.6 GB and audio 3.3 GB within two
weeks and the box swapped itself into stuttering Icecast audio.

The test drives a real ``PubSub`` against the Redis the suite already uses
(``REDIS_HOST``/``REDIS_PORT``, a service container in CI) on a uniquely
named channel, and counts gc-tracked lists before and after. It is skipped
when no Redis is reachable.
"""

import gc
import os
import uuid

import pytest

redis = pytest.importorskip("redis")
pytest.importorskip("hiredis")

_MESSAGES = 600


def _client():
    client = redis.Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        db=int(os.environ.get("REDIS_DB", "15")),
        decode_responses=True,
        socket_timeout=5,
    )
    try:
        client.ping()
    except redis.exceptions.ConnectionError:
        pytest.skip("Redis not reachable")
    return client


def _list_count() -> int:
    gc.collect()
    return sum(1 for o in gc.get_objects() if type(o) is list)


def test_pubsub_does_not_leak_one_list_per_message():
    client = _client()
    channel = f"test:pubsub-leak:{uuid.uuid4().hex}"
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        pubsub.subscribe(channel)
        while pubsub.get_message(timeout=0.2) is not None:
            pass
        for _ in range(_MESSAGES):
            client.publish(channel, "hello")
        before = _list_count()
        received = 0
        while received < _MESSAGES:
            if pubsub.get_message(timeout=2.0) is None:
                break
            received += 1
        leaked = _list_count() - before
    finally:
        pubsub.close()
        client.close()

    assert received == _MESSAGES
    assert leaked < _MESSAGES // 10, (
        f"redis-py {redis.__version__} leaked {leaked} lists for {received} pub/sub "
        "messages -- see requirements.txt before upgrading redis"
    )
