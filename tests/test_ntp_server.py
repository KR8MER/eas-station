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

Tests for webapp/admin/ntp_server.py -- the LAN NTP server admin page.

Like webapp.admin.mail_server, this module is deliberately stateless: the
chrony conf.d fragment on disk (never a DB row) is the single source of
truth for "which subnets are currently allowed", read back fresh on every
status check. The firewall side mirrors webapp.admin.security_checkup's
idempotent, tag-scoped reconciliation -- every rule this feature creates
carries a fixed UFW comment, and only rules carrying that exact comment are
ever added or removed through it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from webapp.admin.ntp_server import (
    _CONF_ALLOW_RE,
    _UFW_TAG,
    _client_summary,
    _configured_subnets,
    _detect_local_subnets,
    _firewall_subnets,
    _format_last_seen,
    _render_conf,
    _validate_cidr,
    configure_ntp_server,
    ntp_server_status,
)


def _proc(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestValidateCidr:
    def test_valid_cidr_passes_through_normalized(self):
        assert _validate_cidr("192.168.1.0/24") == "192.168.1.0/24"

    def test_single_ip_normalizes_to_slash_32(self):
        assert _validate_cidr("192.168.1.5") == "192.168.1.5/32"

    def test_ipv6_cidr_is_accepted(self):
        assert _validate_cidr("2001:db8::/32") == "2001:db8::/32"

    def test_host_bits_set_is_tolerated_not_strict(self):
        # strict=False: "192.168.1.5/24" describes a host inside that
        # network, not the network itself -- normalize rather than reject,
        # since an admin typing a host address with a prefix is a common
        # and unambiguous case.
        assert _validate_cidr("192.168.1.5/24") == "192.168.1.0/24"

    def test_garbage_raises_value_error(self):
        try:
            _validate_cidr("not-an-ip-address")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "not-an-ip-address" in str(exc)

    def test_empty_raises_value_error(self):
        try:
            _validate_cidr("   ")
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestRenderConf:
    def test_empty_list_renders_disabled_comment_only(self):
        content = _render_conf([])
        assert _CONF_ALLOW_RE.findall(content) == []
        assert "No subnets currently allowed" in content

    def test_subnets_render_one_allow_line_each_plus_local_stratum(self):
        content = _render_conf(["192.168.1.0/24", "100.64.0.0/10"])
        assert "allow 192.168.1.0/24" in content
        assert "allow 100.64.0.0/10" in content
        assert "local stratum 10" in content


class TestConfiguredSubnets:
    def test_parses_allow_lines_from_conf_file(self, tmp_path):
        conf = tmp_path / "eas-station-ntp-server.conf"
        conf.write_text("# comment\nallow 192.168.1.0/24\nallow 10.0.0.0/8\n\nlocal stratum 10\n")
        with patch("webapp.admin.ntp_server._CHRONY_CONF_FILE", conf):
            assert _configured_subnets() == ["192.168.1.0/24", "10.0.0.0/8"]

    def test_missing_file_returns_empty_list(self, tmp_path):
        with patch("webapp.admin.ntp_server._CHRONY_CONF_FILE", tmp_path / "does-not-exist.conf"):
            assert _configured_subnets() == []

    def test_regex_ignores_indented_or_trailing_content(self):
        # Sanity check on the shared regex directly: only a bare `allow
        # <subnet>` line (this module's own generated form) should match.
        text = "allow 192.168.1.0/24\n  allow 10.0.0.0/8\nallowlist something\n"
        assert _CONF_ALLOW_RE.findall(text) == ["192.168.1.0/24"]


class TestFirewallSubnets:
    def test_extracts_subnets_tagged_with_our_comment(self):
        stdout = (
            "22/tcp                     ALLOW IN    Anywhere\n"
            f"123/udp                    ALLOW IN    192.168.1.0/24             # {_UFW_TAG}\n"
            f"123/udp                    ALLOW IN    100.64.0.0/10              # {_UFW_TAG}\n"
        )
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(0, stdout)):
            assert _firewall_subnets() == ["192.168.1.0/24", "100.64.0.0/10"]

    def test_ignores_rules_with_a_different_comment(self):
        stdout = "123/udp                    ALLOW IN    203.0.113.0/24             # some-other-tool\n"
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(0, stdout)):
            assert _firewall_subnets() == []

    def test_ignores_non_123_rules_even_with_our_tag(self):
        # Defensive: this feature only ever writes port-123 rules, but the
        # parser itself must not accidentally pick up an unrelated port
        # that happened to reuse the same comment text.
        stdout = f"8000/tcp                   ALLOW IN    192.168.1.0/24             # {_UFW_TAG}\n"
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(0, stdout)):
            assert _firewall_subnets() == []

    def test_ufw_command_failure_returns_empty_list(self):
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(1, "", "permission denied")):
            assert _firewall_subnets() == []


