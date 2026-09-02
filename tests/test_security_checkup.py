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

from __future__ import annotations

"""Tests for webapp.admin.security_checkup's UFW status parsing.

Guards the fix for a real deployment found running with no host firewall at
all: install.sh only configures UFW on a *fresh* install (v2.19.7+), and
update.sh never backfills it on an older deployment. These tests cover the
parser against real `ufw status verbose` output captured from both a
never-configured host and a properly baselined one.
"""

from webapp.admin.security_checkup import parse_ufw_status


def test_parses_inactive_ufw():
    output = "Status: inactive"
    result = parse_ufw_status(output)
    assert result["active"] is False
    assert result["default_deny_incoming"] is False
    assert result["allowed_ports"] == []
    assert result["missing_baseline_ports"] == ["22", "80", "443"]


def test_parses_properly_baselined_ufw():
    output = """\
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
8000/tcp                   ALLOW IN    Anywhere
22/tcp (v6)                ALLOW IN    Anywhere (v6)
80/tcp (v6)                ALLOW IN    Anywhere (v6)
443/tcp (v6)               ALLOW IN    Anywhere (v6)
8000/tcp (v6)              ALLOW IN    Anywhere (v6)
"""
    result = parse_ufw_status(output)
    assert result["active"] is True
    assert result["default_deny_incoming"] is True
    assert result["allowed_ports"] == ["22", "80", "443", "8000"]
    assert result["missing_baseline_ports"] == []


def test_parses_active_but_missing_baseline_port():
    # e.g. an operator enabled ufw manually but only opened SSH.
    output = """\
Status: active
Default: deny (incoming), allow (outgoing), disabled (routed)

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
"""
    result = parse_ufw_status(output)
    assert result["active"] is True
    assert result["default_deny_incoming"] is True
    assert result["missing_baseline_ports"] == ["80", "443"]


def test_parses_active_with_allow_incoming_default():
    # The dangerous misconfiguration this whole check exists to catch: active,
    # but not actually filtering anything by default.
    output = """\
Status: active
Default: allow (incoming), allow (outgoing), disabled (routed)
"""
    result = parse_ufw_status(output)
    assert result["active"] is True
    assert result["default_deny_incoming"] is False
