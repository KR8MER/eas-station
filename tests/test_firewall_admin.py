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

Tests for webapp.admin.firewall -- the consolidated firewall page that
replaced Icecast's undocumented "manually run ufw allow 8000/tcp" gap and
the inline firewall widget that used to live on the NTP server settings
page. Mirrors the mocking pattern tests/test_ntp_server.py already
established for its own tagged-rule reconciliation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from webapp.admin.firewall import (
    _ICECAST_UFW_TAG,
    _icecast_firewall_subnets,
    configure_icecast_firewall,
    firewall_page,
    icecast_firewall_status,
)


def _proc(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _fake_icecast_settings(port=8000, enabled=True):
    return SimpleNamespace(port=port, enabled=enabled)


class TestIcecastFirewallSubnets:
    def test_no_rules_returns_empty(self):
        with patch("webapp.admin.firewall.subprocess.run", return_value=_proc(0, "Status: active\n")):
            assert _icecast_firewall_subnets(8000) == []

    def test_parses_tagged_rule_for_matching_port(self):
        stdout = f"8000/tcp                   ALLOW IN    192.168.1.0/24             # {_ICECAST_UFW_TAG}\n"
        with patch("webapp.admin.firewall.subprocess.run", return_value=_proc(0, stdout)):
            assert _icecast_firewall_subnets(8000) == ["192.168.1.0/24"]

    def test_ignores_rules_for_a_different_port(self):
        stdout = f"9000/tcp                   ALLOW IN    192.168.1.0/24             # {_ICECAST_UFW_TAG}\n"
        with patch("webapp.admin.firewall.subprocess.run", return_value=_proc(0, stdout)):
            assert _icecast_firewall_subnets(8000) == []

    def test_ignores_rules_with_a_different_comment(self):
        # Same port/proto but not this feature's tag -- e.g. an operator's
        # own manually-added rule, or a different feature's tagged rule.
        stdout = "8000/tcp                   ALLOW IN    192.168.1.0/24             # eas-station-ntp-server\n"
        with patch("webapp.admin.firewall.subprocess.run", return_value=_proc(0, stdout)):
            assert _icecast_firewall_subnets(8000) == []

    def test_ufw_command_failure_returns_empty_list(self):
        with patch("webapp.admin.firewall.subprocess.run", return_value=_proc(1, "", "permission denied")):
            assert _icecast_firewall_subnets(8000) == []


class TestIcecastFirewallStatusRoute:
    def _get(self, app, headers=None):
        with app.test_request_context("/admin/firewall/api/icecast/status", headers=headers):
            return icecast_firewall_status()

    def test_requires_authentication(self, app):
        # require_auth only returns a JSON (body, status) tuple for requests
        # that look like API calls (JSON body or an Accept: application/json
        # header) -- a plain browser GET instead gets a login-page redirect.
        result = self._get(app, headers={"Accept": "application/json"})
        _body, status = result
        assert status == 401

    def test_reports_enabled_port_and_subnets(self, app, authenticated_user):
        stdout = f"8000/tcp                   ALLOW IN    10.0.0.0/24             # {_ICECAST_UFW_TAG}\n"
        with patch("webapp.admin.firewall.get_icecast_settings", return_value=_fake_icecast_settings(port=8000, enabled=True)), \
             patch("webapp.admin.firewall.subprocess.run", return_value=_proc(0, stdout)), \
             patch("webapp.admin.firewall.detect_local_subnets", return_value=["192.168.1.0/24"]):
            response = self._get(app)
        data = response.get_json()
        assert data["enabled"] is True
        assert data["port"] == 8000
        assert data["firewall_subnets"] == ["10.0.0.0/24"]
        assert data["reachable"] is True
        assert data["detected_local_subnets"] == ["192.168.1.0/24"]


class TestConfigureIcecastFirewallRoute:
    URL = "/admin/firewall/api/icecast"

    def _post(self, app, payload):
        with app.test_request_context(self.URL, method="POST", json=payload):
            return configure_icecast_firewall()

    def test_requires_authentication(self, app):
        result = self._post(app, {"subnets": []})
        _body, status = result
        assert status == 401

    def test_invalid_cidr_is_rejected(self, app, authenticated_user):
        with patch("webapp.admin.firewall.get_icecast_settings", return_value=_fake_icecast_settings()):
            response, status = self._post(app, {"subnets": ["not-a-subnet"]})
        assert status == 400
        assert "not-a-subnet" in response.get_json()["error"]

    def test_subnets_must_be_a_list(self, app, authenticated_user):
        with patch("webapp.admin.firewall.get_icecast_settings", return_value=_fake_icecast_settings()):
            response, status = self._post(app, {"subnets": "192.168.1.0/24"})
        assert status == 400

    def test_adds_missing_and_removes_stale_tagged_rules(self, app, authenticated_user):
        calls = []

        # Current state (from a prior "ufw status verbose" read): tagged
        # rule for 172.16.0.0/24 already exists but is no longer desired;
        # 192.168.1.0/24 is desired but missing.
        current_status = (
            f"8000/tcp                   ALLOW IN    172.16.0.0/24             # {_ICECAST_UFW_TAG}\n"
        )

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "status" in cmd:
                return _proc(0, current_status)
            return _proc(0, "Rule added")

        with patch("webapp.admin.firewall.get_icecast_settings", return_value=_fake_icecast_settings(port=8000)), \
             patch("webapp.admin.firewall.subprocess.run", side_effect=fake_run):
            response = self._post(app, {"subnets": ["192.168.1.0/24"]})

        data = response.get_json()
        assert data["success"] is True

        allow_calls = [c for c in calls if "allow" in c and "status" not in c and "delete" not in c]
        delete_calls = [c for c in calls if "delete" in c]
        assert any("192.168.1.0/24" in c for c in allow_calls)
        assert any("172.16.0.0/24" in c for c in delete_calls)

    def test_empty_subnets_closes_the_port(self, app, authenticated_user):
        # Tracks real UFW state across calls so the final re-read (used to
        # build the response) reflects the delete this request issues,
        # rather than a static fixture that would mask a real "still
        # reachable after supposedly closing it" bug.
        subnets_present = {"192.168.1.0/24"}
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "status" in cmd:
                lines = [
                    f"8000/tcp                   ALLOW IN    {s}             # {_ICECAST_UFW_TAG}\n"
                    for s in subnets_present
                ]
                return _proc(0, "".join(lines))
            if "delete" in cmd:
                subnets_present.discard(cmd[cmd.index("from") + 1])
                return _proc(0, "Rule deleted")
            return _proc(0, "Rule added")

        with patch("webapp.admin.firewall.get_icecast_settings", return_value=_fake_icecast_settings(port=8000)), \
             patch("webapp.admin.firewall.subprocess.run", side_effect=fake_run):
            response = self._post(app, {"subnets": []})

        data = response.get_json()
        assert data["success"] is True
        assert data["reachable"] is False
        assert any("delete" in c and "192.168.1.0/24" in c for c in calls)


class TestFirewallPageRoute:
    def test_requires_authentication(self, app):
        with app.test_request_context("/admin/firewall/", headers={"Accept": "application/json"}):
            result = firewall_page()
        _body, status = result
        assert status == 401

    def test_renders_for_authenticated_admin(self, app, authenticated_user):
        # _build_checks() (security_checkup) and _ntp_status() (ntp_server)
        # are each covered by their own test suites; stub them here so this
        # test verifies firewall_page()'s own aggregation/rendering without
        # needing fail2ban/chrony's real DB tables and subprocess calls too.
        fake_checkup = {"checks": [], "ufw": {"installed": True, "active": True, "default_deny_incoming": True, "missing_baseline_ports": []}, "fail2ban": {}}
        fake_ntp = {"installed": True, "active": True, "enabled": False, "configured_subnets": [], "firewall_subnets": [], "firewall_in_sync": True, "detected_local_subnets": [], "clients": {"clients": []}}
        with patch("webapp.admin.security_checkup._build_checks", return_value=fake_checkup), \
             patch("webapp.admin.ntp_server._ntp_status", return_value=fake_ntp), \
             patch("webapp.admin.firewall.get_icecast_settings", return_value=_fake_icecast_settings()), \
             patch("webapp.admin.firewall.subprocess.run", return_value=_proc(0, "Status: inactive\n")):
            with app.test_request_context("/admin/firewall/"):
                result = firewall_page()
        # A rendered template string, not an error tuple.
        assert isinstance(result, str)
        assert "Firewall" in result
