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

"""Characterization tests for ``_collect_smart_health``, written before
Phase 4a-ii splits it (see ``docs/development/LARGE_FILE_REFACTOR_PLAN.md``).

``tests/test_smart_health.py`` already covers the exit-code-based
``overall_status`` inference in depth; this file covers the rest of the
function's behaviour that a restructure could break: smartctl discovery,
subprocess failure modes, output validation, and the field extraction that
wires a parsed smartctl report into the device result dict. The individual
field extractors in ``smart_fields.py`` (``_extract_attribute_value``,
``_populate_nvme_metrics``, etc.) already have their own tests in
``tests/test_system_health_fixes.py`` / ``tests/test_system_health_utils.py``
— this file only pins that ``_collect_smart_health`` wires their results
into the right keys, not their internal correctness.
"""

import logging
from unittest.mock import MagicMock, patch

from app_utils.system.smart import _collect_smart_health

_LOGGER = logging.getLogger("test")


def _device(name="sda", transport="sata", **overrides):
    device = {"name": name, "type": "disk", "path": f"/dev/{name}", "transport": transport}
    device.update(overrides)
    return device


def _proc(returncode, stdout, stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# smartctl discovery
# ---------------------------------------------------------------------------


def test_smartctl_not_found_anywhere():
    with patch("shutil.which", return_value=None), patch(
        "app_utils.system.smart_command.os.path.exists", return_value=False
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert result["available"] is False
    assert result["error"] == "smartctl utility not installed"
    assert "smartmontools" in result["install_guide"]
    assert result["devices"] == []


def test_smartctl_found_via_fallback_candidate_path():
    with patch("shutil.which", return_value=None), patch(
        "app_utils.system.smart_command.os.path.exists", side_effect=lambda p: p == "/usr/sbin/smartctl"
    ), patch("app_utils.system.smart_command.os.access", return_value=True), patch(
        "app_utils.system.smart_query.subprocess.run",
        return_value=_proc(0, '{"ata_smart_attributes": {"table": []}}'),
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert result["available"] is True
    assert result["devices"][0]["overall_status"] == "passed"


def test_no_devices_at_all_reports_summary_error():
    with patch("shutil.which", return_value="/usr/sbin/smartctl"):
        result = _collect_smart_health(_LOGGER, [])

    assert result["available"] is True
    assert result["devices"] == []
    assert result["error"] == "No SMART-capable block devices found"


def test_device_without_a_derivable_path_is_skipped(caplog):
    device = {"name": None, "type": "disk", "path": None, "transport": "sata"}
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run"
    ) as run_mock:
        result = _collect_smart_health(_LOGGER, [device])

    run_mock.assert_not_called()
    assert result["devices"] == []
    # Falls through to the "no eligible devices" summary, same as an empty list.
    assert result["error"] == "No SMART-capable block devices found"


# ---------------------------------------------------------------------------
# subprocess failure modes
# ---------------------------------------------------------------------------


def test_subprocess_timeout(monkeypatch):
    import subprocess

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="smartctl", timeout=15)

    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", side_effect=raise_timeout
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    device = result["devices"][0]
    assert "timed out" in device["error"]
    assert device["exit_status"] is None


def test_subprocess_permission_denied():
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", side_effect=PermissionError("denied")
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert "Permission denied" in result["devices"][0]["error"]


def test_subprocess_generic_exception():
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", side_effect=OSError("no such executable")
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert "smartctl execution failed" in result["devices"][0]["error"]
    assert "no such executable" in result["devices"][0]["error"]


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


def test_nonzero_exit_with_empty_output_invalid_command_line():
    # Bit 0 (0x01) only.
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(1, "", stderr="")
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert "Invalid command line arguments" in result["devices"][0]["error"]


def test_nonzero_exit_with_empty_output_device_open_failed():
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(2, "", stderr="")
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    device = result["devices"][0]
    assert device["exit_status"] == 2
    assert "Device open failed" in device["error"]


def test_nonzero_exit_with_empty_output_smart_command_failed():
    # Bit 2 (0x04) only.
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(4, "", stderr="")
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert "SMART command failed" in result["devices"][0]["error"]


def test_zero_exit_with_empty_output():
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(0, "")
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert result["devices"][0]["error"] == "No data returned from smartctl"


def test_invalid_json_output():
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(0, "{not valid json")
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert "Unable to parse smartctl output" in result["devices"][0]["error"]


def test_stderr_only_error_when_nothing_more_specific_was_derived():
    # Bit 3 (disk failing) set, bits 0-2 clear: overall_status is derived but
    # no error message is set by the status-inference branch, so the final
    # stderr fallback should fire.
    stdout = '{"ata_smart_attributes": {"table": []}}'
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run",
        return_value=_proc(0x08, stdout, stderr="SMART overall-health: FAILED"),
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    device = result["devices"][0]
    assert device["overall_status"] == "failed"
    assert device["error"] == "SMART overall-health: FAILED"


def test_stderr_not_recorded_when_exit_code_is_zero():
    stdout = '{"ata_smart_attributes": {"table": []}}'
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run",
        return_value=_proc(0, stdout, stderr="harmless sudo banner"),
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert result["devices"][0]["error"] is None


# ---------------------------------------------------------------------------
# Field extraction wiring
# ---------------------------------------------------------------------------


def test_ata_device_field_wiring():
    stdout = """
    {
        "model_name": "Samsung SSD 860",
        "serial_number": "S3Z9NB0K123456",
        "firmware_version": "RVT03B6Q",
        "user_capacity": {"bytes": 500107862016},
        "smart_status": {"passed": true},
        "temperature": {"current": 34},
        "ata_smart_attributes": {
            "table": [
                {"name": "Power_On_Hours", "raw": {"value": 8760}},
                {"name": "Power_Cycle_Count", "raw": {"value": 42}},
                {"name": "Reallocated_Sector_Ct", "raw": {"value": 0}},
                {"name": "Current_Pending_Sector", "raw": {"value": 0}}
            ]
        }
    }
    """
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(0, stdout)
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    device = result["devices"][0]
    assert device["model"] == "Samsung SSD 860"
    assert device["serial"] == "S3Z9NB0K123456"
    assert device["firmware_version"] == "RVT03B6Q"
    assert device["total_capacity_bytes"] == 500107862016
    assert device["overall_status"] == "passed"
    assert device["temperature_celsius"] == 34
    assert device["power_on_hours"] == 8760
    assert device["power_cycle_count"] == 42
    assert device["reallocated_sector_count"] == 0
    assert device["pending_sector_count"] == 0


def test_model_name_falls_back_through_model_family_and_device_model():
    stdout = '{"device_model": "WDC WD40EFRX-68N32N0"}'
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(0, stdout)
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert result["devices"][0]["model"] == "WDC WD40EFRX-68N32N0"


def test_reallocated_sector_count_falls_back_to_alternate_attribute_name():
    stdout = """
    {
        "ata_smart_attributes": {
            "table": [
                {"name": "Reallocated_Sector_Count", "raw": {"value": 3}}
            ]
        }
    }
    """
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(0, stdout)
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert result["devices"][0]["reallocated_sector_count"] == 3


def test_nvme_device_field_wiring_and_temperature_sensor_conversion():
    stdout = """
    {
        "nvme_total_capacity": 1000204886016,
        "nvme_unallocated_capacity": 0,
        "nvme_controller_id": 1,
        "nvme_number_of_namespaces": 1,
        "nvme_version": {"string": "1.4"},
        "nvme_ieee_oui_identifier": 6083300,
        "nvme_smart_health_information_log": {
            "critical_warning": 0,
            "available_spare": 100,
            "available_spare_threshold": 10,
            "warning_comp_temperature_time": 5,
            "critical_comp_temperature_time": 2,
            "num_err_log_entries": 1,
            "temperature_sensors": [307, 45, 9999]
        }
    }
    """
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(0, stdout)
    ):
        result = _collect_smart_health(_LOGGER, [_device("nvme0n1", transport="nvme")])

    device = result["devices"][0]
    assert device["total_capacity_bytes"] == 1000204886016
    assert device["nvme_controller_id"] == 1
    assert device["nvme_number_of_namespaces"] == 1
    assert device["nvme_version_string"] == "1.4"
    assert device["ieee_oui_identifier"] == "5CD2E4"  # hex(6083300) zero-padded to 6 digits
    assert device["overall_status"] == "passed"
    assert device["available_spare"] == 100
    assert device["available_spare_threshold"] == 10
    assert device["warning_temp_time_minutes"] == 5
    assert device["critical_temp_time_minutes"] == 2
    assert device["num_error_log_entries"] == 1
    # 307 (>200, treated as Kelvin) -> 33.85 C, valid. 45 (<=200) is kept as
    # a raw Celsius reading, valid. 9999 (>200) converts to ~9725.85 C, which
    # fails the -50..150 plausibility check and is dropped.
    assert device["temperature_sensors_celsius"] == [33.9, 45.0]


