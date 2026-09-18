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

"""Characterization tests for ``build_system_health_snapshot``.

Written *before* Phase 4a-ii splits the inline CPU/memory/disk/network/
process/load-average/database collection and the status computation out of
``app_utils/system/snapshot.py`` into their own collector modules (see
``docs/development/LARGE_FILE_REFACTOR_PLAN.md``). Every branch the function
takes through psutil, the process table, and the database probe is pinned
here first, with the twelve already-extracted sibling collectors (systemd,
hardware, SMART, temperature, dependencies, GPS, RTC, clock sync,
Raspberry-Pi health, OS details, shields badges, distro logo) stubbed out so
this file exercises only the orchestration logic that is moving.
"""

import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app_utils import system as system_utils

snap = system_utils.snapshot


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class ExecResult:
    def __init__(self, scalar_value=None, row=None):
        self._scalar_value = scalar_value
        self._row = row

    def scalar(self):
        return self._scalar_value

    def fetchone(self):
        return self._row


class MockSession:
    def __init__(self, execute_fn=None):
        self._execute_fn = execute_fn or self._default_execute
        self.rollback_calls = 0

    @staticmethod
    def _default_execute(query):
        sql = str(query)
        if "version()" in sql:
            return ExecResult(scalar_value="PostgreSQL 15.4")
        if "pg_size_pretty" in sql:
            return ExecResult(row=("42 MB",))
        if "pg_stat_activity" in sql:
            return ExecResult(row=(7,))
        raise AssertionError(f"unexpected query: {sql}")

    def rollback(self):
        self.rollback_calls += 1

    def execute(self, query):
        return self._execute_fn(query)


class MockDB:
    def __init__(self, execute_fn=None):
        self.session = MockSession(execute_fn)


class MockLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        self.warnings.append((args, kwargs))

    def error(self, *args, **kwargs):
        self.errors.append((args, kwargs))


class FakeProc:
    def __init__(self, pid, name, username, status, cpu_percent, memory_percent,
                 cmdline, access_error=None):
        self.pid = pid
        self.info = {"pid": pid, "name": name, "username": username, "status": status}
        self._cpu_percent = cpu_percent
        self._memory_percent = memory_percent
        self._cmdline = cmdline
        self._access_error = access_error

    def cpu_percent(self, interval=None):
        if self._access_error:
            raise self._access_error
        return self._cpu_percent

    def memory_percent(self):
        return self._memory_percent

    def name(self):
        return self.info["name"]

    def cmdline(self):
        return self._cmdline


def _addr(family, address, netmask=None, broadcast=None):
    return SimpleNamespace(family=family, address=address, netmask=netmask, broadcast=broadcast)


def _if_stat(isup=True, speed=1000, mtu=1500, duplex=2):
    return SimpleNamespace(isup=isup, speed=speed, mtu=mtu, duplex=duplex)


STUB_OS_DETAILS = {"distribution_id": "raspbian", "distribution": "Raspberry Pi OS"}
STUB_SYSTEMD = {
    "status": "operational",
    "services": [{"name": "eas-station-web", "status": "running"}],
    "summary": {"failed": 0},
}
STUB_HARDWARE_SUBSYSTEMS = {"network": {"status": "ok"}}
STUB_HARDWARE_INVENTORY = {
    "block_devices": {"devices": [{"name": "sda"}]},
    "platform": "raspberry-pi-4b",
}
STUB_SMART = {"devices": []}
STUB_TEMPERATURE = {"readings": []}
STUB_DEPENDENCIES = {"flask": "3.0.0"}
STUB_GPS = {"fix": None}
STUB_RTC = {"present": False}
STUB_CLOCK_SYNC = {"synced": True}
STUB_RASPBERRY_PI = {"model": "4B"}
STUB_BADGES = {"os": "https://img.shields.io/badge/os-raspbian-blue"}
STUB_DISTRO_LOGO = "https://example.invalid/logo.svg"


