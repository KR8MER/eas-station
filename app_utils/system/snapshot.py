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

"""The composed system health snapshot."""

import os
import platform
import socket
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil
from sqlalchemy import text

from ..formatting import format_uptime
from ..time import UTC_TZ, local_now, utc_now
from .badges import get_distro_logo_url, get_shields_io_badges
from .common import SystemHealth
from .dependencies import _collect_dependency_versions
from .hardware import _collect_hardware_inventory
from .network import _collect_network_traffic, _select_primary_interface
from .osinfo import _collect_operating_system_details
from .raspberry_pi import collect_raspberry_pi_health
from .clocksync import _collect_clock_sync
from .rtc import _collect_rtc_status
from .services import _collect_systemd_services
from .smart import _collect_smart_health
from .subsystems import _collect_gps_status, _collect_hardware_subsystems
from .temperature import _collect_temperature_readings

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
            "clock_sync": _collect_clock_sync(logger),
            "raspberry_pi": collect_raspberry_pi_health(
                logger, hardware_info.get("platform")
            ),
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