def test_warning_and_critical_temp_time_zero_is_pre_existing_quirk():
    """Pinning current behaviour, not endorsing it: ``_coerce_int(x) or
    _coerce_int(y)`` treats a genuine ``0`` from the first field as falsy and
    falls through to the (absent) second field name, so a literal 0 comes out
    as ``None`` rather than ``0``. Documented here rather than fixed in a
    pure-motion split — fixing it is a behaviour change."""

    stdout = """
    {
        "nvme_smart_health_information_log": {
            "warning_comp_temperature_time": 0,
            "critical_comp_temperature_time": 0
        }
    }
    """
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(0, stdout)
    ):
        result = _collect_smart_health(_LOGGER, [_device("nvme0n1", transport="nvme")])

    device = result["devices"][0]
    assert device["warning_temp_time_minutes"] is None
    assert device["critical_temp_time_minutes"] is None


def test_diagnostic_report_keys_are_recorded():
    stdout = '{"ata_smart_attributes": {"table": []}, "temperature": {"current": 30}}'
    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", return_value=_proc(0, stdout)
    ):
        result = _collect_smart_health(_LOGGER, [_device()])

    assert result["devices"][0]["_diag_report_keys"] == ["ata_smart_attributes", "temperature"]


def test_multiple_devices_are_each_queried_independently():
    def run_side_effect(command, **kwargs):
        if "/dev/sda" in command:
            return _proc(0, '{"smart_status": {"passed": true}}')
        return _proc(0, '{"smart_status": {"passed": false}}')

    with patch("shutil.which", return_value="/usr/sbin/smartctl"), patch(
        "app_utils.system.smart_query.subprocess.run", side_effect=run_side_effect
    ):
        result = _collect_smart_health(_LOGGER, [_device("sda"), _device("sdb")])

    assert len(result["devices"]) == 2
    statuses = {d["name"]: d["overall_status"] for d in result["devices"]}
    assert statuses == {"sda": "passed", "sdb": "failed"}


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------
#
# _detect_device_type() (app_utils/system/disks.py) currently only ever
# returns "nvme" or "auto" -- it never produces "ata"/"sat" -- so
# _collect_smart_health() can't exercise the "-n standby" branch end to end
# today. Test _build_smartctl_command() directly instead; it is its own
# importable unit since Phase 4a-ii.


def test_standby_flag_added_for_ata_and_sat_device_types():
    # "-n" alone is ambiguous: sudo's own "don't prompt" flag is also "-n".
    # "standby" only ever appears as the argument to the query's own -n.
    from app_utils.system.smart_command import _build_smartctl_command

    for flag in ("ata", "sat"):
        command = _build_smartctl_command("/usr/sbin/smartctl", flag, "/dev/sda")
        assert "standby" in command
        assert command[command.index("standby") - 1] == "-n"


def test_standby_flag_omitted_for_other_device_types():
    from app_utils.system.smart_command import _build_smartctl_command

    for flag in ("nvme", "auto", None):
        command = _build_smartctl_command("/usr/sbin/smartctl", flag, "/dev/sda")
        assert "standby" not in command
