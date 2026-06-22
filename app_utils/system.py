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

"""System monitoring helpers."""

from datetime import datetime
import contextlib
import http.client
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from urllib.parse import urlparse

import psutil
from sqlalchemy import text

from .formatting import format_uptime
from .time import UTC_TZ, local_now, utc_now


DEVICE_TREE_CANDIDATES = [
    Path("/proc/device-tree"),
    Path("/sys/firmware/devicetree/base"),
]


SystemHealth = Dict[str, Any]


NVME_DATA_UNIT_BYTES = 512_000

_AUDIO_PROCESS_KEYWORDS = (
    "ffmpeg",
    "sox",
    "gst-launch",
    "gst-launch-1.0",
    "arecord",
    "aplay",
    "liquidsoap",
    "pulseaudio",
    "jackd",
    "audio_service",
    "eas_decode",
    "eas_detection",
)


def _is_audio_processing_process(name: Optional[str], cmdline: Optional[str]) -> bool:
    """Return True when process metadata suggests active audio decoding/encoding."""

    haystack = " ".join(filter(None, [name, cmdline])).lower()
    return any(keyword in haystack for keyword in _AUDIO_PROCESS_KEYWORDS)


def _collect_dependency_versions(logger) -> List[Dict[str, str]]:
    """Collect version information for key software dependencies."""

    versions: List[Dict[str, str]] = []

    # Python runtime
    versions.append({
        "name": "Python",
        "version": platform.python_version(),
        "category": "runtime",
    })

    # Key Python packages
    _pkg_list = [
        ("Flask", "flask", "framework"),
        ("SQLAlchemy", "sqlalchemy", "database"),
        ("Alembic", "alembic", "database"),
        ("Redis", "redis", "database"),
        ("psutil", "psutil", "system"),
        ("Gunicorn", "gunicorn", "server"),
        ("Jinja2", "jinja2", "framework"),
        ("Werkzeug", "werkzeug", "framework"),
        ("NumPy", "numpy", "processing"),
        ("SciPy", "scipy", "processing"),
        ("lxml", "lxml", "processing"),
        ("Requests", "requests", "network"),
        ("httpx", "httpx", "network"),
        ("Pillow", "PIL", "processing"),
        ("PyYAML", "yaml", "processing"),
        ("pytest", "pytest", "testing"),
    ]

    from importlib.metadata import version as pkg_version, PackageNotFoundError

    for display_name, import_name, category in _pkg_list:
        try:
            ver = pkg_version(import_name if import_name != "PIL" else "Pillow")
            versions.append({"name": display_name, "version": ver, "category": category})
        except PackageNotFoundError:
            pass
        except Exception:
            pass

    # System-level tools
    for cmd, name, category in [
        (["redis-server", "--version"], "Redis Server", "database"),
        (["ffmpeg", "-version"], "FFmpeg", "processing"),
        (["smartctl", "--version"], "smartmontools", "system"),
    ]:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=5,
            )
            output = (result.stdout or "").strip()
            if output:
                # Extract version from first line
                first_line = output.split("\n")[0]
                # Common patterns: "redis-server v=7.0.0", "ffmpeg version 6.1"
                ver_str = first_line
                for prefix in ("redis-server ", "Redis server ", "ffmpeg version ", "smartctl "):
                    if prefix.lower() in ver_str.lower():
                        idx = ver_str.lower().index(prefix.lower()) + len(prefix)
                        ver_str = ver_str[idx:].split()[0].strip("v=,")
                        break
                versions.append({"name": name, "version": ver_str, "category": category})
        except Exception:
            pass

    return versions


