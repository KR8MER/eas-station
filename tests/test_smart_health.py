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

Tests for app_utils/system/smart.py's exit-code-based health inference.

smartctl's exit code is a bitmask (see `man smartctl`): bits 0-2 mean it
never actually got real SMART data at all (bad command line, device open
failed, or the SMART/ATA command itself failed), while bits 3-7 describe
actual disk health once bits 0-2 are clear. The fallback inference used
when smartctl's JSON has no `smart_status` block used to only check bits
3-7, so exit code 2 ("device open failed") sailed through as "no problem
bits set -> passed" -- reported as a healthy drive despite smartctl never
having successfully talked to anything.

Found on a Vultr KVM instance: its virtio-blk-backed /dev/vda has no
ATA/NVMe protocol to the underlying disk at all (true of virtio-blk
generally, not specific to this app or this cloud provider), so every
smartctl device-type probe returns exit code 2 with a mostly-empty but
validly-parsing JSON report -- exactly the shape that tripped this bug.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from app_utils.system.smart import _collect_smart_health

_LOGGER = logging.getLogger("test")


def _device(name="sda", transport="sata"):
    return {"name": name, "type": "disk", "path": f"/dev/{name}", "transport": transport}


def _proc(returncode, stdout, stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestExecutionFailureIsNotReportedAsPassed:
    def test_device_open_failed_reports_unknown_with_smartctl_message(self):
        # Real captured shape from a virtio-blk device: exit code 2, JSON
        # parses fine but has none of smart_status/ata_smart_attributes/
        # nvme_smart_health_information_log -- only smartctl's own message.
        stdout = (
            '{"json_format_version": [1, 0], "smartctl": {"messages": '
            '[{"string": "/dev/sda [SAT]: Unable to detect device type", '
            '"severity": "error"}]}, "device": {"name": "/dev/sda"}}'
        )
        with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
            "app_utils.system.smart.subprocess.run",
            return_value=_proc(2, stdout),
        ):
            result = _collect_smart_health(_LOGGER, [_device()])

        device = result["devices"][0]
        assert device["overall_status"] == "unknown"
        assert device["overall_status"] != "passed"
        assert "Unable to detect device type" in device["error"]

    def test_device_open_failed_without_messages_gets_generic_error(self):
        stdout = '{"json_format_version": [1, 0], "smartctl": {}, "device": {"name": "/dev/sda"}}'
        with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
            "app_utils.system.smart.subprocess.run",
            return_value=_proc(2, stdout),
        ):
            result = _collect_smart_health(_LOGGER, [_device()])

        device = result["devices"][0]
        assert device["overall_status"] == "unknown"
        assert "exit code 2" in device["error"]

    def test_command_line_error_bit_also_treated_as_no_data(self):
        # Bit 0 (command line did not parse) is in the same 0-2 range as
        # bit 1 (device open failed) -- neither should ever infer "passed".
        stdout = '{"smartctl": {"messages": [{"string": "bad flag", "severity": "error"}]}}'
        with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
            "app_utils.system.smart.subprocess.run",
            return_value=_proc(1, stdout),
        ):
            result = _collect_smart_health(_LOGGER, [_device()])

        assert result["devices"][0]["overall_status"] == "unknown"

    def test_stderr_does_not_clobber_the_more_specific_derived_message(self):
        stdout = (
            '{"smartctl": {"messages": [{"string": "specific reason", "severity": "error"}]}}'
        )
        with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
            "app_utils.system.smart.subprocess.run",
            return_value=_proc(2, stdout, stderr="generic sudo warning"),
        ):
            result = _collect_smart_health(_LOGGER, [_device()])

        assert result["devices"][0]["error"] == "specific reason"


class TestRealHealthInferenceStillWorks:
    """Regression coverage: bits 3-7 inference must keep working once bits
    0-2 are confirmed clear -- this fix must not change outcomes for a
    device smartctl actually could talk to.
    """

    def test_no_problem_bits_set_reports_passed(self):
        stdout = '{"ata_smart_attributes": {"table": []}}'
        with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
            "app_utils.system.smart.subprocess.run",
            return_value=_proc(0, stdout),
        ):
            result = _collect_smart_health(_LOGGER, [_device()])

        assert result["devices"][0]["overall_status"] == "passed"
        assert result["devices"][0]["error"] is None

    def test_disk_failing_bit_reports_failed(self):
        # Bit 3 (0x08) set, bits 0-2 clear.
        stdout = '{"ata_smart_attributes": {"table": []}}'
        with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
            "app_utils.system.smart.subprocess.run",
            return_value=_proc(0x08, stdout),
        ):
            result = _collect_smart_health(_LOGGER, [_device()])

        assert result["devices"][0]["overall_status"] == "failed"

    def test_nvme_critical_warning_nonzero_reports_failed(self):
        stdout = '{"nvme_smart_health_information_log": {"critical_warning": 1}}'
        with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
            "app_utils.system.smart.subprocess.run",
            return_value=_proc(0, stdout),
        ):
            result = _collect_smart_health(_LOGGER, [_device("nvme0n1", transport="nvme")])

        assert result["devices"][0]["overall_status"] == "failed"

    def test_nvme_critical_warning_zero_reports_passed(self):
        stdout = '{"nvme_smart_health_information_log": {"critical_warning": 0}}'
        with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
            "app_utils.system.smart.subprocess.run",
            return_value=_proc(0, stdout),
        ):
            result = _collect_smart_health(_LOGGER, [_device("nvme0n1", transport="nvme")])

        assert result["devices"][0]["overall_status"] == "passed"