def _install_common_stubs(monkeypatch):
    """Stub every sibling collector snapshot.py delegates to untouched."""

    monkeypatch.setattr(snap, "_collect_operating_system_details", lambda: dict(STUB_OS_DETAILS))
    monkeypatch.setattr(snap, "_collect_systemd_services", lambda logger: dict(STUB_SYSTEMD))
    monkeypatch.setattr(
        snap, "_collect_hardware_subsystems", lambda logger: dict(STUB_HARDWARE_SUBSYSTEMS)
    )
    monkeypatch.setattr(
        snap, "_collect_hardware_inventory", lambda logger: dict(STUB_HARDWARE_INVENTORY)
    )
    monkeypatch.setattr(snap, "_collect_smart_health", lambda logger, devices: dict(STUB_SMART))
    monkeypatch.setattr(
        snap, "_collect_temperature_readings", lambda logger, smart_info: dict(STUB_TEMPERATURE)
    )
    monkeypatch.setattr(
        snap, "_collect_dependency_versions", lambda logger: dict(STUB_DEPENDENCIES)
    )
    monkeypatch.setattr(snap, "_collect_gps_status", lambda logger: dict(STUB_GPS))
    monkeypatch.setattr(snap, "_collect_rtc_status", lambda logger: dict(STUB_RTC))
    monkeypatch.setattr(snap, "_collect_clock_sync", lambda logger: dict(STUB_CLOCK_SYNC))
    monkeypatch.setattr(
        snap, "collect_raspberry_pi_health", lambda logger, platform: dict(STUB_RASPBERRY_PI)
    )
    monkeypatch.setattr(snap, "get_shields_io_badges", lambda health_data: dict(STUB_BADGES))
    monkeypatch.setattr(snap, "get_distro_logo_url", lambda distro_id: STUB_DISTRO_LOGO)

    monkeypatch.setattr(socket, "gethostname", lambda: "eas-station-test")

    # psutil is a single shared module object; patching it here patches the
    # same attribute every importer (snapshot.py, network.py, ...) sees.
    monkeypatch.setattr(psutil, "boot_time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(psutil, "cpu_freq", lambda: SimpleNamespace(max=2400.0, current=1500.0))
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)
    monkeypatch.setattr(
        psutil,
        "cpu_percent",
        lambda interval=None, percpu=False: [10.0, 12.0, 8.0, 5.0] if percpu else 8.75,
    )
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=1000, available=600, used=400, free=600, percent=40.0),
    )
    monkeypatch.setattr(
        psutil,
        "swap_memory",
        lambda: SimpleNamespace(total=200, used=10, free=190, percent=5.0),
    )
    monkeypatch.setattr(
        psutil,
        "disk_partitions",
        lambda: [SimpleNamespace(device="/dev/root", mountpoint="/", fstype="ext4")],
    )
    monkeypatch.setattr(
        psutil,
        "disk_usage",
        lambda mountpoint: SimpleNamespace(total=1000, used=250, free=750),
    )
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {})
    monkeypatch.setattr(psutil, "net_if_stats", lambda: {})

    def fake_net_io_counters(pernic=False):
        raise OSError("no io counters")

    monkeypatch.setattr(psutil, "net_io_counters", fake_net_io_counters)
    monkeypatch.setattr(psutil, "process_iter", lambda fields=None: [])
    monkeypatch.setattr(os, "getloadavg", lambda: (0.1, 0.2, 0.3), raising=False)


