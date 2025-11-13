"""System monitoring helpers."""

from datetime import datetime
import contextlib
import http.client
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from urllib.parse import urlparse

import psutil
from sqlalchemy import text

from .time import UTC_TZ, local_now, utc_now


DEVICE_TREE_CANDIDATES = [
    Path("/proc/device-tree"),
    Path("/sys/firmware/devicetree/base"),
]


SystemHealth = Dict[str, Any]


NVME_DATA_UNIT_BYTES = 512_000


def build_system_health_snapshot(db, logger) -> SystemHealth:
    """Collect detailed system health metrics."""

    try:
        uname = platform.uname()
        boot_time = psutil.boot_time()

        cpu_freq = psutil.cpu_freq()
        cpu_usage_per_core = psutil.cpu_percent(interval=1, percpu=True)
        cpu_usage_percent = (
            sum(cpu_usage_per_core) / len(cpu_usage_per_core)
            if cpu_usage_per_core
            else psutil.cpu_percent(interval=None) or 0
        )

        os_details = _collect_operating_system_details()

        cpu_info = {
            "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True),
            "max_frequency": cpu_freq.max if cpu_freq else 0,
            "current_frequency": cpu_freq.current if cpu_freq else 0,
            "cpu_usage_percent": cpu_usage_percent,
            "cpu_usage_per_core": cpu_usage_per_core,
        }

        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        memory_info = {
            "total": memory.total,
            "available": memory.available,
            "used": memory.used,
            "free": memory.free,
            "percentage": memory.percent,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_free": swap.free,
            "swap_percentage": swap.percent,
        }

        disk_info = []
        try:
            partitions = psutil.disk_partitions()
            for partition in partitions:
                try:
                    partition_usage = psutil.disk_usage(partition.mountpoint)
                    disk_info.append(
                        {
                            "device": partition.device,
                            "mountpoint": partition.mountpoint,
                            "fstype": partition.fstype,
                            "total": partition_usage.total,
                            "used": partition_usage.used,
                            "free": partition_usage.free,
                            "percentage": (partition_usage.used / partition_usage.total) * 100,
                        }
                    )
                except PermissionError:
                    continue
        except Exception:
            disk_usage = psutil.disk_usage("/")
            disk_info.append(
                {
                    "device": "/",
                    "mountpoint": "/",
                    "fstype": "unknown",
                    "total": disk_usage.total,
                    "used": disk_usage.used,
                    "free": disk_usage.free,
                    "percentage": (disk_usage.used / disk_usage.total) * 100,
                }
            )

        network_info = {"hostname": socket.gethostname(), "interfaces": []}

        try:
            net_if_addrs = psutil.net_if_addrs()
            net_if_stats = psutil.net_if_stats()

            for interface_name, interface_addresses in net_if_addrs.items():
                interface_info = {
                    "name": interface_name,
                    "addresses": [],
                    "is_up": net_if_stats[interface_name].isup if interface_name in net_if_stats else False,
                }

                for address in interface_addresses:
                    if address.family == socket.AF_INET:
                        interface_info["addresses"].append(
                            {
                                "type": "IPv4",
                                "address": address.address,
                                "netmask": address.netmask,
                                "broadcast": address.broadcast,
                            }
                        )
                    elif address.family == socket.AF_INET6:
                        interface_info["addresses"].append(
                            {
                                "type": "IPv6",
                                "address": address.address,
                                "netmask": address.netmask,
                            }
                        )

                if interface_info["addresses"]:
                    network_info["interfaces"].append(interface_info)
        except Exception:
            pass

        network_info["traffic"] = _collect_network_traffic()

        process_info = {
            "total_processes": len(psutil.pids()),
            "running_processes": len(
                [p for p in psutil.process_iter(["status"]) if p.info["status"] == psutil.STATUS_RUNNING]
            ),
            "top_processes": [],
        }

        try:
            observed_processes: List[Tuple[psutil.Process, Dict[str, Any]]] = []

            for proc in psutil.process_iter(["pid", "name", "username"]):
                try:
                    proc.cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                observed_processes.append((proc, dict(proc.info)))

            # Allow a short interval so psutil can calculate CPU deltas using the same
            # Process instances collected above. Using new Process objects here would
            # reset the internal CPU counters and always report 0%.
            time.sleep(0.3)

            processes: List[Dict[str, Any]] = []
            for proc, metadata in observed_processes:
                try:
                    cpu_percent = proc.cpu_percent(None)
                    memory_percent = proc.memory_percent()
                    name = metadata.get("name") or proc.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                if cpu_percent is None:
                    cpu_percent = 0.0
                if memory_percent is None:
                    memory_percent = 0.0

                processes.append(
                    {
                        "pid": metadata.get("pid", proc.pid),
                        "name": name,
                        "username": metadata.get("username"),
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory_percent,
                    }
                )

            processes.sort(key=lambda entry: entry.get("cpu_percent", 0) or 0, reverse=True)
            process_info["top_processes"] = processes[:10]
        except Exception:
            pass

        load_averages = None
        try:
            if hasattr(os, "getloadavg"):
                load_averages = os.getloadavg()
        except Exception:
            pass

        db_status = "unknown"
        db_info: Dict[str, Any] = {}
        try:
            version_result = db.session.execute(text("SELECT version()"))
            if version_result:
                db_status = "connected"
                version_value = version_result.scalar()
                db_info["version"] = version_value if version_value else "Unknown"

                try:
                    size_result = db.session.execute(
                        text("SELECT pg_size_pretty(pg_database_size(current_database()))")
                    ).fetchone()
                    if size_result:
                        db_info["size"] = size_result[0]
                except Exception:
                    db_info["size"] = "Unknown"

                try:
                    conn_result = db.session.execute(
                        text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                    ).fetchone()
                    if conn_result:
                        db_info["active_connections"] = conn_result[0]
                except Exception:
                    db_info["active_connections"] = "Unknown"
        except Exception as exc:
            db_status = f"error: {exc}"

        containers_info = _collect_container_statuses(logger)
        services_status: Dict[str, Any] = {
            container.get("display_name")
            or container.get("name")
            or f"container-{index}": container.get("status")
            for index, container in enumerate(containers_info.get("containers", []), start=1)
        }

        hardware_info = _collect_hardware_inventory(logger)
        smart_info = _collect_smart_health(
            logger, hardware_info.get("block_devices", {}).get("devices") or []
        )
        temperature_info = _collect_temperature_readings(logger, smart_info)

        return {
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
            "system": {
                "hostname": uname.node,
                "system": uname.system,
                "release": uname.release,
                "version": uname.version,
                "machine": uname.machine,
                "processor": uname.processor,
                "boot_time": datetime.fromtimestamp(boot_time, UTC_TZ).isoformat(),
                "uptime_seconds": time.time() - boot_time,
                **os_details,
            },
            "cpu": cpu_info,
            "memory": memory_info,
            "disk": disk_info,
            "network": network_info,
            "processes": process_info,
            "load_averages": load_averages,
            "database": {"status": db_status, "info": db_info},
            "services": services_status,
            "containers": containers_info,
            "temperature": temperature_info,
            "hardware": hardware_info,
            "smart": smart_info,
        }

    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.error("Error getting system health: %s", exc)
        return {
            "error": str(exc),
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
        }


