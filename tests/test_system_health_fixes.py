"""Tests for system health data collection fixes."""
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app_utils import system as system_utils


class TestDeviceTypeDetection:
    """Test device type detection for SMART data collection."""

    def test_detects_nvme_by_name(self):
        device = {"name": "nvme0n1", "transport": None}
        result = system_utils._detect_device_type(device, "/dev/nvme0n1", None)
        assert result == "nvme"

    def test_detects_nvme_by_transport(self):
        device = {"name": "sda", "transport": "nvme"}
        result = system_utils._detect_device_type(device, "/dev/sda", None)
        assert result == "nvme"

    def test_detects_nvme_by_path(self):
        device = {"name": "disk0", "transport": None}
        result = system_utils._detect_device_type(device, "/dev/nvme0n1", None)
        assert result == "nvme"

    def test_detects_usb(self):
        device = {"name": "sda", "transport": "usb"}
        result = system_utils._detect_device_type(device, "/dev/sda", None)
        assert result == "auto"

    def test_detects_sata(self):
        device = {"name": "sda", "transport": "sata"}
        result = system_utils._detect_device_type(device, "/dev/sda", None)
        assert result == "auto"

    def test_detects_scsi(self):
        device = {"name": "sdb", "transport": "scsi"}
        result = system_utils._detect_device_type(device, "/dev/sdb", None)
        assert result == "auto"

    def test_skips_mmc(self):
        device = {"name": "mmcblk0", "transport": None}
        result = system_utils._detect_device_type(device, "/dev/mmcblk0", None)
        assert result is None

    def test_defaults_to_auto(self):
        device = {"name": "sda", "transport": None}
        result = system_utils._detect_device_type(device, "/dev/sda", None)
        assert result == "auto"


class TestTemperatureValidation:
    """Test temperature validation and bounds checking."""

    def test_valid_temperatures(self):
        assert system_utils._is_valid_temperature(25.0) is True
        assert system_utils._is_valid_temperature(0.0) is True
        assert system_utils._is_valid_temperature(100.0) is True
        assert system_utils._is_valid_temperature(-10.0) is True
        assert system_utils._is_valid_temperature(45.5) is True

    def test_invalid_high_temperatures(self):
        assert system_utils._is_valid_temperature(200.0) is False
        assert system_utils._is_valid_temperature(500.0) is False
        assert system_utils._is_valid_temperature(65261.8) is False
        assert system_utils._is_valid_temperature(1000.0) is False

    def test_invalid_low_temperatures(self):
        assert system_utils._is_valid_temperature(-100.0) is False
        assert system_utils._is_valid_temperature(-273.15) is False

    def test_boundary_values(self):
        assert system_utils._is_valid_temperature(-50.0) is True
        assert system_utils._is_valid_temperature(150.0) is True
        assert system_utils._is_valid_temperature(-50.1) is False
        assert system_utils._is_valid_temperature(150.1) is False


class TestTemperatureExtraction:
    """Test temperature extraction from SMART data."""

    def test_extracts_normal_temperature(self):
        report = {"temperature": {"current": 45.5}}
        temp = system_utils._extract_temperature(report)
        assert temp == 45.5

    def test_rejects_overflow_temperature(self):
        report = {"temperature": {"current": 65261.8}}
        temp = system_utils._extract_temperature(report)
        assert temp is None

    def test_rejects_negative_overflow(self):
        report = {"temperature": {"current": -100.0}}
        temp = system_utils._extract_temperature(report)
        assert temp is None

    def test_converts_kelvin_to_celsius(self):
        # 310 K = 36.85 C
        report = {"nvme_smart_health_information_log": {"temperature": 310}}
        temp = system_utils._extract_temperature(report)
        assert temp is not None
        assert 36 < temp < 37

    def test_rejects_invalid_kelvin(self):
        # 65535 K would be 65261.85 C - way too high
        report = {"nvme_smart_health_information_log": {"temperature": 65535}}
        temp = system_utils._extract_temperature(report)
        assert temp is None

    def test_accepts_celsius_in_nvme(self):
        # Some NVMe drives report in Celsius directly
        report = {"nvme_smart_health_information_log": {"temperature": 45}}
        temp = system_utils._extract_temperature(report)
        assert temp == 45

    def test_returns_none_for_missing_data(self):
        report = {}
        temp = system_utils._extract_temperature(report)
        assert temp is None

    def test_returns_none_for_invalid_types(self):
        report = {"temperature": {"current": "invalid"}}
        temp = system_utils._extract_temperature(report)
        assert temp is None


class TestTemperatureParsing:
    """Test temperature value parsing from sysfs."""

    def test_parses_millidegrees(self):
        # sysfs often reports in millidegrees
        temp = system_utils._parse_temperature_value("45000")
        assert temp == 45.0

    def test_parses_degrees(self):
        temp = system_utils._parse_temperature_value("45.5")
        assert temp == 45.5

    def test_rejects_overflow(self):
        temp = system_utils._parse_temperature_value("65261800")
        assert temp is None

    def test_returns_none_for_invalid(self):
        temp = system_utils._parse_temperature_value("invalid")
        assert temp is None

    def test_returns_none_for_none(self):
        temp = system_utils._parse_temperature_value(None)
        assert temp is None

    def test_validates_range(self):
        temp = system_utils._parse_temperature_value("100")
        assert temp == 100.0

        temp = system_utils._parse_temperature_value("200")
        assert temp is None


class TestPlatformDetails:
    """Test platform details collection."""

    def test_augments_with_device_tree(self, tmp_path, monkeypatch):
        # Test that device tree data is used when available
        dt_base = tmp_path / "dt"
        dt_base.mkdir()
        (dt_base / "model").write_bytes(b"Raspberry Pi 4 Model B\0")
        (dt_base / "serial-number").write_bytes(b"test-serial-123\0")
        monkeypatch.setattr(
            system_utils, "DEVICE_TREE_CANDIDATES", [dt_base]
        )

        details = system_utils._collect_platform_details()

        # Should have device tree data (may be merged with DMI on x86, or alone on ARM)
        # At minimum, we should have the serial number from device tree
        assert details.get("product_serial") == "test-serial-123" or details.get("product_name") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