class TestDetectLocalSubnets:
    def test_excludes_loopback_and_computes_network(self):
        ip_json = (
            '[{"ifname": "lo", "flags": ["LOOPBACK", "UP"], '
            '"addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]}, '
            '{"ifname": "eth0", "flags": ["BROADCAST", "UP"], '
            '"addr_info": [{"family": "inet", "local": "192.168.1.42", "prefixlen": 24}]}]'
        )
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(0, ip_json)):
            assert _detect_local_subnets() == ["192.168.1.0/24"]

    def test_ignores_ipv6_and_dedupes(self):
        ip_json = (
            '[{"ifname": "eth0", "flags": ["UP"], "addr_info": ['
            '{"family": "inet6", "local": "fe80::1", "prefixlen": 64}, '
            '{"family": "inet", "local": "10.0.0.5", "prefixlen": 24}, '
            '{"family": "inet", "local": "10.0.0.6", "prefixlen": 24}'
            ']}]'
        )
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(0, ip_json)):
            assert _detect_local_subnets() == ["10.0.0.0/24"]

    def test_command_failure_returns_empty_list_not_raise(self):
        with patch("webapp.admin.ntp_server.subprocess.run", side_effect=OSError("no ip binary")):
            assert _detect_local_subnets() == []


class TestFormatLastSeen:
    def test_dash_means_never(self):
        assert _format_last_seen("-") == "never"

    def test_seconds(self):
        assert _format_last_seen("45") == "45s ago"

    def test_minutes(self):
        assert _format_last_seen("125") == "2m ago"

    def test_hours(self):
        assert _format_last_seen(str(3 * 3600 + 60)) == "3h ago"

    def test_days(self):
        assert _format_last_seen(str(2 * 86400)) == "2d ago"

    def test_non_integer_passed_through(self):
        # Defensive: if a chrony build ever pre-formats this column itself
        # (some do, with a unit suffix), don't mangle it -- show it as-is.
        assert _format_last_seen("12m") == "12m"


class TestClientSummary:
    def test_excludes_localhost_row_and_includes_last_seen(self):
        stdout = (
            "Hostname                      NTP   Drop Int IntL Last     Cmd   Drop Int  Last\n"
            "===============================================================================\n"
            "localhost                       0      0   -   -     -  910780      0   2     3\n"
            "192.168.1.50                     3      0   6   -    12       0      0   -     -\n"
        )
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(0, stdout)):
            summary = _client_summary()
        assert summary["available"] is True
        assert summary["clients"] == [{"host": "192.168.1.50", "last_seen": "12s ago"}]

    def test_client_that_has_never_synced_shows_never(self):
        stdout = (
            "Hostname                      NTP   Drop Int IntL Last     Cmd   Drop Int  Last\n"
            "===============================================================================\n"
            "192.168.1.60                     0      0   -   -     -       2      0   1     1\n"
        )
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(0, stdout)):
            summary = _client_summary()
        assert summary["clients"] == [{"host": "192.168.1.60", "last_seen": "never"}]

    def test_command_failure_reports_unavailable(self):
        with patch("webapp.admin.ntp_server.subprocess.run", return_value=_proc(1, "", "not permitted")):
            summary = _client_summary()
        assert summary["available"] is False
        assert summary["clients"] == []


