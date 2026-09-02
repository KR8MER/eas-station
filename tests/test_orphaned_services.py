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

Tests for app_utils/system/services.py's orphaned-failed-unit detection.

Found on a real deployment: eas-station-eas.service (retired when its
functionality was folded into -audio/-demod during the hardware subsystem
split) was left in systemd as a stale `not-found`/`failed` unit -- update.sh
never disables/removes units for services that get renamed or removed. The
System Services dashboard only ever checked a fixed allowlist
(EAS_SERVICES/POLLER_SERVICES), so that failed unit was completely invisible
to it. _collect_orphaned_failed_services closes that gap by also asking
systemd directly for any eas-station-* unit in a failed state, regardless of
whether the allowlist still knows its name.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from app_utils.system.services import _collect_orphaned_failed_services

_LOGGER = logging.getLogger("test")


def _proc(stdout):
    result = MagicMock()
    result.stdout = stdout
    return result


class TestCollectOrphanedFailedServices:
    def test_finds_a_failed_unit_not_in_the_known_list(self):
        # `systemctl list-units --plain --no-legend` column format.
        stdout = "eas-station-eas.service loaded failed failed eas-station-eas.service\n"
        with patch("app_utils.system.services.subprocess.run", return_value=_proc(stdout)):
            orphans = _collect_orphaned_failed_services(_LOGGER, "eas-station", set())

        assert len(orphans) == 1
        assert orphans[0]["name"] == "eas-station-eas.service"

    def test_excludes_a_unit_already_in_the_known_list(self):
        # If it's still in EAS_SERVICES, the per-name loop already reports
        # it -- this sweep must not double-report it as an "orphan".
        stdout = "eas-station-audio.service loaded failed failed EAS Station Audio\n"
        with patch("app_utils.system.services.subprocess.run", return_value=_proc(stdout)):
            orphans = _collect_orphaned_failed_services(
                _LOGGER, "eas-station", {"eas-station-audio.service"}
            )

        assert orphans == []

    def test_excludes_template_instantiated_units(self):
        # eas-station-failure-recovery@<subsystem>.service is legitimate,
        # currently-relevant infrastructure the static allowlist can't
        # enumerate ahead of time (the instance name is dynamic) -- it must
        # not get the "leftover from a retired service" message.
        stdout = (
            "eas-station-failure-recovery@eas-station-audio.service loaded failed failed "
            "EAS Station Failure Recovery for eas-station-audio.service\n"
        )
        with patch("app_utils.system.services.subprocess.run", return_value=_proc(stdout)):
            orphans = _collect_orphaned_failed_services(_LOGGER, "eas-station", set())

        assert orphans == []

    def test_no_failed_units_returns_empty_list(self):
        with patch("app_utils.system.services.subprocess.run", return_value=_proc("")):
            orphans = _collect_orphaned_failed_services(_LOGGER, "eas-station", set())

        assert orphans == []

    def test_subprocess_failure_returns_empty_list_rather_than_raising(self):
        with patch(
            "app_utils.system.services.subprocess.run",
            side_effect=OSError("systemctl not found"),
        ):
            orphans = _collect_orphaned_failed_services(_LOGGER, "eas-station", set())

        assert orphans == []


class TestCollectSystemdServicesIncludesOrphans:
    """Integration-style: _collect_systemd_services must fold orphan results
    into `services`, `summary`, and `issues` the same way it does for
    allowlisted services.
    """

    def test_orphan_counted_in_summary_and_flagged_as_an_issue(self):
        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["systemctl", "list-unit-files"]:
                # Every allowlisted service "exists" but produces no other
                # output worth asserting on here.
                return _proc(cmd[2])
            if cmd[:2] == ["systemctl", "show"]:
                return MagicMock(
                    returncode=0,
                    stdout=(
                        "ActiveState=active\nSubState=running\n"
                        "LoadState=loaded\nUnitFileState=enabled\n"
                        "Description=fake\n"
                    ),
                )
            if cmd[:2] == ["systemctl", "list-units"]:
                return _proc(
                    "eas-station-eas.service loaded failed failed "
                    "EAS Station EAS Monitoring Service\n"
                )
            raise AssertionError(f"unexpected command: {cmd}")

        with patch("app_utils.system.services.subprocess.run", side_effect=fake_run):
            from app_utils.system.services import _collect_systemd_services

            result = _collect_systemd_services(_LOGGER)

        orphan_services = [s for s in result["services"] if s.get("orphaned")]
        assert len(orphan_services) == 1
        assert orphan_services[0]["name"] == "eas-station-eas.service"
        assert orphan_services[0]["active_state"] == "failed"

        assert result["summary"]["failed"] >= 1
        assert any(
            "eas-station-eas.service" in issue["service"] and issue["severity"] == "error"
            for issue in result["issues"]
        )