def _scrub(health_data):
    """Drop wall-clock-derived fields so the rest can be asserted exactly."""

    scrubbed = dict(health_data)
    scrubbed.pop("timestamp", None)
    scrubbed.pop("local_timestamp", None)
    system_block = dict(scrubbed.get("system", {}))
    system_block.pop("boot_time", None)
    system_block.pop("uptime_seconds", None)
    system_block.pop("uptime_human", None)
    scrubbed["system"] = system_block
    return scrubbed


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_structure(monkeypatch):
    _install_common_stubs(monkeypatch)
    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["cpu"]["cpu_usage_percent"] == pytest.approx(8.75)
    assert health["cpu"]["cpu_usage_per_core"] == [10.0, 12.0, 8.0, 5.0]
    assert health["cpu"]["physical_cores"] == 4
    assert health["memory"]["percentage"] == 40.0
    assert health["memory"]["swap_percentage"] == 5.0
    assert health["disk"] == [
        {
            "device": "/dev/root",
            "mountpoint": "/",
            "fstype": "ext4",
            "total": 1000,
            "used": 250,
            "free": 750,
            "percentage": 25.0,
        }
    ]
    assert health["network"]["hostname"] == "eas-station-test"
    assert health["network"]["interfaces"] == []
    assert "primary_interface" not in health["network"]
    assert health["network"]["traffic"]["available"] is False
    assert "no io counters" in health["network"]["traffic"]["error"]
    assert health["processes"] == {
        "total_processes": 0,
        "running_processes": 0,
        "top_processes": [],
        "audio_decoding": {"cpu_percent_total": 0.0, "processes": []},
    }
    assert health["load_averages"] == (0.1, 0.2, 0.3)
    assert health["database"] == {
        "status": "connected",
        "info": {"version": "PostgreSQL 15.4", "size": "42 MB", "active_connections": 7},
    }
    assert health["systemd"] == STUB_SYSTEMD
    assert health["services"] == {"eas-station-web": "running"}
    assert health["hardware_subsystems"] == STUB_HARDWARE_SUBSYSTEMS
    assert health["smart"] == STUB_SMART
    assert health["dependencies"] == STUB_DEPENDENCIES
    assert health["gps"] == STUB_GPS
    assert health["rtc"] == STUB_RTC
    assert health["clock_sync"] == STUB_CLOCK_SYNC
    assert health["raspberry_pi"] == STUB_RASPBERRY_PI
    assert health["shields_badges"] == STUB_BADGES
    assert health["distro_logo_url"] == STUB_DISTRO_LOGO
    assert health["status"] == "healthy"
    assert health["status_summary"] == "All systems operational"
    assert health["status_reasons"] == []


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------


def test_disk_partition_permission_error_is_skipped(monkeypatch):
    _install_common_stubs(monkeypatch)
    monkeypatch.setattr(
        psutil,
        "disk_partitions",
        lambda: [
            SimpleNamespace(device="/dev/sda1", mountpoint="/mnt/denied", fstype="ext4"),
            SimpleNamespace(device="/dev/sdb1", mountpoint="/data", fstype="ext4"),
        ],
    )

    def fake_disk_usage(mountpoint):
        if mountpoint == "/mnt/denied":
            raise PermissionError("denied")
        if mountpoint == "/data":
            return SimpleNamespace(total=1000, used=100, free=900)
        # Neither partition is "/" — if PermissionError escapes the
        # per-partition catch instead of being skipped, the outer except
        # falls back to querying "/", which must not happen here.
        raise AssertionError(f"unexpected disk_usage query for {mountpoint!r}")

    monkeypatch.setattr(psutil, "disk_usage", fake_disk_usage)

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert len(health["disk"]) == 1
    assert health["disk"][0]["mountpoint"] == "/data"
    assert health["disk"][0]["device"] == "/dev/sdb1"


def test_disk_partitions_call_failure_falls_back_to_root(monkeypatch):
    _install_common_stubs(monkeypatch)

    def raise_partitions():
        raise OSError("boom")

    monkeypatch.setattr(psutil, "disk_partitions", raise_partitions)
    monkeypatch.setattr(
        psutil, "disk_usage", lambda mountpoint: SimpleNamespace(total=2000, used=500, free=1500)
    )

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["disk"] == [
        {
            "device": "/",
            "mountpoint": "/",
            "fstype": "unknown",
            "total": 2000,
            "used": 500,
            "free": 1500,
            "percentage": 25.0,
        }
    ]


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def test_network_interfaces_and_primary_selection(monkeypatch):
    _install_common_stubs(monkeypatch)
    monkeypatch.setattr(
        psutil,
        "net_if_addrs",
        lambda: {
            "lo": [_addr(socket.AF_INET, "127.0.0.1", "255.0.0.0")],
            "eth0": [
                _addr(socket.AF_INET, "192.168.1.50", "255.255.255.0", "192.168.1.255"),
                _addr(psutil.AF_LINK, "aa:bb:cc:dd:ee:ff"),
            ],
            "linkonly0": [_addr(psutil.AF_LINK, "11:22:33:44:55:66")],
        },
    )
    monkeypatch.setattr(
        psutil,
        "net_if_stats",
        lambda: {
            "lo": _if_stat(isup=True),
            "eth0": _if_stat(isup=True, speed=1000),
        },
    )
    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    names = {entry["name"] for entry in health["network"]["interfaces"]}
    assert names == {"lo", "eth0"}  # linkonly0 has no addresses and is dropped

    eth0 = next(e for e in health["network"]["interfaces"] if e["name"] == "eth0")
    assert eth0["mac_address"] == "aa:bb:cc:dd:ee:ff"
    assert eth0["addresses"] == [
        {"type": "IPv4", "address": "192.168.1.50", "netmask": "255.255.255.0",
         "broadcast": "192.168.1.255"}
    ]

    assert health["network"]["primary_interface"]["name"] == "eth0"
    assert health["network"]["primary_ipv4"] == "192.168.1.50"
    assert health["network"]["primary_interface_name"] == "eth0"