def build_system_health_snapshot(db, logger) -> SystemHealth:
    """Collect detailed system health metrics.

    Performance: this function runs on the single WebSocket-push thread and
    used to block for ~1.3 s every minute (psutil.cpu_percent(interval=1) +
    time.sleep(0.3) for per-process CPU sampling), stalling the 4 Hz VU-meter
    push.  Both blocking calls have been removed.  CPU samples are now taken
    with ``interval=None`` (non-blocking, reporting the delta since the last
    call); because callers cache the snapshot for ~30 s, the resulting numbers
    are meaningful 30-second averages without ever blocking the loop.
    """

    try:
        uname = platform.uname()
        boot_time = psutil.boot_time()

        cpu_freq = psutil.cpu_freq()
        # Non-blocking CPU sample: returns the delta since the previous call.
        # Cached at the get_system_health() layer, so the delta is over the
        # cache TTL (~30 s) and remains an accurate utilization figure.
        cpu_usage_per_core = psutil.cpu_percent(interval=None, percpu=True)
        cpu_usage_percent = (
            sum(cpu_usage_per_core) / len(cpu_usage_per_core)
            if cpu_usage_per_core
            else psutil.cpu_percent(interval=None) or 0
        )

        os_details = _collect_operating_system_details()

        cpu_info = {
            "physical_cores": psutil.cpu_count(logical=False) or 0,
            "total_cores": psutil.cpu_count(logical=True) or 0,
            "max_frequency": cpu_freq.max if cpu_freq and cpu_freq.max else None,
            "current_frequency": cpu_freq.current if cpu_freq and cpu_freq.current else None,
            "cpu_usage_percent": cpu_usage_percent,
            "cpu_usage_per_core": cpu_usage_per_core if cpu_usage_per_core else [],
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

                if interface_name in net_if_stats:
                    stats_entry = net_if_stats[interface_name]
                    interface_info["speed_mbps"] = getattr(stats_entry, "speed", None)
                    interface_info["mtu"] = getattr(stats_entry, "mtu", None)
                    interface_info["duplex"] = getattr(stats_entry, "duplex", None)

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
                    else:
                        link_family = getattr(psutil, "AF_LINK", None)
                        if link_family is not None and address.family == link_family:
                            interface_info["mac_address"] = address.address

                if interface_info["addresses"]:
                    network_info["interfaces"].append(interface_info)
        except Exception:
            pass

        network_info["traffic"] = _collect_network_traffic()

        primary_interface = _select_primary_interface(network_info["interfaces"])
        if primary_interface:
            network_info["primary_interface"] = primary_interface
            primary_ipv4 = next(
                (
                    address.get("address")
                    for address in primary_interface.get("addresses", [])
                    if address.get("type") == "IPv4"
                ),
                None,
            )
            if primary_ipv4:
                network_info["primary_ipv4"] = primary_ipv4
            if primary_interface.get("name"):
                network_info["primary_interface_name"] = primary_interface["name"]

        process_info = {
            "total_processes": 0,
            "running_processes": 0,
            "top_processes": [],
            "audio_decoding": {
                "cpu_percent_total": 0.0,
                "processes": [],
            },
        }

        try:
            # Single pass over the process table.  Previously this section
            # iterated psutil.process_iter() three times and slept for 300 ms
            # between samples to compute CPU deltas — that 0.3 s stall, run
            # on the shared WebSocket-push thread, dropped audio-monitoring
            # ticks every snapshot.  We now call ``cpu_percent(None)`` once
            # per process which returns the delta since the previous call by
            # the *same* psutil bookkeeping (process objects keyed by pid).
            # Because get_system_health() caches the snapshot for ~30 s,
            # consecutive calls produce a meaningful 30-second average
            # without any sleep.
            processes: List[Dict[str, Any]] = []
            audio_processes: List[Dict[str, Any]] = []
            audio_cpu_total = 0.0
            total_processes = 0
            running_processes = 0
            running_status = psutil.STATUS_RUNNING

            for proc in psutil.process_iter(["pid", "name", "username", "status"]):
                total_processes += 1
                info = proc.info
                if info.get("status") == running_status:
                    running_processes += 1

                try:
                    cpu_percent = proc.cpu_percent(None)
                    memory_percent = proc.memory_percent()
                    name = info.get("name") or proc.name()
                    cmdline_list = proc.cmdline()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                cmdline = " ".join(cmdline_list[:12]) if cmdline_list else None

                if cpu_percent is None:
                    cpu_percent = 0.0
                if memory_percent is None:
                    memory_percent = 0.0

                process_entry = {
                    "pid": info.get("pid", proc.pid),
                    "name": name,
                    "username": info.get("username"),
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                }

                if cmdline:
                    process_entry["command"] = cmdline

                processes.append(process_entry)

                if _is_audio_processing_process(name, cmdline):
                    audio_cpu_total += cpu_percent
                    audio_processes.append({
                        **process_entry,
                        "command": cmdline or name,
                    })

            processes.sort(key=lambda entry: entry.get("cpu_percent", 0) or 0, reverse=True)
            audio_processes.sort(key=lambda entry: entry.get("cpu_percent", 0) or 0, reverse=True)

            process_info["total_processes"] = total_processes
            process_info["running_processes"] = running_processes
            process_info["top_processes"] = processes[:10]
            process_info["audio_decoding"] = {
                "cpu_percent_total": round(audio_cpu_total, 1),
                "processes": audio_processes[:5],
            }
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
        # If a prior query in the same scoped session left the PostgreSQL
        # transaction in the aborted state (InFailedSqlTransaction), every
        # subsequent statement raises until a rollback. The websocket push
        # loop reuses one session across many emits, so a single failed
        # query elsewhere would otherwise wedge this probe forever.
        try:
            db.session.rollback()
        except Exception:
            pass
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
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    db_info["size"] = "Unknown"

                try:
                    conn_result = db.session.execute(
                        text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                    ).fetchone()
                    if conn_result:
                        db_info["active_connections"] = conn_result[0]
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    db_info["active_connections"] = "Unknown"
        except Exception as exc:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("Database health probe failed: %s", exc)
            db_status = "error"
            db_info["error"] = str(exc)[:200]

        systemd_services = _collect_systemd_services(logger)
        services_status: Dict[str, Any] = {
            service.get("display_name")
            or service.get("name")
            or f"service-{index}": service.get("status")
            for index, service in enumerate(systemd_services.get("services", []), start=1)
        }

        hardware_subsystems = _collect_hardware_subsystems(logger)
        hardware_info = _collect_hardware_inventory(logger)
        smart_info = _collect_smart_health(
            logger, hardware_info.get("block_devices", {}).get("devices") or []
        )
        temperature_info = _collect_temperature_readings(logger, smart_info)

        # Build the health data structure
        health_data = {
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
            "systemd": systemd_services,
            "temperature": temperature_info,
            "hardware": hardware_info,
            "hardware_subsystems": hardware_subsystems,
            "smart": smart_info,
            "dependencies": _collect_dependency_versions(logger),
            "gps": _collect_gps_status(logger),
            "rtc": _collect_rtc_status(logger),
        }
        
        # Add shields.io badges and distro logo
        health_data["shields_badges"] = get_shields_io_badges(health_data)
        health_data["distro_logo_url"] = get_distro_logo_url(os_details.get("distribution_id"))

        uptime_seconds = health_data["system"].get("uptime_seconds")
        if isinstance(uptime_seconds, (int, float)):
            health_data["system"]["uptime_human"] = format_uptime(uptime_seconds)

        # Compute overall status and summary for the header indicator
        status = "healthy"
        status_reasons = []

        # Check CPU usage
        if cpu_usage_percent >= 90:
            status = "critical"
            status_reasons.append(f"CPU usage is {cpu_usage_percent:.1f}%")
        elif cpu_usage_percent >= 75:
            if status != "critical":
                status = "warning"
            status_reasons.append(f"CPU usage is {cpu_usage_percent:.1f}%")

        # Check memory usage
        if memory.percent >= 92:
            status = "critical"
            status_reasons.append(f"Memory usage is {memory.percent:.1f}%")
        elif memory.percent >= 80:
            if status != "critical":
                status = "warning"
            status_reasons.append(f"Memory usage is {memory.percent:.1f}%")

        # Check database status
        if db_status != "connected":
            status = "critical"
            status_reasons.append(f"Database: {db_status}")

        # Check systemd services
        systemd_status = systemd_services.get("status", "unknown")
        if systemd_status == "degraded":
            if status != "critical":
                status = "warning"
            failed_count = systemd_services.get("summary", {}).get("failed", 0)
            status_reasons.append(f"{failed_count} service(s) failed")
        elif systemd_status == "stopped":
            status = "critical"
            status_reasons.append("All services stopped")

        # Build status summary
        if status == "healthy":
            status_summary = "All systems operational"
        elif status_reasons:
            status_summary = "; ".join(status_reasons[:2])  # Show up to 2 reasons
        else:
            status_summary = "System status unknown"

        health_data["status"] = status
        health_data["status_summary"] = status_summary
        health_data["status_reasons"] = status_reasons

        return health_data

    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.error("Error getting system health: %s", exc)
        return {
            "error": str(exc),
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
        }


def _collect_systemd_services(logger) -> Dict[str, Any]:
    """Collect status information for EAS Station systemd services."""
    
    # Import here to avoid circular dependency (app_core imports app_utils)
    from app_core.config import get_eas_services, INFRASTRUCTURE_SERVICES
    
    result: Dict[str, Any] = {
        "available": False,
        "status": "unavailable",
        "services": [],
        "summary": {"total": 0, "active": 0, "inactive": 0, "failed": 0},
        "issues": [],
        "error": None,
    }
    
    # List of EAS Station services to monitor (from centralized config)
    eas_services = get_eas_services()

    # Additional system services that EAS Station depends on
    dependency_services = INFRASTRUCTURE_SERVICES + ["icecast2.service"]
    
    try:
        all_services = eas_services + dependency_services
        services_data = []
        
        for service_name in all_services:
            try:
                # Check if service exists first
                check_cmd = ["systemctl", "list-unit-files", service_name]
                check_result = subprocess.run(
                    check_cmd,
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if service_name not in check_result.stdout:
                    # Service doesn't exist, skip it
                    continue
                
                # Get service status
                status_cmd = ["systemctl", "show", service_name, 
                             "--property=ActiveState,SubState,LoadState,UnitFileState,Description"]
                status_result = subprocess.run(
                    status_cmd,
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if status_result.returncode == 0:
                    # Parse systemctl output
                    props = {}
                    for line in status_result.stdout.strip().split('\n'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            props[key] = value
                    
                    active_state = props.get('ActiveState', 'unknown')
                    sub_state = props.get('SubState', 'unknown')
                    description = props.get('Description', service_name)
                    
                    # Determine if this is an EAS service or dependency
                    is_eas_service = service_name in eas_services
                    
                    service_info = {
                        "name": service_name,
                        "display_name": description,
                        "active_state": active_state,
                        "sub_state": sub_state,
                        "status": active_state,
                        "is_running": active_state == "active",
                        "is_eas_service": is_eas_service,
                        "category": "EAS Station" if is_eas_service else "Dependencies"
                    }
                    
                    services_data.append(service_info)
                    
                    # Track issues
                    if active_state == "failed":
                        result["issues"].append({
                            "service": service_name,
                            "issue": f"{description} has failed",
                            "severity": "error"
                        })
                    elif active_state != "active" and is_eas_service:
                        result["issues"].append({
                            "service": service_name,
                            "issue": f"{description} is not running",
                            "severity": "warning"
                        })
                        
            except subprocess.TimeoutExpired:
                if logger:
                    logger.debug(f"Timeout checking service {service_name}")
            except Exception as exc:
                if logger:
                    logger.debug(f"Error checking service {service_name}: {exc}")
        
        if services_data:
            result["available"] = True
            result["status"] = "available"
            result["services"] = services_data
            
            # Calculate summary
            result["summary"]["total"] = len(services_data)
            result["summary"]["active"] = len([s for s in services_data if s["active_state"] == "active"])
            result["summary"]["inactive"] = len([s for s in services_data if s["active_state"] == "inactive"])
            result["summary"]["failed"] = len([s for s in services_data if s["active_state"] == "failed"])
        else:
            result["error"] = "No systemd services found"
            
    except FileNotFoundError:
        result["error"] = "systemctl command not found - systemd not available"
    except Exception as exc:
        if logger:
            logger.error(f"Error collecting systemd service status: {exc}")
        result["error"] = str(exc)
    
    return result


def get_distro_logo_url(distro_id: Optional[str]) -> Optional[str]:
    """Return logo URL for common Linux distributions."""
    
    # Map distribution IDs to their logo URLs
    distro_logos = {
        "ubuntu": "https://assets.ubuntu.com/v1/29985a98-ubuntu-logo32.png",
        "debian": "https://www.debian.org/logos/openlogo-nd-50.png",
        "fedora": "https://fedoraproject.org/assets/images/fedora-coreos-logo.png",
        "centos": "https://www.centos.org/assets/img/logo-centos-white.png",
        "rhel": "https://www.redhat.com/cms/managed-files/Logo-Red_Hat-A-Reverse-RGB.png",
        "arch": "https://archlinux.org/static/logos/archlinux-logo-dark-90dpi.ebdee92a15b3.png",
        "alpine": "https://alpinelinux.org/alpinelinux-logo.svg",
        "opensuse": "https://en.opensuse.org/images/c/cd/Button-filled-colour.png",
        "raspbian": "https://www.raspberrypi.com/app/uploads/2022/02/COLOUR-Raspberry-Pi-Symbol-Registered.png",
    }
    
    if not distro_id:
        return None
        
    distro_id_lower = distro_id.lower()
    
    # Check for exact match first
    if distro_id_lower in distro_logos:
        return distro_logos[distro_id_lower]
    
    # Check for partial matches
    for key, url in distro_logos.items():
        if key in distro_id_lower or distro_id_lower in key:
            return url
    
    return None


def _escape_shields_io_text(text: str) -> str:
    """Escape text for use in shields.io badge URLs.
    
    Shields.io uses specific escape sequences:
    - Dashes (-) must be doubled (--) as they're used as separators
    - Underscores (_) must be doubled (__) as they're used for spaces
    - Spaces can remain as-is or be replaced with underscores
    
    Args:
        text: The text to escape for shields.io
        
    Returns:
        Escaped text safe for use in shields.io badge URLs
    """
    # Replace underscores first (before dashes) to avoid double-escaping
    escaped = text.replace('_', '__')
    # Replace dashes with double dashes (shields.io separator escape)
    escaped = escaped.replace('-', '--')
    # Spaces are fine in shields.io, but we can optionally replace with underscores
    # For now, keep spaces as they're more readable
    return escaped


def get_shields_io_badges(health_data: Dict[str, Any]) -> Dict[str, str]:
    """Generate shields.io badge URLs for system metrics."""
    
    badges = {}
    system = health_data.get("system", {})
    cpu = health_data.get("cpu", {})
    memory = health_data.get("memory", {})
    
    # OS Badge
    os_name = system.get("distribution") or system.get("system") or "Unknown"
    os_version = system.get("distribution_version") or system.get("release") or ""
    if os_version:
        os_label = f"{os_name} {os_version}"
    else:
        os_label = os_name
    badges["os"] = f"https://img.shields.io/badge/OS-{_escape_shields_io_text(os_label)}-blue?style=flat-square&logo=linux"
    
    # Kernel Badge
    kernel = system.get("kernel_release") or system.get("release") or "Unknown"
    badges["kernel"] = f"https://img.shields.io/badge/Kernel-{_escape_shields_io_text(kernel)}-lightgrey?style=flat-square"
    
    # Architecture Badge
    arch = system.get("machine") or "Unknown"
    badges["architecture"] = f"https://img.shields.io/badge/Arch-{_escape_shields_io_text(arch)}-informational?style=flat-square"
    
    # Uptime Badge (format for badge)
    uptime_seconds = system.get("uptime_seconds", 0)
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    if days > 0:
        uptime_label = f"{days}d {hours}h"
    else:
        uptime_label = f"{hours}h"
    badges["uptime"] = f"https://img.shields.io/badge/Uptime-{_escape_shields_io_text(uptime_label)}-success?style=flat-square"
    
    # CPU Usage Badge
    cpu_usage = cpu.get("cpu_usage_percent", 0)
    cpu_color = "critical" if cpu_usage > 80 else "yellow" if cpu_usage > 50 else "success"
    badges["cpu"] = f"https://img.shields.io/badge/CPU-{cpu_usage:.0f}%25-{cpu_color}?style=flat-square&logo=intel"
    
    # Memory Usage Badge
    mem_usage = memory.get("percentage", 0)
    mem_color = "critical" if mem_usage > 90 else "yellow" if mem_usage > 75 else "success"
    badges["memory"] = f"https://img.shields.io/badge/Memory-{mem_usage:.0f}%25-{mem_color}?style=flat-square&logo=memory"
    
    # CPU Cores Badge
    physical_cores = cpu.get("physical_cores", 0)
    total_cores = cpu.get("total_cores", 0)
    badges["cores"] = f"https://img.shields.io/badge/Cores-{physical_cores}p/{total_cores}t-informational?style=flat-square"

    # Disk Usage Badge (root partition)
    disk_list = health_data.get("disk") or []
    root_disk = next(
        (d for d in disk_list if isinstance(d, dict) and d.get("mountpoint") == "/"),
        disk_list[0] if disk_list else None,
    )
    if root_disk and isinstance(root_disk, dict):
        disk_pct = root_disk.get("percentage", 0) or 0
        disk_color = "critical" if disk_pct > 90 else "yellow" if disk_pct > 75 else "success"
        badges["disk"] = (
            f"https://img.shields.io/badge/Disk-{disk_pct:.0f}%25-{disk_color}?style=flat-square&logo=databricks&logoColor=white"
        )

    # Load Average Badge (1-minute load)
    load_avgs = health_data.get("load_averages") or {}
    load_1m = load_avgs.get("1m") if isinstance(load_avgs, dict) else None
    if load_1m is not None:
        load_label = f"{load_1m:.2f}"
        core_count = total_cores or 4
        load_color = "critical" if load_1m > core_count else "yellow" if load_1m > core_count * 0.7 else "success"
        badges["load"] = (
            f"https://img.shields.io/badge/Load%20Avg-{_escape_shields_io_text(load_label)}-{load_color}?style=flat-square"
        )

    # Temperature Badge (highest sensor reading)
    temp_data = health_data.get("temperature") or {}
    sensors = temp_data.get("sensors") if isinstance(temp_data, dict) else None
    highest_temp: Optional[float] = None
    if isinstance(sensors, dict):
        for sensor_entries in sensors.values():
            if not isinstance(sensor_entries, list):
                continue
            for entry in sensor_entries:
                current = entry.get("current") if isinstance(entry, dict) else None
                if isinstance(current, (int, float)) and (highest_temp is None or current > highest_temp):
                    highest_temp = current
    if highest_temp is not None:
        temp_color = "critical" if highest_temp > 80 else "yellow" if highest_temp > 65 else "success"
        badges["temperature"] = (
            f"https://img.shields.io/badge/Temp-{highest_temp:.0f}%C2%B0C-{temp_color}?style=flat-square&logo=thermal&logoColor=white"
        )

    # Database Status Badge
    db_info = health_data.get("database") or {}
    db_status = db_info.get("status", "unknown") if isinstance(db_info, dict) else "unknown"
    if db_status == "connected":
        db_color = "success"
        db_label = "connected"
    elif db_status and db_status != "unknown":
        db_color = "critical"
        db_label = "error"
    else:
        db_color = "lightgrey"
        db_label = "unknown"
    badges["database"] = (
        f"https://img.shields.io/badge/Database-{db_label}-{db_color}?style=flat-square&logo=postgresql&logoColor=white"
    )

    return badges


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


def _select_primary_interface(interfaces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the most relevant network interface for display purposes."""

    if not interfaces:
        return None

    def interface_priority(entry: Dict[str, Any]) -> Tuple[int, int]:
        name = (entry.get("name") or "").lower()
        is_loopback = name in {"lo", "loopback"}
        is_up = bool(entry.get("is_up"))
        has_ipv4 = any(addr.get("type") == "IPv4" for addr in entry.get("addresses", []))
        priority = 0
        if is_loopback:
            priority += 2
        if not is_up:
            priority += 1
        if not has_ipv4:
            priority += 1
        return (priority, 0 if name else 1)

    sorted_interfaces = sorted(interfaces, key=interface_priority)
    return sorted_interfaces[0] if sorted_interfaces else None


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

    result: Dict[str, Any] = {
        "available": False, 
        "devices": [], 
        "error": None,
        "install_guide": None
    }

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
        result["install_guide"] = "Install smartmontools: apt install smartmontools (Debian/Ubuntu) or yum install smartmontools (RHEL/CentOS)"
        if logger:
            logger.info("SMART monitoring unavailable: smartctl not found. Install smartmontools package.")
        return result

    result["available"] = True

    for device in _iter_disk_devices(devices):
        path = device.get("path") or (f"/dev/{device.get('name')}" if device.get("name") else None)
        if not path:
            continue

        device_name = device.get("name") or ""

        device_result: Dict[str, Any] = {
            "name": device.get("name"),
            "path": path,
            "model": device.get("model"),
            "serial": device.get("serial"),
            "transport": device.get("transport"),
            "is_rotational": device.get("is_rotational"),
            "firmware_version": None,
            "nvme_version_string": None,
            "nvme_controller_id": None,
            "nvme_number_of_namespaces": None,
            "total_capacity_bytes": None,
            "unallocated_capacity_bytes": None,
            "ieee_oui_identifier": None,
            "overall_status": "unknown",
            "temperature_celsius": None,
            "temperature_sensors_celsius": [],
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
            "host_read_commands": None,
            "host_write_commands": None,
            "controller_busy_time_minutes": None,
            "percentage_used": None,
            "unsafe_shutdowns": None,
            "available_spare": None,
            "available_spare_threshold": None,
            "warning_temp_time_minutes": None,
            "critical_temp_time_minutes": None,
            "num_error_log_entries": None,
            "exit_status": None,
            "error": None,
        }

        # Detect device type and add appropriate flags for smartctl.
        # Returns None only when there's no plausible SMART support (e.g. ramdisk).
        device_type_flag = _detect_device_type(device, path, logger)

        # For NVMe devices, use the controller character device (/dev/nvme0)
        # instead of the namespace block device (/dev/nvme0n1).  The namespace
        # path causes "Read Self-test Log failed" (exit code 4) on drives that
        # don't support the self-test log on the namespace, while the controller
        # path returns a clean exit code 0.
        query_path = _nvme_controller_path(path) if device_type_flag == "nvme" else path

        # Check if we need sudo (smartctl requires root access to read device data)
        # If smartctl_path doesn't start with /usr or /sbin, or if we're not root, use sudo
        use_sudo = os.geteuid() != 0 if hasattr(os, 'geteuid') else True

        command = []
        if use_sudo:
            # Use sudo for smartctl (requires sudoers configuration)
            command.extend(["sudo", "-n"])  # -n means don't prompt for password

        command.append(smartctl_path)

        # Add device type flag first (must come before other flags for some smartctl versions)
        if device_type_flag:
            command.extend(["-d", device_type_flag])

        # -a (all) = -H -i -c -A -l error -l selftest: provides complete
        # device info, capabilities, attributes, and health status.  Using -a
        # instead of just -H -A ensures NVMe health logs and ATA attributes
        # are both fully populated in the JSON output.
        command.extend(["--json", "-a"])

        # The -n standby flag is for ATA/SATA devices to skip devices in standby mode.
        # Only add this flag for:
        # - Devices explicitly detected as 'ata' or 'sat' type
        # Skip this flag for:
        # - NVMe devices: don't support standby mode in the same way as ATA/SATA
        # - Auto-detected devices: may be USB, SCSI, or other types that don't support -n standby
        # - Devices with no type flag (None)
        # Including -n standby for incompatible devices causes "invalid argument" errors
        if device_type_flag and device_type_flag in ("ata", "sat"):
            command.extend(["-n", "standby"])

        command.append(query_path)

        if logger:
            logger.debug("Querying SMART data for %s with command: %s", query_path, " ".join(command))

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
        except subprocess.TimeoutExpired:  # pragma: no cover - depends on hardware
            device_result["error"] = "smartctl query timed out (device may be sleeping or unresponsive)"
            if logger:
                logger.warning("smartctl timeout for %s", path)
            result["devices"].append(device_result)
            continue
        except PermissionError:  # pragma: no cover - depends on user permissions
            device_result["error"] = "Permission denied (may require root/sudo privileges)"
            if logger:
                logger.warning("smartctl permission denied for %s", path)
            result["devices"].append(device_result)
            continue
        except Exception as exc:  # pragma: no cover - depends on host configuration
            device_result["error"] = f"smartctl execution failed: {str(exc)}"
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
        
        # smartctl exit codes: bit 0 = command line error, bit 1 = device open failed, 
        # bit 2 = SMART command failed, bits 3-7 indicate disk problems
        if completed.returncode != 0 and not raw_output:
            # Provide more detailed error message based on exit code
            if completed.returncode & 1:
                error_msg = "Invalid command line arguments"
            elif completed.returncode & 2:
                error_msg = "Device open failed (device may be unavailable or requires elevated privileges)"
            elif completed.returncode & 4:
                error_msg = "SMART command failed (device may not support SMART)"
            else:
                error_msg = stderr_output if stderr_output else f"smartctl exited with code {completed.returncode}"
            device_result["error"] = error_msg
            if logger:
                logger.info("SMART not available for %s: %s", path, error_msg)
            result["devices"].append(device_result)
            continue
        
        if not raw_output:
            device_result["error"] = "No data returned from smartctl"
            if logger:
                logger.debug("No smartctl output for %s", path)
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

        # Diagnostic: log which top-level JSON keys smartctl returned so we
        # can quickly identify missing sections when debugging attribute
        # extraction failures.
        report_keys = sorted(report.keys()) if isinstance(report, dict) else []
        has_nvme_log = "nvme_smart_health_information_log" in report_keys
        has_temperature = "temperature" in report_keys
        has_ata_attrs = "ata_smart_attributes" in report_keys
        if logger:
            logger.debug(
                "smartctl JSON for %s: keys=%s nvme_log=%s temp=%s ata_attrs=%s",
                path, report_keys, has_nvme_log, has_temperature, has_ata_attrs,
            )
        # Store diagnostic info so it's visible in the API response
        device_result["_diag_report_keys"] = report_keys

        device_result["model"] = (
            device_result.get("model")
            or report.get("model_name")
            or report.get("model_family")
            or report.get("device_model")
        )
        device_result["serial"] = device_result.get("serial") or report.get("serial_number")

        firmware_version = report.get("firmware_version") or report.get("firmware")
        if firmware_version:
            device_result["firmware_version"] = str(firmware_version)

        total_capacity = report.get("nvme_total_capacity")
        if total_capacity is None:
            user_capacity = report.get("user_capacity")
            if isinstance(user_capacity, dict):
                total_capacity = _coerce_int(user_capacity.get("bytes"))
        if total_capacity is not None:
            coerced_capacity = _coerce_int(total_capacity)
            if coerced_capacity is not None:
                device_result["total_capacity_bytes"] = coerced_capacity

        unallocated_capacity = report.get("nvme_unallocated_capacity")
        if unallocated_capacity is not None:
            coerced_unallocated = _coerce_int(unallocated_capacity)
            if coerced_unallocated is not None:
                device_result["unallocated_capacity_bytes"] = coerced_unallocated

        controller_id = _coerce_int(report.get("nvme_controller_id"))
        if controller_id is not None:
            device_result["nvme_controller_id"] = controller_id

        namespaces = _coerce_int(report.get("nvme_number_of_namespaces"))
        if namespaces is not None:
            device_result["nvme_number_of_namespaces"] = namespaces

        nvme_version = report.get("nvme_version")
        if isinstance(nvme_version, dict):
            version_string = nvme_version.get("string") or nvme_version.get("value")
            if version_string:
                device_result["nvme_version_string"] = str(version_string)

        ieee_identifier = _coerce_int(report.get("nvme_ieee_oui_identifier"))
        if ieee_identifier is not None:
            device_result["ieee_oui_identifier"] = f"{ieee_identifier:06X}"

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
            else:
                # Fallback: infer health status from exit code and available data
                # smartctl exit code bits 3-7 indicate disk problems:
                #   bit 3 = DISK FAILING, bit 4 = prefail attrs <= threshold,
                #   bit 5 = usage attrs <= threshold, bit 6 = error log has errors,
                #   bit 7 = self-test log has errors
                exit_code = completed.returncode
                disk_failing_bits = exit_code & 0x18  # bits 3-4: critical failures
                disk_problem_bits = exit_code & 0xF8  # bits 3-7: any disk issues

                nvme_info = report.get("nvme_smart_health_information_log")
                if isinstance(nvme_info, dict):
                    # NVMe: use critical_warning field as authoritative source
                    critical_warning = _coerce_int(nvme_info.get("critical_warning"))
                    if critical_warning is not None:
                        device_result["overall_status"] = "failed" if critical_warning != 0 else "passed"
                    elif disk_problem_bits == 0:
                        device_result["overall_status"] = "passed"
                elif disk_failing_bits:
                    # ATA/SATA with critical failure bits set
                    device_result["overall_status"] = "failed"
                elif disk_problem_bits == 0:
                    # No disk problem bits set and we parsed valid data
                    device_result["overall_status"] = "passed"

                if logger:
                    if device_result["overall_status"] != "unknown":
                        logger.debug(
                            "Inferred SMART status '%s' for %s from exit code %d",
                            device_result["overall_status"], path, exit_code,
                        )
                    elif exit_code == 0:
                        logger.debug(
                            "SMART status unavailable for %s despite successful smartctl execution", path,
                        )

        device_result["temperature_celsius"] = _extract_temperature(report)
        device_result["power_on_hours"] = _extract_attribute_value(report, "Power_On_Hours")
        device_result["power_cycle_count"] = _extract_attribute_value(report, "Power_Cycle_Count")
        device_result["reallocated_sector_count"] = _extract_attribute_value(
            report, "Reallocated_Sector_Ct"
        )

        # Fallback: also try "Reallocated_Sector_Count" (used by some drives)
        if device_result["reallocated_sector_count"] is None:
            device_result["reallocated_sector_count"] = _extract_attribute_value(
                report, "Reallocated_Sector_Count"
            )

        # ATA pending sector count (another common health indicator)
        pending = _extract_attribute_value(report, "Current_Pending_Sector")
        if pending is not None:
            device_result.setdefault("pending_sector_count", pending)

        device_result["media_errors"] = _extract_nvme_field(report, "media_errors")
        device_result["critical_warnings"] = _extract_nvme_field(report, "critical_warning")
        nvme_stats = _extract_nvme_statistics(report)
        for key, value in nvme_stats.items():
            device_result[key] = value

        _populate_nvme_metrics(device_result, report)

        nvme_info = report.get("nvme_smart_health_information_log")
        if isinstance(nvme_info, dict):
            available_spare = _coerce_int(nvme_info.get("available_spare"))
            if available_spare is not None:
                device_result["available_spare"] = available_spare

            spare_threshold = _coerce_int(nvme_info.get("available_spare_threshold"))
            if spare_threshold is not None:
                device_result["available_spare_threshold"] = spare_threshold

            warning_time = (
                _coerce_int(nvme_info.get("warning_comp_temperature_time"))
                or _coerce_int(nvme_info.get("warning_temp_time"))
            )
            if warning_time is not None:
                device_result["warning_temp_time_minutes"] = warning_time

            critical_time = (
                _coerce_int(nvme_info.get("critical_comp_temperature_time"))
                or _coerce_int(nvme_info.get("critical_comp_time"))
            )
            if critical_time is not None:
                device_result["critical_temp_time_minutes"] = critical_time

            error_logs = _coerce_int(nvme_info.get("num_err_log_entries"))
            if error_logs is not None:
                device_result["num_error_log_entries"] = error_logs

            sensors = nvme_info.get("temperature_sensors")
            if isinstance(sensors, list):
                readings: List[float] = []
                for entry in sensors:
                    if isinstance(entry, (int, float)):
                        value = float(entry)
                        if value > 200:
                            value -= 273.15
                        if _is_valid_temperature(value):
                            readings.append(round(value, 1))
                if readings:
                    device_result["temperature_sensors_celsius"] = readings

        # Diagnostic: log extraction results for debugging
        if logger:
            logger.debug(
                "SMART extraction for %s: temp=%s hours=%s pct_used=%s spare=%s media_err=%s",
                path,
                device_result.get("temperature_celsius"),
                device_result.get("power_on_hours"),
                device_result.get("percentage_used"),
                device_result.get("available_spare"),
                device_result.get("media_errors"),
            )

        # Only store stderr as error if it indicates a real problem
        if stderr_output and completed.returncode != 0:
            device_result["error"] = stderr_output

        result["devices"].append(device_result)

    if not result["devices"] and result["available"]:
        result["error"] = "No SMART-capable block devices found"
        if logger:
            logger.info("SMART monitoring available but no eligible devices found")

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


def _nvme_controller_path(path: str) -> str:
    """Convert an NVMe namespace path to its controller path.

    smartctl requires the controller character device (e.g. ``/dev/nvme0``)
    rather than the namespace block device (e.g. ``/dev/nvme0n1``) to
    retrieve SMART data.  If *path* doesn't match the namespace pattern it
    is returned unchanged.
    """
    m = re.match(r'^(/dev/nvme\d+)n\d+', path)
    return m.group(1) if m else path


def _detect_device_type(device: Dict[str, Any], path: str, logger) -> Optional[str]:
    """Detect the device type and return appropriate smartctl -d flag value.

    Returns the ``-d`` value for smartctl, or ``"auto"`` to let smartctl
    probe the device itself.  Never returns ``None`` — every block device
    gets a chance to report SMART data because some PCIe NVMe drives on
    Raspberry Pi appear as ``mmcblk`` rather than ``nvme``.
    """

    name = device.get("name") or ""
    transport = (device.get("transport") or "").lower()

    # ── Explicit NVMe detection ──
    if name.startswith("nvme") or transport == "nvme" or "nvme" in path.lower():
        return "nvme"

    # ── PCIe-attached storage (e.g. Raspberry Pi 5 NVMe hat) ──
    # On the Pi 5 an NVMe SSD on the PCIe bus can appear as /dev/mmcblk* with
    # transport "" or "pcie".  Also check the sysfs NVMe path as a hint.
    if transport in ("pcie", "pci"):
        # Almost certainly NVMe behind a PCIe bridge
        return "nvme"

    # Check sysfs for NVMe backing — covers mmcblk devices backed by NVMe
    try:
        sysfs_link = Path(f"/sys/block/{name}").resolve()
        sysfs_str = str(sysfs_link).lower()
        if "nvme" in sysfs_str or "pci" in sysfs_str:
            if logger:
                logger.debug(
                    "Detected PCIe/NVMe backing for %s via sysfs: %s",
                    path, sysfs_link,
                )
            return "nvme"
    except Exception:
        pass

    # ── Known transports ──
    if transport in ("usb", "usb-storage"):
        return "auto"
    if transport in ("sata", "scsi", "ata"):
        return "auto"

    # ── Fall-through: let smartctl auto-detect ──
    # This includes mmcblk devices where we couldn't confirm NVMe backing.
    # smartctl will gracefully fail for true SD cards.
    return "auto"


def _iter_disk_devices(devices: List[Dict[str, Any]]):
    for device in devices:
        if not isinstance(device, dict):
            continue
        device_type = (device.get("type") or "").lower()
        name = device.get("name") or ""
        # Skip virtual/RAM devices that don't support SMART
        if device_type == "disk" and not name.startswith(("ram", "loop", "zram")):
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
            value = _coerce_int(nvme_info.get(key))
            if value is not None:
                device_result[field] = value
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
        value = _coerce_int(nvme_info.get(source_key))
        if value is not None:
            device_result[target_field] = value

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


def _collect_rtc_status(logger) -> Dict[str, Any]:
    """Inspect any battery-backed real-time clock exposed via ``/sys/class/rtc``.

    Targets the on-board RTC of the Uputronics Raspberry Pi GPS/RTC Expansion
    Board — DS3231 at I²C ``0x68`` on older revisions (``dtoverlay=i2c-rtc,ds3231``)
    and RV-3028-C7 at I²C ``0x52`` on current revisions
    (``dtoverlay=i2c-rtc,rv3028``) — but works for any Linux RTC. All reads
    come from sysfs — ``hwclock`` is never invoked, so the function is safe
    to run without root, never blocks, and does not depend on the
    ``util-linux-extra`` package being installed.

    Returns a best-effort dict that is always safe to serialise. When no RTC
    is present the dict will contain ``available=False`` so the health page
    can simply omit the section.
    """
    result: Dict[str, Any] = {"available": False}
    try:
        rtc_root = Path("/sys/class/rtc/rtc0")
        if not rtc_root.exists():
            result["status"] = "not_present"
            return result

        result["available"] = True
        result["device"] = "/dev/rtc0"
        result["sysfs_path"] = str(rtc_root)

        name = _safe_read_text(rtc_root / "name")
        if name:
            # The kernel reports e.g. "rtc-ds3231 1-0068" for the DS3231 driver
            # bound on I²C bus 1 address 0x68, or "rtc-rv3028 1-0052" for the
            # RV-3028-C7 used on current Uputronics boards. Normalise for
            # downstream UI.
            result["name"] = name
            lowered = name.lower()
            result["is_ds3231"] = "ds3231" in lowered
            result["is_rv3028"] = "rv3028" in lowered
            result["is_battery_backed"] = (
                result["is_ds3231"]
                or result["is_rv3028"]
                or "ds1307" in lowered
                or "pcf85" in lowered
            )

        # Current RTC time. ``since_epoch`` is exported in seconds (UTC) and
        # is the most reliable source — the textual ``date``/``time`` files
        # are local-time on some kernels.
        since_epoch = _safe_int(_safe_read_text(rtc_root / "since_epoch"))
        system_epoch = time.time()
        result["system_time_iso"] = datetime.fromtimestamp(system_epoch, UTC_TZ).isoformat()

        if since_epoch is not None and since_epoch > 0:
            # Sanity-clip against absurd values (e.g. driver returned 0).
            result["rtc_epoch"] = since_epoch
            result["rtc_time_iso"] = datetime.fromtimestamp(since_epoch, UTC_TZ).isoformat()
            drift = float(since_epoch) - float(system_epoch)
            result["drift_seconds"] = drift
            abs_drift = abs(drift)
            if abs_drift < 2.0:
                result["drift_status"] = "in_sync"
            elif abs_drift < 60.0:
                result["drift_status"] = "minor"
            elif abs_drift < 3600.0:
                result["drift_status"] = "moderate"
            else:
                # Large drift after a power cycle is the classic "RTC battery
                # failed and the clock reset" symptom on both the DS3231 and
                # the RV-3028-C7.
                result["drift_status"] = "severe"
        else:
            # An unreadable ``since_epoch`` typically means the OSF
            # (Oscillator Stop Flag) tripped — i.e. the backup battery is
            # exhausted and the chip lost time entirely.
            result["drift_status"] = "unreadable"

        # The DS3231 driver also exposes its die temperature via hwmon. This
        # is a useful side-signal because the battery-backup voltage is not
        # surfaced via sysfs; an unusually warm reading (>60 °C) can indicate
        # the part is being heated by an adjacent regulator.
        for hwmon_dir in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            hwmon_name = _safe_read_text(hwmon_dir / "name")
            if not hwmon_name or "ds3231" not in hwmon_name.lower():
                continue
            raw = _safe_read_text(hwmon_dir / "temp1_input")
            milli = _safe_int(raw)
            if milli is not None:
                result["temperature_c"] = round(milli / 1000.0, 1)
            break

        return result
    except Exception as exc:
        if logger:
            logger.debug("Failed to read RTC status from sysfs: %s", exc)
        result["status"] = "error"
        result["error"] = str(exc)
        return result


_HARDWARE_SUBSYSTEMS = ("network", "zigbee", "gps", "displays", "gpio")


def _collect_hardware_subsystems(logger) -> Dict[str, Any]:
    """Read the Phase 4 per-subsystem heartbeat slices from Redis.

    Each hardware subsystem process (network/zigbee/gps/displays/gpio)
    publishes its own slice into ``hardware:metrics:<subsystem>`` every
    5 s with a 60 s TTL.  ``services.common.metrics._publish_slice``
    also refreshes a roll-up at ``hardware:metrics`` keyed by subsystem
    so a single Redis GET tells us which subprocesses are alive.

    Returns a dict suitable for the system-health page::

        {
          "subsystems": {
            "network":  {"alive": True,  "last_seen": "...", "data": {...}},
            "zigbee":   {"alive": False, "last_seen": None,  "data": {}},
            ...
          },
          "alive_count": 4,
          "total": 5,
          "status": "degraded",   # "healthy" / "degraded" / "down" / "unknown"
        }

    A missing slice for a subsystem means that subprocess is down —
    the whole point of the Phase 4 split.
    """
    result: Dict[str, Any] = {
        "subsystems": {
            name: {"alive": False, "last_seen": None, "data": {}}
            for name in _HARDWARE_SUBSYSTEMS
        },
        "alive_count": 0,
        "total": len(_HARDWARE_SUBSYSTEMS),
        "status": "unknown",
    }

    try:
        from app_core.redis_client import get_redis_client
    except Exception as exc:
        if logger:
            logger.debug("hardware_subsystems: redis client unavailable: %s", exc)
        return result

    try:
        client = get_redis_client(max_retries=1)
    except Exception as exc:
        if logger:
            logger.debug("hardware_subsystems: redis connect failed: %s", exc)
        return result
    if client is None:
        return result

    summary: Dict[str, Any] = {}
    try:
        raw = client.get("hardware:metrics")
    except Exception as exc:
        if logger:
            logger.debug("hardware_subsystems: redis GET failed: %s", exc)
        raw = None

    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                summary = parsed
        except Exception as exc:
            if logger:
                logger.debug("hardware_subsystems: bad JSON in hardware:metrics: %s", exc)

    for name in _HARDWARE_SUBSYSTEMS:
        slice_payload = summary.get(name)
        if isinstance(slice_payload, dict):
            result["subsystems"][name] = {
                "alive": True,
                "last_seen": slice_payload.get("timestamp"),
                "data": {k: v for k, v in slice_payload.items() if k != "timestamp"},
            }
            result["alive_count"] += 1

    if result["alive_count"] == result["total"]:
        result["status"] = "healthy"
    elif result["alive_count"] == 0:
        result["status"] = "down"
    else:
        result["status"] = "degraded"

    return result


def _collect_gps_status(logger) -> Dict[str, Any]:
    """Read GPS fix status from Redis (published by the hardware service).

    Returns a best-effort dict that is always safe to serialise.  When the
    hardware service is not running or GPS is disabled the dict will contain
    ``enabled=False`` / ``running=False`` so the health page can render a
    graceful "not configured" state.
    """
    try:
        from app_core.redis_client import get_redis_client

        client = get_redis_client(max_retries=1)
        if client is None:
            return {"enabled": False, "running": False, "status": "redis_unavailable"}

        raw = client.get("gps:status")
        if not raw:
            # No key means GPS either disabled or hardware service not running
            return {"enabled": False, "running": False, "status": "not_started"}

        data: Dict[str, Any] = json.loads(raw)
        # Strip the large recent_sentences list — not needed in health snapshot
        data.pop("recent_sentences", None)
        return data
    except Exception as exc:
        if logger:
            logger.debug("Failed to read GPS status from Redis: %s", exc)
        return {"enabled": False, "running": False, "status": "error", "error": str(exc)}
