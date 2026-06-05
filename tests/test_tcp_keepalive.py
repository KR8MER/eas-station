"""Tests for the TCP keep-alive helper used on serial-to-Ethernet links.

EAS Station holds a long-lived, mostly-idle TCP connection to RS-232↔
Ethernet adapters (LED signs / VFD displays).  ``enable_tcp_keepalive``
turns on OS keep-alive probing so a half-open link is detected and
reconnected instead of silently swallowing the next frame.
"""

import socket

import pytest

from app_utils.network import enable_tcp_keepalive


@pytest.fixture
def connected_tcp_socket():
    """Yield the server-side end of a real loopback TCP connection."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    client = socket.create_connection(srv.getsockname())
    conn, _ = srv.accept()
    try:
        yield conn
    finally:
        for s in (conn, client, srv):
            try:
                s.close()
            except OSError:
                pass


def test_enables_so_keepalive(connected_tcp_socket):
    assert enable_tcp_keepalive(connected_tcp_socket) is True
    assert connected_tcp_socket.getsockopt(
        socket.SOL_SOCKET, socket.SO_KEEPALIVE
    ) == 1


def test_applies_linux_tuning_when_available(connected_tcp_socket):
    enable_tcp_keepalive(connected_tcp_socket, idle=42, interval=7, count=2)

    expected = {
        "TCP_KEEPIDLE": 42,
        "TCP_KEEPINTVL": 7,
        "TCP_KEEPCNT": 2,
    }
    for name, value in expected.items():
        opt = getattr(socket, name, None)
        if opt is None:  # platform without this knob — nothing to assert
            continue
        assert connected_tcp_socket.getsockopt(socket.IPPROTO_TCP, opt) == value


def test_returns_false_when_keepalive_unsupported():
    class _Stubborn:
        def setsockopt(self, *_args, **_kwargs):
            raise OSError("not supported")

    assert enable_tcp_keepalive(_Stubborn()) is False