def test_network_enumeration_failure_yields_empty_interfaces(monkeypatch):
    _install_common_stubs(monkeypatch)

    def raise_addrs():
        raise OSError("no network stack")

    monkeypatch.setattr(psutil, "net_if_addrs", raise_addrs)

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["network"]["interfaces"] == []
    assert "primary_interface" not in health["network"]


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------


def test_process_collection_ranks_and_flags_audio(monkeypatch):
    _install_common_stubs(monkeypatch)
    procs = [
        FakeProc(1, "python3", "pi", "running", 5.0, 1.0, ["python3", "app.py"]),
        FakeProc(2, "ffmpeg", "pi", "running", 40.0, 2.0, ["ffmpeg", "-i", "in.wav"]),
        FakeProc(3, "sleep", "pi", "sleeping", 0.0, 0.1, ["sleep", "10"]),
        FakeProc(4, "gone", "pi", "running", 1.0, 0.1, [],
                 access_error=psutil.NoSuchProcess(pid=4)),
        FakeProc(5, "denied", "pi", "running", 1.0, 0.1, [],
                 access_error=psutil.AccessDenied(pid=5)),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda fields=None: list(procs))

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    proc_info = health["processes"]
    assert proc_info["total_processes"] == 5
    # Status is read straight off proc.info before the per-process try/except,
    # so procs 4 and 5 (which raise once cpu_percent()/memory_percent() are
    # touched) still count toward "running" even though they are excluded
    # from top_processes below.
    assert proc_info["running_processes"] == 4
    assert [p["pid"] for p in proc_info["top_processes"]] == [2, 1, 3]
    assert proc_info["audio_decoding"]["cpu_percent_total"] == pytest.approx(40.0)
    assert [p["pid"] for p in proc_info["audio_decoding"]["processes"]] == [2]
    assert proc_info["audio_decoding"]["processes"][0]["command"] == "ffmpeg -i in.wav"


def test_process_iter_failure_yields_defaults(monkeypatch):
    _install_common_stubs(monkeypatch)

    def raise_iter(fields=None):
        raise OSError("no /proc")

    monkeypatch.setattr(psutil, "process_iter", raise_iter)

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["processes"] == {
        "total_processes": 0,
        "running_processes": 0,
        "top_processes": [],
        "audio_decoding": {"cpu_percent_total": 0.0, "processes": []},
    }


# ---------------------------------------------------------------------------
# Load averages
# ---------------------------------------------------------------------------


def test_load_averages_unavailable_on_this_platform(monkeypatch):
    _install_common_stubs(monkeypatch)
    monkeypatch.delattr(os, "getloadavg", raising=False)

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["load_averages"] is None


def test_load_averages_read_failure_yields_none(monkeypatch):
    _install_common_stubs(monkeypatch)

    def raise_loadavg():
        raise OSError("unsupported")

    monkeypatch.setattr(os, "getloadavg", raise_loadavg, raising=False)

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["load_averages"] is None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def test_database_size_and_connection_queries_fall_back_independently(monkeypatch):
    _install_common_stubs(monkeypatch)

    def execute_fn(query):
        sql = str(query)
        if "version()" in sql:
            return ExecResult(scalar_value="PostgreSQL 16.0")
        if "pg_size_pretty" in sql:
            raise Exception("size query failed")
        if "pg_stat_activity" in sql:
            raise Exception("connection query failed")
        raise AssertionError(sql)

    db = MockDB(execute_fn)
    health = snap.build_system_health_snapshot(db, MockLogger())

    assert health["database"] == {
        "status": "connected",
        "info": {
            "version": "PostgreSQL 16.0",
            "size": "Unknown",
            "active_connections": "Unknown",
        },
    }
    # One rollback for the pre-emptive cleanup, one for each failed sub-query.
    assert db.session.rollback_calls == 3


