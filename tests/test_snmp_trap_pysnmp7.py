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

"""Regression test: SNMP compliance traps must actually send on pysnmp 7.

pysnmp 7 restructured hlapi into arch-specific, asyncio-native submodules
(pysnmp.hlapi.v3arch.asyncio) and dropped the old flat pysnmp.hlapi module
this code used to import from (CommunityData, SnmpEngine, sendNotification
as a sync-flavored generator, etc.). The old import silently failed under
pysnmp 7 -- both HealthAlertWorker._send_snmp_traps() and the admin
"Test SNMP" route (webapp/admin/notifications.py::test_snmp) catch that
ImportError broadly and just log/return a warning, so this broke with no
crash and no prior test coverage to catch it: SNMP compliance traps would
have silently stopped sending entirely.

This test sends a real trap over a real UDP socket to a local listener and
checks the payload actually arrives, rather than only checking that the
import succeeds -- an import-only check would have missed the earlier
`addVarBinds` (deprecated) / raw-string-varbind (raises AttributeError)
issues this fix also had to work around.
"""

import logging
import socket
from types import SimpleNamespace

import pytest

from app_core.system_health import HealthAlertWorker

pysnmp = pytest.importorskip("pysnmp", reason="pysnmp is an optional dependency")


@pytest.fixture
def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(5)
    yield sock
    sock.close()


class TestSendSnmpTraps:
    def test_trap_reaches_a_real_udp_listener_with_the_payload(self, udp_listener):
        port = udp_listener.getsockname()[1]
        app = SimpleNamespace(config={
            "COMPLIANCE_SNMP_TARGETS": [f"127.0.0.1:{port}"],
            "COMPLIANCE_SNMP_COMMUNITY": "public",
        })
        worker = HealthAlertWorker(app, logging.getLogger("test-snmp"))

        worker._send_snmp_traps(["regression test issue"])

        data, _addr = udp_listener.recvfrom(4096)
        assert b"regression test issue" in data

    def test_no_targets_configured_sends_nothing(self, udp_listener):
        """Sanity check the fixture/test itself: with no targets, nothing
        should arrive -- proves the positive test above isn't a false
        positive from some other traffic on the port."""
        port = udp_listener.getsockname()[1]
        app = SimpleNamespace(config={
            "COMPLIANCE_SNMP_TARGETS": [],
            "COMPLIANCE_SNMP_COMMUNITY": "public",
        })
        worker = HealthAlertWorker(app, logging.getLogger("test-snmp"))

        worker._send_snmp_traps(["should not be sent"])

        with pytest.raises(socket.timeout):
            udp_listener.recvfrom(4096)
