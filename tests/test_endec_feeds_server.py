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

"""Tests for the ENDEC device-feed TCP fan-out (services.endec_feeds.server)."""

import socket
import time

import pytest

from app_utils.endec_feeds import STX, FeedEvent, FeedStatus
from services.endec_feeds.server import FeedManager, normalize_feeds


# --- normalize_feeds -------------------------------------------------------

def test_normalize_feeds_filters_and_dedupes():
    feeds = normalize_feeds([
        {"name": "cg", "format": "generic_cgen", "port": 9601, "enabled": True},
        {"name": "off", "format": "news_feed", "port": 9602, "enabled": False},
        {"name": "bad-fmt", "format": "nope", "port": 9603, "enabled": True},
        {"name": "bad-port", "format": "decoder", "port": 99999, "enabled": True},
        {"name": "dup", "format": "decoder", "port": 9601, "enabled": True},
    ])
    assert [f["port"] for f in feeds] == [9601]
    assert feeds[0]["format"] == "generic_cgen"


def test_normalize_feeds_master_disabled_returns_empty():
    feeds = [{"name": "cg", "format": "decoder", "port": 9601, "enabled": True}]
    assert normalize_feeds(feeds, master_enabled=False) == []


# --- TCP fan-out round trip ------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_manager_dispatch_pushes_to_connected_client():
    port = _free_port()
    manager = FeedManager(host="127.0.0.1")
    manager.reconfigure([{"name": "decoder", "format": "decoder", "port": port}])
    try:
        # Connect a client and wait for the listener to register it.
        client = socket.create_connection(("127.0.0.1", port), timeout=2)
        client.settimeout(2)
        deadline = time.time() + 2
        while manager._listeners[port].client_count == 0 and time.time() < deadline:
            time.sleep(0.02)

        event = FeedEvent(
            status=FeedStatus.MATCH.value,
            event_code="TOR",
            header="ZCZC-WXR-TOR-039001+0030-1561200-KR8MER -",
            text="Tornado Warning",
        )
        manager.dispatch(event)

        received = client.recv(4096).decode("utf-8")
        assert received.startswith("match:ZCZC-WXR-TOR-")
        assert "Tornado Warning" in received
        client.close()
    finally:
        manager.stop_all()


def test_manager_reconfigure_stops_removed_feeds():
    port = _free_port()
    manager = FeedManager(host="127.0.0.1")
    manager.reconfigure([{"name": "cg", "format": "generic_cgen", "port": port}])
    assert manager.active_ports == [port]
    manager.reconfigure([])
    assert manager.active_ports == []
    # Port should be free to bind again.
    manager.reconfigure([{"name": "cg2", "format": "decoder", "port": port}])
    assert manager.active_ports == [port]
    manager.stop_all()