def _collect_container_statuses(logger) -> Dict[str, Any]:
    """Collect information about running containers using Docker or Podman."""

    result: Dict[str, Any] = {
        "available": False,
        "status": "unavailable",
        "engine": None,
        "containers": [],
        "summary": {"total": 0, "running": 0, "healthy": 0, "unhealthy": 0, "stopped": 0},
        "issues": [],
        "error": None,
        "compose_project": None,
        "collector": None,
    }

    compose_project = os.getenv("COMPOSE_PROJECT_NAME") or os.getenv("STACK_PROJECT_NAME") or os.getenv(
        "STACK_NAME"
    )

    attempt_errors: List[str] = []

    # Prefer direct API access (Docker/Podman sockets or remote hosts) to avoid CLI dependencies.
    for target in _candidate_container_api_targets():
        try:
            containers = _fetch_containers_via_api(target, compose_project)
            if containers is None:
                continue
            return _build_container_result(
                containers,
                engine=target["engine"],
                compose_project=compose_project,
                collector=f"{target['engine']}-api",
            )
        except Exception as exc:  # pragma: no cover - host specific behaviour
            message = f"{target['engine']} API ({target['description']}): {exc}"
            attempt_errors.append(message)
            if logger:
                logger.warning("Failed to collect container status via %s", message)

    # Fallback to CLI lookups when API access is unavailable.
    for engine in ("docker", "podman"):
        try:
            containers = _fetch_containers_via_cli(engine, compose_project)
            if containers is None:
                attempt_errors.append(f"{engine} CLI not available")
                continue
            return _build_container_result(
                containers,
                engine=engine,
                compose_project=compose_project,
                collector=f"{engine}-cli",
            )
        except Exception as exc:  # pragma: no cover - depends on host configuration
            message = f"{engine} CLI: {exc}"
            attempt_errors.append(message)
            if logger:
                logger.warning("Failed to collect container status via %s", message)

    if attempt_errors:
        result["error"] = "; ".join(attempt_errors)
    else:
        result["error"] = "Container engine not available"

    result["compose_project"] = compose_project
    return result


def _collect_operating_system_details() -> Dict[str, Any]:
    """Return distribution and kernel metadata for the host."""

    details: Dict[str, Any] = {
        "distribution": None,
        "distribution_version": None,
        "distribution_codename": None,
        "distribution_id": None,
        "distribution_like": None,
        "os_pretty_name": None,
        "kernel": platform.system(),
        "kernel_release": platform.release(),
        "kernel_version": platform.version(),
        "virtualization": None,
    }

    os_release_path = Path("/etc/os-release")
    release_data: Dict[str, str] = {}
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        content = os_release_path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().upper()
            if not key:
                continue
            value = value.strip().strip('"')
            release_data[key] = value

    if release_data:
        details["os_pretty_name"] = release_data.get("PRETTY_NAME") or None
        details["distribution"] = release_data.get("NAME") or None
        details["distribution_id"] = release_data.get("ID") or None
        details["distribution_version"] = (
            release_data.get("VERSION_ID") or release_data.get("VERSION") or None
        )
        details["distribution_codename"] = release_data.get("VERSION_CODENAME") or None
        details["distribution_like"] = release_data.get("ID_LIKE") or None

    virtualization = _detect_virtualization_environment()
    if virtualization:
        details["virtualization"] = virtualization

    return details


