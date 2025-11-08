"""System monitoring helpers."""

from datetime import datetime
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional

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

        containers_info = _collect_container_statuses(logger)
        services_status: Dict[str, Any] = {
            container.get("display_name")
            or container.get("name")
            or f"container-{index}": container.get("status")
            for index, container in enumerate(containers_info.get("containers", []), start=1)
        }

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
            "containers": containers_info,
            "temperature": temperature_info,
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
    }

    compose_project = os.getenv("COMPOSE_PROJECT_NAME") or os.getenv("STACK_PROJECT_NAME") or os.getenv(
        "STACK_NAME"
    )
    engines: List[str] = ["docker", "podman"]
    last_error: Optional[str] = None

    for engine in engines:
        engine_path = shutil.which(engine)
        if not engine_path:
            continue

        command = [engine_path, "ps", "--all"]
        if compose_project:
            if engine == "docker":
                command.extend(["--filter", f"label=com.docker.compose.project={compose_project}"])
            else:
                command.extend(["--filter", f"label=io.podman.compose.project={compose_project}"])
        command.extend(["--format", "{{json .}}"])  # Return machine-readable output

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )

            if completed.returncode != 0:
                stderr = completed.stderr.strip() or "unknown error"
                raise RuntimeError(f"{engine} ps failed: {stderr}")

            lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            containers: List[Dict[str, Any]] = []

            for raw_line in lines:
                try:
                    info = json.loads(raw_line)
                except json.JSONDecodeError:
                    last_error = f"Unable to parse {engine} output: {raw_line}"
                    continue

                labels_text = info.get("Labels") or ""
                labels: Dict[str, str] = {}
                if labels_text:
                    for item in labels_text.split(","):
                        if "=" in item:
                            key, value = item.split("=", 1)
                            labels[key.strip()] = value.strip()

                name = info.get("Names") or "unknown"
                status_text = info.get("Status") or "unknown"
                state = (info.get("State") or "").lower()
                status_lower = status_text.lower()
                health_state = None
                if "unhealthy" in status_lower:
                    health_state = "unhealthy"
                elif "healthy" in status_lower:
                    health_state = "healthy"
                elif "starting" in status_lower:
                    health_state = "starting"

                is_running = state == "running" or status_lower.startswith("up")

                service = labels.get("com.docker.compose.service") or labels.get("io.podman.compose.service")
                display_name = None
                if service:
                    display_name = service.replace("_", " ").replace("-", " ").title()

                containers.append(
                    {
                        "name": name,
                        "display_name": display_name,
                        "service": service,
                        "project": labels.get("com.docker.compose.project")
                        or labels.get("io.podman.compose.project")
                        or compose_project,
                        "status": status_text,
                        "state": state or None,
                        "health": health_state,
                        "is_running": is_running,
                        "image": info.get("Image"),
                        "ports": info.get("Ports"),
                        "running_for": info.get("RunningFor"),
                        "created_at": info.get("CreatedAt"),
                        "labels": labels,
                    }
                )

            total = len(containers)
            running = len([item for item in containers if item.get("is_running")])
            unhealthy = len([item for item in containers if item.get("health") == "unhealthy"])
            stopped = max(total - running, 0)

            issues = [
                item
                for item in containers
                if not item.get("is_running") or item.get("health") == "unhealthy"
            ]

            result.update(
                {
                    "available": True,
                    "status": "healthy" if not issues else "degraded",
                    "engine": engine,
                    "containers": containers,
                    "summary": {
                        "total": total,
                        "running": running,
                        "healthy": len([item for item in containers if item.get("health") == "healthy"]),
                        "unhealthy": unhealthy,
                        "stopped": stopped,
                    },
                    "issues": issues,
                    "error": None,
                    "compose_project": compose_project,
                }
            )

            return result

        except Exception as exc:  # pragma: no cover - depends on host environment
            last_error = str(exc)
            if logger:
                logger.warning("Failed to collect container status via %s: %s", engine, exc)

    if not result["available"]:
        result["error"] = last_error or "Container engine not available"

    return result
