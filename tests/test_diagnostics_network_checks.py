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

"""Regression tests for the Outbound Connectivity and Poll Latency
diagnostic checks.

Added after a live investigation found a Wi-Fi interface with a valid
global IPv6 address and default route that nonetheless had no working
upstream IPv6 transit -- every connection attempt over that family just
hung until timeout. Nothing in the existing diagnostics suite tested
outbound reachability at all, so this class of problem was invisible
short of SSHing in and running `ip`/`curl` by hand. These checks pin down
two behavioural contracts: IPv4 failing is a hard failure (the box truly
cannot reach NOAA), while IPv6 failing is only a warning (IPv4 fallback
still works, so it should not read as an outage) -- and that a poller
stuck in that fallback-delay failure mode becomes visible via
poll_history.execution_time_ms.
"""

import socket
from types import SimpleNamespace

import pytest

import webapp.routes_diagnostics as diagnostics

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# check_outbound_connectivity
# --------------------------------------------------------------------------- #

class _FakeSocket:
    def __init__(self, outcome):
        self._outcome = outcome  # None = success, else an exception instance

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def settimeout(self, value):
        pass

    def connect(self, sockaddr):
        if self._outcome is not None:
            raise self._outcome


def _addrinfo(family, addr):
    sockaddr = (addr, 443) if family == socket.AF_INET else (addr, 443, 0, 0)
    return (family, socket.SOCK_STREAM, 6, "", sockaddr)


def _install_fake_network(monkeypatch, *, infos, outcomes):
    """outcomes: {socket.AF_INET: None-or-exception, socket.AF_INET6: ...}"""

    monkeypatch.setattr(diagnostics.socket, "getaddrinfo", lambda *a, **k: infos)

    def fake_socket_factory(family, socktype):
        return _FakeSocket(outcomes.get(family))

    monkeypatch.setattr(diagnostics.socket, "socket", fake_socket_factory)


def test_both_families_reachable_pass(monkeypatch):
    infos = [_addrinfo(socket.AF_INET, "23.62.33.239"), _addrinfo(socket.AF_INET6, "2600::1")]
    _install_fake_network(monkeypatch, infos=infos, outcomes={socket.AF_INET: None, socket.AF_INET6: None})

    result = diagnostics.check_outbound_connectivity()

    assert len(result["passed"]) == 2
    assert result["warnings"] == []
    assert result["failed"] == []


def test_ipv4_failure_is_a_hard_failure(monkeypatch):
    infos = [_addrinfo(socket.AF_INET, "23.62.33.239"), _addrinfo(socket.AF_INET6, "2600::1")]
    _install_fake_network(
        monkeypatch,
        infos=infos,
        outcomes={socket.AF_INET: OSError("Network is unreachable"), socket.AF_INET6: None},
    )

    result = diagnostics.check_outbound_connectivity()

    assert any("IPv4" in msg for msg in result["failed"]), (
        "IPv4 unreachable means the box cannot reach NOAA at all -- must fail"
    )
    assert result["warnings"] == []


def test_ipv6_failure_is_a_warning_not_a_failure(monkeypatch):
    """The exact scenario found live: IPv6 configured but no upstream transit.

    IPv4 still works, so this must not read as an outage.
    """
    infos = [_addrinfo(socket.AF_INET, "23.62.33.239"), _addrinfo(socket.AF_INET6, "2600::1")]
    _install_fake_network(
        monkeypatch,
        infos=infos,
        outcomes={socket.AF_INET: None, socket.AF_INET6: OSError("Network is unreachable")},
    )

    result = diagnostics.check_outbound_connectivity()

    assert any("IPv4" in msg for msg in result["passed"])
    assert any("IPv6" in msg for msg in result["warnings"])
    assert result["failed"] == []


def test_ipv6_timeout_is_also_a_warning(monkeypatch):
    infos = [_addrinfo(socket.AF_INET, "23.62.33.239"), _addrinfo(socket.AF_INET6, "2600::1")]
    _install_fake_network(
        monkeypatch,
        infos=infos,
        outcomes={socket.AF_INET: None, socket.AF_INET6: socket.timeout()},
    )

    result = diagnostics.check_outbound_connectivity()

    assert any("timed out" in msg and "IPv6" in msg for msg in result["warnings"])
    assert result["failed"] == []


def test_no_aaaa_record_is_informational_not_a_warning(monkeypatch):
    infos = [_addrinfo(socket.AF_INET, "23.62.33.239")]
    _install_fake_network(monkeypatch, infos=infos, outcomes={socket.AF_INET: None})

    result = diagnostics.check_outbound_connectivity()

    assert any("no IPv6 address" in msg for msg in result["info"])
    assert result["warnings"] == []
    assert result["failed"] == []


def test_dns_resolution_failure_is_a_hard_failure(monkeypatch):
    def raise_gaierror(*a, **k):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(diagnostics.socket, "getaddrinfo", raise_gaierror)

    result = diagnostics.check_outbound_connectivity()

    assert any("DNS resolution" in msg for msg in result["failed"])


# --------------------------------------------------------------------------- #
# check_poll_latency
# --------------------------------------------------------------------------- #

class _FakePollHistoryQuery:
    def __init__(self, rows):
        self._rows = rows

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


def _row(execution_time_ms, data_source="NOAA"):
    return SimpleNamespace(execution_time_ms=execution_time_ms, data_source=data_source)


class _FakeTimestampColumn:
    """Stands in for PollHistory.timestamp -- only needs a no-op .desc()
    since the fake query object ignores order_by's arguments entirely."""

    def desc(self):
        return self


def _install_fake_poll_history(monkeypatch, rows):
    # check_poll_latency() does `from app_core.models import PollHistory`
    # locally inside the function, resolved fresh on every call -- patching
    # the module attribute is enough, no need to touch the diagnostics module.
    fake_model = SimpleNamespace(query=_FakePollHistoryQuery(rows), timestamp=_FakeTimestampColumn())
    import app_core.models as models_module
    monkeypatch.setattr(models_module, "PollHistory", fake_model, raising=True)


def test_no_history_reports_info(monkeypatch):
    _install_fake_poll_history(monkeypatch, [])

    result = diagnostics.check_poll_latency()

    assert any("No poll history" in msg for msg in result["info"])
    assert result["passed"] == result["warnings"] == result["failed"] == []


def test_normal_latency_passes(monkeypatch):
    _install_fake_poll_history(monkeypatch, [_row(800), _row(900), _row(750)])

    result = diagnostics.check_poll_latency()

    assert result["passed"]
    assert result["warnings"] == []
    assert result["failed"] == []


def test_slow_polls_warn(monkeypatch):
    _install_fake_poll_history(monkeypatch, [_row(9000), _row(700), _row(800)])

    result = diagnostics.check_poll_latency()

    assert result["warnings"]
    assert result["failed"] == []


def test_very_slow_polls_fail(monkeypatch):
    """Roughly what a poll stuck in the IPv6-fallback-delay failure mode looks like."""
    _install_fake_poll_history(monkeypatch, [_row(28000), _row(750), _row(800)])

    result = diagnostics.check_poll_latency()

    assert result["failed"]