def _detect_virtualization_environment() -> Optional[str]:
    """Attempt to detect virtualization technology in use."""

    detect_path = shutil.which("systemd-detect-virt")
    if detect_path:
        try:
            completed = subprocess.run(
                [detect_path],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except Exception:  # pragma: no cover - host specific behaviour
            completed = None
        else:
            if completed:
                output = (completed.stdout or "").strip()
                if output and output.lower() != "none":
                    return output

    product_name = _safe_read_text(Path("/sys/class/dmi/id/product_name"))
    system_vendor = _safe_read_text(Path("/sys/class/dmi/id/sys_vendor"))

    virtualization_markers = (
        (product_name or "", "product"),
        (system_vendor or "", "vendor"),
    )
    known_labels = (
        ("virtualbox", "VirtualBox"),
        ("vmware", "VMware"),
        ("kvm", "KVM"),
        ("qemu", "QEMU"),
        ("hyper-v", "Hyper-V"),
        ("xen", "Xen"),
        ("parallels", "Parallels"),
        ("bhyve", "bhyve"),
    )

    for raw_value, _source in virtualization_markers:
        lowered = raw_value.lower() if raw_value else ""
        for marker, label in known_labels:
            if marker in lowered:
                return label

    cpuinfo_path = Path("/proc/cpuinfo")
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        content = cpuinfo_path.read_text(encoding="utf-8", errors="ignore")
        if "hypervisor" in content.lower():
            return "Hypervisor detected"

    return None


def _collect_network_traffic() -> Dict[str, Any]:
    """Return cumulative network I/O statistics."""

    result: Dict[str, Any] = {
        "available": False,
        "interfaces": [],
        "totals": {},
        "error": None,
    }

    try:
        totals = psutil.net_io_counters()
        result["totals"] = {
            "bytes_sent": totals.bytes_sent,
            "bytes_recv": totals.bytes_recv,
            "packets_sent": totals.packets_sent,
            "packets_recv": totals.packets_recv,
            "errin": totals.errin,
            "errout": totals.errout,
            "dropin": totals.dropin,
            "dropout": totals.dropout,
        }
        result["available"] = True
    except Exception as exc:  # pragma: no cover - depends on psutil support
        result["error"] = str(exc)

    try:
        pernic = psutil.net_io_counters(pernic=True)
    except Exception:
        pernic = {}

    stats = {}
    with contextlib.suppress(Exception):
        stats = psutil.net_if_stats()

    for name in sorted(pernic.keys()):
        counters = pernic[name]
        stat = stats.get(name)
        result["interfaces"].append(
            {
                "name": name,
                "bytes_sent": counters.bytes_sent,
                "bytes_recv": counters.bytes_recv,
                "packets_sent": counters.packets_sent,
                "packets_recv": counters.packets_recv,
                "errin": counters.errin,
                "errout": counters.errout,
                "dropin": counters.dropin,
                "dropout": counters.dropout,
                "speed_mbps": getattr(stat, "speed", None),
                "mtu": getattr(stat, "mtu", None),
                "is_up": getattr(stat, "isup", None),
                "duplex": getattr(stat, "duplex", None),
            }
        )

    if result["interfaces"]:
        result["available"] = True

    return result


def _collect_hardware_inventory(logger) -> Dict[str, Any]:
    """Gather hardware inventory details for the host."""

    cpu_details = _collect_cpu_details(logger)
    platform_details = _collect_platform_details()
    block_devices = _collect_block_devices(logger)
    usb_devices = _collect_usb_devices(logger)

    return {
        "cpu": cpu_details,
        "platform": platform_details,
        "block_devices": block_devices,
        "usb": usb_devices,
    }


def _collect_usb_devices(logger) -> Dict[str, Any]:
    """Inspect USB devices via sysfs for detailed inventory."""

    result: Dict[str, Any] = {
        "available": False,
        "devices": [],
        "summary": {"devices": 0, "hubs": 0},
        "error": None,
    }

    devices_root = Path("/sys/bus/usb/devices")
    if not devices_root.exists():
        result["error"] = "USB sysfs tree not available"
        return result

    try:
        entries = sorted(devices_root.iterdir(), key=lambda path: path.name)
    except Exception as exc:  # pragma: no cover - depends on host permissions
        result["error"] = str(exc)
        return result

    for entry in entries:
        if not entry.is_dir():
            continue

        id_vendor = _safe_read_text(entry / "idVendor")
        id_product = _safe_read_text(entry / "idProduct")
        if not id_vendor or not id_product:
            continue

        product = _safe_read_text(entry / "product")
        manufacturer = _safe_read_text(entry / "manufacturer")
        serial = _safe_read_text(entry / "serial")
        busnum = _safe_read_text(entry / "busnum")
        devnum = _safe_read_text(entry / "devnum")
        device_class = _safe_read_text(entry / "bDeviceClass")
        device_subclass = _safe_read_text(entry / "bDeviceSubClass")
        device_protocol = _safe_read_text(entry / "bDeviceProtocol")

        speed_value: Optional[float] = None
        speed_raw = _safe_read_text(entry / "speed")
        if speed_raw:
            with contextlib.suppress(ValueError):
                speed_value = float(speed_raw)

        driver = None
        driver_path = entry / "driver"
        if driver_path.exists():
            with contextlib.suppress(OSError):
                target = os.readlink(driver_path)
                driver = os.path.basename(target)

        interface_classes: List[str] = []
        for interface_dir in entry.iterdir():
            if not interface_dir.is_dir():
                continue
            class_value = _safe_read_text(interface_dir / "bInterfaceClass")
            if class_value:
                interface_classes.append(class_value)

        device_entry = {
            "path": entry.name,
            "vendor_id": id_vendor,
            "product_id": id_product,
            "manufacturer": manufacturer,
            "product": product,
            "serial": serial,
            "bus_number": busnum,
            "device_number": devnum,
            "device_class": device_class,
            "device_subclass": device_subclass,
            "device_protocol": device_protocol,
            "speed_mbps": speed_value,
            "driver": driver,
            "interfaces": interface_classes,
            "is_hub": (device_class or "").lower() in {"09", "9"},
        }

        result["devices"].append(device_entry)

    result["summary"]["devices"] = len(result["devices"])
    result["summary"]["hubs"] = sum(1 for device in result["devices"] if device.get("is_hub"))

    if result["devices"]:
        result["available"] = True
    else:
        result["error"] = result.get("error") or "No USB devices detected"

    return result


def _collect_cpu_details(logger) -> Dict[str, Any]:
    """Return static CPU capabilities and metadata."""

    cpu_freq = psutil.cpu_freq()

    details: Dict[str, Any] = {
        "model_name": None,
        "vendor_id": None,
        "architecture": platform.machine() or None,
        "processor": platform.processor() or None,
        "cache_size": None,
        "microcode": None,
        "stepping": None,
        "family": None,
        "model": None,
        "hardware": None,
        "revision": None,
        "serial": None,
        "cpu_implementer": None,
        "cpu_part": None,
        "flags": [],
        "supports_virtualization": None,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "max_frequency": cpu_freq.max if cpu_freq else None,
        "min_frequency": cpu_freq.min if cpu_freq else None,
    }

    try:
        cpuinfo_path = Path("/proc/cpuinfo")
        if cpuinfo_path.exists():
            content = cpuinfo_path.read_text(encoding="utf-8", errors="ignore")
            sections = [segment for segment in content.split("\n\n") if segment.strip()]
            merged_fields: Dict[str, str] = {}
            features: List[str] = []

            for section in sections:
                for line in section.splitlines():
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if not value:
                        continue

                    merged_fields.setdefault(key, value)

                    if key in {"flags", "features"}:
                        features.extend(flag.strip() for flag in value.split() if flag.strip())

            def _set_from_fields(target: str, *candidates: str) -> None:
                for candidate in candidates:
                    value = merged_fields.get(candidate)
                    if value:
                        details[target] = value
                        return

            _set_from_fields("model_name", "model name", "model")
            _set_from_fields("vendor_id", "vendor_id", "cpu implementer")
            _set_from_fields("microcode", "microcode")
            _set_from_fields("stepping", "stepping", "cpu revision")
            _set_from_fields("family", "cpu family", "cpu architecture")
            _set_from_fields("model", "model")
            _set_from_fields("cache_size", "cache size")
            _set_from_fields("hardware", "hardware")
            _set_from_fields("revision", "revision")
            _set_from_fields("serial", "serial")
            _set_from_fields("cpu_implementer", "cpu implementer")
            _set_from_fields("cpu_part", "cpu part")

            if features:
                details["flags"] = sorted(set(features))

            virtualization_field = merged_fields.get("virtualization")
            if virtualization_field:
                lowered = virtualization_field.strip().lower()
                if lowered in {"vt-x", "svm", "hardware", "full"}:
                    details["supports_virtualization"] = True
                elif lowered in {"none", "n/a", "no"}:
                    details["supports_virtualization"] = False
    except Exception as exc:  # pragma: no cover - depends on host filesystem
        if logger:
            logger.debug("Failed to parse /proc/cpuinfo: %s", exc)

    flags_set = set(details.get("flags") or [])
    if flags_set:
        if details["supports_virtualization"] is None:
            details["supports_virtualization"] = any(flag in {"vmx", "svm"} for flag in flags_set)

    return details


def _collect_platform_details() -> Dict[str, Any]:
    """Return chassis / firmware metadata using DMI and device-tree sources."""

    details: Dict[str, Any] = {}
    has_dmi = False

    base_path = Path("/sys/devices/virtual/dmi/id")
    if base_path.exists():
        fields = {
            "sys_vendor": "sys_vendor",
            "product_name": "product_name",
            "product_version": "product_version",
            "product_serial": "product_serial",
            "board_name": "board_name",
            "board_vendor": "board_vendor",
            "board_version": "board_version",
            "chassis_asset_tag": "chassis_asset_tag",
            "bios_vendor": "bios_vendor",
            "bios_version": "bios_version",
            "bios_date": "bios_date",
        }

        for key, filename in fields.items():
            value = _safe_read_text(base_path / filename)
            if value is not None:
                details[key] = value
                has_dmi = True

    # Augment with device-tree metadata when available (common on ARM boards).
    dt_details = _collect_device_tree_details()
    if dt_details:
        for key, value in dt_details.items():
            details.setdefault(key, value)
        
        # If we have device-tree data but no DMI BIOS info, mark BIOS fields as not applicable
        if dt_details and not has_dmi:
            # Remove any empty/placeholder BIOS fields that might confuse the UI
            for bios_key in ["bios_vendor", "bios_version", "bios_date"]:
                if bios_key in details and not details[bios_key]:
                    del details[bios_key]

    return details


def _collect_block_devices(logger) -> Dict[str, Any]:
    """Use lsblk to inspect attached block devices."""

    result: Dict[str, Any] = {
        "available": False,
        "devices": [],
        "error": None,
        "summary": {"disks": 0, "partitions": 0, "virtual": 0},
    }

    lsblk_path = shutil.which("lsblk")
    if not lsblk_path:
        result["error"] = "lsblk utility not available"
        return result

    columns = [
        "NAME",
        "PATH",
        "TYPE",
        "SIZE",
        "MODEL",
        "SERIAL",
        "ROTA",
        "TRAN",
        "VENDOR",
        "RO",
        "RM",
        "MOUNTPOINT",
        "MOUNTPOINTS",
        "FSTYPE",
    ]

    try:
        completed = subprocess.run(
            [
                lsblk_path,
                "--bytes",
                "--json",
                "--output",
                ",".join(columns),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception as exc:  # pragma: no cover - depends on host configuration
        result["error"] = str(exc)
        if logger:
            logger.warning("Failed to execute lsblk: %s", exc)
        return result

    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        result["error"] = stderr or "lsblk returned a non-zero exit status"
        if logger:
            logger.warning("lsblk exited with status %s: %s", completed.returncode, result["error"])

    if not stdout:
        return result

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - host specific output
        result["error"] = f"Unable to parse lsblk output: {exc}"
        if logger:
            logger.warning("Unable to parse lsblk output: %s", exc)
        return result

    simplified_devices, summary = _simplify_block_devices(payload.get("blockdevices") or [])
    result["devices"] = simplified_devices
    result["summary"] = summary
    result["available"] = bool(simplified_devices)

    return result


def _collect_device_tree_details() -> Dict[str, Any]:
    """Gather platform metadata from device-tree files on ARM systems."""

    base: Optional[Path] = None
    for candidate in DEVICE_TREE_CANDIDATES:
        if candidate.exists():
            base = candidate
            break

    if base is None:
        return {}

    details: Dict[str, Any] = {}

    model = _safe_read_device_tree_text(base / "model")
    if model:
        details.setdefault("product_name", model)
        details.setdefault("board_name", model)
        if "raspberry" in model.lower():
            details.setdefault("sys_vendor", "Raspberry Pi Foundation")

    serial = _safe_read_device_tree_text(base / "serial-number")
    if serial:
        details.setdefault("product_serial", serial)

    revision = _safe_read_device_tree_revision(base / "system/linux,revision")
    if revision:
        details.setdefault("product_version", revision)
        details.setdefault("board_version", revision)

    compatible = _safe_read_device_tree_compatible(base / "compatible")
    if compatible:
        details.setdefault("compatible", compatible)

    return details


def _simplify_block_devices(entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Normalize lsblk output into a compact, UI-friendly structure."""

    simplified: List[Dict[str, Any]] = []
    summary = {"disks": 0, "partitions": 0, "virtual": 0}

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        children_entries = entry.get("children") or []
        children, child_summary = _simplify_block_devices(children_entries)

        for key, value in child_summary.items():
            summary[key] = summary.get(key, 0) + value

        entry_type = (entry.get("type") or "").lower()
        if entry_type == "disk":
            summary["disks"] = summary.get("disks", 0) + 1
        elif entry_type == "part":
            summary["partitions"] = summary.get("partitions", 0) + 1
        elif entry_type in {"loop", "rom"}:
            summary["virtual"] = summary.get("virtual", 0) + 1

        mountpoints = entry.get("mountpoints")
        if mountpoints is None:
            mountpoint = entry.get("mountpoint")
            if mountpoint:
                mountpoints = [mountpoint]
            else:
                mountpoints = []

        if isinstance(mountpoints, str):
            mountpoints = [mountpoints]

        device = {
            "name": entry.get("name"),
            "path": entry.get("path"),
            "type": entry_type or None,
            "size_bytes": _safe_int(entry.get("size")),
            "model": entry.get("model"),
            "serial": entry.get("serial"),
            "vendor": entry.get("vendor"),
            "transport": entry.get("tran"),
            "is_rotational": _to_bool(entry.get("rota")),
            "is_read_only": _to_bool(entry.get("ro")),
            "is_removable": _to_bool(entry.get("rm")),
            "filesystem": entry.get("fstype"),
            "mountpoints": mountpoints if isinstance(mountpoints, list) else [],
            "children": children,
        }

        simplified.append(device)

    return simplified, summary


def _collect_smart_health(logger, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collect S.M.A.R.T. health summaries for detected block devices."""

    result: Dict[str, Any] = {"available": False, "devices": [], "error": None}

    smartctl_path = shutil.which("smartctl")
    if not smartctl_path:
        for candidate in (
            "/usr/sbin/smartctl",
            "/sbin/smartctl",
            "/usr/local/sbin/smartctl",
        ):
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                smartctl_path = candidate
                break
    if not smartctl_path:
        result["error"] = "smartctl utility not installed"
        return result

    result["available"] = True

    for device in _iter_disk_devices(devices):
        path = device.get("path") or (f"/dev/{device.get('name')}" if device.get("name") else None)
        if not path:
            continue

        device_result: Dict[str, Any] = {
            "name": device.get("name"),
            "path": path,
            "model": device.get("model"),
            "serial": device.get("serial"),
            "transport": device.get("transport"),
            "is_rotational": device.get("is_rotational"),
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
            "exit_status": None,
            "error": None,
        }

        # Detect device type and add appropriate flags for smartctl
        device_type_flag = _detect_device_type(device, path, logger)
        command = [smartctl_path, "--json=o", "-H", "-A", "-n", "standby,now"]
        if device_type_flag:
            command.extend(["-d", device_type_flag])
        command.append(path)

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
        except Exception as exc:  # pragma: no cover - depends on host configuration
            device_result["error"] = str(exc)
            if logger:
                logger.warning("smartctl failed for %s: %s", path, exc)
            result["devices"].append(device_result)
            continue

        device_result["exit_status"] = completed.returncode

        raw_output = (completed.stdout or "").strip()
        stderr_output = (completed.stderr or "").strip()
        
        # Log stderr for debugging, but don't necessarily treat it as an error
        if stderr_output and logger:
            logger.debug("smartctl stderr for %s: %s", path, stderr_output)
        
        if not raw_output:
            # Provide more detailed error message
            error_msg = stderr_output if stderr_output else f"No output from smartctl (exit code: {completed.returncode})"
            device_result["error"] = error_msg
            if logger:
                logger.warning("No smartctl output for %s: %s", path, error_msg)
            result["devices"].append(device_result)
            continue

        try:
            report = json.loads(raw_output)
        except json.JSONDecodeError as exc:  # pragma: no cover - host specific output
            device_result["error"] = f"Unable to parse smartctl output: {exc}"
            if logger:
                logger.warning("Unable to parse smartctl output for %s: %s", path, exc)
            result["devices"].append(device_result)
            continue

        smart_status = report.get("smart_status") or {}
        passed = smart_status.get("passed")
        if passed is True:
            device_result["overall_status"] = "passed"
        elif passed is False:
            device_result["overall_status"] = "failed"
        else:
            status_text = smart_status.get("status") or smart_status.get("string")
            if status_text:
                device_result["overall_status"] = str(status_text)
            # If still unknown but smartctl succeeded, log for debugging
            elif logger and completed.returncode == 0:
                logger.debug("SMART status unavailable for %s despite successful smartctl execution", path)

        device_result["temperature_celsius"] = _extract_temperature(report)
        device_result["power_on_hours"] = _extract_attribute_value(report, "Power_On_Hours")
        device_result["power_cycle_count"] = _extract_attribute_value(report, "Power_Cycle_Count")
        device_result["reallocated_sector_count"] = _extract_attribute_value(
            report, "Reallocated_Sector_Ct"
        )
        device_result["media_errors"] = _extract_nvme_field(report, "media_errors")
        device_result["critical_warnings"] = _extract_nvme_field(report, "critical_warning")
        nvme_stats = _extract_nvme_statistics(report)
        for key, value in nvme_stats.items():
            device_result[key] = value

        _populate_nvme_metrics(device_result, report)

        # Only store stderr as error if it indicates a real problem
        if stderr_output and completed.returncode != 0:
            device_result["error"] = stderr_output

        result["devices"].append(device_result)

    if not result["devices"]:
        result["error"] = result.get("error") or "No eligible block devices detected"

    return result


def _collect_temperature_readings(logger, smart_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate temperature readings from psutil, sysfs, and SMART."""

    readings: Dict[str, List[Dict[str, Any]]] = {}

    try:
        temps = psutil.sensors_temperatures()
    except Exception as exc:  # pragma: no cover - depends on psutil support
        if logger:
            logger.debug("psutil temperature query failed: %s", exc)
        temps = {}

    for name, entries in (temps or {}).items():
        if not isinstance(entries, Iterable):
            continue
        for entry in entries:
            current = getattr(entry, "current", None)
            if current is None:
                continue
            
            # Validate current temperature
            if not isinstance(current, (int, float)):
                continue
            current_float = float(current)
            if not _is_valid_temperature(current_float):
                if logger:
                    logger.debug("Skipping invalid temperature reading from psutil: %s = %s°C", name, current_float)
                continue
            
            # Validate high/critical thresholds
            high = getattr(entry, "high", None)
            critical = getattr(entry, "critical", None)
            high_float = float(high) if isinstance(high, (int, float)) and _is_valid_temperature(float(high)) else None
            critical_float = float(critical) if isinstance(critical, (int, float)) and _is_valid_temperature(float(critical)) else None
            
            _add_temperature_entry(
                readings,
                name,
                getattr(entry, "label", None) or "Sensor",
                current_float,
                high_float,
                critical_float,
            )

    thermal_root = Path("/sys/class/thermal")
    if thermal_root.exists():
        for zone in sorted(thermal_root.glob("thermal_zone*")):
            zone_type = _safe_read_text(zone / "type") or zone.name
            current_value = _parse_temperature_value(_safe_read_text(zone / "temp"))
            if current_value is None:
                continue

            trip_points: Dict[str, float] = {}
            for trip_type_path in zone.glob("trip_point_*_type"):
                trip_type = _safe_read_text(trip_type_path)
                if not trip_type:
                    continue
                temp_path = zone / trip_type_path.name.replace("_type", "_temp")
                trip_temp = _parse_temperature_value(_safe_read_text(temp_path))
                if trip_temp is not None:
                    trip_points[trip_type.strip().lower()] = trip_temp

            _add_temperature_entry(
                readings,
                zone_type,
                zone_type,
                current_value,
                trip_points.get("high") or trip_points.get("passive"),
                trip_points.get("critical"),
            )

    if isinstance(smart_info, dict):
        for device in smart_info.get("devices") or []:
            temperature = device.get("temperature_celsius")
            if temperature is None:
                continue
            if not isinstance(temperature, (int, float)):
                continue
            temp_float = float(temperature)
            # Validate temperature from SMART data
            if not _is_valid_temperature(temp_float):
                if logger:
                    logger.debug("Skipping invalid temperature from SMART: %s = %s°C", device.get("name"), temp_float)
                continue
            label = (
                device.get("product")
                or device.get("model")
                or device.get("path")
                or device.get("name")
                or "Storage device"
            )
            _add_temperature_entry(
                readings,
                "Storage",
                label,
                temp_float,
                None,
                None,
            )

    for group_entries in readings.values():
        group_entries.sort(key=lambda entry: str(entry.get("label") or ""))

    return readings


def _add_temperature_entry(
    container: Dict[str, List[Dict[str, Any]]],
    group: str,
    label: str,
    current: Optional[float],
    high: Optional[float],
    critical: Optional[float],
) -> None:
    if current is None:
        return
    
    # Validate all temperature values are reasonable
    if not _is_valid_temperature(current):
        return
    
    # Validate high/critical thresholds if present
    validated_high = high if high and _is_valid_temperature(high) else None
    validated_critical = critical if critical and _is_valid_temperature(critical) else None

    entry = {
        "label": label,
        "current": current,
        "high": validated_high,
        "critical": validated_critical,
    }

    container.setdefault(group, []).append(entry)


def _parse_temperature_value(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value > 1000:
        value = value / 1000.0
    # Validate the temperature is in a reasonable range
    if not _is_valid_temperature(value):
        return None
    return value


def _is_valid_temperature(temp: float) -> bool:
    """Check if temperature value is within reasonable bounds for Celsius."""
    # Allow range from -50°C to 150°C (should cover all realistic hardware scenarios)
    return -50 <= temp <= 150


def _detect_device_type(device: Dict[str, Any], path: str, logger) -> Optional[str]:
    """Detect the device type and return appropriate smartctl -d flag value."""
    
    # Check device name patterns for NVMe devices
    name = device.get("name") or ""
    if name.startswith("nvme"):
        return "nvme"
    
    # Check transport type from lsblk
    transport = (device.get("transport") or "").lower()
    if transport == "nvme":
        return "nvme"
    
    # Check path patterns
    if "nvme" in path.lower():
        return "nvme"
    
    # For USB devices, try auto detection
    if transport in ("usb", "usb-storage"):
        return "auto"
    
    # Check if device has SCSI transport
    if transport in ("sata", "scsi", "ata"):
        # Let smartctl auto-detect SATA/SCSI devices
        return "auto"
    
    # For MMC/SD cards
    if name.startswith("mmcblk"):
        # Most SD cards don't support SMART
        if logger:
            logger.debug("Skipping SMART for MMC/SD device %s", path)
        return None
    
    # Default: let smartctl auto-detect
    return "auto"


def _iter_disk_devices(devices: List[Dict[str, Any]]):
    for device in devices:
        if not isinstance(device, dict):
            continue
        device_type = (device.get("type") or "").lower()
        name = device.get("name") or ""
        if device_type == "disk" and not name.startswith(("ram", "loop")):
            yield device
        for child in device.get("children") or []:
            yield from _iter_disk_devices([child])


def _extract_temperature(report: Dict[str, Any]) -> Optional[float]:
    temperature = report.get("temperature")
    if isinstance(temperature, dict):
        current = temperature.get("current")
        if isinstance(current, (int, float)):
            temp_value = float(current)
            # Validate temperature is in reasonable range for Celsius
            if -50 <= temp_value <= 150:
                return temp_value
            # If out of range, it might be in a different unit - skip it
            return None

    nvme_info = report.get("nvme_smart_health_information_log")
    if isinstance(nvme_info, dict):
        current = nvme_info.get("temperature")
        if isinstance(current, (int, float)):
            temp_value = float(current)
            # NVMe devices commonly report temperature in Kelvin; convert when it appears elevated.
            # Kelvin absolute zero is -273.15°C, so valid Kelvin values are > 273
            if temp_value > 200:
                # Likely Kelvin, convert to Celsius
                celsius = temp_value - 273.15
                # Validate the converted temperature is reasonable
                if -50 <= celsius <= 150:
                    return celsius
                # If still unreasonable, return None
                return None
            # If already in Celsius range, validate and return
            elif -50 <= temp_value <= 150:
                return temp_value
            # Otherwise, unreasonable value
            return None

    return None


def _extract_attribute_value(report: Dict[str, Any], name: str) -> Optional[int]:
    attributes = report.get("ata_smart_attributes")
    if isinstance(attributes, dict):
        table = attributes.get("table")
        if isinstance(table, list):
            for entry in table:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("name")) == name:
                    raw = entry.get("raw")
                    if isinstance(raw, dict):
                        value = raw.get("value")
                        if isinstance(value, (int, float)):
                            return int(value)
    # Fallback for NVMe data stored directly on the report
    direct_value = report.get(name)
    if isinstance(direct_value, (int, float)):
        return int(direct_value)
    return None


def _extract_nvme_statistics(report: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Normalise NVMe-specific counters from smartctl output."""

    stats: Dict[str, Optional[int]] = {
        "data_units_written_bytes": None,
        "data_units_read_bytes": None,
        "host_read_commands": None,
        "host_write_commands": None,
        "controller_busy_time_minutes": None,
        "unsafe_shutdowns": None,
        "percentage_used": None,
    }

    nvme_info = report.get("nvme_smart_health_information_log")
    if not isinstance(nvme_info, dict):
        return stats

    def pull(*keys: str) -> Optional[int]:
        for candidate in keys:
            if candidate in nvme_info:
                value = _coerce_int(nvme_info.get(candidate))
                if value is not None:
                    return value
        return None

    bytes_written = pull("data_units_written_bytes")
    if bytes_written is not None:
        stats["data_units_written_bytes"] = bytes_written
    else:
        units_written = pull("data_units_written", "data_units_written_raw")
        if units_written is not None:
            stats["data_units_written_bytes"] = units_written * NVME_DATA_UNIT_BYTES

    bytes_read = pull("data_units_read_bytes")
    if bytes_read is not None:
        stats["data_units_read_bytes"] = bytes_read
    else:
        units_read = pull("data_units_read", "data_units_read_raw")
        if units_read is not None:
            stats["data_units_read_bytes"] = units_read * NVME_DATA_UNIT_BYTES

    stats["host_read_commands"] = pull("host_read_commands", "host_reads")
    stats["host_write_commands"] = pull("host_write_commands", "host_writes")
    stats["controller_busy_time_minutes"] = pull("controller_busy_time_minutes", "controller_busy_time")
    stats["unsafe_shutdowns"] = pull("unsafe_shutdowns")
    stats["percentage_used"] = pull("percentage_used")

    return stats


def _extract_nvme_field(report: Dict[str, Any], key: str) -> Optional[int]:
    nvme_info = report.get("nvme_smart_health_information_log")
    if isinstance(nvme_info, dict):
        value = nvme_info.get(key)
        coerced = _coerce_int(value)
        if coerced is not None:
            return coerced
    return None


def _populate_nvme_metrics(device_result: Dict[str, Any], report: Dict[str, Any]) -> None:
    nvme_info = report.get("nvme_smart_health_information_log")
    if not isinstance(nvme_info, dict):
        return

    def _update_if_absent(field: str, *keys: str) -> None:
        if device_result.get(field) is not None:
            return
        for key in keys:
            value = nvme_info.get(key)
            if isinstance(value, (int, float)):
                device_result[field] = int(value)
                return

    _update_if_absent("power_on_hours", "power_on_hours", "power_on_time_hours")
    _update_if_absent("power_cycle_count", "power_cycles")
    _update_if_absent("unsafe_shutdowns", "unsafe_shutdowns")
    _update_if_absent("percentage_used", "percentage_used")

    for source_key, target_field in (
        ("data_units_written", "data_units_written"),
        ("data_units_read", "data_units_read"),
        ("host_writes_32mib", "host_writes_32mib"),
        ("host_reads_32mib", "host_reads_32mib"),
    ):
        value = nvme_info.get(source_key)
        if isinstance(value, (int, float)):
            device_result[target_field] = int(value)

    if device_result.get("data_units_written") is not None:
        device_result["data_units_written_bytes"] = _convert_nvme_data_units(
            device_result["data_units_written"]
        )
    if device_result.get("data_units_read") is not None:
        device_result["data_units_read_bytes"] = _convert_nvme_data_units(
            device_result["data_units_read"]
        )

    if device_result.get("host_writes_32mib") is not None:
        device_result["host_writes_bytes"] = _convert_nvme_host_io(
            device_result["host_writes_32mib"]
        )
    if device_result.get("host_reads_32mib") is not None:
        device_result["host_reads_bytes"] = _convert_nvme_host_io(
            device_result["host_reads_32mib"]
        )


def _convert_nvme_data_units(units: int) -> int:
    # Per the NVMe specification, each data unit represents 512,000 bytes.
    return int(units) * 512_000


def _convert_nvme_host_io(units_32mib: int) -> int:
    # smartctl reports host reads/writes in units of 32 MiB.
    return int(units_32mib) * 32 * 1024 * 1024


def _safe_read_text(path: Path) -> Optional[str]:
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        value = path.read_text(encoding="utf-8", errors="ignore").strip()
        if value:
            lower = value.lower()
            if lower not in {"none", "unknown", "not specified"}:
                return value
    return None


def _safe_read_device_tree_text(path: Path) -> Optional[str]:
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        data = path.read_bytes()
        if not data:
            return None
        text = data.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
        if text and text.lower() not in {"", "none", "unknown", "not specified"}:
            return text
    return None


def _safe_read_device_tree_revision(path: Path) -> Optional[str]:
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        data = path.read_bytes()
        if not data:
            return None
        if len(data) in {4, 8}:
            value = int.from_bytes(data[:4], byteorder="big", signed=False)
            if value:
                return f"0x{value:08x}"
        text = data.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
        if text:
            return text
    return None


def _safe_read_device_tree_compatible(path: Path) -> Optional[List[str]]:
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        data = path.read_bytes()
        if not data:
            return None
        parts = [
            part.decode("utf-8", errors="ignore").strip()
            for part in data.split(b"\x00")
            if part.strip()
        ]
        cleaned = [part for part in parts if part and part.lower() not in {"none", "unknown"}]
        if cleaned:
            return cleaned
    return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort conversion of nested numeric representations to int."""

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            if cleaned.lower().startswith("0x"):
                return int(cleaned, 16)
            return int(float(cleaned))
        except ValueError:
            return None

    if isinstance(value, dict):
        for key in ("value", "raw", "raw_value", "raw_value_64", "count", "hex"):
            if key in value:
                coerced = _coerce_int(value.get(key))
                if coerced is not None:
                    return coerced

    return None


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        numeric = int(str(value).strip())
        return bool(numeric)
    except (TypeError, ValueError):
        lowered = str(value).strip().lower()
        if lowered in {"y", "yes", "true"}:
            return True
        if lowered in {"n", "no", "false"}:
            return False
    return None


class _UnixHTTPConnection(http.client.HTTPConnection):
    """Minimal HTTP connection implementation for UNIX domain sockets."""

    def __init__(self, path: str, timeout: float = 10.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._unix_path = path

    def connect(self) -> None:  # pragma: no cover - requires system socket access
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout is not None:
            sock.settimeout(self.timeout)
        sock.connect(self._unix_path)
        self.sock = sock


def _candidate_container_api_targets() -> Iterable[Dict[str, Any]]:
    """Yield potential container engine API endpoints to query."""

    candidates: List[Tuple[str, str]] = []

    docker_host = os.getenv("DOCKER_HOST")
    if docker_host:
        candidates.append(("docker", docker_host.strip()))

    podman_host = os.getenv("PODMAN_HOST")
    if podman_host:
        candidates.append(("podman", podman_host.strip()))

    # Common default socket paths
    candidates.extend(
        [
            ("docker", "unix:///var/run/docker.sock"),
            ("docker", "unix:///run/docker.sock"),
            ("podman", "unix:///run/podman/podman.sock"),
        ]
    )

    runtime_dir = os.getenv("XDG_RUNTIME_DIR")
    if runtime_dir:
        podman_socket = os.path.join(runtime_dir, "podman", "podman.sock")
        candidates.append(("podman", f"unix://{podman_socket}"))

    normalised: List[Dict[str, Any]] = []
    seen: set = set()

    for engine, raw_value in candidates:
        if not raw_value:
            continue

        parsed = urlparse(raw_value)
        scheme = parsed.scheme or "unix"

        if scheme == "unix":
            path = parsed.path or parsed.netloc
            if not path:
                continue
            key = (engine, "unix", path)
            if key in seen:
                continue
            seen.add(key)
            normalised.append(
                {
                    "engine": engine,
                    "scheme": "unix",
                    "address": path,
                    "description": path,
                }
            )
        elif scheme in {"tcp", "http", "https"}:
            host = parsed.hostname or parsed.netloc
            port = parsed.port or (443 if scheme == "https" else 80)
            http_scheme = "https" if scheme == "https" else "http"
            if not host:
                continue
            key = (engine, http_scheme, host, port)
            if key in seen:
                continue
            seen.add(key)
            normalised.append(
                {
                    "engine": engine,
                    "scheme": http_scheme,
                    "address": host,
                    "port": port,
                    "description": f"{http_scheme}://{host}:{port}",
                }
            )

    return normalised


def _perform_api_request(target: Dict[str, Any], path: str) -> Any:
    """Execute an HTTP GET against a container engine endpoint."""

    timeout = 5

    if target["scheme"] == "unix":
        connection: http.client.HTTPConnection = _UnixHTTPConnection(target["address"], timeout=timeout)
    elif target["scheme"] == "http":
        connection = http.client.HTTPConnection(target["address"], target.get("port"), timeout=timeout)
    else:
        connection = http.client.HTTPSConnection(target["address"], target.get("port"), timeout=timeout)

    try:
        connection.request("GET", path, headers={"Host": "localhost"})
        response = connection.getresponse()
        payload = response.read()
    finally:  # pragma: no cover - defensive cleanup
        connection.close()

    if response.status >= 400:
        raise RuntimeError(f"HTTP {response.status} {response.reason}")

    if not payload:
        return None

    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response: {exc}") from exc


def _fetch_containers_via_api(target: Dict[str, Any], compose_project: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Attempt to load container data from the engine API."""

    if target["engine"] == "docker":
        candidates = ["/containers/json?all=1", "/v1.41/containers/json?all=1"]
    else:
        # Podman exposes both Docker-compatible and libpod endpoints.
        candidates = [
            "/containers/json?all=1",
            "/v1.41/containers/json?all=1",
            "/v1.0.0/libpod/containers/json?all=true",
        ]

    last_error: Optional[Exception] = None

    for path in candidates:
        try:
            response = _perform_api_request(target, path)
        except Exception as exc:
            last_error = exc
            continue

        if response is None:
            continue

        if isinstance(response, dict) and "containers" in response:
            entries = response.get("containers") or []
        elif isinstance(response, list):
            entries = response
        else:
            raise RuntimeError("Unexpected API response structure")

        containers = [_normalize_api_container(entry, compose_project) for entry in entries]

        # Filter to the compose project when possible. If the filter removes everything and we
        # had entries, fall back to displaying all containers so operators still see something.
        if compose_project:
            filtered = [item for item in containers if item.get("project") == compose_project]
            if filtered or not containers:
                containers = filtered

        return containers

    if last_error:
        raise last_error

    return None


def _fetch_containers_via_cli(engine: str, compose_project: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Collect container information using the Docker or Podman CLI."""

    engine_path = shutil.which(engine)
    if not engine_path:
        return None

    command = [engine_path, "ps", "--all"]
    if compose_project:
        label_key = "com.docker.compose.project" if engine == "docker" else "io.podman.compose.project"
        command.extend(["--filter", f"label={label_key}={compose_project}"])
    command.extend(["--format", "{{json .}}"])  # Machine-readable output

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "unknown error"
        raise RuntimeError(stderr)

    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    containers: List[Dict[str, Any]] = []

    for raw_line in lines:
        try:
            info = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unable to parse {engine} output: {raw_line}") from exc

        containers.append(_normalize_cli_container(info, compose_project))

    return containers


def _normalize_cli_container(info: Dict[str, Any], compose_project: Optional[str]) -> Dict[str, Any]:
    labels_text = info.get("Labels") or ""
    labels: Dict[str, str] = {}
    for item in labels_text.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            labels[key.strip()] = value.strip()

    name = info.get("Names") or info.get("Name") or info.get("ID") or info.get("Id") or "unknown"
    status_text = info.get("Status") or info.get("State") or "unknown"
    state = (info.get("State") or "").lower() or None
    health_state = _extract_health(status_text)
    is_running = (state == "running") or status_text.lower().startswith("up")

    service = labels.get("com.docker.compose.service") or labels.get("io.podman.compose.service")
    display_name = _format_display_name(service)

    project = (
        labels.get("com.docker.compose.project")
        or labels.get("io.podman.compose.project")
        or compose_project
    )

    return {
        "name": name,
        "display_name": display_name,
        "service": service,
        "project": project,
        "status": status_text,
        "state": state,
        "health": health_state,
        "is_running": is_running,
        "image": info.get("Image"),
        "ports": info.get("Ports"),
        "running_for": info.get("RunningFor"),
        "created_at": info.get("CreatedAt"),
        "labels": labels,
    }


def _normalize_api_container(info: Dict[str, Any], compose_project: Optional[str]) -> Dict[str, Any]:
    labels = info.get("Labels") or {}
    if not isinstance(labels, dict):
        labels = {}

    names = info.get("Names")
    if isinstance(names, list) and names:
        raw_name = names[0]
        name = raw_name[1:] if raw_name.startswith("/") else raw_name
    else:
        name = info.get("Id") or info.get("ID") or "unknown"

    status_text = info.get("Status") or info.get("State") or "unknown"
    state = (info.get("State") or "").lower() or None
    health_state = _extract_health(status_text)
    is_running = (state == "running") or status_text.lower().startswith("up")

    service = labels.get("com.docker.compose.service") or labels.get("io.podman.compose.service")
    display_name = _format_display_name(service)

    project = (
        labels.get("com.docker.compose.project")
        or labels.get("io.podman.compose.project")
        or compose_project
    )

    created = info.get("Created")
    if isinstance(created, (int, float)):
        created_dt = datetime.fromtimestamp(created, UTC_TZ)
        created_iso = created_dt.isoformat()
        running_for = _format_duration(max((utc_now() - created_dt).total_seconds(), 0))
    else:
        created_iso = None
        running_for = None

    ports_value = info.get("Ports")
    if isinstance(ports_value, list):
        ports = _format_ports(ports_value)
    else:
        ports = ports_value

    return {
        "name": name,
        "display_name": display_name,
        "service": service,
        "project": project,
        "status": status_text,
        "state": state,
        "health": health_state,
        "is_running": is_running,
        "image": info.get("Image"),
        "ports": ports,
        "running_for": running_for,
        "created_at": created_iso,
        "labels": labels,
    }


def _format_display_name(service: Optional[str]) -> Optional[str]:
    if not service:
        return None
    return service.replace("_", " ").replace("-", " ").title()


def _extract_health(status_text: str) -> Optional[str]:
    lowered = (status_text or "").lower()
    if "unhealthy" in lowered:
        return "unhealthy"
    if "healthy" in lowered:
        return "healthy"
    if "starting" in lowered:
        return "starting"
    return None


def _format_ports(ports: Iterable[Dict[str, Any]]) -> str:
    formatted: List[str] = []
    for entry in ports:
        if not isinstance(entry, dict):
            continue
        private_port = entry.get("PrivatePort")
        public_port = entry.get("PublicPort")
        proto = entry.get("Type")
        ip = entry.get("IP")

        if public_port:
            if ip and ip not in {"0.0.0.0", "::"}:
                formatted.append(f"{ip}:{public_port}->{private_port}/{proto or 'tcp'}")
            else:
                formatted.append(f"{public_port}->{private_port}/{proto or 'tcp'}")
        elif private_port:
            formatted.append(f"{private_port}/{proto or 'tcp'}")

    return ", ".join(formatted)


def _format_duration(seconds: float) -> str:
    total_seconds = int(max(seconds, 0))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds_left = divmod(remainder, 60)

    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds_left}s")

    return " ".join(parts)


def _build_container_result(
    containers: List[Dict[str, Any]],
    *,
    engine: Optional[str],
    compose_project: Optional[str],
    collector: Optional[str],
) -> Dict[str, Any]:
    total = len(containers)
    running = len([item for item in containers if item.get("is_running")])
    healthy = len([item for item in containers if item.get("health") == "healthy"])
    unhealthy = len([item for item in containers if item.get("health") == "unhealthy"])
    stopped = max(total - running, 0)

    issues = [
        item
        for item in containers
        if not item.get("is_running") or item.get("health") == "unhealthy"
    ]

    status = "healthy"
    if issues and running:
        status = "degraded"
    elif issues and not running and total:
        status = "stopped"

    return {
        "available": True,
        "status": status,
        "engine": engine,
        "containers": containers,
        "summary": {
            "total": total,
            "running": running,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "stopped": stopped,
        },
        "issues": issues,
        "error": None,
        "compose_project": compose_project,
        "collector": collector,
    }