def test_database_probe_failure_marks_error_status(monkeypatch):
    _install_common_stubs(monkeypatch)

    def execute_fn(query):
        raise Exception("connection refused")

    db = MockDB(execute_fn)
    logger = MockLogger()
    health = snap.build_system_health_snapshot(db, logger)

    assert health["database"]["status"] == "error"
    assert "connection refused" in health["database"]["info"]["error"]
    assert len(logger.warnings) == 1


# ---------------------------------------------------------------------------
# Overall status
# ---------------------------------------------------------------------------


def test_status_warning_thresholds(monkeypatch):
    _install_common_stubs(monkeypatch)
    monkeypatch.setattr(
        psutil, "cpu_percent", lambda interval=None, percpu=False: [80.0] if percpu else 80.0
    )
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=1000, available=150, used=850, free=150, percent=85.0),
    )

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["status"] == "warning"
    assert "CPU usage is 80.0%" in health["status_reasons"]
    assert "Memory usage is 85.0%" in health["status_reasons"]


def test_status_critical_cpu_alone(monkeypatch):
    """CPU at/above 90% is critical on its own, independent of every other
    figure — isolated from DB/memory/systemd so a threshold regression can't
    hide behind one of the other critical triggers."""

    _install_common_stubs(monkeypatch)
    monkeypatch.setattr(
        psutil, "cpu_percent", lambda interval=None, percpu=False: [95.0] if percpu else 95.0
    )

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["status"] == "critical"
    assert health["status_reasons"] == ["CPU usage is 95.0%"]


def test_status_critical_memory_alone(monkeypatch):
    """Memory at/above 92% is critical on its own, isolated from CPU/DB/systemd."""

    _install_common_stubs(monkeypatch)
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=1000, available=50, used=950, free=50, percent=95.0),
    )

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["status"] == "critical"
    assert health["status_reasons"] == ["Memory usage is 95.0%"]


def test_status_critical_db_alone_overrides_healthy_cpu(monkeypatch):
    _install_common_stubs(monkeypatch)

    def execute_fn(query):
        raise Exception("down")

    db = MockDB(execute_fn)
    health = snap.build_system_health_snapshot(db, MockLogger())

    assert health["status"] == "critical"
    assert health["status_reasons"] == ["Database: error"]


def test_status_degraded_systemd_is_warning_unless_already_critical(monkeypatch):
    _install_common_stubs(monkeypatch)
    monkeypatch.setattr(
        snap,
        "_collect_systemd_services",
        lambda logger: {
            "status": "degraded",
            "services": [],
            "summary": {"failed": 2},
        },
    )

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["status"] == "warning"
    assert "2 service(s) failed" in health["status_reasons"]


def test_status_stopped_systemd_is_always_critical(monkeypatch):
    _install_common_stubs(monkeypatch)
    monkeypatch.setattr(
        snap,
        "_collect_systemd_services",
        lambda logger: {"status": "stopped", "services": [], "summary": {}},
    )

    health = snap.build_system_health_snapshot(MockDB(), MockLogger())

    assert health["status"] == "critical"
    assert "All services stopped" in health["status_reasons"]


# ---------------------------------------------------------------------------
# Top-level exception safety net
# ---------------------------------------------------------------------------


def test_unexpected_exception_returns_error_payload(monkeypatch):
    _install_common_stubs(monkeypatch)

    def raise_uname():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(snap.platform, "uname", raise_uname)

    logger = MockLogger()
    health = snap.build_system_health_snapshot(MockDB(), logger)

    assert health["error"] == "kaboom"
    assert "timestamp" in health
    assert "local_timestamp" in health
    assert len(logger.errors) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
