"""System monitoring helpers."""

from datetime import datetime
import os
import platform
import shutil
import socket
import subprocess
import time
from typing import Any, Dict

import psutil
from sqlalchemy import text

from .time import UTC_TZ, local_now, utc_now


SystemHealth = Dict[str, Any]


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

        process_info = {
            "total_processes": len(psutil.pids()),
            "running_processes": len(
                [p for p in psutil.process_iter(["status"]) if p.info["status"] == psutil.STATUS_RUNNING]
            ),
            "top_processes": [],
        }

        try:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "username"]):
                try:
                    proc.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            time.sleep(0.1)

            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "username"]):
                try:
                    pinfo = proc.as_dict(
                        attrs=["pid", "name", "cpu_percent", "memory_percent", "username"]
                    )
                    if pinfo["cpu_percent"] is not None:
                        processes.append(pinfo)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            processes.sort(key=lambda x: x["cpu_percent"] or 0, reverse=True)
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

        services_status: Dict[str, Any] = {}
        services_to_check = ["apache2", "postgresql"]
        systemctl_path = shutil.which("systemctl")

        if systemctl_path:
            for service in services_to_check:
                try:
                    result = subprocess.run(
                        [systemctl_path, "is-active", service],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    service_status = result.stdout.strip() if result.stdout else "unknown"
                    services_status[service] = service_status or "unknown"
                except Exception:
                    services_status[service] = "unknown"
        else:
            for service in services_to_check:
                services_status[service] = "unavailable"

        temperature_info: Dict[str, Any] = {}
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    temperature_info[name] = []
                    for entry in entries:
                        temperature_info[name].append(
                            {
                                "label": entry.label or "Unknown",
                                "current": entry.current,
                                "high": entry.high,
                                "critical": entry.critical,
                            }
                        )
        except Exception:
            pass

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
            },
            "cpu": cpu_info,
            "memory": memory_info,
            "disk": disk_info,
            "network": network_info,
            "processes": process_info,
            "load_averages": load_averages,
            "database": {"status": db_status, "info": db_info},
            "services": services_status,
            "temperature": temperature_info,
        }

    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.error("Error getting system health: %s", exc)
        return {
            "error": str(exc),
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
        }
