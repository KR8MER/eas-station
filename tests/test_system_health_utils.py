import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app_utils import system as system_utils


class DummyCPUFreq:
    def __init__(self, current=1500.0, min_freq=600.0, max_freq=2400.0):
        self.current = current
        self.min = min_freq
        self.max = max_freq


@pytest.fixture
def sample_cpuinfo_text():
    return (
        "processor\t: 0\n"
        "model name\t: ARMv8 Processor rev 3 (v8l)\n"
        "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32\n"
        "CPU implementer\t: 0x41\n"
        "CPU architecture\t: 8\n"
        "CPU part\t: 0xd0c\n"
        "CPU revision\t: 3\n\n"
        "Hardware\t: BCM2835\n"
        "Revision\t: d03114\n"
        "Serial\t: 10000000abcdef01\n"
    )


def test_collect_cpu_details_reads_arm_fields(monkeypatch, sample_cpuinfo_text):
    original_exists = Path.exists
    original_read_text = Path.read_text

    def fake_exists(self):
        if str(self) == "/proc/cpuinfo":
            return True
        return original_exists(self)

    def fake_read_text(self, *args, **kwargs):
        if str(self) == "/proc/cpuinfo":
            return sample_cpuinfo_text
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(system_utils, "Path", Path)
    monkeypatch.setattr(Path, "exists", fake_exists, raising=False)
    monkeypatch.setattr(Path, "read_text", fake_read_text, raising=False)

    # Ensure predictable CPU frequency values to avoid relying on host environment.
    monkeypatch.setattr(system_utils.psutil, "cpu_freq", lambda: DummyCPUFreq())
    monkeypatch.setattr(system_utils.psutil, "cpu_count", lambda logical=True: 8 if logical else 4)

    details = system_utils._collect_cpu_details(logger=None)

    assert details["model_name"] == "ARMv8 Processor rev 3 (v8l)"
    assert details["vendor_id"] == "0x41"
    assert details["hardware"] == "BCM2835"
    assert details["revision"] == "d03114"
    assert details["serial"] == "10000000abcdef01"
    assert "asimd" in details["flags"]
    assert details["supports_virtualization"] is False


def test_collect_device_tree_details(tmp_path, monkeypatch):
    base = tmp_path / "dt"
    base.mkdir()
    (base / "model").write_bytes(b"Raspberry Pi 5 Model B\0")
    (base / "serial-number").write_bytes(b"123456789abcdef0\0")
    system_dir = base / "system"
    system_dir.mkdir()
    (system_dir / "linux,revision").write_bytes((0x1A2B3C4D).to_bytes(4, byteorder="big"))
    (base / "compatible").write_bytes(b"raspberrypi,5-model-b\0brcm,bcm2712\0")

    monkeypatch.setattr(system_utils, "DEVICE_TREE_CANDIDATES", [base])

    details = system_utils._collect_device_tree_details()

    assert details["product_name"] == "Raspberry Pi 5 Model B"
    assert details["board_name"] == "Raspberry Pi 5 Model B"
    assert details["sys_vendor"] == "Raspberry Pi Foundation"
    assert details["product_serial"] == "123456789abcdef0"
    assert details["product_version"] == "0x1a2b3c4d"
    assert "raspberrypi,5-model-b" in details["compatible"]


def test_populate_nvme_metrics_converts_units():
    device_result = {
        "power_on_hours": None,
        "power_cycle_count": None,
        "unsafe_shutdowns": None,
        "percentage_used": None,
        "data_units_written": None,
        "data_units_written_bytes": None,
        "data_units_read": None,
        "data_units_read_bytes": None,
        "host_writes_32mib": None,
        "host_writes_bytes": None,
        "host_reads_32mib": None,
        "host_reads_bytes": None,
    }

    report = {
        "nvme_smart_health_information_log": {
            "power_on_hours": 123,
            "power_cycles": 45,
            "unsafe_shutdowns": 2,
            "percentage_used": 7,
            "data_units_written": 100,
            "data_units_read": 50,
            "host_writes_32mib": 4,
            "host_reads_32mib": 2,
        }
    }

    system_utils._populate_nvme_metrics(device_result, report)

    assert device_result["power_on_hours"] == 123
    assert device_result["power_cycle_count"] == 45
    assert device_result["unsafe_shutdowns"] == 2
    assert device_result["percentage_used"] == 7
    assert device_result["data_units_written_bytes"] == 100 * 512_000
    assert device_result["data_units_read_bytes"] == 50 * 512_000
    assert device_result["host_writes_bytes"] == 4 * 32 * 1024 * 1024
    assert device_result["host_reads_bytes"] == 2 * 32 * 1024 * 1024
