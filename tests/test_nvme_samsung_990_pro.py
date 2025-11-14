"""Test NVMe SMART data parsing with real Samsung 990 PRO output."""
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app_utils import system as system_utils


class TestNVMESamsung990Pro:
    """Test SMART data parsing for Samsung SSD 990 PRO 2TB."""

    def get_samsung_990_pro_smartctl_output(self):
        """Return the actual JSON structure from smartctl --json=o for Samsung 990 PRO."""
        return {
            "json_format_version": [1, 0],
            "smartctl": {
                "version": [7, 3],
                "platform_info": "aarch64-linux-6.12.47+rpt-rpi-2712"
            },
            "device": {
                "name": "/dev/nvme0",
                "info_name": "/dev/nvme0",
                "type": "nvme",
                "protocol": "NVMe"
            },
            "model_name": "Samsung SSD 990 PRO 2TB",
            "serial_number": "S7KHNU0X828984V",
            "firmware_version": "4B2QJXD7",
            "nvme_pci_vendor": {
                "id": 5197,
                "subsystem_id": 5197
            },
            "nvme_ieee_oui_identifier": 9528,
            "nvme_total_capacity": 2000398934016,
            "nvme_unallocated_capacity": 0,
            "nvme_controller_id": 1,
            "nvme_version": {
                "string": "2.0",
                "value": 131072
            },
            "nvme_number_of_namespaces": 1,
            "smart_status": {
                "passed": True,
                "nvme": {
                    "value": 0
                }
            },
            "nvme_smart_health_information_log": {
                "critical_warning": 0,
                "temperature": 45,
                "available_spare": 100,
                "available_spare_threshold": 10,
                "percentage_used": 2,
                "data_units_read": 55446743,
                "data_units_written": 54041648,
                "host_reads": 346082272,
                "host_writes": 382760336,
                "controller_busy_time": 1224,
                "power_cycles": 348,
                "power_on_hours": 3191,
                "unsafe_shutdowns": 57,
                "media_errors": 0,
                "num_err_log_entries": 0,
                "warning_temp_time": 0,
                "critical_comp_time": 0,
                "temperature_sensors": [45, 46]
            }
        }

    def test_overall_status_parsing(self):
        """Test that overall SMART status is correctly identified as 'passed'."""
        report = self.get_samsung_990_pro_smartctl_output()
        
        smart_status = report.get("smart_status") or {}
        passed = smart_status.get("passed")
        
        assert passed is True
        # This is how _collect_smart_health determines the status
        status = "passed" if passed is True else "failed" if passed is False else "unknown"
        assert status == "passed"

    def test_temperature_extraction(self):
        """Test temperature extraction from NVMe SMART data."""
        report = self.get_samsung_990_pro_smartctl_output()
        
        temperature = system_utils._extract_temperature(report)
        
        assert temperature is not None, "Temperature should be extracted"
        assert temperature == 45.0, f"Expected 45.0°C, got {temperature}°C"

    def test_power_metrics_extraction(self):
        """Test power-on hours and power cycles extraction."""
        report = self.get_samsung_990_pro_smartctl_output()
        
        # For NVMe, these come from nvme_smart_health_information_log via _populate_nvme_metrics
        device_result = {
            "power_on_hours": None,
            "power_cycle_count": None,
        }
        
        system_utils._populate_nvme_metrics(device_result, report)
        
        assert device_result["power_on_hours"] == 3191, "Power-on hours should be 3191"
        assert device_result["power_cycle_count"] == 348, "Power cycles should be 348"

    def test_media_errors_and_warnings(self):
        """Test media errors and critical warnings extraction."""
        report = self.get_samsung_990_pro_smartctl_output()
        
        media_errors = system_utils._extract_nvme_field(report, "media_errors")
        critical_warning = system_utils._extract_nvme_field(report, "critical_warning")
        
        assert media_errors == 0, "Media errors should be 0"
        assert critical_warning == 0, "Critical warning should be 0"

    def test_nvme_statistics_extraction(self):
        """Test NVMe-specific statistics extraction."""
        report = self.get_samsung_990_pro_smartctl_output()
        
        stats = system_utils._extract_nvme_statistics(report)
        
        # Check data units
        assert stats["data_units_written_bytes"] is not None, "Written bytes should be extracted"
        assert stats["data_units_read_bytes"] is not None, "Read bytes should be extracted"
        assert stats["data_units_written_bytes"] > 0, "Written bytes should be > 0"
        assert stats["data_units_read_bytes"] > 0, "Read bytes should be > 0"
        
        # Check host commands
        assert stats["host_read_commands"] == 346082272, "Host read commands should match"
        assert stats["host_write_commands"] == 382760336, "Host write commands should match"
        
        # Check other metrics
        assert stats["controller_busy_time_minutes"] == 1224, "Controller busy time should match"
        assert stats["unsafe_shutdowns"] == 57, "Unsafe shutdowns should match"
        assert stats["percentage_used"] == 2, "Percentage used should match"

    def test_complete_device_result(self):
        """Test complete device result as would be returned by _collect_smart_health."""
        report = self.get_samsung_990_pro_smartctl_output()
        
        # Simulate what _collect_smart_health does
        device_result = {
            "name": "nvme0n1",
            "path": "/dev/nvme0n1",
            "model": "Samsung SSD 990 PRO 2TB",
            "serial": "S7KHNU0X828984V",
            "transport": "nvme",
            "is_rotational": False,
            "overall_status": "unknown",
            "temperature_celsius": None,
            "power_on_hours": None,
            "power_cycle_count": None,
            "reallocated_sector_count": None,
            "media_errors": None,
            "critical_warnings": None,
            "data_units_written": None,
            "data_units_written_bytes": None,
            "data_units_read": None,
            "data_units_read_bytes": None,
            "host_writes_32mib": None,
            "host_writes_bytes": None,
            "host_reads_32mib": None,
            "host_reads_bytes": None,
            "percentage_used": None,
            "unsafe_shutdowns": None,
            "exit_status": 0,
            "error": None,
        }
        
        # Parse smart status
        smart_status = report.get("smart_status") or {}
        passed = smart_status.get("passed")
        if passed is True:
            device_result["overall_status"] = "passed"
        elif passed is False:
            device_result["overall_status"] = "failed"
        
        # Extract metrics
        device_result["temperature_celsius"] = system_utils._extract_temperature(report)
        device_result["power_on_hours"] = system_utils._extract_attribute_value(report, "Power_On_Hours")
        device_result["power_cycle_count"] = system_utils._extract_attribute_value(report, "Power_Cycle_Count")
        device_result["reallocated_sector_count"] = system_utils._extract_attribute_value(
            report, "Reallocated_Sector_Ct"
        )
        device_result["media_errors"] = system_utils._extract_nvme_field(report, "media_errors")
        device_result["critical_warnings"] = system_utils._extract_nvme_field(report, "critical_warning")
        
        nvme_stats = system_utils._extract_nvme_statistics(report)
        for key, value in nvme_stats.items():
            device_result[key] = value
        
        system_utils._populate_nvme_metrics(device_result, report)
        
        # Verify all key fields are populated correctly
        assert device_result["overall_status"] == "passed", "Status should be 'passed'"
        assert device_result["temperature_celsius"] == 45.0, "Temperature should be 45°C"
        assert device_result["power_on_hours"] == 3191, "Power-on hours should be 3191"
        assert device_result["power_cycle_count"] == 348, "Power cycles should be 348"
        assert device_result["media_errors"] == 0, "Media errors should be 0"
        assert device_result["critical_warnings"] == 0, "Critical warnings should be 0"
        assert device_result["percentage_used"] == 2, "Percentage used should be 2%"
        assert device_result["unsafe_shutdowns"] == 57, "Unsafe shutdowns should be 57"
        assert device_result["data_units_written_bytes"] > 0, "Data written should be > 0"
        assert device_result["data_units_read_bytes"] > 0, "Data read should be > 0"
        
        # NVMe devices don't have reallocated sectors (ATA-specific)
        assert device_result["reallocated_sector_count"] is None, "Reallocated sectors N/A for NVMe"
        
        # Verify key fields that the UI displays are NOT None
        ui_critical_fields = [
            "overall_status",
            "temperature_celsius",
            "power_on_hours",
            "media_errors",
            "percentage_used",
        ]
        for field in ui_critical_fields:
            assert device_result[field] is not None, f"UI field '{field}' should not be None"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