class TestConfigureNtpServerRoute:
    """Calls the decorated view function inside a bare request context, the
    same pattern test_upgrade_progress.py uses for routes gated only by
    ``require_permission`` -- this module's routes add ``require_auth`` on
    top, which ``authenticated_user`` also satisfies (see conftest.py).
    """

    URL = "/admin/ntp-server/configure"

    def _post(self, app, payload):
        with app.test_request_context(self.URL, method="POST", json=payload):
            return configure_ntp_server()

    def test_requires_authentication(self, app):
        result = self._post(app, {"enabled": False, "subnets": []})
        # An unauthenticated call returns a (body, status) tuple rather than
        # a Response, same as every other route in this codebase's suites.
        _body, status = result
        assert status == 401

    def test_enabling_with_no_subnets_is_rejected(self, app, authenticated_user):
        with patch("webapp.admin.ntp_server._chronyd_installed", return_value=True):
            response, status = self._post(app, {"enabled": True, "subnets": []})
        assert status == 400
        assert "at least one subnet" in response.get_json()["error"].lower()

    def test_invalid_cidr_is_rejected(self, app, authenticated_user):
        with patch("webapp.admin.ntp_server._chronyd_installed", return_value=True):
            response, status = self._post(app, {"enabled": True, "subnets": ["not-a-subnet"]})
        assert status == 400
        assert "not-a-subnet" in response.get_json()["error"]

    def test_chrony_not_installed_is_rejected(self, app, authenticated_user):
        with patch("webapp.admin.ntp_server._chronyd_installed", return_value=False):
            response, status = self._post(app, {"enabled": True, "subnets": ["192.168.1.0/24"]})
        assert status == 400
        assert "not installed" in response.get_json()["error"].lower()

    def test_enable_writes_conf_restarts_chrony_and_adds_firewall_rule(self, app, authenticated_user, tmp_path):
        conf_file = tmp_path / "eas-station-ntp-server.conf"
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["sudo", "tee"]:
                conf_file.write_text(kwargs.get("input", ""))
                return _proc(0, "")
            if "systemctl" in cmd and "restart" in cmd:
                return _proc(0, "")
            if "ufw" in cmd and "status" in cmd:
                return _proc(0, "")  # no existing tagged rules yet
            if "ufw" in cmd and "allow" in cmd:
                return _proc(0, "Rule added")
            raise AssertionError(f"unexpected command: {cmd}")

        with patch("webapp.admin.ntp_server._chronyd_installed", return_value=True), \
             patch("webapp.admin.ntp_server._CHRONY_CONF_FILE", conf_file), \
             patch("webapp.admin.ntp_server.subprocess.run", side_effect=fake_run):
            response = self._post(app, {"enabled": True, "subnets": ["192.168.1.0/24", "192.168.1.0/24"]})

        data = response.get_json()
        assert data["success"] is True
        assert "allow 192.168.1.0/24" in conf_file.read_text()
        # Deduped: the exact duplicate must not produce two firewall calls
        # or two conf lines.
        ufw_allow_calls = [c for c in calls if "ufw" in c and "allow" in c and "status" not in c]
        assert len(ufw_allow_calls) == 1
        assert ufw_allow_calls[0] == [
            "sudo", "-n", "ufw", "allow", "from", "192.168.1.0/24", "to", "any", "port", "123",
            "proto", "udp", "comment", _UFW_TAG,
        ]

    def test_disable_clears_conf_and_removes_only_our_tagged_rules(self, app, authenticated_user, tmp_path):
        conf_file = tmp_path / "eas-station-ntp-server.conf"
        conf_file.write_text(f"allow 192.168.1.0/24\n")
        calls = []

        ufw_status_output = f"123/udp                    ALLOW IN    192.168.1.0/24             # {_UFW_TAG}\n"

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["sudo", "tee"]:
                conf_file.write_text(kwargs.get("input", ""))
                return _proc(0, "")
            if "systemctl" in cmd and "restart" in cmd:
                return _proc(0, "")
            if "ufw" in cmd and "status" in cmd:
                return _proc(0, ufw_status_output)
            if "ufw" in cmd and "delete" in cmd:
                return _proc(0, "Rule deleted")
            raise AssertionError(f"unexpected command: {cmd}")

        with patch("webapp.admin.ntp_server._chronyd_installed", return_value=True), \
             patch("webapp.admin.ntp_server._CHRONY_CONF_FILE", conf_file), \
             patch("webapp.admin.ntp_server.subprocess.run", side_effect=fake_run):
            response = self._post(app, {"enabled": False, "subnets": ["192.168.1.0/24"]})

        data = response.get_json()
        assert data["success"] is True
        assert _CONF_ALLOW_RE.findall(conf_file.read_text()) == []
        delete_calls = [c for c in calls if "ufw" in c and "delete" in c]
        assert delete_calls == [
            ["sudo", "-n", "ufw", "delete", "allow", "from", "192.168.1.0/24", "to", "any",
             "port", "123", "proto", "udp"]
        ]


class TestNtpServerStatusRoute:
    URL = "/admin/ntp-server/status"

    def test_requires_authentication(self, app):
        with app.test_request_context(self.URL, headers={"Accept": "application/json"}):
            result = ntp_server_status()
        _body, status = result
        assert status == 401
